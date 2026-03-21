from __future__ import annotations

from typing import List
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..database import get_db
from . import (
    buyer_match,
    conversation_closer,
    listing_cma,
    mls_auth,
    models,
    ops,
    orchestrator,
    schemas as agent_schemas,
    service,
    strategy_coordination,
)


router = APIRouter()


def _bad_request_from_value_error(error: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _serialize_conversation_closer_result(raw_result: str | None):
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    try:
        if hasattr(agent_schemas.ConversationCloserResultResponse, "model_validate"):
            model = agent_schemas.ConversationCloserResultResponse.model_validate(parsed)
            return model.model_dump()
        model = agent_schemas.ConversationCloserResultResponse.parse_obj(parsed)
        return model.dict()
    except (ValidationError, TypeError, ValueError):
        return None


def _serialize_listing_cma_result(raw_result: str | None):
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    try:
        if hasattr(agent_schemas.ListingCmaResultResponse, "model_validate"):
            model = agent_schemas.ListingCmaResultResponse.model_validate(parsed)
            return model.model_dump()
        model = agent_schemas.ListingCmaResultResponse.parse_obj(parsed)
        return model.dict()
    except (ValidationError, TypeError, ValueError):
        return None


def _serialize_buyer_match_result(raw_result: str | None):
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    try:
        if hasattr(agent_schemas.BuyerMatchResultResponse, "model_validate"):
            model = agent_schemas.BuyerMatchResultResponse.model_validate(parsed)
            return model.model_dump()
        model = agent_schemas.BuyerMatchResultResponse.parse_obj(parsed)
        return model.dict()
    except (ValidationError, TypeError, ValueError):
        return None


def _serialize_strategy_coordination_result(raw_result: str | None):
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    try:
        if hasattr(agent_schemas.StrategyCoordinationResultResponse, "model_validate"):
            model = agent_schemas.StrategyCoordinationResultResponse.model_validate(
                parsed
            )
            return model.model_dump()
        model = agent_schemas.StrategyCoordinationResultResponse.parse_obj(parsed)
        return model.dict()
    except (ValidationError, TypeError, ValueError):
        return None


@router.post(
    "/follow-up/run-once",
    response_model=agent_schemas.AgentRun,
    summary="Trigger a single Follow-up Agent run (MVP).",
)
def trigger_follow_up_run_once(db: Session = Depends(get_db)):
    """
    Manually trigger the Follow-up Agent to:
    - analyze current nudges
    - generate follow-up recommendations and email drafts
    - create approval records and audit logs

    This endpoint does NOT send any emails or push notifications.
    """
    run = orchestrator.run_follow_up_agent_once(db)
    return run


@router.get(
    "/runs",
    response_model=List[agent_schemas.AgentRun],
    summary="List recent agent runs.",
)
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    """
    Return recent AgentRun records, ordered by creation time descending.
    """
    q = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "follow_up")
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
    )
    return q.all()


@router.get(
    "/approvals",
    response_model=List[agent_schemas.AgentApproval],
    summary="List pending agent approvals.",
)
def list_pending_approvals(db: Session = Depends(get_db)):
    """
    Return all pending AgentApproval records.
    """
    q = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
            models.AgentTask.agent_type == "follow_up",
        )
        .order_by(models.AgentApproval.created_at.desc())
    )
    return q.all()


@router.get(
    "/approvals/history",
    response_model=List[agent_schemas.AgentApproval],
    summary="List recent resolved approval decisions.",
)
def list_recent_approval_decisions(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    Return recent approved or rejected AgentApproval records for the
    Follow-up Agent MVP, ordered by decision time descending.
    """
    approvals = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status.in_(("approved", "rejected")),
            models.AgentTask.agent_type == "follow_up",
        )
        .all()
    )
    approvals.sort(
        key=lambda approval: (
            approval.approved_at
            or approval.rejected_at
            or approval.created_at
        ),
        reverse=True,
    )
    return approvals[:limit]


@router.get(
    "/runs/{run_id}/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="List audit logs for a follow-up run.",
)
def list_run_audit_logs(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Return chronological audit logs for a single Follow-up Agent run.
    """
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "follow_up",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    q = (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
    )
    return q.all()


@router.get(
    "/mls-auth/status",
    response_model=agent_schemas.MlsAuthStatusResponse,
    summary="Get current Authenticated MLS access status.",
)
def get_mls_auth_status(
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    db: Session = Depends(get_db),
):
    """
    Return the current internal-only, manual-simulated MLS auth/session status.

    This endpoint does not execute browser login, collect secrets, or bypass OTP.
    """
    return mls_auth.load_persisted_status(db, provider=provider)


@router.get(
    "/mls-auth/history",
    response_model=agent_schemas.MlsAuthHistoryResponse,
    summary="Get persisted Authenticated MLS attempt history.",
)
def get_mls_auth_history(
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    db: Session = Depends(get_db),
):
    """
    Return persisted MLS auth attempts newest-first.

    Safe empty collections are returned when no attempts exist yet.
    """
    return mls_auth.load_persisted_history(db, provider=provider)


@router.get(
    "/mls-auth/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="Get chronological Authenticated MLS audit logs.",
)
def list_mls_auth_audit_logs(
    provider: agent_schemas.MlsAuthProviderKey = "stratus_authenticated",
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Return chronological MLS auth lifecycle audit logs for the provider.

    Safe empty collections are returned when no auth task exists yet.
    """
    task = (
        db.query(models.AgentTask)
        .filter(
            models.AgentTask.agent_type == "mls_auth",
            models.AgentTask.subject_type == provider,
        )
        .first()
    )
    if task is None:
        return []

    return (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.task_id == task.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )


@router.post(
    "/mls-auth/start",
    response_model=agent_schemas.MlsAuthStartResponse,
    summary="Start an internal-only Authenticated MLS login attempt.",
)
def start_mls_auth_attempt(
    request: agent_schemas.MlsAuthStartRequest,
    db: Session = Depends(get_db),
):
    """
    Begin an internal-only, manual-simulated MLS auth attempt.

    This endpoint may reuse an existing in-progress or awaiting-OTP attempt
    and will not create parallel active attempts for the same provider.
    """
    try:
        return mls_auth.start_auth_attempt_persisted(db, request=request)
    except ValueError as error:
        raise _bad_request_from_value_error(error) from error


@router.post(
    "/mls-auth/submit-otp",
    response_model=agent_schemas.MlsAuthSubmitOtpResponse,
    summary="Submit OTP for an existing Authenticated MLS attempt.",
)
def submit_mls_auth_otp(
    request: agent_schemas.MlsAuthSubmitOtpRequest,
    db: Session = Depends(get_db),
):
    """
    Resume an existing MLS auth attempt with a human-supplied OTP.

    OTP submission is bound to the provider, attempt reference, and
    session reference. OTP values are never persisted.
    """
    try:
        return mls_auth.submit_otp_for_attempt_persisted(db, request=request)
    except ValueError as error:
        raise _bad_request_from_value_error(error) from error


@router.get(
    "/follow-up/recommendations",
    response_model=agent_schemas.FollowUpRecommendationsResponse,
    summary="Get latest Follow-up Agent recommendations.",
)
def get_follow_up_recommendations(db: Session = Depends(get_db)):
    """
    Convenience endpoint to read the most recent Follow-up Agent run result.

    For agent-triggered follow-up actions, AgentApproval is the source of truth
    for review state. This endpoint returns the latest planned recommendations
    and generated draft payloads only; it does not imply approval.
    """
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type == "follow_up",
            models.AgentRun.result.isnot(None),
        )
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )

    if not run or not run.result:
        return {"recommendations": [], "drafts": [], "run_id": None}

    try:
        parsed = json.loads(run.result)
    except json.JSONDecodeError:
        parsed = {"recommendations": [], "drafts": []}

    return {
        "recommendations": parsed.get("recommendations", []),
        "drafts": parsed.get("drafts", []),
        "run_id": run.id,
    }


@router.post(
    "/conversation-closer/run-once",
    response_model=agent_schemas.AgentRun,
    summary="Trigger a single Client Conversation Closer Agent run (MVP).",
)
def trigger_conversation_closer_run_once(
    request: agent_schemas.ConversationCloserRunRequest,
    db: Session = Depends(get_db),
):
    """
    Manually trigger the Conversation Closer Agent to:
    - analyze a client objection or hesitation message
    - generate a response strategy and up to two reply drafts
    - create approval records and audit logs

    This endpoint does NOT send any client messages or push notifications.
    """
    return conversation_closer.run_conversation_closer_once(db, request)


@router.get(
    "/conversation-closer/runs",
    response_model=List[agent_schemas.AgentRun],
    summary="List recent Conversation Closer runs.",
)
def list_conversation_closer_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "conversation_closer")
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get(
    "/conversation-closer/latest",
    response_model=agent_schemas.ConversationCloserLatestResponse,
    summary="Get the latest Conversation Closer result.",
)
def get_latest_conversation_closer_result(db: Session = Depends(get_db)):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "conversation_closer")
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )

    if run is None:
        return {
            "run_id": None,
            "status": None,
            "error": None,
            "result": None,
        }

    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "result": _serialize_conversation_closer_result(run.result),
    }


@router.post(
    "/listing-cma/run-once",
    response_model=agent_schemas.AgentRun,
    summary="Trigger a single Listing / CMA Agent run (MVP).",
)
def trigger_listing_cma_run_once(
    request: agent_schemas.ListingCmaRunRequest,
    db: Session = Depends(get_db),
):
    """
    Manually trigger the Listing / CMA Agent to:
    - analyze operator-entered seller and comparable context
    - generate internal listing prep and CMA-support output
    - optionally create one approval-only seller-facing draft

    This endpoint does NOT send any client messages or push notifications.
    """
    return listing_cma.run_listing_cma_once(db, request)


@router.get(
    "/listing-cma/runs",
    response_model=List[agent_schemas.AgentRun],
    summary="List recent Listing / CMA runs.",
)
def list_listing_cma_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "listing_cma")
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get(
    "/listing-cma/latest",
    response_model=agent_schemas.ListingCmaLatestResponse,
    summary="Get the latest Listing / CMA result.",
)
def get_latest_listing_cma_result(db: Session = Depends(get_db)):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "listing_cma")
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )

    if run is None:
        return {
            "run_id": None,
            "status": None,
            "error": None,
            "result": None,
        }

    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "result": _serialize_listing_cma_result(run.result),
    }


@router.post(
    "/buyer-match/run-once",
    response_model=agent_schemas.AgentRun,
    summary="Trigger a single Buyer Match Agent run (MVP).",
)
def trigger_buyer_match_run_once(
    request: agent_schemas.BuyerMatchRunRequest,
    db: Session = Depends(get_db),
):
    """
    Manually trigger the Buyer Match Agent to:
    - normalize buyer criteria
    - compare an operator-entered shortlist-sized candidate set
    - generate internal shortlist support and at most one review-only buyer draft

    This endpoint does NOT send any client messages or push notifications.
    """
    return buyer_match.run_buyer_match_once(db, request)


@router.get(
    "/buyer-match/runs",
    response_model=List[agent_schemas.AgentRun],
    summary="List recent Buyer Match runs.",
)
def list_buyer_match_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "buyer_match")
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get(
    "/buyer-match/latest",
    response_model=agent_schemas.BuyerMatchLatestResponse,
    summary="Get the latest Buyer Match result.",
)
def get_latest_buyer_match_result(db: Session = Depends(get_db)):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "buyer_match")
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )

    if run is None:
        return {
            "run_id": None,
            "status": None,
            "error": None,
            "result": None,
        }

    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "result": _serialize_buyer_match_result(run.result),
    }


@router.post(
    "/strategy-coordination/run-once",
    response_model=agent_schemas.AgentRun,
    summary="Trigger a single Strategy Coordination run (MVP).",
)
def trigger_strategy_coordination_run_once(
    request: agent_schemas.StrategyCoordinationRunRequest,
    db: Session = Depends(get_db),
):
    """
    Manually trigger the Strategy Coordination layer to:
    - classify an internal or external event
    - map lightweight linked business context
    - produce a structured internal operator report

    This endpoint does NOT execute actions, create client-facing outputs,
    or trigger any frozen modules.
    """
    return strategy_coordination.run_strategy_coordination_once(db, request)


@router.get(
    "/strategy-coordination/runs",
    response_model=List[agent_schemas.AgentRun],
    summary="List recent Strategy Coordination runs.",
)
def list_strategy_coordination_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "strategy_coordination")
        .order_by(models.AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get(
    "/strategy-coordination/latest",
    response_model=agent_schemas.StrategyCoordinationLatestResponse,
    summary="Get the latest Strategy Coordination report.",
)
def get_latest_strategy_coordination_result(db: Session = Depends(get_db)):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == "strategy_coordination")
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )

    if run is None:
        return {
            "run_id": None,
            "status": None,
            "error": None,
            "result": None,
        }

    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "result": _serialize_strategy_coordination_result(run.result),
    }


@router.get(
    "/strategy-coordination/runs/{run_id}/report",
    response_model=agent_schemas.StrategyCoordinationResultResponse,
    summary="Get a structured Strategy Coordination report for a run.",
)
def get_strategy_coordination_run_report(
    run_id: int,
    db: Session = Depends(get_db),
):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "strategy_coordination",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    result = _serialize_strategy_coordination_result(run.result)
    if result is None:
        raise HTTPException(status_code=404, detail="Report not found")

    return result


@router.get(
    "/strategy-coordination/runs/{run_id}/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="List audit logs for a Strategy Coordination run.",
)
def list_strategy_coordination_run_audit_logs(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "strategy_coordination",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )


@router.get(
    "/buyer-match/approvals",
    response_model=List[agent_schemas.AgentApproval],
    summary="List pending Buyer Match approvals.",
)
def list_buyer_match_pending_approvals(
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
            models.AgentTask.agent_type == "buyer_match",
        )
        .order_by(models.AgentApproval.created_at.desc())
        .all()
    )


@router.get(
    "/buyer-match/approvals/history",
    response_model=List[agent_schemas.AgentApproval],
    summary="List recent resolved Buyer Match approval decisions.",
)
def list_buyer_match_approval_history(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    approvals = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status.in_(("approved", "rejected")),
            models.AgentTask.agent_type == "buyer_match",
        )
        .all()
    )
    approvals.sort(
        key=lambda approval: (
            approval.approved_at
            or approval.rejected_at
            or approval.created_at
        ),
        reverse=True,
    )
    return approvals[:limit]


@router.get(
    "/buyer-match/runs/{run_id}/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="List audit logs for a Buyer Match run.",
)
def list_buyer_match_run_audit_logs(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "buyer_match",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )


@router.get(
    "/listing-cma/approvals",
    response_model=List[agent_schemas.AgentApproval],
    summary="List pending Listing / CMA approvals.",
)
def list_listing_cma_pending_approvals(
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
            models.AgentTask.agent_type == "listing_cma",
        )
        .order_by(models.AgentApproval.created_at.desc())
        .all()
    )


@router.get(
    "/listing-cma/approvals/history",
    response_model=List[agent_schemas.AgentApproval],
    summary="List recent resolved Listing / CMA approval decisions.",
)
def list_listing_cma_approval_history(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    approvals = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status.in_(("approved", "rejected")),
            models.AgentTask.agent_type == "listing_cma",
        )
        .all()
    )
    approvals.sort(
        key=lambda approval: (
            approval.approved_at
            or approval.rejected_at
            or approval.created_at
        ),
        reverse=True,
    )
    return approvals[:limit]


@router.get(
    "/listing-cma/runs/{run_id}/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="List audit logs for a Listing / CMA run.",
)
def list_listing_cma_run_audit_logs(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "listing_cma",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )


@router.get(
    "/conversation-closer/approvals",
    response_model=List[agent_schemas.AgentApproval],
    summary="List pending Conversation Closer approvals.",
)
def list_conversation_closer_pending_approvals(
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
            models.AgentTask.agent_type == "conversation_closer",
        )
        .order_by(models.AgentApproval.created_at.desc())
        .all()
    )


@router.get(
    "/conversation-closer/approvals/history",
    response_model=List[agent_schemas.AgentApproval],
    summary="List recent resolved Conversation Closer approval decisions.",
)
def list_conversation_closer_approval_history(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    approvals = (
        db.query(models.AgentApproval)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentApproval.status.in_(("approved", "rejected")),
            models.AgentTask.agent_type == "conversation_closer",
        )
        .all()
    )
    approvals.sort(
        key=lambda approval: (
            approval.approved_at
            or approval.rejected_at
            or approval.created_at
        ),
        reverse=True,
    )
    return approvals[:limit]


@router.get(
    "/conversation-closer/runs/{run_id}/audit-logs",
    response_model=List[agent_schemas.AgentAuditLog],
    summary="List audit logs for a Conversation Closer run.",
)
def list_conversation_closer_run_audit_logs(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    run = (
        db.query(models.AgentRun)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentRun.id == run_id,
            models.AgentTask.agent_type == "conversation_closer",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return (
        db.query(models.AgentAuditLog)
        .filter(models.AgentAuditLog.run_id == run.id)
        .order_by(models.AgentAuditLog.created_at.asc())
        .limit(limit)
        .all()
    )


@router.get(
    "/ops/overview",
    response_model=agent_schemas.AgentOpsOverviewResponse,
    summary="Get a cross-agent operations overview.",
)
def get_agent_ops_overview(
    db: Session = Depends(get_db),
):
    """
    Return a compact cross-agent summary across the frozen review-only agents.

    This endpoint reads directly from the shared agent tables through the ops
    aggregation layer. It does not call per-agent route helpers.
    """
    return ops.get_ops_overview(db)


@router.get(
    "/ops/approvals/pending",
    response_model=List[agent_schemas.AgentOpsApprovalItem],
    summary="List pending approvals across frozen agents.",
)
def list_agent_ops_pending_approvals(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Return the unified pending approval queue across the frozen agents.
    """
    return ops.list_ops_pending_approvals(db, limit=limit)


@router.get(
    "/ops/approvals/history",
    response_model=List[agent_schemas.AgentOpsApprovalItem],
    summary="List recent approval decisions across frozen agents.",
)
def list_agent_ops_approval_history(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Return recent approved/rejected decisions across the frozen agents.
    """
    return ops.list_ops_recent_decisions(db, limit=limit)


@router.get(
    "/ops/runs/recent",
    response_model=List[agent_schemas.AgentOpsRunItem],
    summary="List recent runs across frozen agents.",
)
def list_agent_ops_recent_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Return recent runs across the frozen agents, including internal-only runs.
    """
    return ops.list_ops_recent_runs(db, limit=limit)


@router.get(
    "/ops/runs/failed",
    response_model=List[agent_schemas.AgentOpsRunItem],
    summary="List failed runs across frozen agents.",
)
def list_agent_ops_failed_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Return failed runs across the frozen agents, including failures without
    any approval records.
    """
    return ops.list_ops_failed_runs(db, limit=limit)


@router.get(
    "/ops/runs/{run_id}/audit-logs",
    response_model=agent_schemas.AgentOpsRunAuditResponse,
    summary="Inspect audit logs for a frozen-agent run.",
)
def get_agent_ops_run_audit(
    run_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Return the run summary plus chronological audit logs for a frozen-agent run.
    """
    try:
        return ops.get_ops_run_audit(db, run_id=run_id, limit=limit)
    except ValueError as exc:
        if str(exc) == "run_not_found":
            raise HTTPException(status_code=404, detail="Run not found") from exc
        raise


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=agent_schemas.AgentApproval,
    summary="Approve a pending agent action.",
)
def approve_agent_action(
    approval_id: int,
    db: Session = Depends(get_db),
):
    """
    Mark an AgentApproval as approved.

    This endpoint only updates the approval record; it does NOT send emails
    or push notifications in this MVP phase.
    """
    approval = db.query(models.AgentApproval).filter(
        models.AgentApproval.id == approval_id
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Approval is not in pending state",
        )

    if approval.run is None or approval.run.status != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail="Approval is not attached to an active review run",
        )

    updated = service.update_approval_status(
        db,
        approval,
        status="approved",
        approved_by="manual_review",  # placeholder; can be wired to auth later
    )
    service.log_approval_decision(
        db,
        approval=updated,
        action="approve_agent_action",
        details={
            "approval_id": updated.id,
            "status": updated.status,
            "approved_by": updated.approved_by,
        },
    )
    service.sync_run_review_state(db, run=updated.run)
    return updated


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=agent_schemas.AgentApproval,
    summary="Reject a pending agent action.",
)
def reject_agent_action(
    approval_id: int,
    reason: str = "",
    db: Session = Depends(get_db),
):
    """
    Mark an AgentApproval as rejected.

    This endpoint only updates the approval record; it does NOT trigger any
    external side effects in this MVP phase.
    """
    approval = db.query(models.AgentApproval).filter(
        models.AgentApproval.id == approval_id
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Approval is not in pending state",
        )

    if approval.run is None or approval.run.status != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail="Approval is not attached to an active review run",
        )

    updated = service.update_approval_status(
        db,
        approval,
        status="rejected",
        rejection_reason=reason,
    )
    service.log_approval_decision(
        db,
        approval=updated,
        action="reject_agent_action",
        details={
            "approval_id": updated.id,
            "status": updated.status,
            "rejection_reason": updated.rejection_reason,
        },
    )
    service.sync_run_review_state(db, run=updated.run)
    return updated
