from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service


OTP_TIMEOUT_MINUTES = 5
MLS_AUTH_AGENT_TYPE = "mls_auth"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _new_reference(prefix: str, provider: agent_schemas.MlsAuthProviderKey) -> str:
    return f"mls_auth_{prefix}_{provider}_{uuid4().hex[:12]}"


def _is_active_state(state: agent_schemas.MlsAuthState) -> bool:
    return state in {"auth_in_progress", "awaiting_otp"}


def _model_dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return model


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _json_loads(raw: str | None) -> Any | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _validate_schema(schema_cls: type[BaseException] | Any, payload: Any):
    if hasattr(schema_cls, "model_validate"):
        return schema_cls.model_validate(payload)
    return schema_cls.parse_obj(payload)


def build_initial_status(
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    *,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStatusResponse:
    timestamp = now or _utcnow_naive()
    return agent_schemas.MlsAuthStatusResponse(
        provider=provider,
        state="unauthenticated",
        available=False,
        last_checked_at=timestamp,
    )


def _clone_status(
    status: agent_schemas.MlsAuthStatusResponse,
) -> agent_schemas.MlsAuthStatusResponse:
    if hasattr(status, "model_copy"):
        return status.model_copy(deep=True)
    return status.copy(deep=True)


def _clone_attempt(
    attempt: agent_schemas.MlsAuthAttemptRecord,
) -> agent_schemas.MlsAuthAttemptRecord:
    if hasattr(attempt, "model_copy"):
        return attempt.model_copy(deep=True)
    return attempt.copy(deep=True)


def start_auth_attempt(
    *,
    request: agent_schemas.MlsAuthStartRequest,
    current_status: agent_schemas.MlsAuthStatusResponse | None = None,
    active_attempt: agent_schemas.MlsAuthAttemptRecord | None = None,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStartResponse:
    timestamp = now or _utcnow_naive()
    baseline_status = current_status or build_initial_status(
        request.provider,
        now=timestamp,
    )
    status = _clone_status(baseline_status)

    if status.provider != request.provider:
        raise ValueError("provider_mismatch")

    if active_attempt is not None:
        active_attempt = _clone_attempt(active_attempt)
        if active_attempt.provider != request.provider:
            raise ValueError("provider_mismatch")

        status, active_attempt, expired = expire_otp_attempt_if_needed(
            status=status,
            attempt=active_attempt,
            now=timestamp,
        )
        if (
            not expired
            and _is_active_state(status.state)
            and active_attempt.finished_at is None
            and status.active_attempt_reference == active_attempt.attempt_reference
        ):
            status.last_checked_at = timestamp
            return agent_schemas.MlsAuthStartResponse(
                status=status,
                attempt=active_attempt,
                reused_existing_attempt=True,
            )

    attempt_reference = _new_reference("attempt", request.provider)
    session_reference = _new_reference("session", request.provider)

    status.state = "auth_in_progress"
    status.available = False
    status.mode = request.mode
    status.last_checked_at = timestamp
    status.failure_reason = None
    status.session_reference = session_reference
    status.active_attempt_reference = attempt_reference
    status.otp_requested_at = None
    status.otp_timeout_at = None
    status.expires_at = None

    attempt = agent_schemas.MlsAuthAttemptRecord(
        attempt_reference=attempt_reference,
        provider=request.provider,
        state="auth_in_progress",
        mode=request.mode,
        session_reference=session_reference,
        started_at=timestamp,
        updated_at=timestamp,
        finished_at=None,
        otp_required=False,
        otp_requested_at=None,
        otp_timeout_at=None,
        otp_submitted_at=None,
        failure_reason=None,
    )

    return agent_schemas.MlsAuthStartResponse(
        status=status,
        attempt=attempt,
        reused_existing_attempt=False,
    )


def mark_otp_required(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
    now: datetime | None = None,
    timeout_minutes: int = OTP_TIMEOUT_MINUTES,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)
    next_attempt = _clone_attempt(attempt)

    if next_status.provider != next_attempt.provider:
        raise ValueError("provider_mismatch")
    if next_status.active_attempt_reference != next_attempt.attempt_reference:
        raise ValueError("auth_attempt_mismatch")
    if next_status.state != "auth_in_progress" or next_attempt.state != "auth_in_progress":
        raise ValueError("auth_not_in_progress")

    timeout_at = timestamp + timedelta(minutes=timeout_minutes)

    next_status.state = "awaiting_otp"
    next_status.available = False
    next_status.last_checked_at = timestamp
    next_status.otp_requested_at = timestamp
    next_status.otp_timeout_at = timeout_at
    next_status.failure_reason = None

    next_attempt.state = "awaiting_otp"
    next_attempt.updated_at = timestamp
    next_attempt.otp_required = True
    next_attempt.otp_requested_at = timestamp
    next_attempt.otp_timeout_at = timeout_at
    next_attempt.failure_reason = None

    return next_status, next_attempt


def submit_otp_for_attempt(
    *,
    request: agent_schemas.MlsAuthSubmitOtpRequest,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthSubmitOtpResponse:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)
    next_attempt = _clone_attempt(attempt)

    if next_status.provider != request.provider or next_attempt.provider != request.provider:
        raise ValueError("provider_mismatch")

    next_status, next_attempt, expired = expire_otp_attempt_if_needed(
        status=next_status,
        attempt=next_attempt,
        now=timestamp,
    )
    if expired:
        return agent_schemas.MlsAuthSubmitOtpResponse(
            status=next_status,
            attempt=next_attempt,
            otp_accepted=False,
        )

    if next_status.state != "awaiting_otp" or next_attempt.state != "awaiting_otp":
        raise ValueError("otp_not_requested")
    if next_status.active_attempt_reference != next_attempt.attempt_reference:
        raise ValueError("auth_attempt_mismatch")
    if request.attempt_reference != next_attempt.attempt_reference:
        raise ValueError("auth_attempt_mismatch")
    if request.session_reference != next_status.session_reference:
        raise ValueError("session_reference_mismatch")
    if request.session_reference != next_attempt.session_reference:
        raise ValueError("session_reference_mismatch")
    if _clean_text(request.otp_code) is None:
        raise ValueError("otp_code_required")

    next_status.state = "auth_in_progress"
    next_status.available = False
    next_status.last_checked_at = timestamp
    next_status.failure_reason = None
    next_status.otp_requested_at = None
    next_status.otp_timeout_at = None

    next_attempt.state = "auth_in_progress"
    next_attempt.updated_at = timestamp
    next_attempt.otp_submitted_at = timestamp
    next_attempt.failure_reason = None

    return agent_schemas.MlsAuthSubmitOtpResponse(
        status=next_status,
        attempt=next_attempt,
        otp_accepted=True,
    )


def mark_auth_available(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)
    next_attempt = _clone_attempt(attempt)

    if next_status.active_attempt_reference != next_attempt.attempt_reference:
        raise ValueError("auth_attempt_mismatch")

    next_status.state = "available"
    next_status.available = True
    next_status.last_checked_at = timestamp
    next_status.last_success_at = timestamp
    next_status.failure_reason = None
    next_status.active_attempt_reference = None
    next_status.otp_requested_at = None
    next_status.otp_timeout_at = None
    next_status.expires_at = expires_at

    next_attempt.state = "available"
    next_attempt.updated_at = timestamp
    next_attempt.finished_at = timestamp
    next_attempt.failure_reason = None

    return next_status, next_attempt


def mark_auth_failed(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
    failure_reason: agent_schemas.MlsAuthFailureReason,
    now: datetime | None = None,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)
    next_attempt = _clone_attempt(attempt)

    if next_status.provider != next_attempt.provider:
        raise ValueError("provider_mismatch")

    next_status.state = "failed"
    next_status.available = False
    next_status.last_checked_at = timestamp
    next_status.last_failure_at = timestamp
    next_status.failure_reason = failure_reason
    next_status.active_attempt_reference = None
    next_status.otp_requested_at = None
    next_status.otp_timeout_at = None
    next_status.expires_at = None

    next_attempt.state = "failed"
    next_attempt.updated_at = timestamp
    next_attempt.finished_at = timestamp
    next_attempt.failure_reason = failure_reason

    return next_status, next_attempt


def expire_session(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStatusResponse:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)

    next_status.state = "expired"
    next_status.available = False
    next_status.last_checked_at = timestamp
    next_status.last_failure_at = timestamp
    next_status.failure_reason = "session_expired"
    next_status.active_attempt_reference = None
    next_status.otp_requested_at = None
    next_status.otp_timeout_at = None
    next_status.expires_at = None

    return next_status


def expire_otp_attempt_if_needed(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
    now: datetime | None = None,
) -> tuple[
    agent_schemas.MlsAuthStatusResponse,
    agent_schemas.MlsAuthAttemptRecord,
    bool,
]:
    timestamp = now or _utcnow_naive()
    next_status = _clone_status(status)
    next_attempt = _clone_attempt(attempt)

    timeout_at = next_status.otp_timeout_at or next_attempt.otp_timeout_at
    if (
        next_status.state == "awaiting_otp"
        and next_attempt.state == "awaiting_otp"
        and timeout_at is not None
        and timestamp >= timeout_at
    ):
        failed_status, failed_attempt = mark_auth_failed(
            status=next_status,
            attempt=next_attempt,
            failure_reason="otp_timeout",
            now=timestamp,
        )
        return failed_status, failed_attempt, True

    return next_status, next_attempt, False


def build_history_response(
    *,
    current_status: agent_schemas.MlsAuthStatusResponse,
    attempts: list[agent_schemas.MlsAuthAttemptRecord],
) -> agent_schemas.MlsAuthHistoryResponse:
    sorted_attempts = sorted(
        attempts,
        key=lambda attempt: (attempt.started_at, attempt.updated_at),
        reverse=True,
    )
    return agent_schemas.MlsAuthHistoryResponse(
        current_status=_clone_status(current_status),
        attempts=[_clone_attempt(attempt) for attempt in sorted_attempts],
    )


def _task_status_from_auth_state(state: agent_schemas.MlsAuthState) -> str:
    if state in {"auth_in_progress", "awaiting_otp"}:
        return "executing"
    if state == "failed":
        return "failed"
    return "completed"


def _run_status_from_auth_state(state: agent_schemas.MlsAuthState) -> str:
    if state in {"auth_in_progress", "awaiting_otp"}:
        return "executing"
    if state == "available":
        return "completed"
    return "failed"


def _build_task_payload(status: agent_schemas.MlsAuthStatusResponse) -> str:
    return _json_dumps(
        {
            "provider": status.provider,
            "current_status": _model_dump(status),
            "internal_only": True,
        }
    )


def _build_run_plan(
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    mode: agent_schemas.MlsAuthMode,
    attempt: agent_schemas.MlsAuthAttemptRecord,
) -> str:
    return _json_dumps(
        {
            "provider": provider,
            "mode": mode,
            "attempt": _model_dump(attempt),
            "execution_policy": {
                "internal_only": True,
                "otp_human_supplied": True,
                "browser_automation_started": False,
            },
        }
    )


def _build_run_result(
    *,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
) -> str:
    return _json_dumps(
        {
            "current_status": _model_dump(status),
            "attempt": _model_dump(attempt),
            "internal_only": True,
            "otp_human_supplied": True,
        }
    )


def _parse_status_from_task(
    task: models.AgentTask | None,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStatusResponse:
    default_status = build_initial_status(provider, now=now)
    if task is None:
        return default_status

    parsed = _json_loads(task.payload)
    if not isinstance(parsed, dict):
        return default_status

    raw_status = parsed.get("current_status") or parsed.get("status")
    if not isinstance(raw_status, dict):
        return default_status

    try:
        status = _validate_schema(agent_schemas.MlsAuthStatusResponse, raw_status)
    except Exception:
        return default_status

    if status.provider != provider:
        return default_status
    return status


def _parse_attempt_from_run(
    run: models.AgentRun,
) -> agent_schemas.MlsAuthAttemptRecord | None:
    for raw_payload in (run.result, run.plan):
        parsed = _json_loads(raw_payload)
        if not isinstance(parsed, dict):
            continue
        raw_attempt = parsed.get("attempt")
        if not isinstance(raw_attempt, dict):
            continue
        try:
            return _validate_schema(agent_schemas.MlsAuthAttemptRecord, raw_attempt)
        except Exception:
            continue
    return None


def _get_provider_task(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
) -> models.AgentTask | None:
    return (
        db.query(models.AgentTask)
        .filter(
            models.AgentTask.agent_type == MLS_AUTH_AGENT_TYPE,
            models.AgentTask.subject_type == provider,
        )
        .order_by(models.AgentTask.created_at.desc())
        .first()
    )


def _get_or_create_provider_task(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    mode: agent_schemas.MlsAuthMode,
    now: datetime | None = None,
) -> models.AgentTask:
    task = _get_provider_task(db, provider=provider)
    if task is not None:
        return task

    initial_status = build_initial_status(provider, now=now)
    task = models.AgentTask(
        agent_type=MLS_AUTH_AGENT_TYPE,
        subject_type=provider,
        subject_id=None,
        payload=_build_task_payload(initial_status),
        status=_task_status_from_auth_state(initial_status.state),
        priority="normal",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _create_attempt_run(
    db: Session,
    *,
    task: models.AgentTask,
    provider: agent_schemas.MlsAuthProviderKey,
    mode: agent_schemas.MlsAuthMode,
    status: agent_schemas.MlsAuthStatusResponse,
    attempt: agent_schemas.MlsAuthAttemptRecord,
) -> models.AgentRun:
    run = models.AgentRun(
        task_id=task.id,
        status=_run_status_from_auth_state(status.state),
        summary=f"MLS auth attempt for {provider}",
        plan=_build_run_plan(provider=provider, mode=mode, attempt=attempt),
        result=_build_run_result(status=status, attempt=attempt),
        error=attempt.failure_reason,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _persist_status_snapshot(
    db: Session,
    *,
    task: models.AgentTask,
    status: agent_schemas.MlsAuthStatusResponse,
    run: models.AgentRun | None = None,
    attempt: agent_schemas.MlsAuthAttemptRecord | None = None,
    mode: agent_schemas.MlsAuthMode | None = None,
) -> None:
    task.payload = _build_task_payload(status)
    task.status = _task_status_from_auth_state(status.state)

    if run is not None and attempt is not None:
        run.status = _run_status_from_auth_state(status.state)
        if mode is not None:
            run.plan = _build_run_plan(
                provider=status.provider,
                mode=mode,
                attempt=attempt,
            )
        run.result = _build_run_result(status=status, attempt=attempt)
        run.error = attempt.failure_reason
        if run.started_at is None:
            run.started_at = attempt.started_at
        run.finished_at = attempt.finished_at

    db.commit()
    db.refresh(task)
    if run is not None:
        db.refresh(run)


def _write_transition_audit_log(
    db: Session,
    *,
    task: models.AgentTask,
    action: str,
    provider: agent_schemas.MlsAuthProviderKey,
    from_state: agent_schemas.MlsAuthState | None,
    to_state: agent_schemas.MlsAuthState,
    run: models.AgentRun | None = None,
    attempt: agent_schemas.MlsAuthAttemptRecord | None = None,
    failure_reason: agent_schemas.MlsAuthFailureReason | None = None,
    extra: dict[str, Any] | None = None,
) -> models.AgentAuditLog:
    details = {
        "provider": provider,
        "from_state": from_state,
        "to_state": to_state,
        "attempt_reference": attempt.attempt_reference if attempt else None,
        "session_reference": (
            attempt.session_reference
            if attempt is not None
            else None
        ),
        "failure_reason": failure_reason,
    }
    if extra:
        details.update(extra)
    clean_details = {key: value for key, value in details.items() if value is not None}
    return service.write_audit_log(
        db,
        run=run,
        task=task,
        actor_type="system",
        action=action,
        details=_json_dumps(clean_details),
    )


def _get_attempt_run(
    db: Session,
    *,
    task: models.AgentTask,
    attempt_reference: str,
) -> tuple[models.AgentRun | None, agent_schemas.MlsAuthAttemptRecord | None]:
    runs = (
        db.query(models.AgentRun)
        .filter(models.AgentRun.task_id == task.id)
        .order_by(models.AgentRun.created_at.desc())
        .all()
    )
    for run in runs:
        attempt = _parse_attempt_from_run(run)
        if attempt is None:
            continue
        if attempt.attempt_reference == attempt_reference:
            return run, attempt
    return None, None


def _get_active_attempt_run(
    db: Session,
    *,
    task: models.AgentTask,
    status: agent_schemas.MlsAuthStatusResponse,
) -> tuple[models.AgentRun | None, agent_schemas.MlsAuthAttemptRecord | None]:
    if not status.active_attempt_reference:
        return None, None
    return _get_attempt_run(
        db,
        task=task,
        attempt_reference=status.active_attempt_reference,
    )


def _recover_inconsistent_active_state(
    db: Session,
    *,
    task: models.AgentTask,
    status: agent_schemas.MlsAuthStatusResponse,
    now: datetime,
) -> agent_schemas.MlsAuthStatusResponse:
    if not _is_active_state(status.state) or not status.active_attempt_reference:
        return status

    recovered_status = _clone_status(status)
    recovered_status.state = "failed"
    recovered_status.available = False
    recovered_status.last_checked_at = now
    recovered_status.last_failure_at = now
    recovered_status.failure_reason = "unknown_auth_failure"
    recovered_status.active_attempt_reference = None
    recovered_status.otp_requested_at = None
    recovered_status.otp_timeout_at = None
    recovered_status.expires_at = None

    _persist_status_snapshot(
        db,
        task=task,
        status=recovered_status,
    )
    _write_transition_audit_log(
        db,
        task=task,
        action="mls_auth_inconsistent_active_state_recovered",
        provider=recovered_status.provider,
        from_state=status.state,
        to_state=recovered_status.state,
        failure_reason="unknown_auth_failure",
        extra={
            "previous_active_attempt_reference": status.active_attempt_reference,
        },
    )
    return recovered_status


def _persist_timeout_if_needed(
    db: Session,
    *,
    task: models.AgentTask,
    status: agent_schemas.MlsAuthStatusResponse,
    run: models.AgentRun | None,
    attempt: agent_schemas.MlsAuthAttemptRecord | None,
    now: datetime,
) -> tuple[
    agent_schemas.MlsAuthStatusResponse,
    models.AgentRun | None,
    agent_schemas.MlsAuthAttemptRecord | None,
    bool,
]:
    if run is None or attempt is None:
        return status, run, attempt, False

    next_status, next_attempt, expired = expire_otp_attempt_if_needed(
        status=status,
        attempt=attempt,
        now=now,
    )
    if not expired:
        return next_status, run, next_attempt, False

    _persist_status_snapshot(
        db,
        task=task,
        status=next_status,
        run=run,
        attempt=next_attempt,
        mode=next_attempt.mode,
    )
    _write_transition_audit_log(
        db,
        task=task,
        run=run,
        action="mls_auth_otp_timed_out",
        provider=next_status.provider,
        from_state="awaiting_otp",
        to_state=next_status.state,
        attempt=next_attempt,
        failure_reason=next_attempt.failure_reason,
    )
    return next_status, run, next_attempt, True


def load_persisted_status(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStatusResponse:
    timestamp = now or _utcnow_naive()
    task = _get_provider_task(db, provider=provider)
    status = _parse_status_from_task(task, provider=provider, now=timestamp)
    if task is None:
        return status

    active_run, active_attempt = _get_active_attempt_run(
        db,
        task=task,
        status=status,
    )
    if _is_active_state(status.state) and active_attempt is None:
        return _recover_inconsistent_active_state(
            db,
            task=task,
            status=status,
            now=timestamp,
        )

    status, _, _, _ = _persist_timeout_if_needed(
        db,
        task=task,
        status=status,
        run=active_run,
        attempt=active_attempt,
        now=timestamp,
    )
    return status


def load_persisted_history(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    now: datetime | None = None,
) -> agent_schemas.MlsAuthHistoryResponse:
    status = load_persisted_status(db, provider=provider, now=now)
    task = _get_provider_task(db, provider=provider)
    if task is None:
        return build_history_response(current_status=status, attempts=[])

    runs = (
        db.query(models.AgentRun)
        .filter(models.AgentRun.task_id == task.id)
        .order_by(models.AgentRun.created_at.desc())
        .all()
    )
    attempts = [attempt for attempt in (_parse_attempt_from_run(run) for run in runs) if attempt]
    return build_history_response(current_status=status, attempts=attempts)


def start_auth_attempt_persisted(
    db: Session,
    *,
    request: agent_schemas.MlsAuthStartRequest,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthStartResponse:
    timestamp = now or _utcnow_naive()
    task = _get_or_create_provider_task(
        db,
        provider=request.provider,
        mode=request.mode,
        now=timestamp,
    )
    current_status = _parse_status_from_task(task, provider=request.provider, now=timestamp)
    active_run, active_attempt = _get_active_attempt_run(
        db,
        task=task,
        status=current_status,
    )

    if _is_active_state(current_status.state) and active_attempt is None:
        current_status = _recover_inconsistent_active_state(
            db,
            task=task,
            status=current_status,
            now=timestamp,
        )
        active_run = None

    current_status, active_run, active_attempt, _ = _persist_timeout_if_needed(
        db,
        task=task,
        status=current_status,
        run=active_run,
        attempt=active_attempt,
        now=timestamp,
    )

    response = start_auth_attempt(
        request=request,
        current_status=current_status,
        active_attempt=active_attempt,
        now=timestamp,
    )

    if response.reused_existing_attempt:
        if active_run is None:
            raise ValueError("active_attempt_missing")
        _persist_status_snapshot(
            db,
            task=task,
            status=response.status,
            run=active_run,
            attempt=response.attempt,
            mode=response.attempt.mode,
        )
        _write_transition_audit_log(
            db,
            task=task,
            run=active_run,
            action="mls_auth_attempt_reused",
            provider=request.provider,
            from_state=current_status.state,
            to_state=response.status.state,
            attempt=response.attempt,
            extra={"reused_existing_attempt": True},
        )
        return response

    new_run = _create_attempt_run(
        db,
        task=task,
        provider=request.provider,
        mode=request.mode,
        status=response.status,
        attempt=response.attempt,
    )
    _persist_status_snapshot(
        db,
        task=task,
        status=response.status,
        run=new_run,
        attempt=response.attempt,
        mode=request.mode,
    )
    _write_transition_audit_log(
        db,
        task=task,
        run=new_run,
        action="mls_auth_attempt_started",
        provider=request.provider,
        from_state=current_status.state,
        to_state=response.status.state,
        attempt=response.attempt,
    )
    return response


def mark_otp_required_persisted(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    attempt_reference: str,
    now: datetime | None = None,
    timeout_minutes: int = OTP_TIMEOUT_MINUTES,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    task = _get_provider_task(db, provider=provider)
    if task is None:
        raise ValueError("provider_task_missing")

    status = load_persisted_status(db, provider=provider, now=timestamp)
    run, attempt = _get_attempt_run(db, task=task, attempt_reference=attempt_reference)
    if run is None or attempt is None:
        raise ValueError("auth_attempt_not_found")

    next_status, next_attempt = mark_otp_required(
        status=status,
        attempt=attempt,
        now=timestamp,
        timeout_minutes=timeout_minutes,
    )
    _persist_status_snapshot(
        db,
        task=task,
        status=next_status,
        run=run,
        attempt=next_attempt,
        mode=next_attempt.mode,
    )
    _write_transition_audit_log(
        db,
        task=task,
        run=run,
        action="mls_auth_otp_requested",
        provider=provider,
        from_state=status.state,
        to_state=next_status.state,
        attempt=next_attempt,
        extra={"otp_timeout_at": next_attempt.otp_timeout_at},
    )
    return next_status, next_attempt


def submit_otp_for_attempt_persisted(
    db: Session,
    *,
    request: agent_schemas.MlsAuthSubmitOtpRequest,
    now: datetime | None = None,
) -> agent_schemas.MlsAuthSubmitOtpResponse:
    timestamp = now or _utcnow_naive()
    task = _get_provider_task(db, provider=request.provider)
    if task is None:
        raise ValueError("provider_task_missing")

    status = load_persisted_status(db, provider=request.provider, now=timestamp)
    run, attempt = _get_attempt_run(
        db,
        task=task,
        attempt_reference=request.attempt_reference,
    )
    if run is None or attempt is None:
        raise ValueError("auth_attempt_not_found")

    from_state = status.state
    response = submit_otp_for_attempt(
        request=request,
        status=status,
        attempt=attempt,
        now=timestamp,
    )
    _persist_status_snapshot(
        db,
        task=task,
        status=response.status,
        run=run,
        attempt=response.attempt,
        mode=response.attempt.mode,
    )
    if response.otp_accepted:
        _write_transition_audit_log(
            db,
            task=task,
            run=run,
            action="mls_auth_otp_submitted",
            provider=request.provider,
            from_state=from_state,
            to_state=response.status.state,
            attempt=response.attempt,
        )
    else:
        _write_transition_audit_log(
            db,
            task=task,
            run=run,
            action="mls_auth_otp_timed_out",
            provider=request.provider,
            from_state=from_state,
            to_state=response.status.state,
            attempt=response.attempt,
            failure_reason=response.attempt.failure_reason,
        )
    return response


def mark_auth_available_persisted(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    attempt_reference: str,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    task = _get_provider_task(db, provider=provider)
    if task is None:
        raise ValueError("provider_task_missing")

    status = load_persisted_status(db, provider=provider, now=timestamp)
    run, attempt = _get_attempt_run(db, task=task, attempt_reference=attempt_reference)
    if run is None or attempt is None:
        raise ValueError("auth_attempt_not_found")

    next_status, next_attempt = mark_auth_available(
        status=status,
        attempt=attempt,
        now=timestamp,
        expires_at=expires_at,
    )
    _persist_status_snapshot(
        db,
        task=task,
        status=next_status,
        run=run,
        attempt=next_attempt,
        mode=next_attempt.mode,
    )
    _write_transition_audit_log(
        db,
        task=task,
        run=run,
        action="mls_auth_available",
        provider=provider,
        from_state=status.state,
        to_state=next_status.state,
        attempt=next_attempt,
    )
    return next_status, next_attempt


def mark_auth_failed_persisted(
    db: Session,
    *,
    provider: agent_schemas.MlsAuthProviderKey,
    attempt_reference: str,
    failure_reason: agent_schemas.MlsAuthFailureReason,
    now: datetime | None = None,
) -> tuple[agent_schemas.MlsAuthStatusResponse, agent_schemas.MlsAuthAttemptRecord]:
    timestamp = now or _utcnow_naive()
    task = _get_provider_task(db, provider=provider)
    if task is None:
        raise ValueError("provider_task_missing")

    status = load_persisted_status(db, provider=provider, now=timestamp)
    run, attempt = _get_attempt_run(db, task=task, attempt_reference=attempt_reference)
    if run is None or attempt is None:
        raise ValueError("auth_attempt_not_found")

    next_status, next_attempt = mark_auth_failed(
        status=status,
        attempt=attempt,
        failure_reason=failure_reason,
        now=timestamp,
    )
    _persist_status_snapshot(
        db,
        task=task,
        status=next_status,
        run=run,
        attempt=next_attempt,
        mode=next_attempt.mode,
    )
    _write_transition_audit_log(
        db,
        task=task,
        run=run,
        action="mls_auth_failed",
        provider=provider,
        from_state=status.state,
        to_state=next_status.state,
        attempt=next_attempt,
        failure_reason=failure_reason,
    )
    return next_status, next_attempt
