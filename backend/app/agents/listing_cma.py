from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service, tools


MAX_SELLER_DRAFTS = 1
SELLER_DRAFT_VARIANT = "post_meeting_summary"
SELLER_DRAFT_APPROVAL_ACTION = "send_listing_cma_summary"
PRICING_SUPPORT_DISCLAIMER = (
    "Internal discussion support only. Not final list-price authority."
)


def _format_currency(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:,.0f}"


def _get_context(
    db: Session,
    request: agent_schemas.ListingCmaRunRequest,
) -> dict[str, Any]:
    contact = tools.get_contact_tool(db, request.contact_id)
    if contact is None:
        raise ValueError("contact_not_found")

    property_record = None
    if request.property_id is not None:
        property_record = tools.get_property_tool(db, request.property_id)
        if property_record is None:
            raise ValueError("property_not_found")

    owned_properties = tools.get_contact_owned_properties_tool(db, request.contact_id)
    return {
        "contact": contact,
        "property": property_record,
        "owned_properties": owned_properties,
    }


def _comparable_prices(
    comparables: list[agent_schemas.ListingCmaComparableInput],
) -> list[float]:
    values: list[float] = []
    for comparable in comparables:
        if comparable.price is not None and comparable.price > 0:
            values.append(comparable.price)
    return values


def _missing_data_flags(
    request: agent_schemas.ListingCmaRunRequest,
    property_record,
    owned_properties,
) -> list[str]:
    flags: list[str] = []

    if not request.comparables:
        flags.append("manual_comparables_missing")
    elif not _comparable_prices(request.comparables):
        flags.append("comparable_prices_missing")

    if property_record is None:
        if request.property_id is None:
            flags.append("subject_property_not_selected")
        else:
            flags.append("subject_property_missing")

    if property_record is None and not request.subject_property_notes:
        flags.append("subject_property_notes_missing")

    if request.property_id is None and owned_properties:
        flags.append("contact_has_linked_properties_but_none_selected")

    return flags


def _build_property_highlights(property_record, request) -> list[str]:
    highlights: list[str] = []

    if property_record is not None:
        if property_record.property_type:
            highlights.append(property_record.property_type.title())
        if property_record.bedrooms is not None or property_record.bathrooms is not None:
            bed = property_record.bedrooms if property_record.bedrooms is not None else "?"
            bath = property_record.bathrooms if property_record.bathrooms is not None else "?"
            highlights.append(f"{bed} bed / {bath} bath")
        if property_record.sqft:
            highlights.append(f"{property_record.sqft} sqft")
        if property_record.parking:
            highlights.append(f"{property_record.parking} parking")
        if property_record.neighborhood:
            highlights.append(f"Neighborhood: {property_record.neighborhood}")

    if request.subject_property_notes:
        highlights.append(request.subject_property_notes)

    return highlights[:5]


def _build_seller_context(contact, request) -> list[str]:
    context: list[str] = []
    if getattr(contact, "client_type", None):
        context.append(f"Client type: {contact.client_type}")
    if request.meeting_goal:
        context.append(f"Meeting goal: {request.meeting_goal}")
    if request.seller_context_notes:
        context.append(request.seller_context_notes)
    if getattr(contact, "notes", None):
        context.append(contact.notes)
    return context[:4]


def _build_listing_brief(
    contact,
    property_record,
    request: agent_schemas.ListingCmaRunRequest,
) -> dict[str, Any]:
    property_label = "property"
    if property_record is not None:
        street = getattr(property_record, "street", None)
        unit = getattr(property_record, "unit", None)
        if street and unit:
            property_label = f"{street} #{unit}"
        elif street:
            property_label = street

    summary = (
        f"Listing prep brief for {getattr(contact, 'name', 'seller')} "
        f"around {property_label}."
    )
    return {
        "summary": summary,
        "property_highlights": _build_property_highlights(property_record, request),
        "seller_context": _build_seller_context(contact, request),
    }


def _build_comparable_narrative(
    comparables: list[agent_schemas.ListingCmaComparableInput],
    prices: list[float],
) -> list[str]:
    if not comparables:
        return ["No operator-entered comparables were provided for this run."]

    lines = [f"{len(comparables)} operator-entered comparable(s) were provided."]

    sold_count = sum(1 for comparable in comparables if comparable.status.lower() == "sold")
    active_count = sum(1 for comparable in comparables if comparable.status.lower() == "active")
    if sold_count:
        lines.append(f"{sold_count} comparable(s) are sold references.")
    if active_count:
        lines.append(f"{active_count} comparable(s) are active competition.")

    if prices:
        low = _format_currency(min(prices))
        high = _format_currency(max(prices))
        lines.append(
            f"Comparable pricing spans roughly {low} to {high} based on manual input."
        )
    else:
        lines.append("Comparable prices were not sufficient to frame a discussion range.")

    return lines


def _build_cma_support(
    request: agent_schemas.ListingCmaRunRequest,
    missing_data_flags: list[str],
) -> dict[str, Any]:
    prices = _comparable_prices(request.comparables)
    range_text = None
    if prices:
        low = _format_currency(min(prices))
        high = _format_currency(max(prices))
        if low == high:
            range_text = f"{low} discussion point"
        else:
            range_text = f"{low}-{high} discussion band"

    return {
        "internal_price_discussion_range": range_text,
        "range_framing": PRICING_SUPPORT_DISCLAIMER,
        "comparable_narrative": _build_comparable_narrative(request.comparables, prices),
        "missing_data_flags": missing_data_flags,
    }


def _build_talking_points(
    request: agent_schemas.ListingCmaRunRequest,
    cma_support: dict[str, Any],
) -> list[str]:
    points = [
        "Frame any pricing language as positioning support, not authority.",
        "Use manual comparable input to support a discussion, not a final recommendation.",
        "Keep seller-facing discussion focused on reasoning, competition, and execution.",
    ]
    if cma_support["internal_price_discussion_range"] is None:
        points.append("Do not discuss a pricing band externally until stronger comparables are entered.")
    if request.meeting_goal == "post_walkthrough_summary":
        points.append("Keep the follow-up concise and recap-oriented.")
    return points


def _build_operator_notes(
    missing_data_flags: list[str],
) -> list[str]:
    notes = [
        PRICING_SUPPORT_DISCLAIMER,
        "Seller-facing drafts must be reviewed before any external use.",
    ]
    if "manual_comparables_missing" in missing_data_flags:
        notes.append("Add operator-entered comparables before using this for CMA discussion.")
    if "comparable_prices_missing" in missing_data_flags:
        notes.append("Comparable pricing data is incomplete; do not imply a market-supported range.")
    if "subject_property_not_selected" in missing_data_flags:
        notes.append("Property context is incomplete; keep output internal only.")
    return notes


def _build_risk_flags(
    cma_support: dict[str, Any],
    missing_data_flags: list[str],
) -> list[str]:
    flags = ["pricing_language_requires_review"]
    if cma_support["internal_price_discussion_range"] is None:
        flags.append("insufficient_comparable_data")
    if missing_data_flags:
        flags.append("missing_context_data")
    return flags


def _build_plan(
    request: agent_schemas.ListingCmaRunRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    contact = context["contact"]
    property_record = context["property"]
    owned_properties = context["owned_properties"]
    missing_flags = _missing_data_flags(request, property_record, owned_properties)
    cma_support = _build_cma_support(request, missing_flags)

    return {
        "input_snapshot": request.model_dump(),
        "subject_property": {
            "property_id": getattr(property_record, "id", None),
            "address": (
                f"{property_record.street} #{property_record.unit}"
                if property_record is not None
                and getattr(property_record, "street", None)
                and getattr(property_record, "unit", None)
                else getattr(property_record, "street", None)
                if property_record is not None
                else None
            ),
            "property_type": getattr(property_record, "property_type", None),
            "bedrooms": getattr(property_record, "bedrooms", None),
            "bathrooms": getattr(property_record, "bathrooms", None),
            "sqft": getattr(property_record, "sqft", None),
        },
        "seller_context": {
            "contact_name": getattr(contact, "name", None),
            "client_type": getattr(contact, "client_type", None),
            "preferred_language": getattr(contact, "preferred_language", None),
            "linked_owned_properties_count": len(owned_properties),
        },
        "comparables_summary": {
            "count": len(request.comparables),
            "operator_entered": True,
            "price_span": (
                [min(_comparable_prices(request.comparables)), max(_comparable_prices(request.comparables))]
                if _comparable_prices(request.comparables)
                else None
            ),
        },
        "support_framing": {
            "pricing_note": PRICING_SUPPORT_DISCLAIMER,
            "missing_data_flags": missing_flags,
            "internal_price_discussion_range": cma_support["internal_price_discussion_range"],
        },
    }


def _fallback_seller_draft(contact_name: str, result: dict[str, Any]) -> dict[str, str]:
    range_text = result["cma_support"]["internal_price_discussion_range"] or "the current discussion range"
    return {
        "subject": "Summary from today",
        "body": (
            f"Hi {contact_name},\n\n"
            "Thanks again for the conversation today.\n\n"
            f"I have organized the comparable discussion points and internal market framing around {range_text}. "
            "I am keeping this focused on positioning and decision support rather than a final pricing recommendation.\n\n"
            "I can walk you through the reasoning and next steps live so the discussion stays grounded and clear.\n\n"
            "Kevin"
        ),
    }


def _build_seller_draft_prompt(
    contact_name: str,
    request: agent_schemas.ListingCmaRunRequest,
    result: dict[str, Any],
) -> str:
    return f"""
You are drafting one seller-facing follow-up for a real estate operator.

Hard rules:
- This is review-only drafting support.
- Do not present any price or range as final authority.
- Do not state or imply a final list-price recommendation.
- Do not make legal, disclosure, or compliance claims.
- Keep the tone clear, professional, and measured.
- Return ONLY JSON with keys "subject" and "body".

Context:
- Seller name: {contact_name}
- Meeting goal: {request.meeting_goal}
- Pricing framing: {result["cma_support"]["range_framing"]}
- Internal discussion range: {result["cma_support"]["internal_price_discussion_range"]}
- Comparable summary: {json.dumps(result["cma_support"]["comparable_narrative"], ensure_ascii=False)}
- Talking points: {json.dumps(result["talking_points"], ensure_ascii=False)}
- Operator notes: {json.dumps(result["operator_notes"], ensure_ascii=False)}
""".strip()


def _parse_seller_draft(raw: str) -> dict[str, str] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    candidate = parsed[0] if isinstance(parsed, list) and parsed else parsed
    if not isinstance(candidate, dict):
        return None

    subject = candidate.get("subject")
    body = candidate.get("body")
    if not isinstance(subject, str) or not subject.strip():
        return None
    if not isinstance(body, str) or not body.strip():
        return None

    return {"subject": subject.strip(), "body": body.strip()}


def _should_generate_seller_draft(result: dict[str, Any]) -> bool:
    return result["cma_support"]["internal_price_discussion_range"] is not None


def _generate_seller_draft(
    contact_name: str,
    request: agent_schemas.ListingCmaRunRequest,
    result: dict[str, Any],
) -> dict[str, str]:
    raw = tools.call_llm_tool(_build_seller_draft_prompt(contact_name, request, result))
    parsed = _parse_seller_draft(raw)
    if parsed is not None:
        return parsed
    return _fallback_seller_draft(contact_name, result)


def plan_listing_cma_run(
    db: Session,
    request: agent_schemas.ListingCmaRunRequest,
) -> dict[str, Any]:
    context = _get_context(db, request)
    return _build_plan(request, context)


def execute_listing_cma_run(
    db: Session,
    run: models.AgentRun,
    request: agent_schemas.ListingCmaRunRequest,
) -> dict[str, Any]:
    if not run.plan:
        raise ValueError("listing_cma_plan_missing")

    plan = json.loads(run.plan)
    context = _get_context(db, request)
    contact = context["contact"]
    property_record = context["property"]
    owned_properties = context["owned_properties"]
    missing_flags = _missing_data_flags(request, property_record, owned_properties)

    result = {
        "listing_brief": _build_listing_brief(contact, property_record, request),
        "cma_support": _build_cma_support(request, missing_flags),
        "talking_points": _build_talking_points(request, _build_cma_support(request, missing_flags)),
        "seller_drafts": [],
        "risk_flags": [],
        "operator_notes": _build_operator_notes(missing_flags),
    }
    result["risk_flags"] = _build_risk_flags(result["cma_support"], missing_flags)

    if not _should_generate_seller_draft(result):
        service.write_audit_log(
            db,
            run=run,
            task=run.task if run.task is not None else None,
            actor_type="system",
            action="listing_cma_insufficient_comparables",
            details=json.dumps(
                {
                    "missing_data_flags": missing_flags,
                    "pricing_note": PRICING_SUPPORT_DISCLAIMER,
                },
                ensure_ascii=False,
            ),
        )
        return result

    draft = _generate_seller_draft(getattr(contact, "name", "Seller"), request, result)
    approval_payload = {
        "contact_id": request.contact_id,
        "property_id": request.property_id,
        "variant": SELLER_DRAFT_VARIANT,
        "subject": draft["subject"],
        "body": draft["body"],
        "pricing_framing": PRICING_SUPPORT_DISCLAIMER,
        "internal_price_discussion_range": result["cma_support"]["internal_price_discussion_range"],
        "review_mode": "manual_only",
    }
    approval = service.create_approval(
        db,
        run=run,
        action_type=SELLER_DRAFT_APPROVAL_ACTION,
        risk_level="high",
        payload=json.dumps(approval_payload, ensure_ascii=False),
    )
    service.write_audit_log(
        db,
        run=run,
        task=run.task if run.task is not None else None,
        actor_type="agent",
        action="generate_listing_cma_seller_draft",
        details=json.dumps(approval_payload, ensure_ascii=False),
    )
    result["seller_drafts"].append(
        {
            "variant": SELLER_DRAFT_VARIANT,
            "subject": draft["subject"],
            "body": draft["body"],
            "approval_id": approval.id,
        }
    )
    return result


def run_listing_cma_once(
    db: Session,
    request: agent_schemas.ListingCmaRunRequest,
) -> models.AgentRun:
    task = service.create_task(
        db,
        agent_type="listing_cma",
        subject_type="property" if request.property_id is not None else "contact",
        subject_id=request.property_id or request.contact_id,
        payload=json.dumps(request.model_dump(), ensure_ascii=False),
    )
    run = service.create_run(db, task=task, summary="Listing / CMA run (MVP)")

    now = datetime.utcnow()
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(db, run, status="planning", started_at=now)

    try:
        plan_data = plan_listing_cma_run(db, request)
        run = service.update_run_status(
            db,
            run,
            status="executing",
            plan=json.dumps(plan_data, ensure_ascii=False),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="listing_cma_context_loaded",
            details=json.dumps(
                {
                    "contact_id": request.contact_id,
                    "property_id": request.property_id,
                    "comparables_count": len(request.comparables),
                    "meeting_goal": request.meeting_goal,
                },
                ensure_ascii=False,
            ),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="listing_cma_analysis_generated",
            details=json.dumps(plan_data["support_framing"], ensure_ascii=False),
        )

        result = execute_listing_cma_run(db, run, request)
        next_status = "waiting_approval" if result["seller_drafts"] else "completed"
        finished_at = datetime.utcnow()
        run = service.update_run_status(
            db,
            run,
            status=next_status,
            result=json.dumps(result, ensure_ascii=False),
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status=next_status)
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action=(
                "listing_cma_run_waiting_approval"
                if result["seller_drafts"]
                else "listing_cma_run_completed"
            ),
            details=json.dumps(result, ensure_ascii=False),
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
            action="listing_cma_run_failed",
            details=json.dumps({"error": str(exc)}, ensure_ascii=False),
        )
        return run
