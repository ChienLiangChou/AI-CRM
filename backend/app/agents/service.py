from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def create_task(
    db: Session,
    *,
    agent_type: str,
    subject_type: Optional[str] = None,
    subject_id: Optional[int] = None,
    payload: Optional[str] = None,
    priority: str = "normal",
) -> models.AgentTask:
    task = models.AgentTask(
        agent_type=agent_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        priority=priority,
        status="queued",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def create_run(
    db: Session,
    *,
    task: models.AgentTask,
    summary: str | None = None,
) -> models.AgentRun:
    run = models.AgentRun(
        task_id=task.id,
        status="queued",
        summary=summary,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_task_status(
    db: Session,
    task: models.AgentTask,
    *,
    status: str,
) -> models.AgentTask:
    task.status = status
    db.commit()
    db.refresh(task)
    return task


def update_run_status(
    db: Session,
    run: models.AgentRun,
    *,
    status: str,
    plan: str | None = None,
    result: str | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> models.AgentRun:
    run.status = status
    if plan is not None:
        run.plan = plan
    if result is not None:
        run.result = result
    if error is not None:
        run.error = error
    if started_at is not None:
        run.started_at = started_at
    if finished_at is not None:
        run.finished_at = finished_at

    db.commit()
    db.refresh(run)
    return run


def create_approval(
    db: Session,
    *,
    run: models.AgentRun,
    action_type: str,
    risk_level: str = "medium",
    payload: str | None = None,
) -> models.AgentApproval:
    approval = models.AgentApproval(
        run_id=run.id,
        action_type=action_type,
        risk_level=risk_level,
        payload=payload,
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def update_approval_status(
    db: Session,
    approval: models.AgentApproval,
    *,
    status: str,
    approved_by: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> models.AgentApproval:
    now = datetime.utcnow()

    approval.status = status
    if status == "approved":
        approval.approved_by = approved_by
        approval.approved_at = now
    elif status == "rejected":
        approval.rejection_reason = rejection_reason
        approval.rejected_at = now

    db.commit()
    db.refresh(approval)
    return approval


def write_audit_log(
    db: Session,
    *,
    run: Optional[models.AgentRun] = None,
    task: Optional[models.AgentTask] = None,
    actor_type: str = "agent",
    action: str,
    details: str | None = None,
) -> models.AgentAuditLog:
    log = models.AgentAuditLog(
        run_id=run.id if run else None,
        task_id=task.id if task else None,
        actor_type=actor_type,
        action=action,
        details=details,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def sync_run_review_state(
    db: Session,
    *,
    run: models.AgentRun,
) -> models.AgentRun:
    """
    Finalize a review-only run once all approvals have been decided.

    In the current MVP there is no post-approval send step, so a run with
    zero pending approvals is considered complete.
    """
    if run.status != "waiting_approval":
        return run

    pending_approvals = (
        db.query(models.AgentApproval)
        .filter(
            models.AgentApproval.run_id == run.id,
            models.AgentApproval.status == "pending",
        )
        .count()
    )

    if pending_approvals > 0:
        return run

    now = datetime.utcnow()
    run.status = "completed"
    if run.finished_at is None:
        run.finished_at = now

    if run.task is not None:
        run.task.status = "completed"
        run.task.updated_at = now

    db.commit()
    db.refresh(run)
    if run.task is not None:
        db.refresh(run.task)

    agent_type = run.task.agent_type if run.task is not None else None
    action = "follow_up_review_completed"
    if agent_type and agent_type != "follow_up":
        action = f"{agent_type}_review_completed"

    write_audit_log(
        db,
        run=run,
        task=run.task if run.task is not None else None,
        actor_type="system",
        action=action,
        details=json.dumps(
            {
                "run_id": run.id,
                "status": run.status,
                "completed_after_review": True,
            },
            ensure_ascii=False,
        ),
    )
    return run


def log_approval_decision(
    db: Session,
    *,
    approval: models.AgentApproval,
    action: str,
    actor_type: str = "user",
    details: Optional[dict] = None,
) -> models.AgentAuditLog:
    payload = json.dumps(details or {}, ensure_ascii=False)
    return write_audit_log(
        db,
        run=approval.run,
        task=approval.run.task if approval.run else None,
        actor_type=actor_type,
        action=action,
        details=payload,
    )
