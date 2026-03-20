from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service, tools


MAX_DRAFT_VARIANTS = 2
DRAFT_VARIANTS = ("direct_practical", "relationship_first")
CLIENT_REPLY_APPROVAL_ACTION = "send_client_reply"

LEGAL_COMPLIANCE_KEYWORDS = (
    "legal",
    "lawyer",
    "law",
    "lawsuit",
    "contract clause",
    "binding",
    "breach",
    "liability",
    "compliance",
    "illegal",
)
PRICE_AUTHORITY_KEYWORDS = (
    "cut your commission",
    "lower your commission",
    "reduce your fee",
    "discount your fee",
    "match that rate",
    "beat that rate",
    "can you do",
)


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _detect_objection_types(message: str, client_type: str | None) -> list[str]:
    lowered = _normalize_text(message)
    types: list[str] = []

    def add(value: str):
        if value not in types:
            types.append(value)

    fee_keywords = ("commission", "fee", "fees", "rate", "%")
    if _contains_any(lowered, fee_keywords):
        if client_type == "seller":
            add("seller_commission_objection")
        elif client_type == "landlord":
            add("landlord_fee_objection")
        else:
            add("buyer_commission_objection")

    if _contains_any(lowered, ("other agents", "interviewing", "shopping around", "compare", "comparing")):
        add("shopping_around")

    if _contains_any(lowered, ("wait", "later", "hold off", "timing", "rates", "not ready")):
        add("timing_hesitation")

    if _contains_any(lowered, ("overpay", "too expensive", "price too high", "overpriced")):
        add("buyer_price_concern")

    if _contains_any(lowered, ("lowball", "offer is low", "too low", "cheap offer")):
        add("seller_offer_concern")

    if _contains_any(lowered, ("trust", "not sure", "comfortable", "confident", "reassure")):
        add("trust_objection")

    if _contains_any(lowered, ("think about it", "talk to my spouse", "talk to my wife", "talk to my husband", "talk to family", "sleep on it")):
        add("decision_delay")

    if _contains_any(lowered, ("negotiate", "negotiation", "counter", "offer terms")):
        add("negotiation_support")

    if not types:
        add("general_hesitation")

    return types


def _detect_sentiment(message: str) -> str:
    lowered = _normalize_text(message)
    if _contains_any(lowered, ("ridiculous", "frustrated", "upset", "annoyed", "unfair")):
        return "frustrated"
    if _contains_any(lowered, ("not sure", "compare", "think about it", "wait", "hesitant")):
        return "guarded"
    return "neutral"


def _detect_urgency(message: str) -> str:
    lowered = _normalize_text(message)
    if _contains_any(lowered, ("today", "asap", "urgent", "deadline", "tonight")):
        return "high"
    if _contains_any(lowered, ("this week", "soon", "offer", "meeting")):
        return "medium"
    return "low"


def _detect_risk_flags(message: str, objection_types: list[str]) -> list[str]:
    lowered = _normalize_text(message)
    flags: list[str] = []

    def add(value: str):
        if value not in flags:
            flags.append(value)

    if _contains_any(lowered, LEGAL_COMPLIANCE_KEYWORDS):
        add("legal_or_compliance_risk")

    if re.search(r"\$\s?\d+|\d+\s?%", lowered):
        add("pricing_or_commission_authority_requested")
    if _contains_any(lowered, PRICE_AUTHORITY_KEYWORDS):
        add("pricing_or_commission_authority_requested")

    if any(
        objection in objection_types
        for objection in (
            "buyer_commission_objection",
            "seller_commission_objection",
            "landlord_fee_objection",
        )
    ):
        add("commission_or_fee_sensitivity")

    if "shopping_around" in objection_types:
        add("competitor_comparison")

    if any(
        objection in objection_types
        for objection in ("buyer_price_concern", "seller_offer_concern", "negotiation_support")
    ):
        add("negotiation_sensitivity")

    return flags


def _requires_manual_escalation(risk_flags: list[str]) -> bool:
    return "legal_or_compliance_risk" in risk_flags


def _build_strategy(
    request: agent_schemas.ConversationCloserRunRequest,
    primary_type: str,
    risk_flags: list[str],
) -> dict[str, Any]:
    if _requires_manual_escalation(risk_flags):
        return {
            "recommended_action": "manual_escalation_only",
            "goal": request.desired_outcome or "protect_client_trust",
            "tone": "calm_and_cautious",
            "rationale": "Conversation includes legal or compliance risk and should stay human-led.",
            "do_not_say": [
                "Do not interpret legal terms or contract enforceability.",
                "Do not make any pricing or commission commitments.",
            ],
        }

    rationale_by_type = {
        "seller_commission_objection": "Acknowledge the fee concern and redirect toward service value and fit.",
        "buyer_commission_objection": "Acknowledge cost sensitivity and keep the reply focused on representation value and next-step clarity.",
        "landlord_fee_objection": "Address fee concern without negotiating terms or making commitments.",
        "shopping_around": "Keep trust intact while making it easy to continue the conversation.",
        "timing_hesitation": "Reduce pressure and make the next step feel low-friction.",
        "buyer_price_concern": "Acknowledge the concern and reframe around decision quality rather than pressure.",
        "seller_offer_concern": "Protect confidence while avoiding premature negotiation statements.",
        "decision_delay": "Respect the pause while keeping momentum alive.",
        "trust_objection": "Lead with calm reassurance and clarity.",
        "negotiation_support": "Offer a measured response without crossing into authority or commitment.",
        "general_hesitation": "Use a calm, practical reply to keep the dialogue moving.",
    }

    return {
        "recommended_action": "review_reply_drafts",
        "goal": request.desired_outcome or "keep_conversation_open",
        "tone": "calm_and_practical",
        "rationale": rationale_by_type.get(primary_type, rationale_by_type["general_hesitation"]),
        "do_not_say": [
            "Do not make legal or compliance statements.",
            "Do not promise pricing, commission, or negotiation outcomes.",
            "Do not pressure the client into an immediate commitment.",
        ],
    }


def _build_talking_points(primary_type: str, risk_flags: list[str]) -> list[str]:
    base_points = {
        "seller_commission_objection": [
            "Acknowledge the fee concern without getting defensive.",
            "Re-anchor on service, representation quality, and execution.",
            "Invite a short conversation about what the client actually values most.",
        ],
        "buyer_commission_objection": [
            "Acknowledge the concern about cost and clarity.",
            "Keep the conversation focused on representation and guidance value.",
            "Offer to walk through the process without pressure.",
        ],
        "landlord_fee_objection": [
            "Validate the concern about fees.",
            "Keep the response focused on service scope and fit.",
            "Avoid quoting or changing fee terms in writing.",
        ],
        "shopping_around": [
            "Normalize comparison shopping without sounding defensive.",
            "Differentiate based on fit and execution, not pressure.",
            "Invite one focused next step instead of a long sales pitch.",
        ],
        "timing_hesitation": [
            "Respect the timing concern and lower pressure.",
            "Offer clarity on tradeoffs instead of pushing urgency.",
            "Suggest a lightweight next step.",
        ],
        "buyer_price_concern": [
            "Acknowledge concern about overpaying.",
            "Reframe around process, protection, and informed decision-making.",
            "Avoid making price predictions or guarantees.",
        ],
        "seller_offer_concern": [
            "Acknowledge disappointment without escalating emotion.",
            "Keep the conversation focused on options and positioning.",
            "Avoid guaranteeing negotiation outcomes.",
        ],
        "decision_delay": [
            "Respect the pause and avoid pressure.",
            "Make it easy for the client to re-engage.",
            "Offer to answer one or two key concerns directly.",
        ],
        "trust_objection": [
            "Lead with reassurance and transparency.",
            "Keep the reply calm and specific.",
            "Avoid overpromising.",
        ],
        "negotiation_support": [
            "Keep the response measured and non-committal.",
            "Avoid making negotiating promises in writing.",
            "Use the reply to preserve leverage and trust.",
        ],
        "general_hesitation": [
            "Acknowledge the hesitation clearly.",
            "Keep the next step simple and low-pressure.",
            "Avoid sounding scripted or forceful.",
        ],
    }
    talking_points = list(base_points.get(primary_type, base_points["general_hesitation"]))
    if "pricing_or_commission_authority_requested" in risk_flags:
        talking_points.append("Do not quote or authorize pricing or commission changes in the reply.")
    if "legal_or_compliance_risk" in risk_flags:
        talking_points.append("Keep any legal/compliance issue fully human-reviewed.")
    return talking_points


def _build_operator_notes(risk_flags: list[str]) -> list[str]:
    notes = [
        "Review all client-facing drafts manually before use.",
        "Keep the reply focused on trust, clarity, and next-step momentum.",
    ]
    if "pricing_or_commission_authority_requested" in risk_flags:
        notes.append("Do not authorize fee, pricing, or commission changes from this draft alone.")
    if "legal_or_compliance_risk" in risk_flags:
        notes.append("Escalate legal or contract interpretation to manual handling only.")
    return notes


def _build_context_summary(
    request: agent_schemas.ConversationCloserRunRequest,
    contact,
    interactions,
    matched_interaction,
    property_obj,
) -> dict[str, Any]:
    return {
        "contact_id": contact.id,
        "contact_name": contact.name,
        "client_type": getattr(contact, "client_type", None),
        "preferred_language": getattr(contact, "preferred_language", None),
        "stage_id": getattr(contact, "stage_id", None),
        "interaction_id": request.interaction_id,
        "property_id": request.property_id,
        "property_type": getattr(property_obj, "property_type", None) if property_obj else None,
        "channel": request.channel,
        "recent_interaction_count": len(interactions),
        "matched_interaction_type": getattr(matched_interaction, "interaction_type", None) if matched_interaction else None,
    }


def _select_interaction(interactions, interaction_id: int | None):
    if interaction_id is None:
        return None
    for interaction in interactions:
        if interaction.id == interaction_id:
            return interaction
    return None


def _build_context(
    db: Session,
    request: agent_schemas.ConversationCloserRunRequest,
) -> dict[str, Any]:
    contact = tools.get_contact_tool(db, request.contact_id)
    if contact is None:
        raise ValueError("contact_not_found")

    interactions = tools.get_contact_interactions_tool(db, request.contact_id)
    matched_interaction = _select_interaction(interactions, request.interaction_id)
    if request.interaction_id is not None and matched_interaction is None:
        raise ValueError("interaction_not_found_for_contact")

    property_obj = None
    if request.property_id is not None:
        property_obj = tools.get_property_tool(db, request.property_id)
        if property_obj is None:
            raise ValueError("property_not_found")

    return {
        "contact": contact,
        "interactions": interactions,
        "matched_interaction": matched_interaction,
        "property": property_obj,
    }


def plan_conversation_closer_run(
    db: Session,
    request: agent_schemas.ConversationCloserRunRequest,
) -> Dict[str, Any]:
    context = _build_context(db, request)
    contact = context["contact"]

    objection_types = _detect_objection_types(
        request.message,
        getattr(contact, "client_type", None),
    )
    primary_type = objection_types[0]
    secondary_types = objection_types[1:3]
    sentiment = _detect_sentiment(request.message)
    urgency = _detect_urgency(request.message)
    risk_flags = _detect_risk_flags(request.message, objection_types)
    requires_manual_escalation = _requires_manual_escalation(risk_flags)

    analysis = {
        "primary_type": primary_type,
        "secondary_types": secondary_types,
        "sentiment": sentiment,
        "confidence": 0.86 if primary_type != "general_hesitation" else 0.62,
        "urgency": urgency,
        "requires_manual_escalation": requires_manual_escalation,
    }
    strategy = _build_strategy(request, primary_type, risk_flags)
    talking_points = _build_talking_points(primary_type, risk_flags)
    operator_notes = _build_operator_notes(risk_flags)
    summary = (
        f"{getattr(contact, 'name', 'Client')} shows {primary_type.replace('_', ' ')}; "
        f"{strategy['recommended_action']} is recommended."
    )

    return {
        "input_snapshot": request.model_dump(),
        "context_summary": _build_context_summary(
            request,
            contact,
            context["interactions"],
            context["matched_interaction"],
            context["property"],
        ),
        "objection_analysis": analysis,
        "response_strategy": strategy,
        "talking_points": talking_points,
        "risk_flags": risk_flags,
        "operator_notes": operator_notes,
        "summary": summary,
    }


def _build_style_sentence(primary_type: str, variant: str) -> str:
    variant_tone = {
        "direct_practical": {
            "seller_commission_objection": "I understand the fee is an important part of your decision, and it makes sense to look closely at what you are getting in return.",
            "buyer_commission_objection": "I understand you want clarity around cost and what representation actually gives you.",
            "landlord_fee_objection": "I understand the fee question is central to whether this feels worthwhile.",
            "shopping_around": "It is completely reasonable to compare options before deciding who you want to work with.",
            "timing_hesitation": "I understand you may not want to move too quickly without more clarity.",
            "buyer_price_concern": "I understand the concern about overpaying in this market.",
            "seller_offer_concern": "I understand why that offer feels disappointing.",
            "decision_delay": "I understand needing a little more time before deciding.",
            "trust_objection": "I understand you want to feel fully confident before moving ahead.",
            "negotiation_support": "I understand you want a measured response before taking the next step.",
            "general_hesitation": "I understand the hesitation and appreciate you being direct about it.",
        },
        "relationship_first": {
            "seller_commission_objection": "I appreciate you being candid about the fee concern, and I do not take that lightly.",
            "buyer_commission_objection": "I appreciate you being open about what is making you pause.",
            "landlord_fee_objection": "I appreciate you being upfront about the fee concern.",
            "shopping_around": "I appreciate the honesty, and I respect that you are taking the time to compare options.",
            "timing_hesitation": "I appreciate you being honest about the timing concern.",
            "buyer_price_concern": "I appreciate you being direct about the price concern.",
            "seller_offer_concern": "I appreciate you saying that plainly.",
            "decision_delay": "I appreciate you letting me know where things stand.",
            "trust_objection": "I appreciate the honesty, and building trust matters here.",
            "negotiation_support": "I appreciate you flagging that concern before responding.",
            "general_hesitation": "I appreciate you being candid about where you are at.",
        },
    }
    return variant_tone[variant].get(primary_type, variant_tone[variant]["general_hesitation"])


def _build_reframe_sentence(primary_type: str, risk_flags: list[str]) -> str:
    mapping = {
        "seller_commission_objection": "Rather than rush into numbers over message, I would prefer to make sure you have a clear sense of how I approach pricing, positioning, and representation so you can judge whether it is the right fit.",
        "buyer_commission_objection": "My goal is to make sure you understand how I would support the process so you can decide whether the value is there for you.",
        "landlord_fee_objection": "My goal is to make sure you are clear on what support is included and whether it matches what you actually need.",
        "shopping_around": "The most useful next step is usually a simple, honest comparison of approach so you can decide what feels strongest for your situation.",
        "timing_hesitation": "If it helps, I can keep this focused on your options and timing tradeoffs without pushing you into a decision.",
        "buyer_price_concern": "The goal is not to force movement, but to help you make a decision that feels informed and protected.",
        "seller_offer_concern": "The best next move is usually to step back, look at the options clearly, and respond from a position of confidence rather than frustration.",
        "decision_delay": "I am happy to keep this simple and make it easier for you to sort through the main concern before deciding.",
        "trust_objection": "Clarity and consistency matter more than pressure here, and I want the next step to reflect that.",
        "negotiation_support": "The right response should protect the relationship without overcommitting in writing.",
        "general_hesitation": "The next step should be low-pressure and useful.",
    }
    sentence = mapping.get(primary_type, mapping["general_hesitation"])
    if "pricing_or_commission_authority_requested" in risk_flags:
        sentence += " I would not want to make fee or pricing commitments over message without a fuller discussion."
    return sentence


def _build_call_to_action(request: agent_schemas.ConversationCloserRunRequest) -> str:
    if request.desired_outcome:
        return f"If helpful, we can keep the next step focused on {request.desired_outcome.replace('_', ' ')}."
    if request.operator_goal:
        return f"If helpful, I can keep the next step focused on {request.operator_goal.replace('_', ' ')}."
    return "If helpful, we can talk through the concern briefly and decide on the most sensible next step."


def _default_subject(variant: str) -> str:
    if variant == "relationship_first":
        return "Appreciate your honesty"
    return "Quick follow-up"


def _fallback_draft(
    request: agent_schemas.ConversationCloserRunRequest,
    contact,
    primary_type: str,
    risk_flags: list[str],
    variant: str,
) -> dict[str, Any]:
    greeting = f"Hi {getattr(contact, 'name', 'there')},"
    closing = "Kevin"
    body = "\n\n".join(
        [
            greeting,
            _build_style_sentence(primary_type, variant),
            _build_reframe_sentence(primary_type, risk_flags),
            _build_call_to_action(request),
            closing,
        ]
    )
    return {
        "variant": variant,
        "channel": request.channel or "email",
        "subject": _default_subject(variant),
        "body": body,
    }


def _parse_llm_drafts(raw: str, request: agent_schemas.ConversationCloserRunRequest) -> list[dict[str, Any]]:
    if not raw or raw == "{}":
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = parsed if isinstance(parsed, list) else parsed.get("variants", [])
    if not isinstance(items, list):
        return []

    drafts: list[dict[str, Any]] = []
    seen_variants: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        variant = item.get("variant")
        if variant not in DRAFT_VARIANTS or variant in seen_variants:
            continue
        body = str(item.get("body", "")).strip()
        if not body:
            continue
        drafts.append(
            {
                "variant": variant,
                "channel": request.channel or "email",
                "subject": str(item.get("subject") or _default_subject(variant)).strip(),
                "body": body,
            }
        )
        seen_variants.add(variant)
        if len(drafts) >= MAX_DRAFT_VARIANTS:
            break
    return drafts


def _build_llm_prompt(
    request: agent_schemas.ConversationCloserRunRequest,
    plan: dict[str, Any],
) -> str:
    return f"""You are an internal drafting assistant for a Toronto real estate agent.
Draft at most 2 client reply variants for this objection-handling scenario.

Hard constraints:
- Do NOT give legal advice
- Do NOT interpret contract enforceability
- Do NOT promise pricing, commission, fee, or negotiation outcomes
- Keep the reply human, calm, and practical
- Return ONLY JSON with the shape {{"variants":[{{"variant":"direct_practical","subject":"...","body":"..."}},{{"variant":"relationship_first","subject":"...","body":"..."}}]}}

Allowed variant values:
- direct_practical
- relationship_first

Client message:
{request.message}

Operator goal:
{request.operator_goal}

Desired outcome:
{request.desired_outcome}

Context notes:
{request.context_notes}

Context summary:
{json.dumps(plan["context_summary"], ensure_ascii=False)}

Objection analysis:
{json.dumps(plan["objection_analysis"], ensure_ascii=False)}

Response strategy:
{json.dumps(plan["response_strategy"], ensure_ascii=False)}
"""


def generate_conversation_closer_drafts(
    request: agent_schemas.ConversationCloserRunRequest,
    contact,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    primary_type = plan["objection_analysis"]["primary_type"]
    risk_flags = list(plan.get("risk_flags", []))

    llm_prompt = _build_llm_prompt(request, plan)
    llm_drafts = _parse_llm_drafts(tools.call_llm_tool(llm_prompt), request)

    drafts_by_variant = {draft["variant"]: draft for draft in llm_drafts}
    for variant in DRAFT_VARIANTS:
        if len(drafts_by_variant) >= MAX_DRAFT_VARIANTS:
            break
        if variant not in drafts_by_variant:
            drafts_by_variant[variant] = _fallback_draft(
                request,
                contact,
                primary_type,
                risk_flags,
                variant,
            )

    return [drafts_by_variant[variant] for variant in DRAFT_VARIANTS if variant in drafts_by_variant][:MAX_DRAFT_VARIANTS]


def execute_conversation_closer_run(
    db: Session,
    run: models.AgentRun,
    request: agent_schemas.ConversationCloserRunRequest,
) -> Dict[str, Any]:
    if not run.plan:
        return {
            "summary": "No conversation closer plan available.",
            "objection_analysis": {},
            "strategy": {},
            "talking_points": [],
            "drafts": [],
            "risk_flags": [],
            "operator_notes": [],
        }

    plan = json.loads(run.plan)
    result = {
        "summary": plan.get("summary", ""),
        "objection_analysis": plan.get("objection_analysis", {}),
        "strategy": plan.get("response_strategy", {}),
        "talking_points": plan.get("talking_points", []),
        "drafts": [],
        "risk_flags": plan.get("risk_flags", []),
        "operator_notes": plan.get("operator_notes", []),
    }

    if plan["objection_analysis"].get("requires_manual_escalation"):
        service.write_audit_log(
            db,
            run=run,
            task=run.task,
            actor_type="system",
            action="conversation_closer_manual_escalation_required",
            details=json.dumps(
                {
                    "risk_flags": plan.get("risk_flags", []),
                    "recommended_action": plan["response_strategy"].get("recommended_action"),
                },
                ensure_ascii=False,
            ),
        )
        return result

    context = _build_context(db, request)
    drafts = generate_conversation_closer_drafts(
        request,
        context["contact"],
        plan,
    )

    for draft in drafts[:MAX_DRAFT_VARIANTS]:
        approval_payload = json.dumps(
            {
                "contact_id": request.contact_id,
                "channel": draft["channel"],
                "variant": draft["variant"],
                "subject": draft.get("subject"),
                "body": draft["body"],
                "primary_objection": plan["objection_analysis"]["primary_type"],
                "risk_flags": plan.get("risk_flags", []),
                "review_mode": "manual_only",
            },
            ensure_ascii=False,
        )
        approval = service.create_approval(
            db,
            run=run,
            action_type=CLIENT_REPLY_APPROVAL_ACTION,
            risk_level="high",
            payload=approval_payload,
        )
        service.write_audit_log(
            db,
            run=run,
            task=run.task,
            actor_type="agent",
            action="generate_conversation_closer_draft",
            details=approval_payload,
        )
        result["drafts"].append(
            {
                "variant": draft["variant"],
                "channel": draft["channel"],
                "subject": draft.get("subject"),
                "body": draft["body"],
                "approval_id": approval.id,
            }
        )

    if not result["drafts"]:
        service.write_audit_log(
            db,
            run=run,
            task=run.task,
            actor_type="system",
            action="conversation_closer_no_drafts_generated",
            details=json.dumps(
                {"reason": "guardrails_or_empty_generation"},
                ensure_ascii=False,
            ),
        )

    return result


def run_conversation_closer_once(
    db: Session,
    request: agent_schemas.ConversationCloserRunRequest,
) -> models.AgentRun:
    payload_json = json.dumps(request.model_dump(), ensure_ascii=False)
    task = service.create_task(
        db,
        agent_type="conversation_closer",
        subject_type="contact",
        subject_id=request.contact_id,
        payload=payload_json,
        priority="normal",
    )
    run = service.create_run(
        db,
        task=task,
        summary="Conversation Closer run (MVP)",
    )
    service.update_task_status(db, task, status="executing")

    try:
        now = datetime.utcnow()
        plan_data = plan_conversation_closer_run(db, request)
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
            actor_type="system",
            action="conversation_closer_context_loaded",
            details=json.dumps(plan_data["context_summary"], ensure_ascii=False),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="conversation_closer_analysis_generated",
            details=json.dumps(
                {
                    "objection_analysis": plan_data["objection_analysis"],
                    "response_strategy": plan_data["response_strategy"],
                    "risk_flags": plan_data["risk_flags"],
                },
                ensure_ascii=False,
            ),
        )

        run = service.update_run_status(db, run, status="executing")
        exec_result = execute_conversation_closer_run(db, run, request)
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
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action=(
                "conversation_closer_run_waiting_approval"
                if exec_result["drafts"]
                else "conversation_closer_run_completed"
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
            action="conversation_closer_run_failed",
            details=str(exc),
        )
        return run
