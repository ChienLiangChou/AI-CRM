from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas


OPENCLAW_AGENT_SPECS: tuple[tuple[agent_schemas.AgentType, str], ...] = (
    ("follow_up", "Follow-up"),
    ("conversation_closer", "Client Conversation Closer"),
    ("listing_cma", "Listing / CMA"),
    ("buyer_match", "Buyer Match"),
    ("strategy_coordination", "Strategy Coordination"),
    ("daily_market_scan", "Daily Market Scan"),
)
OPENCLAW_AGENT_TYPES: tuple[agent_schemas.AgentType, ...] = tuple(
    agent_type for agent_type, _ in OPENCLAW_AGENT_SPECS
)
AGENT_LABELS = {agent_type: label for agent_type, label in OPENCLAW_AGENT_SPECS}
DAILY_MARKET_SCAN_ATTENTION_STATUSES = {"partial", "failed", "no_providers"}
RECENT_RUNS_LIMIT = 20
RECENT_FAILURES_LIMIT = 20
PENDING_APPROVALS_LIMIT = 20
NEEDS_INPUT_LIMIT = 20


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    if value is None or isinstance(value, bool):
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
    title = {
        "send_email": "follow-up email",
        "send_client_reply": "client reply",
        "send_listing_cma_summary": "seller summary",
        "send_buyer_shortlist_summary": "buyer shortlist summary",
    }.get(action_type)
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
        .filter(models.AgentTask.agent_type.in_(OPENCLAW_AGENT_TYPES))
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


def _validate_model(model_cls: Any, parsed: Any):
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(parsed)
        return model_cls.parse_obj(parsed)
    except (ValidationError, TypeError, ValueError):
        return None


def _parse_run_result(raw_result: str | None, model_cls: Any):
    if not raw_result:
        return None

    parsed, _ = _safe_json_loads(raw_result)
    if parsed is None:
        return None
    return _validate_model(model_cls, parsed)


def _list_pending_approvals(db: Session) -> list[agent_schemas.AgentOpsApprovalItem]:
    rows = (
        db.query(models.AgentApproval, models.AgentRun, models.AgentTask)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(OPENCLAW_AGENT_TYPES),
            models.AgentApproval.status == "pending",
            models.AgentRun.status == "waiting_approval",
        )
        .order_by(models.AgentApproval.created_at.desc())
        .limit(PENDING_APPROVALS_LIMIT)
        .all()
    )
    return [
        _serialize_approval_item(approval, run, task)
        for approval, run, task in rows
    ]


def _list_recent_runs(db: Session) -> list[agent_schemas.AgentOpsRunItem]:
    rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type.in_(OPENCLAW_AGENT_TYPES))
        .order_by(models.AgentRun.created_at.desc())
        .limit(RECENT_RUNS_LIMIT)
        .all()
    )
    approval_counts = _load_approval_counts(db)
    return [
        _serialize_run_item(run, task, approval_counts)
        for run, task in rows
    ]


def _list_recent_failures(db: Session) -> list[agent_schemas.AgentOpsRunItem]:
    rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(
            models.AgentTask.agent_type.in_(OPENCLAW_AGENT_TYPES),
            models.AgentRun.status == "failed",
        )
        .order_by(models.AgentRun.created_at.desc())
        .limit(RECENT_FAILURES_LIMIT)
        .all()
    )
    approval_counts = _load_approval_counts(db)
    return [
        _serialize_run_item(run, task, approval_counts)
        for run, task in rows
    ]


def _get_latest_run(
    db: Session,
    *,
    agent_type: agent_schemas.AgentType,
) -> tuple[models.AgentRun | None, models.AgentTask | None]:
    row = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentTask.agent_type == agent_type)
        .order_by(models.AgentRun.created_at.desc())
        .first()
    )
    if row is None:
        return None, None
    return row


def _follow_up_highlight(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    contact_name = item.get("contact_name")
    contact_id = item.get("contact_id")
    suggested_action = item.get("suggested_action")
    message = item.get("message")

    subject = None
    if isinstance(contact_name, str) and contact_name.strip():
        subject = contact_name.strip()
    elif isinstance(contact_id, int):
        subject = f"Contact #{contact_id}"

    detail = None
    if isinstance(suggested_action, str) and suggested_action.strip():
        detail = suggested_action.strip()
    elif isinstance(message, str) and message.strip():
        detail = _compact_text(message.strip(), limit=80)

    if subject and detail:
        return f"{subject}: {detail}"
    return subject or detail


def _build_follow_up_module_card(
    run: models.AgentRun | None,
    *,
    pending_approvals: int,
) -> agent_schemas.OpenClawModuleCard:
    summary = None
    highlights: list[str] = []

    if run and run.result:
        parsed, _ = _safe_json_loads(run.result)
        if isinstance(parsed, dict):
            recommendations = (
                parsed.get("recommendations")
                if isinstance(parsed.get("recommendations"), list)
                else []
            )
            drafts = (
                parsed.get("drafts")
                if isinstance(parsed.get("drafts"), list)
                else []
            )
            summary = (
                f"{len(recommendations)} recommendation(s), "
                f"{len(drafts)} draft(s) generated."
            )
            for item in recommendations[:3]:
                highlight = _follow_up_highlight(item)
                if highlight:
                    highlights.append(highlight)

    return agent_schemas.OpenClawModuleCard(
        agent_type="follow_up",
        label="Follow-up",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=pending_approvals,
        has_pending_approvals=pending_approvals > 0,
        summary=summary,
        highlights=highlights,
    )


def _build_conversation_closer_module_card(
    run: models.AgentRun | None,
    *,
    pending_approvals: int,
) -> agent_schemas.OpenClawModuleCard:
    result = _parse_run_result(
        run.result if run else None,
        agent_schemas.ConversationCloserResultResponse,
    )
    highlights = list(result.talking_points[:3]) if result else []
    return agent_schemas.OpenClawModuleCard(
        agent_type="conversation_closer",
        label="Client Conversation Closer",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=pending_approvals,
        has_pending_approvals=pending_approvals > 0,
        summary=result.summary if result else None,
        highlights=highlights,
        risk_flags=list(result.risk_flags) if result else [],
        operator_notes=list(result.operator_notes) if result else [],
    )


def _build_listing_cma_module_card(
    run: models.AgentRun | None,
    *,
    pending_approvals: int,
) -> agent_schemas.OpenClawModuleCard:
    result = _parse_run_result(
        run.result if run else None,
        agent_schemas.ListingCmaResultResponse,
    )
    highlights: list[str] = []
    if result:
        highlights.extend(result.listing_brief.property_highlights[:2])
        if result.cma_support.range_framing:
            highlights.append(result.cma_support.range_framing)
    return agent_schemas.OpenClawModuleCard(
        agent_type="listing_cma",
        label="Listing / CMA",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=pending_approvals,
        has_pending_approvals=pending_approvals > 0,
        summary=result.listing_brief.summary if result else None,
        highlights=highlights[:3],
        risk_flags=list(result.risk_flags) if result else [],
        operator_notes=list(result.operator_notes) if result else [],
    )


def _build_buyer_match_module_card(
    run: models.AgentRun | None,
    *,
    pending_approvals: int,
) -> agent_schemas.OpenClawModuleCard:
    result = _parse_run_result(
        run.result if run else None,
        agent_schemas.BuyerMatchResultResponse,
    )
    highlights: list[str] = []
    if result:
        highlights.extend(item.title for item in result.shortlist[:2] if item.title)
        if result.recommended_next_manual_action:
            highlights.append(result.recommended_next_manual_action)
    risk_flags = list(result.risk_flags) if result else []
    if result:
        risk_flags.extend(flag for flag in result.missing_data_flags if flag not in risk_flags)
    return agent_schemas.OpenClawModuleCard(
        agent_type="buyer_match",
        label="Buyer Match",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=pending_approvals,
        has_pending_approvals=pending_approvals > 0,
        summary=result.shortlist_framing if result else None,
        highlights=highlights[:3],
        risk_flags=risk_flags,
        operator_notes=list(result.operator_notes) if result else [],
    )


def _build_strategy_coordination_latest(
    run: models.AgentRun | None,
) -> agent_schemas.StrategyCoordinationLatestResponse:
    result = _parse_run_result(
        run.result if run else None,
        agent_schemas.StrategyCoordinationResultResponse,
    )
    return agent_schemas.StrategyCoordinationLatestResponse(
        run_id=run.id if run else None,
        status=run.status if run else None,
        error=run.error if run else None,
        result=result,
    )


def _build_strategy_coordination_module_card(
    latest: agent_schemas.StrategyCoordinationLatestResponse,
    run: models.AgentRun | None,
) -> agent_schemas.OpenClawModuleCard:
    result = latest.result
    highlights: list[str] = []
    if result:
        highlights.extend(result.strategy_synthesis.key_takeaways[:2])
        highlights.extend(result.recommended_next_actions.human_review_actions[:1])
    return agent_schemas.OpenClawModuleCard(
        agent_type="strategy_coordination",
        label="Strategy Coordination",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=0,
        has_pending_approvals=False,
        summary=result.strategy_synthesis.summary if result else None,
        highlights=highlights[:3],
        risk_flags=list(result.risk_flags) if result else [],
        operator_notes=list(result.operator_notes) if result else [],
    )


def _daily_market_scan_summary(
    result: agent_schemas.DailyMarketScanResultResponse | None,
) -> str | None:
    if result is None:
        return None

    client_count = len(result.client_match_scans)
    competitor_count = len(result.competitor_watch_scans)
    finding_count = sum(
        len(scan.findings)
        for scan in result.client_match_scans + result.competitor_watch_scans
    )
    return (
        f"{result.scan_summary.scan_mode}: {client_count} client scan(s), "
        f"{competitor_count} competitor scan(s), {finding_count} finding(s)."
    )


def _build_daily_market_scan_latest(
    run: models.AgentRun | None,
) -> agent_schemas.DailyMarketScanLatestResponse:
    result = _parse_run_result(
        run.result if run else None,
        agent_schemas.DailyMarketScanResultResponse,
    )
    return agent_schemas.DailyMarketScanLatestResponse(
        run_id=run.id if run else None,
        status=run.status if run else None,
        error=run.error if run else None,
        result=result,
    )


def _build_daily_market_scan_module_card(
    latest: agent_schemas.DailyMarketScanLatestResponse,
    run: models.AgentRun | None,
) -> agent_schemas.OpenClawModuleCard:
    result = latest.result
    highlights: list[str] = []
    if result:
        provider_order = " -> ".join(result.scan_summary.provider_order)
        if provider_order:
            highlights.append(f"Provider order: {provider_order}")
        if result.failure_metadata:
            highlights.append(f"{len(result.failure_metadata)} failure metadata item(s).")
    return agent_schemas.OpenClawModuleCard(
        agent_type="daily_market_scan",
        label="Daily Market Scan",
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        latest_run_created_at=run.created_at if run else None,
        latest_run_finished_at=run.finished_at if run else None,
        latest_run_error=run.error if run else None,
        pending_approvals=0,
        has_pending_approvals=False,
        summary=_daily_market_scan_summary(result),
        highlights=highlights[:3],
        risk_flags=list(result.risk_flags) if result else [],
        operator_notes=list(result.operator_notes) if result else [],
    )


def _build_module_cards(
    db: Session,
    *,
    pending_approvals: list[agent_schemas.AgentOpsApprovalItem],
) -> tuple[
    list[agent_schemas.OpenClawModuleCard],
    agent_schemas.StrategyCoordinationLatestResponse,
    agent_schemas.DailyMarketScanLatestResponse,
]:
    pending_counts: dict[agent_schemas.AgentType, int] = {}
    for item in pending_approvals:
        pending_counts[item.agent_type] = pending_counts.get(item.agent_type, 0) + 1

    cards: list[agent_schemas.OpenClawModuleCard] = []

    follow_up_run, _ = _get_latest_run(db, agent_type="follow_up")
    cards.append(
        _build_follow_up_module_card(
            follow_up_run,
            pending_approvals=pending_counts.get("follow_up", 0),
        )
    )

    conversation_run, _ = _get_latest_run(db, agent_type="conversation_closer")
    cards.append(
        _build_conversation_closer_module_card(
            conversation_run,
            pending_approvals=pending_counts.get("conversation_closer", 0),
        )
    )

    listing_run, _ = _get_latest_run(db, agent_type="listing_cma")
    cards.append(
        _build_listing_cma_module_card(
            listing_run,
            pending_approvals=pending_counts.get("listing_cma", 0),
        )
    )

    buyer_run, _ = _get_latest_run(db, agent_type="buyer_match")
    cards.append(
        _build_buyer_match_module_card(
            buyer_run,
            pending_approvals=pending_counts.get("buyer_match", 0),
        )
    )

    strategy_run, _ = _get_latest_run(db, agent_type="strategy_coordination")
    latest_strategy = _build_strategy_coordination_latest(strategy_run)
    cards.append(_build_strategy_coordination_module_card(latest_strategy, strategy_run))

    market_scan_run, _ = _get_latest_run(db, agent_type="daily_market_scan")
    latest_daily_market_scan = _build_daily_market_scan_latest(market_scan_run)
    cards.append(_build_daily_market_scan_module_card(latest_daily_market_scan, market_scan_run))

    return cards, latest_strategy, latest_daily_market_scan


def _build_pending_approval_needs_input(
    pending_approvals: list[agent_schemas.AgentOpsApprovalItem],
) -> list[agent_schemas.OpenClawNeedsInputItem]:
    items: list[agent_schemas.OpenClawNeedsInputItem] = []
    for approval in pending_approvals:
        title = approval.preview.title or approval.action_type
        summary = (
            approval.preview.subject
            or approval.preview.body_excerpt
            or approval.run_summary
            or "Pending manual review."
        )
        items.append(
            agent_schemas.OpenClawNeedsInputItem(
                kind="pending_approval",
                agent_type=approval.agent_type,
                run_id=approval.run_id,
                approval_id=approval.approval_id,
                title=f"Approval required: {title}",
                summary=summary,
                created_at=approval.created_at,
            )
        )
    return items


def _build_failed_run_needs_input(
    recent_failures: list[agent_schemas.AgentOpsRunItem],
) -> list[agent_schemas.OpenClawNeedsInputItem]:
    items: list[agent_schemas.OpenClawNeedsInputItem] = []
    for run in recent_failures:
        summary = run.error or run.summary or "Run failed."
        items.append(
            agent_schemas.OpenClawNeedsInputItem(
                kind="failed_run",
                agent_type=run.agent_type,
                run_id=run.run_id,
                title=f"Failed run: {AGENT_LABELS.get(run.agent_type, run.agent_type)}",
                summary=summary,
                created_at=run.created_at,
            )
        )
    return items


def _build_strategy_needs_input(
    latest_strategy: agent_schemas.StrategyCoordinationLatestResponse,
    *,
    run_created_at: datetime | None,
) -> list[agent_schemas.OpenClawNeedsInputItem]:
    if latest_strategy.run_id is None or latest_strategy.result is None:
        return []

    items: list[agent_schemas.OpenClawNeedsInputItem] = []
    created_at = run_created_at or _utcnow_naive()
    for action in latest_strategy.result.recommended_next_actions.human_review_actions:
        if not action:
            continue
        items.append(
            agent_schemas.OpenClawNeedsInputItem(
                kind="strategy_human_review",
                agent_type="strategy_coordination",
                run_id=latest_strategy.run_id,
                title="Strategy Coordination review required",
                summary=action,
                created_at=created_at,
            )
        )
    return items


def _daily_attention_summaries(
    result: agent_schemas.DailyMarketScanResultResponse,
) -> list[str]:
    summaries: list[str] = []

    for scan in result.client_match_scans:
        if scan.status in DAILY_MARKET_SCAN_ATTENTION_STATUSES:
            summaries.append(
                f"Client match contact #{scan.contact_id} is {scan.status}."
            )

    for scan in result.competitor_watch_scans:
        if scan.status not in DAILY_MARKET_SCAN_ATTENTION_STATUSES:
            continue

        subject_parts: list[str] = []
        if scan.subject.contact_id is not None:
            subject_parts.append(f"contact #{scan.subject.contact_id}")
        if scan.subject.property_id is not None:
            subject_parts.append(f"property #{scan.subject.property_id}")
        if scan.subject.listing_ref:
            subject_parts.append(scan.subject.listing_ref)
        subject = ", ".join(subject_parts) or scan.subject.competitor_mode
        summaries.append(f"Competitor watch for {subject} is {scan.status}.")

    return summaries


def _build_daily_market_scan_needs_input(
    latest_daily_market_scan: agent_schemas.DailyMarketScanLatestResponse,
    *,
    run_created_at: datetime | None,
) -> list[agent_schemas.OpenClawNeedsInputItem]:
    if (
        latest_daily_market_scan.run_id is None
        or latest_daily_market_scan.result is None
    ):
        return []

    summaries = _daily_attention_summaries(latest_daily_market_scan.result)
    if not summaries:
        return []

    created_at = run_created_at or _utcnow_naive()
    return [
        agent_schemas.OpenClawNeedsInputItem(
            kind="daily_market_scan_attention",
            agent_type="daily_market_scan",
            run_id=latest_daily_market_scan.run_id,
            title="Daily Market Scan needs review",
            summary=summary,
            created_at=created_at,
        )
        for summary in summaries
    ]


def _build_needs_input_today(
    pending_approvals: list[agent_schemas.AgentOpsApprovalItem],
    recent_failures: list[agent_schemas.AgentOpsRunItem],
    recent_runs: list[agent_schemas.AgentOpsRunItem],
    latest_strategy: agent_schemas.StrategyCoordinationLatestResponse,
    latest_daily_market_scan: agent_schemas.DailyMarketScanLatestResponse,
) -> list[agent_schemas.OpenClawNeedsInputItem]:
    run_created_at = {run.run_id: run.created_at for run in recent_runs}
    items = (
        _build_pending_approval_needs_input(pending_approvals)
        + _build_failed_run_needs_input(recent_failures)
        + _build_strategy_needs_input(
            latest_strategy,
            run_created_at=run_created_at.get(latest_strategy.run_id or 0),
        )
        + _build_daily_market_scan_needs_input(
            latest_daily_market_scan,
            run_created_at=run_created_at.get(latest_daily_market_scan.run_id or 0),
        )
    )
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[:NEEDS_INPUT_LIMIT]


def get_control_room_snapshot(
    db: Session,
) -> agent_schemas.OpenClawControlRoomResponse:
    pending_approvals = _list_pending_approvals(db)
    recent_failures = _list_recent_failures(db)
    recent_runs = _list_recent_runs(db)
    module_cards, latest_strategy, latest_daily_market_scan = _build_module_cards(
        db,
        pending_approvals=pending_approvals,
    )

    needs_input_today = _build_needs_input_today(
        pending_approvals,
        recent_failures,
        recent_runs,
        latest_strategy,
        latest_daily_market_scan,
    )

    return agent_schemas.OpenClawControlRoomResponse(
        as_of=_utcnow_naive(),
        guardrails=agent_schemas.OpenClawGuardrails(),
        needs_input_today=needs_input_today,
        pending_approvals=pending_approvals,
        recent_failures=recent_failures,
        recent_runs=recent_runs,
        latest_strategy_coordination=latest_strategy,
        latest_daily_market_scan=latest_daily_market_scan,
        module_cards=module_cards,
    )
