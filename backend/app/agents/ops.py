from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas


TRACKED_AGENT_TYPES: tuple[agent_schemas.AgentType, ...] = (
    "follow_up",
    "conversation_closer",
    "listing_cma",
)

APPROVAL_TITLES = {
    "send_email": "follow-up email",
    "send_client_reply": "client reply",
    "send_listing_cma_summary": "seller summary",
}


def _compact_text(value: Any, *, limit: int = 180) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)

    compact = " ".join(text.split())
    if not compact:
        return None
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _safe_json_loads(raw: str | None) -> tuple[Any | None, str | None]:
    if raw is None:
        return None, None

    try:
        return json.loads(raw), None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, _compact_text(raw)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _approval_preview(
    payload: str | None,
    *,
    action_type: str,
) -> agent_schemas.AgentOpsApprovalPreview:
    parsed, payload_text = _safe_json_loads(payload)
    title = APPROVAL_TITLES.get(action_type)
    subject = None
    body_excerpt = None
    contact_id = None
    property_id = None
    review_mode = None

    if isinstance(parsed, dict):
        variant = parsed.get("variant")
        if isinstance(variant, str) and variant.strip():
            title = variant
        elif isinstance(parsed.get("title"), str) and parsed["title"].strip():
            title = parsed["title"].strip()

        if isinstance(parsed.get("subject"), str):
            subject = parsed["subject"].strip() or None
        if isinstance(parsed.get("body"), str):
            body_excerpt = _compact_text(parsed["body"])

        contact_id = _coerce_optional_int(parsed.get("contact_id"))
        property_id = _coerce_optional_int(parsed.get("property_id"))
        if isinstance(parsed.get("review_mode"), str):
            review_mode = parsed["review_mode"].strip() or None

        if (
            payload_text is None
            and subject is None
            and body_excerpt is None
            and contact_id is None
            and property_id is None
        ):
            payload_text = _compact_text(parsed)
    elif parsed is not None and payload_text is None:
        payload_text = _compact_text(parsed)

    return agent_schemas.AgentOpsApprovalPreview(
        title=title,
        subject=subject,
        body_excerpt=body_excerpt,
        contact_id=contact_id,
        property_id=property_id,
        review_mode=review_mode,
        payload_text=payload_text,
    )


def _serialize_approval_item(
    approval: models.AgentApproval,
    run: models.AgentRun,
    task: models.AgentTask,
) -> agent_schemas.AgentOpsApprovalItem:
    decisioned_at = approval.approved_at or approval.rejected_at
    return agent_schemas.AgentOpsApprovalItem(
        approval_id=approval.id,
        agent_type=task.agent_type,
        run_id=run.id,
        task_id=task.id,
        action_type=approval.action_type,
        risk_level=approval.risk_level,
        status=approval.status,
        created_at=approval.created_at,
        approved_at=approval.approved_at,
        rejected_at=approval.rejected_at,
        decisioned_at=decisioned_at,
        approved_by=approval.approved_by,
        rejection_reason=approval.rejection_reason,
        run_status=run.status,
        run_summary=run.summary,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        preview=_approval_preview(
            approval.payload,
            action_type=approval.action_type,
        ),
    )


def _load_approval_counts(db: Session) -> dict[int, dict[str, int]]:
    rows = (
        db.query(
            models.AgentApproval.run_id,
            models.AgentApproval.status,
        )
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES))
        .all()
    )

    counts: dict[int, dict[str, int]] = {}
    for run_id, status in rows:
        run_counts = counts.setdefault(run_id, {"total": 0, "pending": 0})
        run_counts["total"] += 1
        if status == "pending":
            run_counts["pending"] += 1
    return counts


def _serialize_run_item(
    run: models.AgentRun,
    task: models.AgentTask,
    approval_counts: dict[int, dict[str, int]],
) -> agent_schemas.AgentOpsRunItem:
    counts = approval_counts.get(run.id, {"total": 0, "pending": 0})
    return agent_schemas.AgentOpsRunItem(
        run_id=run.id,
        task_id=task.id,
        agent_type=task.agent_type,
        status=run.status,
        summary=run.summary,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        approval_count=counts["total"],
        pending_approval_count=counts["pending"],
        has_pending_approvals=counts["pending"] > 0,
        is_internal_only=counts["total"] == 0,
    )


def _serialize_audit_item(
    audit_log: models.AgentAuditLog,
) -> agent_schemas.AgentOpsAuditItem:
    parsed, details_text = _safe_json_loads(audit_log.details)
    details_json = parsed if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None else None

    return agent_schemas.AgentOpsAuditItem(
        id=audit_log.id,
        actor_type=audit_log.actor_type,
        action=audit_log.action,
        details_json=details_json,
        details_text=details_text,
        created_at=audit_log.created_at,
    )


def get_ops_overview(db: Session) -> agent_schemas.AgentOpsOverviewResponse:
    run_rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES))
        .order_by(models.AgentRun.created_at.desc())
        .all()
    )
    pending_rows = (
        db.query(models.AgentApproval, models.AgentRun, models.AgentTask)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
        )
        .all()
    )
    decision_rows = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
            models.AgentApproval.status.in_(("approved", "rejected")),
        )
        .all()
    )

    agents: list[agent_schemas.AgentOpsOverviewAgentItem] = []
    for agent_type in TRACKED_AGENT_TYPES:
        agent_runs = [
            run_row for run_row in run_rows if run_row[1].agent_type == agent_type
        ]
        latest_run = agent_runs[0][0] if agent_runs else None
        agents.append(
            agent_schemas.AgentOpsOverviewAgentItem(
                agent_type=agent_type,
                latest_run_id=latest_run.id if latest_run else None,
                latest_run_status=latest_run.status if latest_run else None,
                latest_run_created_at=latest_run.created_at if latest_run else None,
                latest_run_error=latest_run.error if latest_run else None,
                pending_approvals=sum(
                    1 for _, _, task in pending_rows if task.agent_type == agent_type
                ),
                failed_runs=sum(
                    1
                    for run, task in agent_runs
                    if task.agent_type == agent_type and run.status == "failed"
                ),
                runs_tracked=len(agent_runs),
            )
        )

    return agent_schemas.AgentOpsOverviewResponse(
        agents=agents,
        totals=agent_schemas.AgentOpsOverviewTotals(
            pending_approvals=len(pending_rows),
            recent_decisions=len(decision_rows),
            failed_runs=sum(1 for run, _ in run_rows if run.status == "failed"),
            runs_tracked=len(run_rows),
        ),
        review_model=agent_schemas.AgentOpsReviewModel(
            manual_only=True,
            no_send=True,
            tracked_agent_types=list(TRACKED_AGENT_TYPES),
        ),
    )


def list_ops_pending_approvals(
    db: Session,
    *,
    limit: int = 50,
) -> list[agent_schemas.AgentOpsApprovalItem]:
    rows = (
        db.query(models.AgentApproval, models.AgentRun, models.AgentTask)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
        )
        .order_by(models.AgentApproval.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        _serialize_approval_item(approval, run, task)
        for approval, run, task in rows
    ]


def list_ops_recent_decisions(
    db: Session,
    *,
    limit: int = 50,
) -> list[agent_schemas.AgentOpsApprovalItem]:
    rows = (
        db.query(models.AgentApproval, models.AgentRun, models.AgentTask)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
            models.AgentApproval.status.in_(("approved", "rejected")),
        )
        .all()
    )
    items = [
        _serialize_approval_item(approval, run, task)
        for approval, run, task in rows
    ]
    items.sort(
        key=lambda item: item.decisioned_at or item.created_at,
        reverse=True,
    )
    return items[:limit]


def list_ops_recent_runs(
    db: Session,
    *,
    limit: int = 50,
) -> list[agent_schemas.AgentOpsRunItem]:
    rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES))
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )
    approval_counts = _load_approval_counts(db)
    return [
        _serialize_run_item(run, task, approval_counts)
        for run, task in rows
    ]


def list_ops_failed_runs(
    db: Session,
    *,
    limit: int = 50,
) -> list[agent_schemas.AgentOpsRunItem]:
    rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
            models.AgentRun.status == "failed",
        )
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )
    approval_counts = _load_approval_counts(db)
    return [
        _serialize_run_item(run, task, approval_counts)
        for run, task in rows
    ]


def get_ops_run_audit(
    db: Session,
    *,
    run_id: int,
    limit: int = 100,
) -> agent_schemas.AgentOpsRunAuditResponse:
    row = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type.in_(TRACKED_AGENT_TYPES),
        )
        .first()
    )
    if row is None:
        raise ValueError("run_not_found")

    run, task = row
    approval_counts = _load_approval_counts(db)
    audit_logs = (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )
    return agent_schemas.AgentOpsRunAuditResponse(
        run=_serialize_run_item(run, task, approval_counts),
        audit_logs=[_serialize_audit_item(audit_log) for audit_log in audit_logs],
    )
