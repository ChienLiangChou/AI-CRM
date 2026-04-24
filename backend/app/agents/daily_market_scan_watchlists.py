from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import daily_market_scan, models, schemas as agent_schemas, service


WATCHLIST_SCHEDULER_KEY = "daily_market_scan_watchlist_scheduler"
WATCHLIST_SCHEDULER_POLL_INTERVAL_SECONDS = 300
DEFAULT_WATCHLIST_LIMIT = 100


def _utcnow() -> datetime:
    return datetime.utcnow()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe_clean_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _json_dumps(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False)


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return _dedupe_clean_list(parsed)


def _normalized_watchlist_run_request(
    raw: agent_schemas.DailyMarketScanRunRequest | dict[str, Any] | Any,
) -> agent_schemas.DailyMarketScanRunRequest:
    normalized = daily_market_scan.normalize_run_request(raw)
    normalized.run_mode = "scheduled_monitor"
    return normalized


def normalize_watchlist_upsert_request(
    raw: agent_schemas.DailyMarketScanWatchlistUpsertRequest | dict[str, Any] | Any,
) -> agent_schemas.DailyMarketScanWatchlistUpsertRequest:
    if isinstance(raw, agent_schemas.DailyMarketScanWatchlistUpsertRequest):
        payload = raw.model_dump()
    elif hasattr(raw, "model_dump"):
        payload = raw.model_dump()
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        raise TypeError("daily_market_scan_watchlist_request_must_be_dict")

    name = _clean_text(payload.get("name"))
    if name is None:
        raise ValueError("daily_market_scan_watchlist_name_required")

    interval_raw = payload.get("schedule_interval_minutes", 60)
    if isinstance(interval_raw, bool):
        raise ValueError("daily_market_scan_watchlist_interval_invalid")
    try:
        interval = int(interval_raw)
    except (TypeError, ValueError):
        raise ValueError("daily_market_scan_watchlist_interval_invalid") from None
    if interval <= 0 or interval > 10080:
        raise ValueError("daily_market_scan_watchlist_interval_out_of_range")

    run_request = _normalized_watchlist_run_request(payload.get("run_request") or {})

    return agent_schemas.DailyMarketScanWatchlistUpsertRequest(
        name=name,
        enabled=bool(payload.get("enabled", True)),
        schedule_interval_minutes=interval,
        run_request=run_request,
        operator_notes=_dedupe_clean_list(payload.get("operator_notes") or []),
    )


def _next_run_at(*, from_time: datetime, interval_minutes: int) -> datetime:
    return from_time + timedelta(minutes=interval_minutes)


def _watchlist_response(
    watchlist: models.DailyMarketScanWatchlist,
) -> agent_schemas.DailyMarketScanWatchlist:
    try:
        run_request_payload = json.loads(watchlist.request_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("daily_market_scan_watchlist_payload_invalid") from exc

    return agent_schemas.DailyMarketScanWatchlist(
        id=watchlist.id,
        name=watchlist.name,
        enabled=bool(watchlist.enabled),
        schedule_interval_minutes=watchlist.schedule_interval_minutes,
        run_request=_normalized_watchlist_run_request(run_request_payload),
        operator_notes=_safe_json_list(watchlist.operator_notes),
        next_run_at=watchlist.next_run_at,
        last_run_id=watchlist.last_run_id,
        last_run_status=watchlist.last_run_status,
        last_run_error=watchlist.last_run_error,
        last_run_started_at=watchlist.last_run_started_at,
        last_run_finished_at=watchlist.last_run_finished_at,
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )


def _get_watchlist_or_404(
    db: Session,
    watchlist_id: int,
) -> models.DailyMarketScanWatchlist:
    watchlist = (
        db.query(models.DailyMarketScanWatchlist)
        .filter(models.DailyMarketScanWatchlist.id == watchlist_id)
        .first()
    )
    if watchlist is None:
        raise ValueError("daily_market_scan_watchlist_not_found")
    return watchlist


def _get_or_create_scheduler_state(
    db: Session,
) -> models.DailyMarketScanWatchlistSchedulerState:
    state = (
        db.query(models.DailyMarketScanWatchlistSchedulerState)
        .filter(
            models.DailyMarketScanWatchlistSchedulerState.scheduler_key
            == WATCHLIST_SCHEDULER_KEY
        )
        .first()
    )
    if state is not None:
        return state

    state = models.DailyMarketScanWatchlistSchedulerState(
        scheduler_key=WATCHLIST_SCHEDULER_KEY,
        last_status="idle",
    )
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def list_watchlists(
    db: Session,
    *,
    limit: int = DEFAULT_WATCHLIST_LIMIT,
) -> list[agent_schemas.DailyMarketScanWatchlist]:
    rows = (
        db.query(models.DailyMarketScanWatchlist)
        .order_by(models.DailyMarketScanWatchlist.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_watchlist_response(row) for row in rows]


def create_watchlist(
    db: Session,
    request: agent_schemas.DailyMarketScanWatchlistUpsertRequest | dict[str, Any] | Any,
) -> agent_schemas.DailyMarketScanWatchlist:
    normalized = normalize_watchlist_upsert_request(request)
    now = _utcnow()
    row = models.DailyMarketScanWatchlist(
        name=normalized.name,
        enabled=normalized.enabled,
        schedule_interval_minutes=normalized.schedule_interval_minutes,
        request_payload=_json_dumps(normalized.run_request),
        operator_notes=_json_dumps(normalized.operator_notes),
        next_run_at=now if normalized.enabled else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _watchlist_response(row)


def update_watchlist(
    db: Session,
    watchlist_id: int,
    request: agent_schemas.DailyMarketScanWatchlistUpsertRequest | dict[str, Any] | Any,
) -> agent_schemas.DailyMarketScanWatchlist:
    row = _get_watchlist_or_404(db, watchlist_id)
    normalized = normalize_watchlist_upsert_request(request)
    now = _utcnow()
    prior_enabled = bool(row.enabled)
    prior_payload = row.request_payload
    prior_interval = row.schedule_interval_minutes

    row.name = normalized.name
    row.enabled = normalized.enabled
    row.schedule_interval_minutes = normalized.schedule_interval_minutes
    row.request_payload = _json_dumps(normalized.run_request)
    row.operator_notes = _json_dumps(normalized.operator_notes)

    if not row.enabled:
        row.next_run_at = None
    elif (
        not prior_enabled
        or prior_payload != row.request_payload
        or prior_interval != row.schedule_interval_minutes
        or row.next_run_at is None
    ):
        row.next_run_at = now

    db.commit()
    db.refresh(row)
    return _watchlist_response(row)


def delete_watchlist(
    db: Session,
    watchlist_id: int,
) -> None:
    row = _get_watchlist_or_404(db, watchlist_id)
    db.delete(row)
    db.commit()


def _execute_watchlist_run(
    db: Session,
    watchlist: models.DailyMarketScanWatchlist,
    *,
    trigger_source: str,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        Any,
    ]
    | None = None,
) -> models.AgentRun:
    now = _utcnow()
    run_request = _normalized_watchlist_run_request(
        json.loads(watchlist.request_payload)
    )

    watchlist.last_run_started_at = now
    watchlist.last_run_error = None
    if watchlist.enabled:
        watchlist.next_run_at = _next_run_at(
            from_time=now,
            interval_minutes=watchlist.schedule_interval_minutes,
        )
    db.commit()
    db.refresh(watchlist)

    run = daily_market_scan.run_daily_market_scan_once(
        db,
        run_request,
        provider_registry=provider_registry,
        task_subject_type="daily_market_scan_watchlist",
        task_subject_id=watchlist.id,
        summary=f"Daily Market Scan watchlist: {watchlist.name}",
    )

    watchlist.last_run_id = run.id
    watchlist.last_run_status = run.status
    watchlist.last_run_error = run.error
    watchlist.last_run_started_at = run.started_at or now
    watchlist.last_run_finished_at = run.finished_at
    if watchlist.enabled:
        watchlist.next_run_at = _next_run_at(
            from_time=run.finished_at or now,
            interval_minutes=watchlist.schedule_interval_minutes,
        )

    db.commit()
    db.refresh(watchlist)

    service.write_audit_log(
        db,
        run=run,
        task=run.task if run.task is not None else None,
        actor_type="system",
        action="daily_market_scan_watchlist_run_linked",
        details=_json_dumps(
            {
                "watchlist_id": watchlist.id,
                "watchlist_name": watchlist.name,
                "trigger_source": trigger_source,
                "next_run_at": (
                    watchlist.next_run_at.isoformat()
                    if watchlist.next_run_at is not None
                    else None
                ),
            }
        ),
    )
    return run


def trigger_watchlist_run_now(
    db: Session,
    watchlist_id: int,
    *,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        Any,
    ]
    | None = None,
) -> models.AgentRun:
    watchlist = _get_watchlist_or_404(db, watchlist_id)
    return _execute_watchlist_run(
        db,
        watchlist,
        trigger_source="manual",
        provider_registry=provider_registry,
    )


def get_scheduler_status(
    db: Session,
    *,
    now: datetime | None = None,
) -> agent_schemas.DailyMarketScanWatchlistSchedulerStatusResponse:
    current_time = now or _utcnow()
    state = _get_or_create_scheduler_state(db)
    enabled_watchlist_count = (
        db.query(models.DailyMarketScanWatchlist)
        .filter(models.DailyMarketScanWatchlist.enabled.is_(True))
        .count()
    )
    due_watchlist_count = (
        db.query(models.DailyMarketScanWatchlist)
        .filter(
            models.DailyMarketScanWatchlist.enabled.is_(True),
            models.DailyMarketScanWatchlist.next_run_at.isnot(None),
            models.DailyMarketScanWatchlist.next_run_at <= current_time,
        )
        .count()
    )
    next_due_row = (
        db.query(models.DailyMarketScanWatchlist)
        .filter(
            models.DailyMarketScanWatchlist.enabled.is_(True),
            models.DailyMarketScanWatchlist.next_run_at.isnot(None),
        )
        .order_by(models.DailyMarketScanWatchlist.next_run_at.asc())
        .first()
    )
    return agent_schemas.DailyMarketScanWatchlistSchedulerStatusResponse(
        scheduler_key=WATCHLIST_SCHEDULER_KEY,
        poll_interval_seconds=WATCHLIST_SCHEDULER_POLL_INTERVAL_SECONDS,
        enabled_watchlist_count=enabled_watchlist_count,
        due_watchlist_count=due_watchlist_count,
        next_due_at=next_due_row.next_run_at if next_due_row is not None else None,
        last_sweep_started_at=state.last_sweep_started_at,
        last_sweep_finished_at=state.last_sweep_finished_at,
        last_status=state.last_status or "idle",
        last_error=state.last_error,
        last_due_count=state.last_due_count or 0,
        last_triggered_count=state.last_triggered_count or 0,
    )


def run_due_watchlists_once(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 5,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        Any,
    ]
    | None = None,
) -> dict[str, Any]:
    current_time = now or _utcnow()
    state = _get_or_create_scheduler_state(db)
    state.last_sweep_started_at = current_time
    state.last_status = "running"
    state.last_error = None
    db.commit()
    db.refresh(state)

    due_rows = (
        db.query(models.DailyMarketScanWatchlist)
        .filter(
            models.DailyMarketScanWatchlist.enabled.is_(True),
            models.DailyMarketScanWatchlist.next_run_at.isnot(None),
            models.DailyMarketScanWatchlist.next_run_at <= current_time,
        )
        .order_by(models.DailyMarketScanWatchlist.next_run_at.asc())
        .limit(limit)
        .all()
    )

    triggered_run_ids: list[int] = []
    triggered_watchlist_ids: list[int] = []

    try:
        for row in due_rows:
            run = _execute_watchlist_run(
                db,
                row,
                trigger_source="scheduler",
                provider_registry=provider_registry,
            )
            triggered_run_ids.append(run.id)
            triggered_watchlist_ids.append(row.id)

        state.last_sweep_finished_at = _utcnow()
        state.last_status = "completed"
        state.last_due_count = len(due_rows)
        state.last_triggered_count = len(triggered_watchlist_ids)
        state.last_error = None
        db.commit()
        db.refresh(state)
    except Exception as exc:
        state.last_sweep_finished_at = _utcnow()
        state.last_status = "failed"
        state.last_due_count = len(due_rows)
        state.last_triggered_count = len(triggered_watchlist_ids)
        state.last_error = str(exc)
        db.commit()
        db.refresh(state)
        raise

    return {
        "scheduler_key": WATCHLIST_SCHEDULER_KEY,
        "due_count": len(due_rows),
        "triggered_count": len(triggered_watchlist_ids),
        "triggered_watchlist_ids": triggered_watchlist_ids,
        "triggered_run_ids": triggered_run_ids,
    }
