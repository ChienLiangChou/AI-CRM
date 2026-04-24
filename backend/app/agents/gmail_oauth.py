from __future__ import annotations

import base64
import hashlib
import json
import os
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

from . import models, schemas as agent_schemas


LISTING_ALERT_GMAIL_CONNECTION_KEY = "listing_alert_primary"
LISTING_ALERT_GMAIL_USER_ID = "me"
LISTING_ALERT_GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
LISTING_ALERT_GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
LISTING_ALERT_GMAIL_REQUESTED_SCOPES = (
    LISTING_ALERT_GMAIL_READ_SCOPE,
    LISTING_ALERT_GMAIL_COMPOSE_SCOPE,
)
GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
OAUTH_STATE_TTL_MINUTES = 10


@dataclass
class GmailOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    encryption_key: str


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
    )


def is_listing_alert_gmail_oauth_configured() -> bool:
    try:
        _load_oauth_config()
        return True
    except ValueError:
        return False


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
    connection: models.ListingAlertGmailOAuthConnection | None,
) -> agent_schemas.ListingAlertGmailOAuthStatusResponse:
    if connection is None:
        return agent_schemas.ListingAlertGmailOAuthStatusResponse(
            connection_key=LISTING_ALERT_GMAIL_CONNECTION_KEY,
            gmail_user_id=LISTING_ALERT_GMAIL_USER_ID,
            status="disconnected",
            granted_scopes=[],
            oauth_configured=is_listing_alert_gmail_oauth_configured(),
            has_refresh_token=False,
            reconnect_required=False,
        )

    granted_scopes: list[str] = []
    if connection.granted_scopes:
        try:
            granted_scopes = _parse_scopes(json.loads(connection.granted_scopes))
        except (json.JSONDecodeError, TypeError, ValueError):
            granted_scopes = []

    return agent_schemas.ListingAlertGmailOAuthStatusResponse(
        connection_key=connection.connection_key,
        gmail_user_id=connection.gmail_user_id or LISTING_ALERT_GMAIL_USER_ID,
        status=connection.status or "disconnected",
        account_email=connection.account_email,
        granted_scopes=granted_scopes,
        connected_at=connection.connected_at,
        last_refreshed_at=connection.last_refreshed_at,
        last_error=connection.last_error,
        oauth_configured=is_listing_alert_gmail_oauth_configured(),
        has_refresh_token=bool(connection.encrypted_refresh_token),
        reconnect_required=(connection.status == "reconnect_required"),
    )


def _get_connection(
    db: Session,
    *,
    connection_key: str = LISTING_ALERT_GMAIL_CONNECTION_KEY,
) -> models.ListingAlertGmailOAuthConnection | None:
    return (
        db.query(models.ListingAlertGmailOAuthConnection)
        .filter(models.ListingAlertGmailOAuthConnection.connection_key == connection_key)
        .first()
    )


def _get_or_create_connection(
    db: Session,
    *,
    connection_key: str = LISTING_ALERT_GMAIL_CONNECTION_KEY,
) -> models.ListingAlertGmailOAuthConnection:
    connection = _get_connection(db, connection_key=connection_key)
    if connection is not None:
        return connection

    connection = models.ListingAlertGmailOAuthConnection(
        connection_key=connection_key,
        gmail_user_id=LISTING_ALERT_GMAIL_USER_ID,
        status="disconnected",
    )
    db.add(connection)
    db.flush()
    return connection


def _delete_stale_states(db: Session) -> None:
    now = _utcnow_naive()
    (
        db.query(models.ListingAlertGmailOAuthState)
        .filter(
            (models.ListingAlertGmailOAuthState.expires_at < now)
            | (models.ListingAlertGmailOAuthState.used_at.isnot(None))
        )
        .delete(synchronize_session=False)
    )


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _create_state_record(
    db: Session,
    *,
    connection_key: str = LISTING_ALERT_GMAIL_CONNECTION_KEY,
) -> tuple[str, datetime]:
    _delete_stale_states(db)
    now = _utcnow_naive()
    expires_at = now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)
    raw_state = secrets.token_urlsafe(32)
    state_record = models.ListingAlertGmailOAuthState(
        connection_key=connection_key,
        state_hash=_hash_state(raw_state),
        expires_at=expires_at,
    )
    db.add(state_record)
    db.commit()
    return raw_state, expires_at


def _consume_valid_state(
    db: Session,
    raw_state: str,
    *,
    connection_key: str = LISTING_ALERT_GMAIL_CONNECTION_KEY,
) -> None:
    state = _clean_text(raw_state)
    if state is None:
        raise ValueError("gmail_oauth_state_missing")

    state_record = (
        db.query(models.ListingAlertGmailOAuthState)
        .filter(
            models.ListingAlertGmailOAuthState.connection_key == connection_key,
            models.ListingAlertGmailOAuthState.state_hash == _hash_state(state),
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


def get_listing_alert_gmail_oauth_status(
    db: Session,
) -> agent_schemas.ListingAlertGmailOAuthStatusResponse:
    connection = _get_connection(db)
    return _build_status_response(connection)


def start_listing_alert_gmail_oauth(
    db: Session,
) -> agent_schemas.ListingAlertGmailOAuthStartResponse:
    config = _load_oauth_config()
    raw_state, expires_at = _create_state_record(db)
    scope_text = " ".join(LISTING_ALERT_GMAIL_REQUESTED_SCOPES)
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
    return agent_schemas.ListingAlertGmailOAuthStartResponse(
        connection_key=LISTING_ALERT_GMAIL_CONNECTION_KEY,
        authorization_url=authorization_url,
        state_expires_at=expires_at,
        requested_scopes=list(LISTING_ALERT_GMAIL_REQUESTED_SCOPES),
    )


def handle_listing_alert_gmail_oauth_callback(
    db: Session,
    *,
    state: str,
    code: str,
) -> agent_schemas.ListingAlertGmailOAuthStatusResponse:
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

    connection = _get_or_create_connection(db)
    now = _utcnow_naive()
    connection.gmail_user_id = LISTING_ALERT_GMAIL_USER_ID
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


def disconnect_listing_alert_gmail_oauth(
    db: Session,
) -> agent_schemas.ListingAlertGmailOAuthStatusResponse:
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


def refresh_listing_alert_gmail_access_token(
    db: Session,
) -> GmailAccessTokenGrant:
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
        gmail_user_id=connection.gmail_user_id or LISTING_ALERT_GMAIL_USER_ID,
        expires_at=expires_at,
    )


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


def create_listing_alert_gmail_draft(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Create a Gmail draft in the connected mailbox using gmail.compose scope.

    Returns Gmail's draft object (at least `id` and `message.id`) on success.
    Raises ValueError with a stable code for expected failure modes.
    """
    recipient = _clean_text(to_email)
    if recipient is None:
        raise ValueError("gmail_draft_recipient_missing")
    draft_subject = _clean_text(subject)
    if draft_subject is None:
        raise ValueError("gmail_draft_subject_missing")
    draft_body = body.strip() if isinstance(body, str) else ""
    if not draft_body:
        raise ValueError("gmail_draft_body_missing")

    connection = _get_connection(db)
    if connection is None or connection.account_email is None:
        raise ValueError("gmail_oauth_connection_not_ready")

    granted_scopes: list[str] = []
    if connection.granted_scopes:
        try:
            granted_scopes = _parse_scopes(json.loads(connection.granted_scopes))
        except (json.JSONDecodeError, TypeError, ValueError):
            granted_scopes = []
    if LISTING_ALERT_GMAIL_COMPOSE_SCOPE not in granted_scopes:
        raise ValueError("gmail_draft_compose_scope_missing")

    grant = refresh_listing_alert_gmail_access_token(db)
    encoded = _encode_mime_message(
        to_email=recipient,
        from_email=connection.account_email,
        subject=draft_subject,
        body=draft_body,
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
    return response
