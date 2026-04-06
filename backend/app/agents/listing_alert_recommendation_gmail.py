from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from . import (
    gmail_oauth,
    listing_alert_recommendation,
    models,
    schemas as agent_schemas,
    service,
)


GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
DEFAULT_MAX_RESULTS = 10
MAX_ALLOWED_RESULTS = 20


@dataclass
class ResolvedGmailReadConfig:
    config: agent_schemas.ListingAlertGmailReadConfig
    credential_source: str


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_email(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if "<" in lowered and ">" in lowered:
        lowered = lowered.split("<", 1)[1].split(">", 1)[0].strip()
    return lowered or None


def _dedupe_clean_list(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _coerce_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def normalize_gmail_read_config(
    raw: Any,
) -> agent_schemas.ListingAlertGmailReadConfig:
    if isinstance(raw, agent_schemas.ListingAlertGmailReadConfig):
        config = raw
    elif hasattr(raw, "model_dump"):
        config = agent_schemas.ListingAlertGmailReadConfig(**raw.model_dump())
    elif hasattr(raw, "dict"):
        config = agent_schemas.ListingAlertGmailReadConfig(**raw.dict())
    elif isinstance(raw, dict):
        config = agent_schemas.ListingAlertGmailReadConfig(**raw)
    else:
        raise TypeError("gmail_read_config_must_be_dict")

    config.access_token = _clean_text(config.access_token) or ""
    config.gmail_user_id = _clean_text(config.gmail_user_id) or "me"
    config.query_policy.allowed_sender = (
        _normalize_email(config.query_policy.allowed_sender) or ""
    )
    config.query_policy.label_ids = _dedupe_clean_list(config.query_policy.label_ids)
    config.query_policy.subject_keywords = _dedupe_clean_list(
        config.query_policy.subject_keywords
    )
    config.query_policy.max_results = max(
        1,
        min(config.query_policy.max_results or DEFAULT_MAX_RESULTS, MAX_ALLOWED_RESULTS),
    )

    if not config.query_policy.allowed_sender:
        raise ValueError("gmail_allowed_sender_missing")
    if (
        not config.query_policy.label_ids
        and not config.query_policy.subject_keywords
    ):
        raise ValueError("gmail_query_policy_too_broad")

    return config


def _coerce_resolved_gmail_read_config(
    raw: Any,
) -> ResolvedGmailReadConfig:
    if isinstance(raw, ResolvedGmailReadConfig):
        return raw

    normalized_config = normalize_gmail_read_config(raw)
    credential_source = "manual_access_token"
    if not _clean_text(normalized_config.access_token):
        credential_source = "unresolved"
    return ResolvedGmailReadConfig(
        config=normalized_config,
        credential_source=credential_source,
    )


def _refresh_stored_gmail_access_token(
    db: Session,
    resolved_config: ResolvedGmailReadConfig,
) -> None:
    grant = gmail_oauth.refresh_listing_alert_gmail_access_token(db)
    resolved_config.config.access_token = grant.access_token
    resolved_config.config.gmail_user_id = (
        _clean_text(grant.gmail_user_id)
        or resolved_config.config.gmail_user_id
        or gmail_oauth.LISTING_ALERT_GMAIL_USER_ID
    )
    resolved_config.credential_source = "stored_oauth"


def _resolve_gmail_read_config_for_execution(
    db: Session,
    raw: Any,
) -> ResolvedGmailReadConfig:
    resolved_config = _coerce_resolved_gmail_read_config(raw)
    if _clean_text(resolved_config.config.access_token):
        resolved_config.config.access_token = _clean_text(
            resolved_config.config.access_token
        )
        if resolved_config.credential_source != "stored_oauth":
            resolved_config.credential_source = "manual_access_token"
        return resolved_config

    _refresh_stored_gmail_access_token(db, resolved_config)
    return resolved_config


def _quote_query_value(value: str) -> str:
    escaped = value.replace('"', '\\"').strip()
    if " " in escaped:
        return f'"{escaped}"'
    return escaped


def build_constrained_gmail_query(
    policy: agent_schemas.ListingAlertGmailReadQueryPolicy,
) -> str:
    sender = _normalize_email(policy.allowed_sender)
    if not sender:
        raise ValueError("gmail_allowed_sender_missing")

    subject_keywords = _dedupe_clean_list(policy.subject_keywords)
    label_ids = _dedupe_clean_list(policy.label_ids)
    if not label_ids and not subject_keywords:
        raise ValueError("gmail_query_policy_too_broad")

    query_terms = [f"from:{_quote_query_value(sender)}"]
    for keyword in subject_keywords:
        query_terms.append(f"subject:{_quote_query_value(keyword)}")
    return " ".join(query_terms)


def _gmail_api_request_json(
    config: agent_schemas.ListingAlertGmailReadConfig,
    path: str,
    *,
    query_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_id = quote(config.gmail_user_id, safe="")
    encoded_params = urlencode(query_params or {}, doseq=True)
    url = f"{GMAIL_API_BASE_URL}/users/{user_id}/{path}"
    if encoded_params:
        url = f"{url}?{encoded_params}"

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {config.access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request) as response:
            raw = response.read().decode()
    except HTTPError as exc:
        raise ValueError(f"gmail_api_http_error_{exc.code}") from exc
    except URLError as exc:
        raise ValueError("gmail_api_network_error") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("gmail_api_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise ValueError("gmail_api_invalid_response_shape")
    return parsed


def _gmail_api_request_json_with_retry(
    db: Session | None,
    resolved_config: ResolvedGmailReadConfig,
    path: str,
    *,
    query_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _gmail_api_request_json(
            resolved_config.config,
            path,
            query_params=query_params,
        )
    except ValueError as error:
        if (
            db is None
            or str(error) != "gmail_api_http_error_401"
            or resolved_config.credential_source != "stored_oauth"
        ):
            raise

    _refresh_stored_gmail_access_token(db, resolved_config)
    return _gmail_api_request_json(
        resolved_config.config,
        path,
        query_params=query_params,
    )


def list_matching_gmail_message_references(
    config: Any,
    *,
    db: Session | None = None,
) -> tuple[str, list[agent_schemas.ListingAlertGmailMessageReference]]:
    resolved_config = _coerce_resolved_gmail_read_config(config)
    query = build_constrained_gmail_query(resolved_config.config.query_policy)
    response = _gmail_api_request_json_with_retry(
        db,
        resolved_config,
        "messages",
        query_params={
            "q": query,
            "labelIds": resolved_config.config.query_policy.label_ids,
            "maxResults": resolved_config.config.query_policy.max_results,
            "includeSpamTrash": "false",
        },
    )

    refs: list[agent_schemas.ListingAlertGmailMessageReference] = []
    for item in response.get("messages", []):
        if not isinstance(item, dict):
            continue
        message_id = _clean_text(item.get("id"))
        thread_id = _clean_text(item.get("threadId"))
        if message_id is None or thread_id is None:
            continue
        refs.append(
            agent_schemas.ListingAlertGmailMessageReference(
                message_id=message_id,
                thread_id=thread_id,
            )
        )

    return query, refs


def _decode_gmail_body_data(value: str | None) -> str | None:
    if not value:
        return None
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
    except Exception:
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return decoded.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _walk_payload_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [payload]
    for child in payload.get("parts", []) or []:
        if isinstance(child, dict):
            parts.extend(_walk_payload_parts(child))
    return parts


def _extract_text_payload(
    payload: dict[str, Any],
    mime_type: str,
) -> str | None:
    for part in _walk_payload_parts(payload):
        if _clean_text(part.get("mimeType")) != mime_type:
            continue
        body = part.get("body")
        if not isinstance(body, dict):
            continue
        decoded = _decode_gmail_body_data(body.get("data"))
        if _clean_text(decoded):
            return decoded
    return None


def _extract_attachment_names(payload: dict[str, Any]) -> list[str]:
    attachment_names: list[str] = []
    for part in _walk_payload_parts(payload):
        filename = _clean_text(part.get("filename"))
        if filename:
            attachment_names.append(filename)
    return _dedupe_clean_list(attachment_names)


def _extract_header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers")
    if not isinstance(headers, list):
        return {}
    header_map: dict[str, str] = {}
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        value = _clean_text(item.get("value"))
        if name and value:
            header_map[name.lower()] = value
    return header_map


def _parse_received_at(message_data: dict[str, Any], header_map: dict[str, str]) -> datetime | None:
    internal_date = _clean_text(message_data.get("internalDate"))
    if internal_date and internal_date.isdigit():
        try:
            timestamp = int(internal_date) / 1000
            return datetime.fromtimestamp(timestamp, tz=UTC).replace(tzinfo=None)
        except (OverflowError, ValueError):
            pass

    date_header = header_map.get("date")
    if not date_header:
        return None
    try:
        return _coerce_naive_utc(parsedate_to_datetime(date_header))
    except (TypeError, ValueError, IndexError):
        return None


def fetch_normalized_gmail_message(
    config: Any,
    message_ref: Any,
    *,
    db: Session | None = None,
) -> agent_schemas.ListingAlertGmailMessageInput:
    resolved_config = _coerce_resolved_gmail_read_config(config)
    if isinstance(message_ref, agent_schemas.ListingAlertGmailMessageReference):
        reference = message_ref
    elif hasattr(message_ref, "model_dump"):
        reference = agent_schemas.ListingAlertGmailMessageReference(
            **message_ref.model_dump()
        )
    elif hasattr(message_ref, "dict"):
        reference = agent_schemas.ListingAlertGmailMessageReference(
            **message_ref.dict()
        )
    elif isinstance(message_ref, dict):
        reference = agent_schemas.ListingAlertGmailMessageReference(**message_ref)
    else:
        reference = agent_schemas.ListingAlertGmailMessageReference(
            message_id=str(message_ref),
            thread_id=str(message_ref),
        )

    message_data = _gmail_api_request_json_with_retry(
        db,
        resolved_config,
        f"messages/{quote(reference.message_id, safe='')}",
        query_params={"format": "full"},
    )
    payload = message_data.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("gmail_message_payload_missing")

    header_map = _extract_header_map(payload)
    subject = _clean_text(header_map.get("subject"))
    if subject is None:
        raise ValueError("gmail_message_subject_missing")

    label_ids = [
        value
        for value in message_data.get("labelIds", []) or []
        if isinstance(value, str) and _clean_text(value)
    ]

    return agent_schemas.ListingAlertGmailMessageInput(
        message_id=reference.message_id,
        thread_id=_clean_text(message_data.get("threadId")) or reference.thread_id,
        received_at=_parse_received_at(message_data, header_map),
        subject=subject,
        from_address=_normalize_email(header_map.get("from")),
        to_addresses=_dedupe_clean_list(
            [
                email.strip()
                for email in (header_map.get("to") or "").split(",")
                if _clean_text(email)
            ]
        ),
        cc_addresses=_dedupe_clean_list(
            [
                email.strip()
                for email in (header_map.get("cc") or "").split(",")
                if _clean_text(email)
            ]
        ),
        label_ids=_dedupe_clean_list(label_ids),
        snippet=_clean_text(message_data.get("snippet")),
        plain_text_body=_extract_text_payload(payload, "text/plain"),
        html_body=_extract_text_payload(payload, "text/html"),
        attachment_names=_extract_attachment_names(payload),
    )


def _message_matches_query_policy(
    message: agent_schemas.ListingAlertGmailMessageInput,
    policy: agent_schemas.ListingAlertGmailReadQueryPolicy,
) -> str | None:
    if _normalize_email(message.from_address) != _normalize_email(policy.allowed_sender):
        return "sender_not_allowlisted"

    required_labels = set(_dedupe_clean_list(policy.label_ids))
    if required_labels and not required_labels.issubset(set(message.label_ids)):
        return "required_label_missing"

    subject = (_clean_text(message.subject) or "").lower()
    for keyword in _dedupe_clean_list(policy.subject_keywords):
        if keyword.lower() not in subject:
            return "subject_keyword_missing"

    return None


def _extract_message_id_from_task_payload(payload: str | None) -> str | None:
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    gmail_alert = parsed.get("gmail_alert")
    if not isinstance(gmail_alert, dict):
        return None
    return _clean_text(gmail_alert.get("message_id"))


def find_existing_packet_run_by_message_id(
    db: Session,
    *,
    message_id: str,
) -> tuple[models.AgentTask | None, models.AgentRun | None]:
    candidate_tasks = (
        db.query(models.AgentTask)
        .filter(
            models.AgentTask.agent_type
            == listing_alert_recommendation.AGENT_TYPE,
            models.AgentTask.payload.contains(message_id),
        )
        .order_by(models.AgentTask.id.asc())
        .all()
    )

    for task in candidate_tasks:
        if _extract_message_id_from_task_payload(task.payload) != message_id:
            continue
        run = (
            db.query(models.AgentRun)
            .filter(models.AgentRun.task_id == task.id)
            .order_by(models.AgentRun.id.asc())
            .first()
        )
        return task, run

    return None, None


def fetch_gmail_candidates(
    db: Session,
    config: Any,
) -> agent_schemas.ListingAlertGmailFetchCandidatesResponse:
    resolved_config = _resolve_gmail_read_config_for_execution(db, config)
    query, message_refs = list_matching_gmail_message_references(
        resolved_config,
        db=db,
    )
    service.write_audit_log(
        db,
        actor_type="system",
        action="listing_alert_gmail_query_executed",
        details=_safe_json_dumps(
            {
                "gmail_user_id": resolved_config.config.gmail_user_id,
                "query": query,
                "label_ids": resolved_config.config.query_policy.label_ids,
                "matched_message_count": len(message_refs),
                "max_results": resolved_config.config.query_policy.max_results,
            }
        ),
    )

    candidates: list[agent_schemas.ListingAlertGmailCandidateMessage] = []
    for message_ref in message_refs:
        normalized_message = fetch_normalized_gmail_message(
            resolved_config,
            message_ref,
            db=db,
        )
        service.write_audit_log(
            db,
            actor_type="system",
            action="listing_alert_gmail_message_fetched",
            details=_safe_json_dumps(
                {
                    "message_id": normalized_message.message_id,
                    "thread_id": normalized_message.thread_id,
                    "subject": normalized_message.subject,
                }
            ),
        )

        policy_reason = _message_matches_query_policy(
            normalized_message,
            resolved_config.config.query_policy,
        )
        if policy_reason is not None:
            service.write_audit_log(
                db,
                actor_type="system",
                action="listing_alert_gmail_message_policy_skipped",
                details=_safe_json_dumps(
                    {
                        "message_id": normalized_message.message_id,
                        "thread_id": normalized_message.thread_id,
                        "reason": policy_reason,
                    }
                ),
            )
            continue

        existing_task, existing_run = find_existing_packet_run_by_message_id(
            db,
            message_id=normalized_message.message_id,
        )
        candidates.append(
            agent_schemas.ListingAlertGmailCandidateMessage(
                message_id=normalized_message.message_id,
                thread_id=normalized_message.thread_id,
                received_at=normalized_message.received_at,
                subject=normalized_message.subject,
                from_address=normalized_message.from_address,
                label_ids=normalized_message.label_ids,
                existing_task_id=existing_task.id if existing_task else None,
                existing_run_id=existing_run.id if existing_run else None,
            )
        )

    return agent_schemas.ListingAlertGmailFetchCandidatesResponse(
        gmail_user_id=resolved_config.config.gmail_user_id,
        query=query,
        matched_message_count=len(message_refs),
        candidate_count=len(candidates),
        candidates=candidates,
    )


def import_gmail_message_reference(
    db: Session,
    config: Any,
    message_ref: Any,
    *,
    expected_contact_id: int | None = None,
    explicit_contact_mappings: list[
        agent_schemas.ListingAlertExplicitContactMappingInput
    ] | None = None,
    operator_notes: str | None = None,
) -> agent_schemas.ListingAlertGmailImportOutcome:
    resolved_config = _resolve_gmail_read_config_for_execution(db, config)
    if isinstance(message_ref, agent_schemas.ListingAlertGmailMessageReference):
        reference = message_ref
    elif hasattr(message_ref, "model_dump"):
        reference = agent_schemas.ListingAlertGmailMessageReference(
            **message_ref.model_dump()
        )
    elif hasattr(message_ref, "dict"):
        reference = agent_schemas.ListingAlertGmailMessageReference(
            **message_ref.dict()
        )
    elif isinstance(message_ref, dict):
        reference = agent_schemas.ListingAlertGmailMessageReference(**message_ref)
    else:
        message_id = _clean_text(message_ref)
        if message_id is None:
            raise ValueError("gmail_message_id_missing")
        reference = agent_schemas.ListingAlertGmailMessageReference(
            message_id=message_id,
            thread_id=message_id,
        )

    existing_task, existing_run = find_existing_packet_run_by_message_id(
        db,
        message_id=reference.message_id,
    )
    if existing_task is not None:
        service.write_audit_log(
            db,
            run=existing_run,
            task=existing_task,
            actor_type="system",
            action="listing_alert_gmail_message_duplicate_skipped",
            details=_safe_json_dumps(
                {
                    "message_id": reference.message_id,
                    "thread_id": reference.thread_id,
                    "existing_task_id": existing_task.id,
                    "existing_run_id": existing_run.id if existing_run else None,
                }
            ),
        )
        return agent_schemas.ListingAlertGmailImportOutcome(
            status="duplicate_skipped",
            message_id=reference.message_id,
            thread_id=reference.thread_id,
            existing_task_id=existing_task.id,
            existing_run_id=existing_run.id if existing_run else None,
            reason="message_id_already_imported",
        )

    normalized_message = fetch_normalized_gmail_message(
        resolved_config,
        reference,
        db=db,
    )
    service.write_audit_log(
        db,
        actor_type="system",
        action="listing_alert_gmail_message_fetched",
        details=_safe_json_dumps(
            {
                "message_id": normalized_message.message_id,
                "thread_id": normalized_message.thread_id,
                "subject": normalized_message.subject,
            }
        ),
    )

    policy_reason = _message_matches_query_policy(
        normalized_message,
        resolved_config.config.query_policy,
    )
    if policy_reason is not None:
        service.write_audit_log(
            db,
            actor_type="system",
            action="listing_alert_gmail_message_policy_skipped",
            details=_safe_json_dumps(
                {
                    "message_id": normalized_message.message_id,
                    "thread_id": normalized_message.thread_id,
                    "reason": policy_reason,
                }
            ),
        )
        return agent_schemas.ListingAlertGmailImportOutcome(
            status="policy_skipped",
            message_id=normalized_message.message_id,
            thread_id=normalized_message.thread_id,
            received_at=normalized_message.received_at,
            subject=normalized_message.subject,
            normalized_message=normalized_message,
            reason=policy_reason,
        )

    run_request = agent_schemas.ListingAlertRunRequest(
        execution_mode="manual",
        gmail_alert=normalized_message,
        expected_contact_id=expected_contact_id,
        explicit_contact_mappings=explicit_contact_mappings or [],
        operator_notes=(
            _clean_text(operator_notes)
            or "Imported from Gmail API read-only intake."
        ),
    )
    run = listing_alert_recommendation.run_listing_alert_manual_packet_once(db, run_request)
    task = run.task
    service.write_audit_log(
        db,
        run=run,
        task=task,
        actor_type="system",
        action="listing_alert_gmail_message_imported",
        details=_safe_json_dumps(
            {
                "message_id": normalized_message.message_id,
                "thread_id": normalized_message.thread_id,
                "task_id": task.id if task else None,
                "run_id": run.id,
            }
        ),
    )
    return agent_schemas.ListingAlertGmailImportOutcome(
        status="imported",
        message_id=normalized_message.message_id,
        thread_id=normalized_message.thread_id,
        received_at=normalized_message.received_at,
        subject=normalized_message.subject,
        normalized_message=normalized_message,
        imported_task_id=task.id if task else None,
        imported_run_id=run.id,
    )


def fetch_and_import_gmail_alerts(
    db: Session,
    config: Any,
    *,
    expected_contact_id: int | None = None,
    explicit_contact_mappings: list[
        agent_schemas.ListingAlertExplicitContactMappingInput
    ] | None = None,
    operator_notes: str | None = None,
) -> agent_schemas.ListingAlertGmailImportBatchResult:
    resolved_config = _resolve_gmail_read_config_for_execution(db, config)
    query, message_refs = list_matching_gmail_message_references(
        resolved_config,
        db=db,
    )
    service.write_audit_log(
        db,
        actor_type="system",
        action="listing_alert_gmail_query_executed",
        details=_safe_json_dumps(
            {
                "gmail_user_id": resolved_config.config.gmail_user_id,
                "query": query,
                "label_ids": resolved_config.config.query_policy.label_ids,
                "matched_message_count": len(message_refs),
                "max_results": resolved_config.config.query_policy.max_results,
            }
        ),
    )

    outcomes: list[agent_schemas.ListingAlertGmailImportOutcome] = []
    for message_ref in message_refs:
        outcomes.append(
            import_gmail_message_reference(
                db,
                resolved_config,
                message_ref,
                expected_contact_id=expected_contact_id,
                explicit_contact_mappings=explicit_contact_mappings,
                operator_notes=operator_notes,
            )
        )

    return agent_schemas.ListingAlertGmailImportBatchResult(
        gmail_user_id=resolved_config.config.gmail_user_id,
        query=query,
        matched_message_count=len(message_refs),
        outcomes=outcomes,
    )
