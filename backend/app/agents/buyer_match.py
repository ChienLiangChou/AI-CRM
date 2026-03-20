from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service, tools


MAX_CANDIDATES = 5
MAX_BUYER_DRAFTS = 1
BUYER_DRAFT_VARIANT = "shortlist_summary"
BUYER_DRAFT_APPROVAL_ACTION = "send_buyer_shortlist_summary"
SHORTLIST_SUPPORT_DISCLAIMER = (
    "Internal shortlist support only. Not final purchase or offer advice."
)


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _safe_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _add_unique(values: list[str], value: str | None) -> None:
    candidate = (value or "").strip()
    if candidate and candidate not in values:
        values.append(candidate)


def _normalize_area(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    return text or None


def _format_currency(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:,.0f}"


def _property_address(property_record) -> str | None:
    if property_record is None:
        return None
    street = getattr(property_record, "street", None)
    unit = getattr(property_record, "unit", None)
    if street and unit:
        return f"{street} #{unit}"
    return street


def _build_candidate_title(candidate: dict[str, Any]) -> str:
    return candidate.get("address") or f"Candidate #{candidate['index']}"


def _get_context(
    db: Session,
    request: agent_schemas.BuyerMatchRunRequest,
) -> dict[str, Any]:
    contact = tools.get_contact_tool(db, request.contact_id)
    if contact is None:
        raise ValueError("contact_not_found")

    if len(request.candidates) > MAX_CANDIDATES:
        raise ValueError("candidate_limit_exceeded")

    interactions = tools.get_contact_interactions_tool(db, request.contact_id)
    property_ids = [
        candidate.property_id
        for candidate in request.candidates
        if candidate.property_id is not None
    ]
    property_map = {
        property_record.id: property_record
        for property_record in tools.get_properties_tool(db, property_ids)
    }

    resolved_candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(request.candidates, start=1):
        property_record = None
        if candidate.property_id is not None:
            property_record = property_map.get(candidate.property_id)
            if property_record is None:
                raise ValueError("candidate_property_not_found")

        address = candidate.address or _property_address(property_record)
        if not address:
            raise ValueError("candidate_missing_address_or_property_id")

        resolved_candidates.append(
            {
                "index": index,
                "property_id": candidate.property_id,
                "address": address,
                "list_price": (
                    candidate.list_price
                    if candidate.list_price is not None
                    else getattr(property_record, "listing_price", None)
                ),
                "property_type": candidate.property_type
                or getattr(property_record, "property_type", None),
                "bedrooms": (
                    candidate.bedrooms
                    if candidate.bedrooms is not None
                    else getattr(property_record, "bedrooms", None)
                ),
                "bathrooms": (
                    candidate.bathrooms
                    if candidate.bathrooms is not None
                    else getattr(property_record, "bathrooms", None)
                ),
                "sqft": (
                    candidate.sqft
                    if candidate.sqft is not None
                    else getattr(property_record, "sqft", None)
                ),
                "parking": (
                    candidate.parking
                    if candidate.parking is not None
                    else getattr(property_record, "parking", None)
                ),
                "area": candidate.area or getattr(property_record, "neighborhood", None),
                "notes": candidate.notes or getattr(property_record, "notes", None),
            }
        )

    return {
        "contact": contact,
        "interactions": interactions,
        "candidates": resolved_candidates,
    }


def _normalize_criteria(
    contact,
    request: agent_schemas.BuyerMatchRunRequest,
) -> dict[str, Any]:
    property_preferences = _safe_json_dict(getattr(contact, "property_preferences", None))
    preferred_areas = request.criteria.areas or _safe_json_list(
        getattr(contact, "preferred_areas", None)
    )

    property_types = property_preferences.get("types")
    property_type = request.criteria.property_type or property_preferences.get("property_type")
    if property_type is None and isinstance(property_types, list) and property_types:
        property_type = str(property_types[0]).strip()

    bedrooms_min = request.criteria.bedrooms_min
    if bedrooms_min is None and property_preferences.get("bedrooms_min") is not None:
        bedrooms_min = int(property_preferences["bedrooms_min"])

    bathrooms_min = request.criteria.bathrooms_min
    if bathrooms_min is None and property_preferences.get("bathrooms_min") is not None:
        bathrooms_min = int(property_preferences["bathrooms_min"])

    sqft_min = request.criteria.sqft_min
    if sqft_min is None and property_preferences.get("sqft_min") is not None:
        sqft_min = int(property_preferences["sqft_min"])

    parking_required = request.criteria.parking_required or bool(
        property_preferences.get("parking_required")
    )

    must_haves = [item for item in request.criteria.must_haves if item.strip()]
    for item in property_preferences.get("must_haves", []) if isinstance(property_preferences.get("must_haves"), list) else []:
        _add_unique(must_haves, str(item))
    if bedrooms_min is not None:
        _add_unique(must_haves, f"{bedrooms_min}+ beds")
    if bathrooms_min is not None:
        _add_unique(must_haves, f"{bathrooms_min}+ baths")
    if sqft_min is not None:
        _add_unique(must_haves, f"{sqft_min}+ sqft")
    if parking_required:
        _add_unique(must_haves, "parking")

    nice_to_haves = [item for item in request.criteria.nice_to_haves if item.strip()]
    deal_breakers = [item for item in request.criteria.deal_breakers if item.strip()]
    for item in property_preferences.get("deal_breakers", []) if isinstance(property_preferences.get("deal_breakers"), list) else []:
        _add_unique(deal_breakers, str(item))

    return {
        "budget_min": (
            request.criteria.budget_min
            if request.criteria.budget_min is not None
            else getattr(contact, "budget_min", None)
        ),
        "budget_max": (
            request.criteria.budget_max
            if request.criteria.budget_max is not None
            else getattr(contact, "budget_max", None)
        ),
        "areas": preferred_areas,
        "property_type": property_type,
        "bedrooms_min": bedrooms_min,
        "bathrooms_min": bathrooms_min,
        "sqft_min": sqft_min,
        "parking_required": parking_required,
        "timeline": request.criteria.timeline,
        "must_haves": must_haves,
        "nice_to_haves": nice_to_haves,
        "deal_breakers": deal_breakers,
    }


def _score_candidate(
    candidate: dict[str, Any],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    score = 0.0
    why_it_fits: list[str] = []
    tradeoffs: list[str] = []

    price = candidate.get("list_price")
    budget_min = criteria.get("budget_min")
    budget_max = criteria.get("budget_max")
    if price is not None and budget_min is not None and budget_max is not None:
        if budget_min <= price <= budget_max:
            score += 2.0
            _add_unique(why_it_fits, "Fits the current budget range.")
        elif price > budget_max:
            _add_unique(tradeoffs, "Priced above the current budget range.")
        else:
            _add_unique(tradeoffs, "Priced below the stated range, so fit depends on flexibility.")
    elif price is None and (budget_min is not None or budget_max is not None):
        _add_unique(tradeoffs, "Price input is incomplete for a budget check.")

    areas = {_normalize_area(area) for area in criteria.get("areas", []) if _normalize_area(area)}
    candidate_area = _normalize_area(candidate.get("area"))
    if areas:
        if candidate_area in areas:
            score += 1.5
            _add_unique(why_it_fits, "Matches the buyer's preferred area.")
        else:
            _add_unique(tradeoffs, "Area is outside the current preferred area list.")

    property_type = (criteria.get("property_type") or "").strip().lower()
    candidate_type = (candidate.get("property_type") or "").strip().lower()
    if property_type:
        if candidate_type == property_type:
            score += 1.0
            _add_unique(why_it_fits, "Matches the preferred property type.")
        else:
            _add_unique(tradeoffs, "Property type is not an exact match.")

    bedrooms_min = criteria.get("bedrooms_min")
    if bedrooms_min is not None:
        bedrooms = candidate.get("bedrooms")
        if bedrooms is None:
            _add_unique(tradeoffs, "Bedroom count is incomplete.")
        elif bedrooms >= bedrooms_min:
            score += 1.0
            _add_unique(why_it_fits, f"Meets the {bedrooms_min}+ bedroom target.")
        else:
            _add_unique(tradeoffs, "Has fewer bedrooms than requested.")

    bathrooms_min = criteria.get("bathrooms_min")
    if bathrooms_min is not None:
        bathrooms = candidate.get("bathrooms")
        if bathrooms is None:
            _add_unique(tradeoffs, "Bathroom count is incomplete.")
        elif bathrooms >= bathrooms_min:
            score += 0.75
            _add_unique(why_it_fits, f"Meets the {bathrooms_min}+ bathroom target.")
        else:
            _add_unique(tradeoffs, "Has fewer bathrooms than requested.")

    sqft_min = criteria.get("sqft_min")
    if sqft_min is not None:
        sqft = candidate.get("sqft")
        if sqft is None:
            _add_unique(tradeoffs, "Square footage is incomplete.")
        elif sqft >= sqft_min:
            score += 0.75
            _add_unique(why_it_fits, f"Meets the {sqft_min}+ sqft target.")
        else:
            _add_unique(tradeoffs, "Smaller than the current size target.")

    if criteria.get("parking_required"):
        parking = candidate.get("parking")
        if parking and parking > 0:
            score += 1.0
            _add_unique(why_it_fits, "Includes parking.")
        else:
            _add_unique(tradeoffs, "Does not clearly satisfy the parking requirement.")

    if not why_it_fits:
        _add_unique(why_it_fits, "Worth a manual review based on the available context.")

    if score >= 5:
        match_strength = "strong"
    elif score >= 3:
        match_strength = "moderate"
    else:
        match_strength = "limited"

    return {
        "title": _build_candidate_title(candidate),
        "property_id": candidate.get("property_id"),
        "match_strength": match_strength,
        "why_it_fits": why_it_fits[:3],
        "tradeoffs": tradeoffs[:3],
        "_score": score,
    }


def _build_buyer_needs_summary(
    contact,
    criteria: dict[str, Any],
    request: agent_schemas.BuyerMatchRunRequest,
) -> dict[str, Any]:
    summary_parts: list[str] = []

    if criteria.get("property_type"):
        summary_parts.append(f"{criteria['property_type']} buyer")
    else:
        summary_parts.append("buyer")

    if criteria.get("areas"):
        summary_parts.append(
            f"focused on {', '.join(criteria['areas'][:2])}"
        )

    if criteria.get("budget_min") is not None or criteria.get("budget_max") is not None:
        budget_min = _format_currency(criteria.get("budget_min"))
        budget_max = _format_currency(criteria.get("budget_max"))
        if budget_min and budget_max:
            summary_parts.append(f"with a {budget_min}-{budget_max} budget")
        elif budget_max:
            summary_parts.append(f"with a budget up to {budget_max}")
        elif budget_min:
            summary_parts.append(f"with a budget starting around {budget_min}")

    if request.buyer_context_notes:
        summary_parts.append(request.buyer_context_notes)

    summary = " ".join(summary_parts).strip().capitalize()
    if not summary.endswith("."):
        summary = f"{summary}."

    return {
        "summary": summary,
        "must_haves": criteria["must_haves"],
        "nice_to_haves": criteria["nice_to_haves"],
        "deal_breakers": criteria["deal_breakers"],
    }


def _build_tradeoff_summary(shortlist: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in shortlist:
        for tradeoff in item["tradeoffs"]:
            _add_unique(lines, tradeoff)
    if not lines and shortlist:
        lines.append("The current shortlist is fairly balanced on the available criteria.")
    if not lines:
        lines.append("No candidate listings were entered for shortlist comparison.")
    return lines[:3]


def _build_missing_data_flags(
    candidates: list[dict[str, Any]],
    criteria: dict[str, Any],
) -> list[str]:
    flags: list[str] = []

    if not candidates:
        flags.append("manual_candidates_missing")
        return flags

    if any(candidate.get("list_price") is None for candidate in candidates):
        flags.append("candidate_pricing_incomplete")

    if criteria.get("areas") and any(not candidate.get("area") for candidate in candidates):
        flags.append("candidate_area_incomplete")

    return flags


def _build_operator_notes(missing_data_flags: list[str]) -> list[str]:
    notes = [
        SHORTLIST_SUPPORT_DISCLAIMER,
        "Buyer-facing shortlist drafts must be reviewed before external use.",
        "Keep the next step focused on criteria confirmation, not offer or negotiation advice.",
    ]
    if "manual_candidates_missing" in missing_data_flags:
        notes.append("Enter a shortlist-sized candidate set before sharing anything externally.")
    if "candidate_pricing_incomplete" in missing_data_flags:
        notes.append("Missing candidate pricing weakens budget-fit reasoning.")
    return notes


def _build_risk_flags(
    missing_data_flags: list[str],
    has_buyer_draft: bool,
) -> list[str]:
    flags: list[str] = []
    if missing_data_flags:
        flags.append("insufficient_candidate_data")
    if has_buyer_draft:
        flags.append("buyer_facing_summary_requires_review")
    return flags


def _build_recommended_next_action(
    shortlist: list[dict[str, Any]],
    missing_data_flags: list[str],
) -> str:
    if "manual_candidates_missing" in missing_data_flags:
        return (
            "Enter up to 5 candidate listings and confirm the buyer's top two non-negotiables "
            "before sharing any shortlist externally."
        )
    if shortlist:
        return (
            "Review the top 2 matches with the buyer and confirm whether budget, area, or parking "
            "is the first constraint to settle."
        )
    return (
        "Tighten the buyer criteria and candidate set before using this for any external shortlist summary."
    )


def _build_plan(
    request: agent_schemas.BuyerMatchRunRequest,
    context: dict[str, Any],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    contact = context["contact"]
    candidates = context["candidates"]
    property_backed_count = sum(1 for candidate in candidates if candidate["property_id"] is not None)

    return {
        "input_snapshot": request.model_dump(),
        "buyer_context": {
            "contact_name": getattr(contact, "name", None),
            "client_type": getattr(contact, "client_type", None),
            "preferred_language": getattr(contact, "preferred_language", None),
            "recent_interaction_count": len(context["interactions"]),
        },
        "normalized_criteria": {
            "budget_band": (
                f"{_format_currency(criteria['budget_min'])}-{_format_currency(criteria['budget_max'])}"
                if criteria.get("budget_min") is not None and criteria.get("budget_max") is not None
                else _format_currency(criteria.get("budget_max"))
                if criteria.get("budget_max") is not None
                else _format_currency(criteria.get("budget_min"))
            ),
            "areas": criteria["areas"],
            "property_type": criteria["property_type"],
            "must_haves": criteria["must_haves"],
            "nice_to_haves": criteria["nice_to_haves"],
            "deal_breakers": criteria["deal_breakers"],
        },
        "candidate_summary": {
            "count": len(candidates),
            "operator_entered": True,
            "property_backed_count": property_backed_count,
            "manual_only_count": len(candidates) - property_backed_count,
        },
        "matching_frame": {
            "reasoning_note": SHORTLIST_SUPPORT_DISCLAIMER,
        },
    }


def _fallback_buyer_draft(contact_name: str, result: dict[str, Any]) -> dict[str, str]:
    shortlist_lines = []
    for item in result["shortlist"][:2]:
        reasons = ", ".join(item["why_it_fits"][:2])
        shortlist_lines.append(f"- {item['title']}: {reasons}")

    body_sections = [
        f"Hi {contact_name},",
        "I pulled together a short list of options that look worth reviewing based on the criteria we discussed.",
        "This is a starting shortlist for review, not a final recommendation or purchase decision.",
        "\n".join(shortlist_lines) if shortlist_lines else "I still need a stronger candidate set before sharing a shortlist.",
        "If helpful, we can review which criteria matter most before narrowing the next round.",
        "Kevin",
    ]
    return {
        "subject": "Shortlist to review",
        "body": "\n\n".join(section for section in body_sections if section),
    }


def _build_buyer_draft_prompt(
    contact_name: str,
    result: dict[str, Any],
) -> str:
    return f"""
You are drafting one buyer-facing shortlist summary for a Toronto real estate operator.

Hard rules:
- This is review-only drafting support.
- Do not present this shortlist as a final recommendation.
- Do not give offer, negotiation, legal, or purchase advice.
- Do not create urgency or pressure.
- Keep the summary practical, concise, and grounded in fit and tradeoffs.
- Return ONLY JSON with keys "subject" and "body".

Context:
- Buyer name: {contact_name}
- Shortlist framing: {result["shortlist_framing"]}
- Buyer needs summary: {json.dumps(result["buyer_needs_summary"], ensure_ascii=False)}
- Ranked shortlist: {json.dumps(result["shortlist"], ensure_ascii=False)}
- Tradeoff summary: {json.dumps(result["tradeoff_summary"], ensure_ascii=False)}
- Recommended next manual action: {result["recommended_next_manual_action"]}
- Operator notes: {json.dumps(result["operator_notes"], ensure_ascii=False)}
""".strip()


def _parse_buyer_draft(raw: str) -> dict[str, str] | None:
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


def _generate_buyer_draft(contact_name: str, result: dict[str, Any]) -> dict[str, str]:
    raw = tools.call_llm_tool(_build_buyer_draft_prompt(contact_name, result))
    parsed = _parse_buyer_draft(raw)
    if parsed is not None:
        return parsed
    return _fallback_buyer_draft(contact_name, result)


def _should_generate_buyer_draft(result: dict[str, Any]) -> bool:
    return bool(result["shortlist"]) and "manual_candidates_missing" not in result["missing_data_flags"]


def plan_buyer_match_run(
    db: Session,
    request: agent_schemas.BuyerMatchRunRequest,
) -> dict[str, Any]:
    context = _get_context(db, request)
    criteria = _normalize_criteria(context["contact"], request)
    return _build_plan(request, context, criteria)


def execute_buyer_match_run(
    db: Session,
    run: models.AgentRun,
    request: agent_schemas.BuyerMatchRunRequest,
) -> dict[str, Any]:
    if not run.plan:
        raise ValueError("buyer_match_plan_missing")

    context = _get_context(db, request)
    contact = context["contact"]
    criteria = _normalize_criteria(contact, request)
    missing_data_flags = _build_missing_data_flags(context["candidates"], criteria)

    ranked_candidates = [
        _score_candidate(candidate, criteria)
        for candidate in context["candidates"]
    ]
    ranked_candidates.sort(key=lambda item: (-item["_score"], item["title"].lower()))
    shortlist = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        shortlist.append(
            {
                "rank": rank,
                "title": candidate["title"],
                "property_id": candidate["property_id"],
                "match_strength": candidate["match_strength"],
                "why_it_fits": candidate["why_it_fits"],
                "tradeoffs": candidate["tradeoffs"],
            }
        )

    result = {
        "buyer_needs_summary": _build_buyer_needs_summary(contact, criteria, request),
        "shortlist_framing": SHORTLIST_SUPPORT_DISCLAIMER,
        "shortlist": shortlist,
        "tradeoff_summary": _build_tradeoff_summary(shortlist),
        "recommended_next_manual_action": _build_recommended_next_action(
            shortlist,
            missing_data_flags,
        ),
        "buyer_drafts": [],
        "risk_flags": [],
        "missing_data_flags": missing_data_flags,
        "operator_notes": _build_operator_notes(missing_data_flags),
    }

    if not _should_generate_buyer_draft(result):
        service.write_audit_log(
            db,
            run=run,
            task=run.task if run.task is not None else None,
            actor_type="system",
            action="buyer_match_candidate_set_missing",
            details=json.dumps(
                {
                    "missing_data_flags": missing_data_flags,
                    "shortlist_framing": SHORTLIST_SUPPORT_DISCLAIMER,
                },
                ensure_ascii=False,
            ),
        )
        result["risk_flags"] = _build_risk_flags(missing_data_flags, False)
        return result

    draft = _generate_buyer_draft(getattr(contact, "name", "Buyer"), result)
    approval_payload = {
        "contact_id": request.contact_id,
        "variant": BUYER_DRAFT_VARIANT,
        "subject": draft["subject"],
        "body": draft["body"],
        "shortlist_titles": [item["title"] for item in result["shortlist"][:3]],
        "shortlist_framing": SHORTLIST_SUPPORT_DISCLAIMER,
        "review_mode": "manual_only",
    }
    approval = service.create_approval(
        db,
        run=run,
        action_type=BUYER_DRAFT_APPROVAL_ACTION,
        risk_level="high",
        payload=json.dumps(approval_payload, ensure_ascii=False),
    )
    service.write_audit_log(
        db,
        run=run,
        task=run.task if run.task is not None else None,
        actor_type="agent",
        action="generate_buyer_match_draft",
        details=json.dumps(approval_payload, ensure_ascii=False),
    )
    result["buyer_drafts"].append(
        {
            "variant": BUYER_DRAFT_VARIANT,
            "subject": draft["subject"],
            "body": draft["body"],
            "approval_id": approval.id,
        }
    )
    result["risk_flags"] = _build_risk_flags(missing_data_flags, True)
    result["buyer_drafts"] = result["buyer_drafts"][:MAX_BUYER_DRAFTS]
    return result


def run_buyer_match_once(
    db: Session,
    request: agent_schemas.BuyerMatchRunRequest,
) -> models.AgentRun:
    task = service.create_task(
        db,
        agent_type="buyer_match",
        subject_type="contact",
        subject_id=request.contact_id,
        payload=json.dumps(request.model_dump(), ensure_ascii=False),
    )
    run = service.create_run(db, task=task, summary="Buyer Match run (MVP)")

    now = datetime.utcnow()
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(db, run, status="planning", started_at=now)

    try:
        plan_data = plan_buyer_match_run(db, request)
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
            action="buyer_match_context_loaded",
            details=json.dumps(
                {
                    "contact_id": request.contact_id,
                    "goal": request.goal,
                    "candidate_count": len(request.candidates),
                },
                ensure_ascii=False,
            ),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="buyer_match_analysis_generated",
            details=json.dumps(plan_data["matching_frame"], ensure_ascii=False),
        )

        result = execute_buyer_match_run(db, run, request)
        next_status = "waiting_approval" if result["buyer_drafts"] else "completed"
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
                "buyer_match_run_waiting_approval"
                if result["buyer_drafts"]
                else "buyer_match_run_completed"
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
            action="buyer_match_run_failed",
            details=json.dumps({"error": str(exc)}, ensure_ascii=False),
        )
        return run
