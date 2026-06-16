from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from . import models, schemas


GMAIL_CONNECTION_KEY = "superkevin_primary"
GMAIL_USER_ID = "me"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_REQUESTED_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)
GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
GMAIL_DRAFTS_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send"
OAUTH_STATE_TTL_MINUTES = 10
HUMAN_SEND_CONFIRMATIONS = {"ok", "okay", "沒有問題", "没问题", "no problem", "approved"}
GMAIL_PROPERTY_FEED_DEFAULT_QUERY = "newer_than:14d (MLS OR listing OR sold OR leased OR REALM OR TRREB)"
GMAIL_PROPERTY_FEED_SOURCE_TERMS = (
    "realm",
    "trreb",
    "mls",
    "listing",
    "listings",
    "sold",
    "sale",
    "leased",
    "lease",
    "rent",
    "rental",
)
GMAIL_PROPERTY_FEED_TIME_PATTERN = re.compile(r"\b(newer_than|after|newer):", re.IGNORECASE)


@dataclass
class GmailOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    encryption_key: str
    expected_account_email: str | None


@dataclass
class GmailAccessTokenGrant:
    access_token: str
    gmail_user_id: str
    expires_at: datetime | None


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_email(value: Any) -> str | None:
    text = _clean_text(value)
    return text.lower() if text else None


def _manual_send_confirmation_valid(value: str | None) -> bool:
    text = _clean_text(value)
    return bool(text and text.lower() in HUMAN_SEND_CONFIRMATIONS)


def validate_property_feed_query(query: str | None) -> str:
    q = _clean_text(query) or GMAIL_PROPERTY_FEED_DEFAULT_QUERY
    if len(q) > 500:
        raise ValueError("gmail_feed_query_too_long")

    lowered = q.casefold()
    if not GMAIL_PROPERTY_FEED_TIME_PATTERN.search(q):
        raise ValueError("gmail_feed_query_requires_recency")
    if not any(term in lowered for term in GMAIL_PROPERTY_FEED_SOURCE_TERMS):
        raise ValueError("gmail_feed_query_requires_listing_terms")
    return q


def _load_oauth_config() -> GmailOAuthConfig:
    client_id = _clean_text(os.getenv("GMAIL_OAUTH_CLIENT_ID"))
    if client_id is None:
        raise ValueError("gmail_oauth_client_id_missing")

    client_secret = _clean_text(os.getenv("GMAIL_OAUTH_CLIENT_SECRET"))
    if client_secret is None:
        raise ValueError("gmail_oauth_client_secret_missing")

    redirect_uri = _clean_text(os.getenv("GMAIL_OAUTH_REDIRECT_URI"))
    if redirect_uri is None:
        raise ValueError("gmail_oauth_redirect_uri_missing")

    encryption_key = _clean_text(os.getenv("GMAIL_OAUTH_ENCRYPTION_KEY"))
    if encryption_key is None:
        raise ValueError("gmail_oauth_encryption_key_missing")

    try:
        Fernet(encryption_key.encode("utf-8"))
    except (TypeError, ValueError):
        raise ValueError("gmail_oauth_encryption_key_invalid") from None

    return GmailOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        encryption_key=encryption_key,
        expected_account_email=_clean_text(os.getenv("GMAIL_EXPECTED_ACCOUNT_EMAIL")),
    )


def is_gmail_oauth_configured() -> bool:
    try:
        _load_oauth_config()
        return True
    except ValueError:
        return False


def _expected_account_email() -> str | None:
    return _clean_text(os.getenv("GMAIL_EXPECTED_ACCOUNT_EMAIL"))


def _assert_expected_account(connection: models.GmailOAuthConnection) -> None:
    expected_email = _expected_account_email()
    if expected_email and (
        _normalize_email(connection.account_email) != _normalize_email(expected_email)
    ):
        raise ValueError("gmail_oauth_wrong_account")


def _get_fernet(config: GmailOAuthConfig) -> Fernet:
    return Fernet(config.encryption_key.encode("utf-8"))


def _encrypt_refresh_token(config: GmailOAuthConfig, refresh_token: str) -> str:
    return _get_fernet(config).encrypt(refresh_token.encode("utf-8")).decode("utf-8")


def _decrypt_refresh_token(config: GmailOAuthConfig, ciphertext: str) -> str:
    try:
        plaintext = _get_fernet(config).decrypt(ciphertext.encode("utf-8"))
    except (InvalidToken, ValueError, TypeError):
        raise ValueError("gmail_oauth_refresh_token_unreadable") from None
    decoded = _clean_text(plaintext.decode("utf-8"))
    if decoded is None:
        raise ValueError("gmail_oauth_refresh_token_unreadable")
    return decoded


def _parse_scopes(raw: Any) -> list[str]:
    if isinstance(raw, list):
        values = raw
    else:
        scope_text = _clean_text(raw)
        values = scope_text.split(" ") if scope_text else []

    scopes: list[str] = []
    seen: set[str] = set()
    for value in values:
        scope = _clean_text(value)
        if scope is None or scope in seen:
            continue
        seen.add(scope)
        scopes.append(scope)
    return scopes


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("gmail_oauth_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise ValueError("gmail_oauth_invalid_response_shape")
    return parsed


def _post_form_json(url: str, form_data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=urlencode(form_data).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, _parse_json_object(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, _parse_json_object(raw)
    except URLError as exc:
        raise ValueError("gmail_oauth_network_error") from exc


def _post_json_with_bearer(
    url: str,
    *,
    access_token: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, _parse_json_object(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = _parse_json_object(raw)
        except ValueError:
            parsed = {"raw_error": raw}
        return exc.code, parsed
    except URLError as exc:
        raise ValueError("gmail_oauth_network_error") from exc


def _get_json(url: str, *, access_token: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        if exc.code == 401:
            raise ValueError("gmail_oauth_access_token_rejected") from exc
        raise ValueError("gmail_oauth_profile_lookup_failed") from exc
    except URLError as exc:
        raise ValueError("gmail_oauth_network_error") from exc
    return _parse_json_object(raw)


def _build_status_response(
    connection: models.GmailOAuthConnection | None,
) -> schemas.GmailOAuthStatusResponse:
    expected_email = _expected_account_email()
    if connection is None:
        return schemas.GmailOAuthStatusResponse(
            connection_key=GMAIL_CONNECTION_KEY,
            gmail_user_id=GMAIL_USER_ID,
            status="disconnected",
            granted_scopes=[],
            oauth_configured=is_gmail_oauth_configured(),
            has_refresh_token=False,
            expected_account_email=expected_email,
        )

    granted_scopes: list[str] = []
    if connection.granted_scopes:
        try:
            granted_scopes = _parse_scopes(json.loads(connection.granted_scopes))
        except (json.JSONDecodeError, TypeError, ValueError):
            granted_scopes = []

    return schemas.GmailOAuthStatusResponse(
        connection_key=connection.connection_key,
        gmail_user_id=connection.gmail_user_id or GMAIL_USER_ID,
        status=connection.status or "disconnected",
        account_email=connection.account_email,
        granted_scopes=granted_scopes,
        oauth_configured=is_gmail_oauth_configured(),
        has_refresh_token=bool(connection.encrypted_refresh_token),
        reconnect_required=(connection.status == "reconnect_required"),
        expected_account_email=expected_email,
    )


def _get_connection(db: Session) -> models.GmailOAuthConnection | None:
    return (
        db.query(models.GmailOAuthConnection)
        .filter(models.GmailOAuthConnection.connection_key == GMAIL_CONNECTION_KEY)
        .first()
    )


def _get_or_create_connection(db: Session) -> models.GmailOAuthConnection:
    connection = _get_connection(db)
    if connection is not None:
        return connection

    connection = models.GmailOAuthConnection(
        connection_key=GMAIL_CONNECTION_KEY,
        gmail_user_id=GMAIL_USER_ID,
        status="disconnected",
    )
    db.add(connection)
    db.flush()
    return connection


def _delete_stale_states(db: Session) -> None:
    now = _utcnow_naive()
    (
        db.query(models.GmailOAuthState)
        .filter(
            (models.GmailOAuthState.expires_at < now)
            | (models.GmailOAuthState.used_at.isnot(None))
        )
        .delete(synchronize_session=False)
    )


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _create_state_record(db: Session) -> tuple[str, datetime]:
    _delete_stale_states(db)
    now = _utcnow_naive()
    expires_at = now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)
    raw_state = secrets.token_urlsafe(32)
    state_record = models.GmailOAuthState(
        connection_key=GMAIL_CONNECTION_KEY,
        state_hash=_hash_state(raw_state),
        expires_at=expires_at,
    )
    db.add(state_record)
    db.commit()
    return raw_state, expires_at


def _consume_valid_state(db: Session, raw_state: str) -> None:
    state = _clean_text(raw_state)
    if state is None:
        raise ValueError("gmail_oauth_state_missing")

    state_record = (
        db.query(models.GmailOAuthState)
        .filter(
            models.GmailOAuthState.connection_key == GMAIL_CONNECTION_KEY,
            models.GmailOAuthState.state_hash == _hash_state(state),
        )
        .first()
    )
    if state_record is None:
        raise ValueError("gmail_oauth_state_invalid")

    now = _utcnow_naive()
    if state_record.used_at is not None:
        raise ValueError("gmail_oauth_state_invalid")
    if state_record.expires_at < now:
        raise ValueError("gmail_oauth_state_expired")

    state_record.used_at = now
    db.commit()


def _exchange_code_for_tokens(
    config: GmailOAuthConfig,
    *,
    code: str,
) -> dict[str, Any]:
    status_code, response = _post_form_json(
        GOOGLE_OAUTH_TOKEN_URL,
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
        },
    )
    if status_code >= 400:
        raise ValueError("gmail_oauth_code_exchange_failed")
    return response


def _refresh_access_token(
    config: GmailOAuthConfig,
    *,
    refresh_token: str,
) -> dict[str, Any]:
    status_code, response = _post_form_json(
        GOOGLE_OAUTH_TOKEN_URL,
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    if status_code >= 400:
        if _clean_text(response.get("error")) == "invalid_grant":
            raise ValueError("gmail_oauth_refresh_token_invalid")
        raise ValueError("gmail_oauth_refresh_failed")
    return response


def _fetch_gmail_profile(access_token: str) -> dict[str, Any]:
    return _get_json(GMAIL_PROFILE_URL, access_token=access_token)


def get_gmail_oauth_status(db: Session) -> schemas.GmailOAuthStatusResponse:
    return _build_status_response(_get_connection(db))


def start_gmail_oauth(db: Session) -> schemas.GmailOAuthStartResponse:
    config = _load_oauth_config()
    raw_state, expires_at = _create_state_record(db)
    scope_text = " ".join(GMAIL_REQUESTED_SCOPES)
    authorization_url = (
        f"{GOOGLE_OAUTH_AUTHORIZE_URL}?"
        + urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": scope_text,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": raw_state,
            }
        )
    )
    return schemas.GmailOAuthStartResponse(
        connection_key=GMAIL_CONNECTION_KEY,
        authorization_url=authorization_url,
        state_expires_at=expires_at,
        requested_scopes=list(GMAIL_REQUESTED_SCOPES),
    )


def handle_gmail_oauth_callback(
    db: Session,
    *,
    state: str,
    code: str,
) -> schemas.GmailOAuthStatusResponse:
    config = _load_oauth_config()
    _consume_valid_state(db, state)

    oauth_code = _clean_text(code)
    if oauth_code is None:
        raise ValueError("gmail_oauth_code_missing")

    token_response = _exchange_code_for_tokens(config, code=oauth_code)
    access_token = _clean_text(token_response.get("access_token"))
    refresh_token = _clean_text(token_response.get("refresh_token"))
    if access_token is None:
        raise ValueError("gmail_oauth_access_token_missing")
    if refresh_token is None:
        raise ValueError("gmail_oauth_refresh_token_missing")

    profile = _fetch_gmail_profile(access_token)
    account_email = _clean_text(profile.get("emailAddress"))
    if account_email is None:
        raise ValueError("gmail_oauth_profile_email_missing")
    if config.expected_account_email and (
        _normalize_email(account_email) != _normalize_email(config.expected_account_email)
    ):
        raise ValueError("gmail_oauth_wrong_account")

    connection = _get_or_create_connection(db)
    now = _utcnow_naive()
    connection.gmail_user_id = GMAIL_USER_ID
    connection.status = "connected"
    connection.account_email = account_email
    connection.granted_scopes = json.dumps(
        _parse_scopes(token_response.get("scope")),
        ensure_ascii=False,
    )
    connection.encrypted_refresh_token = _encrypt_refresh_token(config, refresh_token)
    connection.refresh_token_updated_at = now
    connection.connected_at = now
    connection.last_refreshed_at = now
    connection.last_error = None
    connection.last_error_at = None
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _build_status_response(connection)


def disconnect_gmail_oauth(db: Session) -> schemas.GmailOAuthStatusResponse:
    connection = _get_or_create_connection(db)
    connection.status = "disconnected"
    connection.account_email = None
    connection.granted_scopes = json.dumps([], ensure_ascii=False)
    connection.encrypted_refresh_token = None
    connection.refresh_token_updated_at = None
    connection.connected_at = None
    connection.last_refreshed_at = None
    connection.last_error = None
    connection.last_error_at = None
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _build_status_response(connection)


def refresh_gmail_access_token(db: Session) -> GmailAccessTokenGrant:
    config = _load_oauth_config()
    connection = _get_connection(db)
    if connection is None or not connection.encrypted_refresh_token:
        raise ValueError("gmail_oauth_connection_not_ready")

    refresh_token = _decrypt_refresh_token(config, connection.encrypted_refresh_token)
    try:
        token_response = _refresh_access_token(config, refresh_token=refresh_token)
    except ValueError as error:
        if str(error) == "gmail_oauth_refresh_token_invalid":
            connection.status = "reconnect_required"
            connection.encrypted_refresh_token = None
            connection.refresh_token_updated_at = None
            connection.last_error = "invalid_grant"
            connection.last_error_at = _utcnow_naive()
            db.add(connection)
            db.commit()
        raise

    access_token = _clean_text(token_response.get("access_token"))
    if access_token is None:
        raise ValueError("gmail_oauth_access_token_missing")

    now = _utcnow_naive()
    connection.status = "connected"
    connection.last_refreshed_at = now
    connection.last_error = None
    connection.last_error_at = None
    refreshed_scopes = _parse_scopes(token_response.get("scope"))
    if refreshed_scopes:
        connection.granted_scopes = json.dumps(refreshed_scopes, ensure_ascii=False)
    db.add(connection)
    db.commit()

    expires_in = token_response.get("expires_in")
    expires_at: datetime | None = None
    if isinstance(expires_in, int) and expires_in > 0:
        expires_at = now + timedelta(seconds=expires_in)
    elif isinstance(expires_in, str) and expires_in.isdigit():
        expires_at = now + timedelta(seconds=int(expires_in))

    return GmailAccessTokenGrant(
        access_token=access_token,
        gmail_user_id=connection.gmail_user_id or GMAIL_USER_ID,
        expires_at=expires_at,
    )


def _encode_mime_message(
    *,
    to_email: str,
    from_email: str,
    subject: str,
    body: str,
) -> str:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = from_email
    message["Subject"] = subject
    message.set_content(body)
    raw_bytes = message.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")


def _draft_content(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"subject": "Follow up", "body": ""}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"subject": "Follow up", "body": raw}
    return parsed if isinstance(parsed, dict) else {"subject": "Follow up", "body": str(parsed)}


def _extract_subject_body(interaction: models.Interaction) -> tuple[str, str]:
    draft = _draft_content(interaction.generated_response_content)
    subject = _clean_text(draft.get("subject")) or "Follow up"
    body = _clean_text(draft.get("body")) or ""
    return subject, body


def _gmail_meta(interaction: models.Interaction) -> dict[str, Any]:
    draft = _draft_content(interaction.generated_response_content)
    meta = draft.get("gmail")
    return meta if isinstance(meta, dict) else {}


def _update_gmail_meta(
    interaction: models.Interaction,
    *,
    status: str,
    gmail: dict[str, Any],
    subject: str | None = None,
    body: str | None = None,
) -> None:
    draft = _draft_content(interaction.generated_response_content)
    if subject is not None:
        draft["subject"] = subject
    if body is not None:
        draft["body"] = body
    existing = draft.get("gmail") if isinstance(draft.get("gmail"), dict) else {}
    draft["gmail"] = {**existing, **gmail}
    interaction.generated_response_content = json.dumps(draft, ensure_ascii=False)
    interaction.generated_response_status = status


def list_pending_email_drafts(db: Session) -> schemas.PendingEmailDraftsResponse:
    rows = (
        db.query(models.Interaction, models.Contact)
        .join(models.Contact, models.Interaction.contact_id == models.Contact.id)
        .filter(models.Interaction.generated_response_type == "email_draft")
        .filter(models.Interaction.generated_response_status.in_(["pending_review", "gmail_draft_created"]))
        .order_by(models.Interaction.date.desc())
        .all()
    )

    drafts: list[schemas.PendingEmailDraft] = []
    for interaction, contact in rows:
        subject, body = _extract_subject_body(interaction)
        gmail = _gmail_meta(interaction)
        drafts.append(
            schemas.PendingEmailDraft(
                interaction_id=interaction.id,
                contact_id=contact.id,
                contact_name=contact.name,
                to_email=contact.email,
                subject=subject,
                body=body,
                status=interaction.generated_response_status,
                created_at=interaction.date,
                gmail_draft_id=_clean_text(gmail.get("draft_id")),
                gmail_message_id=_clean_text(gmail.get("message_id")),
            )
        )
    return schemas.PendingEmailDraftsResponse(drafts=drafts)


def _get_email_draft_interaction(db: Session, interaction_id: int) -> tuple[models.Interaction, models.Contact]:
    row = (
        db.query(models.Interaction, models.Contact)
        .join(models.Contact, models.Interaction.contact_id == models.Contact.id)
        .filter(models.Interaction.id == interaction_id)
        .first()
    )
    if row is None:
        raise ValueError("email_draft_interaction_not_found")
    interaction, contact = row
    if interaction.generated_response_type != "email_draft":
        raise ValueError("email_draft_interaction_not_found")
    return interaction, contact


def _assert_can_use_gmail(db: Session) -> tuple[GmailAccessTokenGrant, models.GmailOAuthConnection]:
    connection = _get_connection(db)
    if connection is None or connection.account_email is None:
        raise ValueError("gmail_oauth_connection_not_ready")
    _assert_expected_account(connection)
    granted_scopes = _parse_scopes(json.loads(connection.granted_scopes or "[]"))
    if GMAIL_COMPOSE_SCOPE not in granted_scopes:
        raise ValueError("gmail_draft_compose_scope_missing")
    grant = refresh_gmail_access_token(db)
    return grant, connection


def _assert_can_read_gmail(db: Session) -> tuple[GmailAccessTokenGrant, models.GmailOAuthConnection]:
    connection = _get_connection(db)
    if connection is None or connection.account_email is None:
        raise ValueError("gmail_oauth_connection_not_ready")
    _assert_expected_account(connection)
    granted_scopes = _parse_scopes(json.loads(connection.granted_scopes or "[]"))
    if GMAIL_READONLY_SCOPE not in granted_scopes:
        raise ValueError("gmail_readonly_scope_missing")
    grant = refresh_gmail_access_token(db)
    return grant, connection


def _decode_gmail_body_data(data: str | None) -> str:
    text = _clean_text(data)
    if text is None:
        return ""
    padded = text + ("=" * (-len(text) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _gmail_payload_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    parsed: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = _clean_text(header.get("name"))
        value = _clean_text(header.get("value"))
        if name and value:
            parsed[name.lower()] = value
    return parsed


def _gmail_payload_text(payload: dict[str, Any]) -> str:
    mime_type = _clean_text(payload.get("mimeType")) or ""
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    text = ""
    if mime_type.startswith("text/"):
        text = _decode_gmail_body_data(body.get("data"))
        if mime_type == "text/html":
            text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    child_text = "\n".join(
        _gmail_payload_text(part)
        for part in parts
        if isinstance(part, dict)
    )
    return "\n".join(piece for piece in [text, child_text] if piece).strip()


def fetch_property_feed_messages(
    db: Session,
    *,
    query: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    q = validate_property_feed_query(query)
    grant, _connection = _assert_can_read_gmail(db)
    safe_limit = max(1, min(int(max_results or 10), 25))
    list_url = f"{GMAIL_MESSAGES_URL}?{urlencode({'q': q, 'maxResults': safe_limit})}"
    list_response = _get_json(list_url, access_token=grant.access_token)
    message_refs = list_response.get("messages") if isinstance(list_response.get("messages"), list) else []

    messages: list[dict[str, Any]] = []
    for ref in message_refs[:safe_limit]:
        message_id = _clean_text(ref.get("id")) if isinstance(ref, dict) else None
        if message_id is None:
            continue
        detail_url = f"{GMAIL_MESSAGES_URL}/{message_id}?{urlencode({'format': 'full'})}"
        detail = _get_json(detail_url, access_token=grant.access_token)
        payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
        headers = _gmail_payload_headers(payload)
        body = _gmail_payload_text(payload)
        messages.append(
            {
                "id": message_id,
                "thread_id": _clean_text(detail.get("threadId")),
                "subject": headers.get("subject"),
                "from": headers.get("from"),
                "date": headers.get("date"),
                "snippet": _clean_text(detail.get("snippet")),
                "body": body,
            }
        )
    return messages


def create_gmail_draft_for_interaction(
    db: Session,
    interaction_id: int,
    *,
    subject_override: str | None = None,
    body_override: str | None = None,
) -> schemas.GmailDraftActionResponse:
    interaction, contact = _get_email_draft_interaction(db, interaction_id)
    to_email = _clean_text(contact.email)
    if to_email is None:
        raise ValueError("gmail_draft_recipient_missing")

    grant, connection = _assert_can_use_gmail(db)
    subject, body = _extract_subject_body(interaction)
    subject = _clean_text(subject_override) or subject
    body = _clean_text(body_override) or body
    if not body:
        raise ValueError("gmail_draft_body_missing")

    gmail = _gmail_meta(interaction)
    draft_id = _clean_text(gmail.get("draft_id"))
    message_id = _clean_text(gmail.get("message_id"))
    if draft_id:
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Gmail draft already exists.",
            interaction_id=interaction.id,
            status=interaction.generated_response_status or "gmail_draft_created",
            account_email=connection.account_email,
            to_email=to_email,
            gmail_draft_id=draft_id,
            gmail_message_id=message_id,
        )

    encoded = _encode_mime_message(
        to_email=to_email,
        from_email=connection.account_email,
        subject=subject,
        body=body,
    )
    status_code, response = _post_json_with_bearer(
        GMAIL_DRAFTS_URL,
        access_token=grant.access_token,
        payload={"message": {"raw": encoded}},
    )
    if status_code == 401:
        raise ValueError("gmail_oauth_access_token_rejected")
    if status_code == 403:
        raise ValueError("gmail_draft_compose_scope_missing")
    if status_code >= 400:
        raise ValueError("gmail_draft_create_failed")

    draft_id = _clean_text(response.get("id"))
    message = response.get("message") if isinstance(response.get("message"), dict) else {}
    message_id = _clean_text(message.get("id"))
    _update_gmail_meta(
        interaction,
        status="gmail_draft_created",
        subject=subject,
        body=body,
        gmail={
            "draft_id": draft_id,
            "message_id": message_id,
            "created_at": _utcnow_naive().isoformat(),
            "account_email": connection.account_email,
        },
    )
    db.add(interaction)
    db.commit()

    return schemas.GmailDraftActionResponse(
        success=True,
        message="Gmail draft created. Review it in Gmail or send from SKC Agent OS.",
        interaction_id=interaction.id,
        status="gmail_draft_created",
        account_email=connection.account_email,
        to_email=to_email,
        gmail_draft_id=draft_id,
        gmail_message_id=message_id,
    )


def send_gmail_draft_for_interaction(
    db: Session,
    interaction_id: int,
    *,
    confirm_send: bool,
    review_confirmation: str | None = None,
    bypass_review_confirmation: bool = False,
    subject_override: str | None = None,
    body_override: str | None = None,
) -> schemas.GmailDraftActionResponse:
    if not confirm_send:
        raise ValueError("gmail_send_confirmation_required")
    if not bypass_review_confirmation and not _manual_send_confirmation_valid(review_confirmation):
        raise ValueError("gmail_send_review_confirmation_required")

    draft_result = create_gmail_draft_for_interaction(
        db,
        interaction_id,
        subject_override=subject_override,
        body_override=body_override,
    )
    interaction, contact = _get_email_draft_interaction(db, interaction_id)
    grant, connection = _assert_can_use_gmail(db)
    draft_id = draft_result.gmail_draft_id
    if not draft_id:
        raise ValueError("gmail_draft_id_missing")

    status_code, response = _post_json_with_bearer(
        GMAIL_DRAFTS_SEND_URL,
        access_token=grant.access_token,
        payload={"id": draft_id},
    )
    if status_code == 401:
        raise ValueError("gmail_oauth_access_token_rejected")
    if status_code == 403:
        raise ValueError("gmail_draft_compose_scope_missing")
    if status_code >= 400:
        raise ValueError("gmail_draft_send_failed")

    sent_message_id = _clean_text(response.get("id")) or draft_result.gmail_message_id
    subject, body = _extract_subject_body(interaction)
    _update_gmail_meta(
        interaction,
        status="sent",
        subject=subject,
        body=body,
        gmail={
            "draft_id": draft_id,
            "sent_message_id": sent_message_id,
            "sent_at": _utcnow_naive().isoformat(),
            "account_email": connection.account_email,
        },
    )
    db.add(interaction)
    db.commit()

    return schemas.GmailDraftActionResponse(
        success=True,
        message="Email sent via Gmail.",
        interaction_id=interaction.id,
        status="sent",
        account_email=connection.account_email,
        to_email=contact.email,
        gmail_draft_id=draft_id,
        gmail_message_id=sent_message_id,
    )
