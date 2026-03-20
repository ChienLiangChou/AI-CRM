from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from . import models, service, tools

EMAIL_DRAFT_ACTIONS = {"email", "re-engage"}


def _build_follow_up_plan_items(nudges) -> List[Dict[str, Any]]:
    """
    Normalize nudges into a single actionable recommendation per contact.

    `generate_smart_nudges` can emit more than one nudge for the same contact.
    For the Follow-up Agent MVP we prefer the highest-priority email-capable
    recommendation for a contact when one exists, because the current review
    flow only produces manual email draft approvals. If no email-capable nudge
    exists, keep the first recommendation after urgency sorting.
    """
    planned_by_contact: Dict[int, Dict[str, Any]] = {}

    for nudge in nudges:
        candidate = {
            "contact_id": nudge.contact_id,
            "contact_name": nudge.contact_name,
            "company": nudge.company,
            "urgency": nudge.urgency,
            "message": nudge.message,
            "suggested_action": nudge.action,
        }
        existing = planned_by_contact.get(nudge.contact_id)
        if existing is None:
            planned_by_contact[nudge.contact_id] = candidate
            continue

        existing_is_email_capable = existing.get("suggested_action") in EMAIL_DRAFT_ACTIONS
        candidate_is_email_capable = candidate["suggested_action"] in EMAIL_DRAFT_ACTIONS
        if not existing_is_email_capable and candidate_is_email_capable:
            planned_by_contact[nudge.contact_id] = candidate

    return list(planned_by_contact.values())


def plan_follow_up_run(db: Session) -> Dict[str, Any]:
    """
    Simple, explainable planning step for the Follow-up Agent.

    For MVP, we:
    - call the existing smart nudge logic to identify candidates
    - for each nudge, record the contact_id and suggested action
    - do NOT send any emails or push notifications
    """
    nudges_response = tools.generate_smart_nudges_tool(db)
    nudges = nudges_response.nudges

    planned_items = _build_follow_up_plan_items(nudges)

    return {
        "generated_at": nudges_response.generated_at.isoformat(),
        "items": planned_items,
    }


def execute_follow_up_run(db: Session, run: models.AgentRun) -> Dict[str, Any]:
    """
    Execute a planned follow-up run by:
    - reading the plan (recommended contacts)
    - generating email drafts for each contact using existing draft_email logic
    - creating approval records for each draft
    - recording audit logs

    For actions created by the agent layer, AgentApproval is the review-state
    source of truth. Legacy Interaction.generated_response_status remains owned
    by older workflow endpoints outside this module.

    This function does NOT:
    - send emails
    - send push notifications
    or perform any irreversible side effects.
    """
    if not run.plan:
        return {"recommendations": [], "drafts": []}

    try:
        plan = json.loads(run.plan)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_plan_json") from exc

    items = plan.get("items", [])
    if not isinstance(items, list):
        raise ValueError("invalid_plan_items")

    drafts: List[Dict[str, Any]] = []

    for item in items:
        contact_id = item.get("contact_id")
        if not contact_id:
            service.write_audit_log(
                db,
                run=run,
                task=run.task,
                actor_type="system",
                action="skip_followup_email_draft",
                details=json.dumps(
                    {"reason": "missing_contact_id", "item": item},
                    ensure_ascii=False,
                ),
            )
            continue

        suggested_action = item.get("suggested_action")
        if suggested_action not in EMAIL_DRAFT_ACTIONS:
            service.write_audit_log(
                db,
                run=run,
                task=run.task,
                actor_type="agent",
                action="skip_followup_email_draft",
                details=json.dumps(
                    {
                        "contact_id": contact_id,
                        "reason": "non_email_action",
                        "suggested_action": suggested_action,
                    },
                    ensure_ascii=False,
                ),
            )
            continue

        contact = tools.get_contact_tool(db, contact_id)
        if contact is None:
            service.write_audit_log(
                db,
                run=run,
                task=run.task,
                actor_type="system",
                action="skip_followup_email_draft",
                details=json.dumps(
                    {"contact_id": contact_id, "reason": "contact_not_found"},
                    ensure_ascii=False,
                ),
            )
            continue

        if not getattr(contact, "email", None):
            service.write_audit_log(
                db,
                run=run,
                task=run.task,
                actor_type="agent",
                action="skip_followup_email_draft",
                details=json.dumps(
                    {"contact_id": contact_id, "reason": "missing_email"},
                    ensure_ascii=False,
                ),
            )
            continue

        # Use existing draft_email logic via the tool wrapper.
        draft = tools.draft_email_tool(db, contact_id)
        if draft is None:
            service.write_audit_log(
                db,
                run=run,
                task=run.task,
                actor_type="system",
                action="skip_followup_email_draft",
                details=json.dumps(
                    {"contact_id": contact_id, "reason": "draft_generation_failed"},
                    ensure_ascii=False,
                ),
            )
            continue

        # Create an approval record for this email draft.
        approval_payload = json.dumps(
            {
                "contact_id": contact_id,
                "subject": draft.subject,
                "body": draft.body,
            },
            ensure_ascii=False,
        )
        approval = service.create_approval(
            db,
            run=run,
            action_type="send_email",
            risk_level="high",
            payload=approval_payload,
        )

        # Audit log for the draft creation.
        service.write_audit_log(
            db,
            run=run,
            task=run.task,
            actor_type="agent",
            action="generate_followup_email_draft",
            details=approval_payload,
        )

        drafts.append(
            {
                "contact_id": contact_id,
                "approval_id": approval.id,
                "subject": draft.subject,
                "body": draft.body,
            }
        )

    return {
        "recommendations": items,
        "drafts": drafts,
    }


def run_follow_up_agent_once(db: Session) -> models.AgentRun:
    """
    High-level helper to create and execute a single Follow-up Agent run.

    For MVP and for internal use only (no auto-scheduling in this step):
    - create an AgentTask of type 'follow_up'
    - create an AgentRun attached to that task
    - perform planning to identify recommended contacts
    - perform execution to generate drafts + approvals + audit logs

    This function leaves approvals in 'pending' status and does not send
    any external communications.
    """
    # Create task and run records.
    task = service.create_task(
        db,
        agent_type="follow_up",
        subject_type=None,
        subject_id=None,
        payload=None,
        priority="normal",
    )
    run = service.create_run(
        db,
        task=task,
        summary="Follow-up Agent run (MVP)",
    )
    service.update_task_status(db, task, status="executing")

    try:
        # Planning phase.
        now = datetime.utcnow()
        plan_data = plan_follow_up_run(db)
        plan_json = json.dumps(plan_data, ensure_ascii=False)

        run = service.update_run_status(
            db,
            run,
            status="planning",
            plan=plan_json,
            started_at=now,
        )

        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="follow_up_recommendations_generated",
            details=plan_json,
        )

        # Execution phase (still review-only, no external communication).
        run = service.update_run_status(db, run, status="executing")
        exec_result = execute_follow_up_run(db, run)
        result_json = json.dumps(exec_result, ensure_ascii=False)

        finished_at = datetime.utcnow()
        next_status = "waiting_approval" if exec_result["drafts"] else "completed"
        run = service.update_run_status(
            db,
            run,
            status=next_status,
            result=result_json,
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status=next_status)

        # High-level audit entry for the run itself.
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action=(
                "follow_up_run_waiting_approval"
                if exec_result["drafts"]
                else "follow_up_run_completed"
            ),
            details=result_json,
        )
        return run
    except Exception as exc:
        finished_at = datetime.utcnow()
        run = service.update_run_status(
            db,
            run,
            status="failed",
            error=str(exc),
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="follow_up_run_failed",
            details=str(exc),
        )
        return run
