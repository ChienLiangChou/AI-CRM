from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service, tools


INTERNAL_ONLY_OPERATOR_NOTE = (
    "Internal strategy support only. Non-executable output. No client delivery."
)
AUTONOMY_OPERATOR_NOTE = (
    "This layer does not trigger frozen modules and does not execute actions."
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError("strategy_coordination_value_is_not_dumpable")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iso_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value) if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _dedupe_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []

    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _coerce_positive_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        deduped.append(parsed)
    return deduped


def _normalize_source_type(value: Any) -> agent_schemas.StrategyCoordinationSourceType:
    text = (_clean_text(value) or "").lower()
    if text == "external":
        return "external"
    return "internal"


def _normalize_urgency(value: Any) -> agent_schemas.StrategyCoordinationUrgency:
    text = (_clean_text(value) or "").lower()
    if text in {"low", "medium", "high"}:
        return text  # type: ignore[return-value]
    return "medium"


def normalize_linked_entities(
    raw: Any,
) -> agent_schemas.StrategyCoordinationLinkedEntities:
    if isinstance(raw, agent_schemas.StrategyCoordinationLinkedEntities):
        return raw

    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()

    if not isinstance(raw, dict):
        raw = {}

    listings_raw = raw.get("listings")
    listings: list[agent_schemas.StrategyCoordinationListingReference] = []
    seen_listing_refs: set[str] = set()
    if isinstance(listings_raw, list):
        for item in listings_raw:
            if isinstance(item, agent_schemas.StrategyCoordinationListingReference):
                listing = item
            elif isinstance(item, dict):
                property_id = _coerce_positive_int(item.get("property_id"))
                listing_ref = _clean_text(item.get("listing_ref"))
                if listing_ref is None and property_id is not None:
                    listing_ref = f"manual:property:{property_id}"
                if listing_ref is None:
                    continue
                listing = agent_schemas.StrategyCoordinationListingReference(
                    listing_ref=listing_ref,
                    property_id=property_id,
                    label=_clean_text(item.get("label")),
                )
            else:
                continue

            if listing.listing_ref in seen_listing_refs:
                continue
            seen_listing_refs.add(listing.listing_ref)
            listings.append(listing)

    return agent_schemas.StrategyCoordinationLinkedEntities(
        contacts=_dedupe_int_list(raw.get("contacts")),
        properties=_dedupe_int_list(raw.get("properties")),
        listings=listings,
        runs=_dedupe_int_list(raw.get("runs")),
        approvals=_dedupe_int_list(raw.get("approvals")),
    )


def normalize_run_request(
    raw: Any,
) -> agent_schemas.StrategyCoordinationRunRequest:
    if isinstance(raw, agent_schemas.StrategyCoordinationRunRequest):
        return raw

    if not isinstance(raw, dict):
        raise TypeError("strategy_coordination_request_must_be_dict")

    event_type = _clean_text(raw.get("event_type")) or "manual_event"
    summary = _clean_text(raw.get("summary")) or "Manual event submitted for review."

    return agent_schemas.StrategyCoordinationRunRequest(
        event_type=event_type,
        source_type=_normalize_source_type(raw.get("source_type")),
        summary=summary,
        details=_clean_text(raw.get("details")),
        urgency=_normalize_urgency(raw.get("urgency")),
        operator_goal=_clean_text(raw.get("operator_goal")),
        linked_entities=normalize_linked_entities(raw.get("linked_entities")),
    )


def _linked_entity_count(
    linked_entities: agent_schemas.StrategyCoordinationLinkedEntities,
) -> int:
    return (
        len(linked_entities.contacts)
        + len(linked_entities.properties)
        + len(linked_entities.listings)
        + len(linked_entities.runs)
        + len(linked_entities.approvals)
    )


def conservative_importance_assessment(
    request: agent_schemas.StrategyCoordinationRunRequest | dict[str, Any],
) -> agent_schemas.StrategyCoordinationImportanceAssessment:
    normalized_request = normalize_run_request(request)
    linked_entities = normalize_linked_entities(normalized_request.linked_entities)
    linked_count = _linked_entity_count(linked_entities)

    if linked_count == 0:
        if normalized_request.urgency == "high":
            return agent_schemas.StrategyCoordinationImportanceAssessment(
                classification="watchlist",
                reason=(
                    "High-urgency event has no linked business entities yet, so it"
                    " should stay on the watchlist until impact is clearer."
                ),
                confidence=0.72,
            )
        return agent_schemas.StrategyCoordinationImportanceAssessment(
            classification="noise",
            reason=(
                "Event lacks linked contacts, properties, listings, runs, or"
                " approvals and does not justify a strategy review yet."
            ),
            confidence=0.86,
        )

    if normalized_request.urgency == "high":
        return agent_schemas.StrategyCoordinationImportanceAssessment(
            classification="strategy_review_required",
            reason=(
                "High-urgency event is already linked to active business entities"
                " and merits a structured strategy review."
            ),
            confidence=0.81,
        )

    if linked_count >= 3 and normalized_request.urgency == "medium":
        return agent_schemas.StrategyCoordinationImportanceAssessment(
            classification="strategy_review_required",
            reason=(
                "Event is linked to multiple business entities and now meets the"
                " threshold for structured strategy review."
            ),
            confidence=0.77,
        )

    return agent_schemas.StrategyCoordinationImportanceAssessment(
        classification="watchlist",
        reason=(
            "Event has some linked business impact, but the current signal remains"
            " below the threshold for immediate strategy review."
        ),
        confidence=0.69,
    )


def _build_perspective_block(
    *,
    relevance: agent_schemas.StrategyCoordinationPerspectiveRelevance,
    summary: str,
    supporting_signals: list[str] | None = None,
    risk_flags: list[str] | None = None,
) -> agent_schemas.StrategyCoordinationPerspectiveBlock:
    return agent_schemas.StrategyCoordinationPerspectiveBlock(
        relevance=relevance,
        summary=summary,
        supporting_signals=supporting_signals or [],
        risk_flags=risk_flags or [],
    )


def default_execution_policy() -> agent_schemas.StrategyCoordinationExecutionPolicy:
    return agent_schemas.StrategyCoordinationExecutionPolicy(
        mode="internal_only_non_executable",
        can_execute_actions=False,
        can_trigger_agents=False,
        can_create_client_outputs=False,
    )


def _safe_task_payload_json(raw: Any) -> str:
    try:
        normalized = normalize_run_request(raw)
        return _json_dumps(_model_dump(normalized))
    except Exception:
        return _json_dumps(
            {
                "raw_event_input": _clean_text(raw) or str(raw),
                "payload_normalization_failed": True,
            }
        )


def _priority_from_urgency(
    urgency: agent_schemas.StrategyCoordinationUrgency,
) -> str:
    if urgency == "high":
        return "high"
    if urgency == "low":
        return "low"
    return "normal"


def _contact_fact(contact: Any) -> dict[str, Any]:
    return {
        "contact_id": getattr(contact, "id", None),
        "name": getattr(contact, "name", None),
        "client_type": getattr(contact, "client_type", None),
        "status": getattr(contact, "status", None),
        "stage_id": getattr(contact, "stage_id", None),
    }


def _property_address(property_record: Any) -> str | None:
    street = getattr(property_record, "street", None)
    unit = getattr(property_record, "unit", None)
    if street and unit:
        return f"{street} #{unit}"
    return street


def _property_fact(property_record: Any) -> dict[str, Any]:
    return {
        "property_id": getattr(property_record, "id", None),
        "address": _property_address(property_record),
        "property_type": getattr(property_record, "property_type", None),
        "status": getattr(property_record, "status", None),
        "neighborhood": getattr(property_record, "neighborhood", None),
    }


def _run_fact(run: models.AgentRun, task: models.AgentTask | None) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "task_id": run.task_id,
        "agent_type": task.agent_type if task is not None else None,
        "status": run.status,
        "summary": run.summary,
        "error": run.error,
        "created_at": _iso_datetime(run.created_at),
        "finished_at": _iso_datetime(run.finished_at),
    }


def _approval_fact(
    approval: models.AgentApproval,
    run: models.AgentRun | None,
    task: models.AgentTask | None,
) -> dict[str, Any]:
    return {
        "approval_id": approval.id,
        "run_id": approval.run_id,
        "task_id": run.task_id if run is not None else None,
        "agent_type": task.agent_type if task is not None else None,
        "action_type": approval.action_type,
        "risk_level": approval.risk_level,
        "status": approval.status,
        "created_at": _iso_datetime(approval.created_at),
    }


def build_linked_context_snapshot(
    db: Session,
    linked_entities: agent_schemas.StrategyCoordinationLinkedEntities,
) -> dict[str, Any]:
    contact_facts = []
    missing_contacts = []
    for contact_id in linked_entities.contacts:
        contact = tools.get_contact_tool(db, contact_id)
        if contact is None:
            missing_contacts.append(contact_id)
            continue
        contact_facts.append(_contact_fact(contact))

    property_facts = []
    missing_properties = []
    for property_id in linked_entities.properties:
        property_record = tools.get_property_tool(db, property_id)
        if property_record is None:
            missing_properties.append(property_id)
            continue
        property_facts.append(_property_fact(property_record))

    run_rows = (
        db.query(models.AgentRun, models.AgentTask)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentRun.id.in_(linked_entities.runs or [-1]))
        .all()
        if linked_entities.runs
        else []
    )
    run_map = {run.id: (run, task) for run, task in run_rows}
    run_facts = []
    missing_runs = []
    for run_id in linked_entities.runs:
        run_row = run_map.get(run_id)
        if run_row is None:
            missing_runs.append(run_id)
            continue
        run_facts.append(_run_fact(run_row[0], run_row[1]))

    approval_rows = (
        db.query(models.AgentApproval, models.AgentRun, models.AgentTask)
        .join(models.AgentRun, models.AgentApproval.run_id == models.AgentRun.id)
        .join(models.AgentTask, models.AgentRun.task_id == models.AgentTask.id)
        .filter(models.AgentApproval.id.in_(linked_entities.approvals or [-1]))
        .all()
        if linked_entities.approvals
        else []
    )
    approval_map = {
        approval.id: (approval, run, task)
        for approval, run, task in approval_rows
    }
    approval_facts = []
    missing_approvals = []
    for approval_id in linked_entities.approvals:
        approval_row = approval_map.get(approval_id)
        if approval_row is None:
            missing_approvals.append(approval_id)
            continue
        approval_facts.append(
            _approval_fact(
                approval_row[0],
                approval_row[1],
                approval_row[2],
            )
        )

    listings = [_model_dump(listing) for listing in linked_entities.listings]

    return {
        "contacts": {
            "found": contact_facts,
            "missing_ids": missing_contacts,
        },
        "properties": {
            "found": property_facts,
            "missing_ids": missing_properties,
        },
        "listings": listings,
        "runs": {
            "found": run_facts,
            "missing_ids": missing_runs,
        },
        "approvals": {
            "found": approval_facts,
            "missing_ids": missing_approvals,
        },
        "counts": {
            "contacts_found": len(contact_facts),
            "properties_found": len(property_facts),
            "listings_linked": len(listings),
            "runs_found": len(run_facts),
            "approvals_found": len(approval_facts),
        },
    }


def _resolved_linked_context_count(linked_context: dict[str, Any]) -> int:
    counts = linked_context.get("counts", {}) if isinstance(linked_context, dict) else {}
    return (
        int(counts.get("contacts_found", 0))
        + int(counts.get("properties_found", 0))
        + int(counts.get("listings_linked", 0))
        + int(counts.get("runs_found", 0))
        + int(counts.get("approvals_found", 0))
    )


def _has_missing_linked_records(linked_context: dict[str, Any]) -> bool:
    if not isinstance(linked_context, dict):
        return False
    for key in ("contacts", "properties", "runs", "approvals"):
        section = linked_context.get(key, {})
        if isinstance(section, dict) and section.get("missing_ids"):
            return True
    return False


def _adjust_importance_for_resolved_context(
    request: agent_schemas.StrategyCoordinationRunRequest,
    importance: agent_schemas.StrategyCoordinationImportanceAssessment,
    linked_context: dict[str, Any],
) -> agent_schemas.StrategyCoordinationImportanceAssessment:
    resolved_count = _resolved_linked_context_count(linked_context)
    if resolved_count > 0:
        return importance

    if request.urgency == "high":
        return agent_schemas.StrategyCoordinationImportanceAssessment(
            classification="watchlist",
            reason=(
                "Linked business references could not be resolved yet, so this event"
                " remains on the watchlist until clearer context is available."
            ),
            confidence=0.66,
        )

    return agent_schemas.StrategyCoordinationImportanceAssessment(
        classification="noise",
        reason=(
            "Linked business references could not be resolved and the event remains"
            " below the threshold for strategy review."
        ),
        confidence=0.78,
    )


def build_perspective_blocks(
    linked_entities: agent_schemas.StrategyCoordinationLinkedEntities,
    importance: agent_schemas.StrategyCoordinationImportanceAssessment,
    *,
    linked_context: dict[str, Any] | None = None,
) -> agent_schemas.StrategyCoordinationPerspectiveBlocks:
    if linked_context is None:
        linked_context = {}

    contacts_present = bool(
        (linked_context.get("contacts", {}) or {}).get("found")
    ) or len(linked_entities.contacts) > 0
    listings_present = len(linked_entities.listings) > 0
    properties_present = bool(
        (linked_context.get("properties", {}) or {}).get("found")
    ) or len(linked_entities.properties) > 0
    runs_present = bool((linked_context.get("runs", {}) or {}).get("found")) or len(
        linked_entities.runs
    ) > 0
    approvals_present = bool(
        (linked_context.get("approvals", {}) or {}).get("found")
    ) or len(linked_entities.approvals) > 0

    follow_up_relevance: agent_schemas.StrategyCoordinationPerspectiveRelevance = (
        "high"
        if contacts_present and importance.classification == "strategy_review_required"
        else "medium"
        if contacts_present
        else "none"
    )
    conversation_relevance: agent_schemas.StrategyCoordinationPerspectiveRelevance = (
        "medium"
        if contacts_present and importance.classification != "noise"
        else "none"
    )
    listing_relevance: agent_schemas.StrategyCoordinationPerspectiveRelevance = (
        "medium"
        if properties_present or listings_present
        else "none"
    )
    operations_relevance: agent_schemas.StrategyCoordinationPerspectiveRelevance = (
        "medium"
        if runs_present or approvals_present
        else "low"
        if importance.classification == "strategy_review_required"
        else "none"
    )

    follow_up_signals = []
    if contacts_present:
        follow_up_signals.append(
            f"{len(linked_entities.contacts)} linked contact(s) are available for follow-up review."
        )

    conversation_signals = []
    if contacts_present:
        conversation_signals.append(
            "Linked contact context may affect buyer or seller retention conversations."
        )

    listing_signals = []
    if properties_present:
        listing_signals.append(
            f"{len(linked_entities.properties)} linked propert"
            f"{'y' if len(linked_entities.properties) == 1 else 'ies'} may be affected."
        )
    if listings_present:
        listing_signals.append(
            f"{len(linked_entities.listings)} linked listing reference(s) are available."
        )

    operations_signals = []
    if runs_present:
        operations_signals.append(
            f"{len(linked_entities.runs)} linked run(s) can be inspected for operational context."
        )
    if approvals_present:
        operations_signals.append(
            f"{len(linked_entities.approvals)} linked approval(s) can be reviewed for bottlenecks."
        )

    return agent_schemas.StrategyCoordinationPerspectiveBlocks(
        follow_up=_build_perspective_block(
            relevance=follow_up_relevance,
            summary=(
                "Follow-up perspective reserved for linked-contact review."
                if contacts_present
                else "No linked contact context was provided for follow-up review."
            ),
            supporting_signals=follow_up_signals,
        ),
        conversation_retention=_build_perspective_block(
            relevance=conversation_relevance,
            summary=(
                "Conversation/retention perspective reserved for linked-contact review."
                if contacts_present
                else "No linked contact context was provided for conversation review."
            ),
            supporting_signals=conversation_signals,
        ),
        listing_seller=_build_perspective_block(
            relevance=listing_relevance,
            summary=(
                "Listing/seller perspective reserved for linked property or listing review."
                if properties_present or listings_present
                else "No linked property or listing context was provided."
            ),
            supporting_signals=listing_signals,
        ),
        operations_compliance=_build_perspective_block(
            relevance=operations_relevance,
            summary=(
                "Operations/compliance perspective reserved for linked run and approval review."
                if runs_present or approvals_present
                else "No linked run or approval context was provided."
            ),
            supporting_signals=operations_signals,
        ),
    )


def build_internal_report(
    request: agent_schemas.StrategyCoordinationRunRequest | dict[str, Any],
    *,
    linked_context: dict[str, Any] | None = None,
    importance_assessment: (
        agent_schemas.StrategyCoordinationImportanceAssessment | None
    ) = None,
) -> agent_schemas.StrategyCoordinationResultResponse:
    normalized_request = normalize_run_request(request)
    linked_entities = normalize_linked_entities(normalized_request.linked_entities)
    if linked_context is None:
        linked_context = {}
    importance = importance_assessment or conservative_importance_assessment(
        normalized_request
    )
    perspective_blocks = build_perspective_blocks(
        linked_entities,
        importance,
        linked_context=linked_context,
    )

    risk_flags: list[str] = []
    if _resolved_linked_context_count(linked_context) == 0:
        risk_flags.append("linked_context_sparse")
    if _has_missing_linked_records(linked_context):
        risk_flags.append("linked_records_missing")

    if importance.classification == "noise":
        synthesis_summary = (
            "Event logged as noise. No structured strategy review is recommended"
            " at this time."
        )
        key_takeaways = [
            "The current event signal is below the strategy-review threshold.",
            "Linked business context is too limited to justify broader coordination.",
        ]
        internal_actions = [
            "Record the event and monitor for clearer linked business impact."
        ]
        human_review_actions: list[str] = []
    elif importance.classification == "watchlist":
        synthesis_summary = (
            "Event should remain on the watchlist until linked business impact is"
            " clearer."
        )
        key_takeaways = [
            "The event has some signal but does not yet justify full strategy review.",
            "Further linked context would improve confidence before escalating.",
        ]
        internal_actions = [
            "Keep the event on the watchlist and update linked entities if new impact appears."
        ]
        human_review_actions = [
            "Decide whether to revisit this event after more business context is available."
        ]
    else:
        synthesis_summary = (
            "Event merits structured internal strategy review across the fixed"
            " perspectives."
        )
        key_takeaways = [
            "Linked business context is strong enough for coordinated review.",
            "Any next step still requires explicit human judgment and manual action.",
        ]
        internal_actions = [
            "Review the linked entities and inspect the relevant fixed perspective blocks."
        ]
        human_review_actions = [
            "Decide whether to manually run any frozen module after reviewing this report."
        ]

    operator_notes = [
        INTERNAL_ONLY_OPERATOR_NOTE,
        AUTONOMY_OPERATOR_NOTE,
    ]
    if "linked_context_sparse" in risk_flags:
        operator_notes.append(
            "Linked business context is sparse; keep this report at metadata level only."
        )
    if "linked_records_missing" in risk_flags:
        operator_notes.append(
            "Some linked IDs could not be resolved; treat affected-entity mapping as partial."
        )

    return agent_schemas.StrategyCoordinationResultResponse(
        event_summary=agent_schemas.StrategyCoordinationEventSummary(
            event_type=normalized_request.event_type,
            source_type=normalized_request.source_type,
            summary=normalized_request.summary,
            details=normalized_request.details,
            urgency=normalized_request.urgency,
        ),
        importance_assessment=importance,
        affected_entities=linked_entities,
        execution_policy=default_execution_policy(),
        perspective_blocks=perspective_blocks,
        strategy_synthesis=agent_schemas.StrategyCoordinationSynthesis(
            summary=synthesis_summary,
            key_takeaways=key_takeaways,
        ),
        recommended_next_actions=agent_schemas.StrategyCoordinationRecommendedActions(
            internal_actions=internal_actions,
            human_review_actions=human_review_actions,
        ),
        risk_flags=risk_flags,
        operator_notes=operator_notes,
    )


def plan_strategy_coordination_run(
    db: Session,
    request: agent_schemas.StrategyCoordinationRunRequest | dict[str, Any],
) -> dict[str, Any]:
    normalized_request = normalize_run_request(request)
    linked_entities = normalize_linked_entities(normalized_request.linked_entities)
    linked_context = build_linked_context_snapshot(db, linked_entities)
    base_importance = conservative_importance_assessment(normalized_request)
    adjusted_importance = _adjust_importance_for_resolved_context(
        normalized_request,
        base_importance,
        linked_context,
    )

    return {
        "event_snapshot": _model_dump(normalized_request),
        "operator_goal": normalized_request.operator_goal,
        "importance_assessment": _model_dump(adjusted_importance),
        "affected_entities": _model_dump(linked_entities),
        "linked_context": linked_context,
        "execution_policy": _model_dump(default_execution_policy()),
        "perspective_scope": [
            "follow_up",
            "conversation_retention",
            "listing_seller",
            "operations_compliance",
        ],
    }


def execute_strategy_coordination_run(
    db: Session,
    run: models.AgentRun,
    request: agent_schemas.StrategyCoordinationRunRequest | dict[str, Any],
) -> dict[str, Any]:
    if not run.plan:
        raise ValueError("strategy_coordination_plan_missing")

    plan = json.loads(run.plan)
    normalized_request = normalize_run_request(request)
    importance = agent_schemas.StrategyCoordinationImportanceAssessment(
        **plan["importance_assessment"]
    )
    result = build_internal_report(
        normalized_request,
        linked_context=plan.get("linked_context", {}),
        importance_assessment=importance,
    )
    return _model_dump(result)


def run_strategy_coordination_once(
    db: Session,
    request: agent_schemas.StrategyCoordinationRunRequest | dict[str, Any] | Any,
) -> models.AgentRun:
    payload_json = _safe_task_payload_json(request)
    try:
        normalized_request = normalize_run_request(request)
    except Exception:
        normalized_request = None
    task = service.create_task(
        db,
        agent_type="strategy_coordination",
        subject_type="event",
        subject_id=None,
        payload=payload_json,
        priority=(
            _priority_from_urgency(normalized_request.urgency)
            if normalized_request is not None
            else "normal"
        ),
    )
    run = service.create_run(
        db,
        task=task,
        summary="Strategy Coordination run (MVP)",
    )

    now = datetime.utcnow()
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(db, run, status="planning", started_at=now)

    try:
        if normalized_request is None:
            normalized_request = normalize_run_request(request)

        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="strategy_coordination_event_intake",
            details=payload_json,
        )

        plan_data = plan_strategy_coordination_run(db, normalized_request)
        plan_json = _json_dumps(plan_data)
        run = service.update_run_status(
            db,
            run,
            status="executing",
            plan=plan_json,
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="strategy_coordination_classification_generated",
            details=_json_dumps(plan_data["importance_assessment"]),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="strategy_coordination_entities_mapped",
            details=_json_dumps(
                {
                    "affected_entities": plan_data["affected_entities"],
                    "linked_context": plan_data["linked_context"],
                }
            ),
        )

        perspective_blocks = build_perspective_blocks(
            normalized_request.linked_entities,
            agent_schemas.StrategyCoordinationImportanceAssessment(
                **plan_data["importance_assessment"]
            ),
            linked_context=plan_data["linked_context"],
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="strategy_coordination_perspectives_generated",
            details=_json_dumps(_model_dump(perspective_blocks)),
        )

        result = execute_strategy_coordination_run(db, run, normalized_request)
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="strategy_coordination_strategy_synthesized",
            details=_json_dumps(
                {
                    "strategy_synthesis": result["strategy_synthesis"],
                    "recommended_next_actions": result["recommended_next_actions"],
                    "execution_policy": result["execution_policy"],
                }
            ),
        )

        finished_at = datetime.utcnow()
        result_json = _json_dumps(result)
        run = service.update_run_status(
            db,
            run,
            status="completed",
            result=result_json,
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status="completed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="strategy_coordination_run_completed",
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
            action="strategy_coordination_run_failed",
            details=_json_dumps({"error": str(exc)}),
        )
        return run
