from sqlalchemy.orm import Session
from sqlalchemy import func
from . import models, schemas
import csv
import hashlib
import re
import json
import os
import logging
import shutil
import subprocess
import tempfile
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from datetime import UTC, datetime, time, timedelta
from urllib.parse import urlsplit, urlunsplit
from pywebpush import webpush, WebPushException
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)
_whisper_model = None
DEFAULT_GMAIL_FEED_QUERY = "newer_than:14d (MLS OR listing OR sold OR leased OR REALM OR TRREB)"
WATCHLIST_MATCH_SCORE_THRESHOLD = 35
WATCHLIST_ACTIVE_FRESH_DAYS = 14
WATCHLIST_OUTCOME_FRESH_DAYS = 45
PROPERTY_CSV_TEMPLATE_COLUMNS = [
    "mls_number",
    "street",
    "city",
    "community",
    "status",
    "property_type",
    "list price",
    "sold price",
    "rent",
    "beds",
    "baths",
    "parking",
    "url",
    "remarks",
]
PROPERTY_CSV_TEMPLATE_ROWS = [
    [
        "TEMPLATE_ONLY_1",
        "REPLACE_WITH_REALM_STREET",
        "REPLACE_WITH_CITY",
        "REPLACE_WITH_COMMUNITY",
        "Sold",
        "Townhouse",
        "REPLACE_WITH_LIST_PRICE",
        "REPLACE_WITH_SOLD_PRICE",
        "",
        "3",
        "3",
        "1",
        "REPLACE_WITH_LISTING_URL",
        "TEMPLATE ONLY - replace this row with an authorized REALM/TRREB sold comparable export row.",
    ],
    [
        "TEMPLATE_ONLY_2",
        "REPLACE_WITH_REALM_STREET",
        "REPLACE_WITH_CITY",
        "REPLACE_WITH_COMMUNITY",
        "For Sale",
        "Townhouse",
        "REPLACE_WITH_LIST_PRICE",
        "",
        "",
        "3",
        "3",
        "1",
        "REPLACE_WITH_LISTING_URL",
        "TEMPLATE ONLY - replace this row with an authorized REALM/TRREB active listing export row.",
    ],
    [
        "TEMPLATE_ONLY_3",
        "REPLACE_WITH_REALM_STREET",
        "REPLACE_WITH_CITY",
        "REPLACE_WITH_COMMUNITY",
        "For Sale",
        "Detached",
        "REPLACE_WITH_LIST_PRICE",
        "",
        "",
        "3",
        "3",
        "1",
        "REPLACE_WITH_LISTING_URL",
        "TEMPLATE ONLY - replace this row with an authorized REALM/TRREB buyer-match listing export row.",
    ],
    [
        "TEMPLATE_ONLY_4",
        "REPLACE_WITH_REALM_STREET",
        "REPLACE_WITH_CITY",
        "REPLACE_WITH_COMMUNITY",
        "For Rent",
        "Condo",
        "",
        "",
        "REPLACE_WITH_MONTHLY_RENT",
        "2",
        "2",
        "1",
        "REPLACE_WITH_LISTING_URL",
        "TEMPLATE ONLY - replace this row with an authorized REALM/TRREB rental export row.",
    ],
]

load_dotenv()

# Gemini is intentionally opt-in. The CRM must work without paid LLM calls even
# when a stale GOOGLE_API_KEY remains in a local .env file.
def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _redacted_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[configured]"
    path = parsed.path or "/"
    query = "[redacted]" if parsed.query else ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _watchlist_reso_connector_status() -> schemas.ResoConnectorStatus:
    enabled = _env_flag_enabled("WATCHLIST_RESO_CONNECTOR_ENABLED")
    connector_url = (os.getenv("WATCHLIST_RESO_CONNECTOR_URL") or "").strip()
    auth_configured = bool(
        (os.getenv("WATCHLIST_RESO_CONNECTOR_BEARER_TOKEN") or "").strip()
        or (os.getenv("RESO_ACCESS_TOKEN") or "").strip()
    )
    if not enabled:
        status = "disabled"
        message = (
            "Formal RESO/OData connector is disabled. CSV, pasted feed, manual RESO JSON, "
            "and Gmail saved-search imports can still be used."
        )
    elif not connector_url:
        status = "needs_url"
        message = "WATCHLIST_RESO_CONNECTOR_ENABLED is on, but WATCHLIST_RESO_CONNECTOR_URL is missing."
    else:
        status = "configured"
        message = "Formal RESO/OData connector is configured; scheduled automation can fetch authorized JSON."

    return schemas.ResoConnectorStatus(
        enabled=enabled,
        url_configured=bool(connector_url),
        auth_configured=auth_configured,
        ready=enabled and bool(connector_url),
        status=status,
        endpoint=_redacted_url(connector_url) if connector_url else None,
        message=message,
    )


def ensure_database_schema(engine):
    """Apply small additive SQLite migrations for existing local CRM databases."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(client_watchlists)").fetchall()
        }
        if "source_query" not in columns:
            conn.exec_driver_sql("ALTER TABLE client_watchlists ADD COLUMN source_query TEXT")

        property_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(properties)").fetchall()
        }
        for column in ["listed_at", "sold_at", "leased_at"]:
            if column not in property_columns:
                conn.exec_driver_sql(f"ALTER TABLE properties ADD COLUMN {column} DATETIME")

        contact_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(contacts)").fetchall()
        }
        if "qualification_status" not in contact_columns:
            conn.exec_driver_sql("ALTER TABLE contacts ADD COLUMN qualification_status VARCHAR")
        if "qualification_route" not in contact_columns:
            conn.exec_driver_sql("ALTER TABLE contacts ADD COLUMN qualification_route VARCHAR")
        if "qualification_json" not in contact_columns:
            conn.exec_driver_sql("ALTER TABLE contacts ADD COLUMN qualification_json TEXT")
        if "qualification_updated_at" not in contact_columns:
            conn.exec_driver_sql("ALTER TABLE contacts ADD COLUMN qualification_updated_at DATETIME")


try:
    api_key = os.getenv("GOOGLE_API_KEY") if _env_flag_enabled("ENABLE_GEMINI") else None
    if api_key and genai:
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel("gemini-2.0-flash-lite")
    else:
        gemini_model = None
except Exception:
    gemini_model = None

# --- Pipeline Stages ---
def get_stages(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.PipelineStage).order_by(models.PipelineStage.order).offset(skip).limit(limit).all()

def create_stage(db: Session, stage: schemas.PipelineStageCreate):
    db_stage = models.PipelineStage(name=stage.name, order=stage.order)
    db.add(db_stage)
    db.commit()
    db.refresh(db_stage)
    return db_stage

# --- Contacts ---
def get_contact(db: Session, contact_id: int):
    return db.query(models.Contact).filter(models.Contact.id == contact_id).first()

def get_contacts(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Contact).offset(skip).limit(limit).all()


GENERIC_VOICE_MEMO_CONTACT_NAMES = {"voice memo lead", "unknown", "unknown lead"}
VOICE_MEMO_NAME_EXCLUSIONS = {
    "voice memo",
    "freehold townhouse",
    "brownstone circle",
    "thornhill ontario",
    "thom hill",
    "ontario",
}


def _is_generic_voice_memo_contact_name(value: str | None) -> bool:
    return str(value or "").strip().lower() in GENERIC_VOICE_MEMO_CONTACT_NAMES


def _legacy_voice_memo_candidate_name(interaction: models.Interaction) -> str | None:
    parsed = _json_object(interaction.ai_parsed_entities)
    parsed_name = str(parsed.get("client_name") or "").strip()
    if parsed_name and not _is_generic_voice_memo_contact_name(parsed_name):
        return parsed_name

    text = " ".join(
        part
        for part in [
            interaction.notes or "",
            interaction.ai_auto_summary or "",
        ]
        if part
    )
    comma_match = re.match(r"\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})\s*[,，]", text)
    if comma_match:
        candidate = comma_match.group(1).strip()
        if candidate.lower() not in VOICE_MEMO_NAME_EXCLUSIONS:
            return candidate

    for match in re.finditer(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})\b", text):
        candidate = match.group(1).strip()
        normalized = candidate.lower()
        if normalized in VOICE_MEMO_NAME_EXCLUSIONS:
            continue
        if "voice memo" in normalized or "brownstone" in normalized:
            continue
        return candidate
    return None


def _existing_contact_by_name(db: Session, name: str, exclude_contact_id: int):
    normalized = name.strip().lower()
    if not normalized:
        return None
    return (
        db.query(models.Contact)
        .filter(func.lower(models.Contact.name) == normalized)
        .filter(models.Contact.id != exclude_contact_id)
        .order_by(models.Contact.id.asc())
        .first()
    )


def get_legacy_voice_memo_reviews(db: Session, limit: int = 50) -> schemas.LegacyVoiceMemoReviewResponse:
    contacts = (
        db.query(models.Contact)
        .filter(func.lower(models.Contact.name).in_(GENERIC_VOICE_MEMO_CONTACT_NAMES))
        .order_by(models.Contact.updated_at.desc(), models.Contact.id.desc())
        .limit(limit)
        .all()
    )

    items: list[schemas.LegacyVoiceMemoReviewItem] = []
    for contact in contacts:
        voice_interactions = [
            interaction
            for interaction in sorted(contact.interactions or [], key=lambda row: row.date or datetime.min, reverse=True)
            if interaction.interaction_type == "voice_memo" or interaction.channel == "voice_memo"
        ]
        if not voice_interactions:
            continue

        for interaction in voice_interactions[:5]:
            candidate_name = _legacy_voice_memo_candidate_name(interaction)
            existing = _existing_contact_by_name(db, candidate_name, contact.id) if candidate_name else None
            evidence = " ".join(
                part
                for part in [
                    interaction.notes or "",
                    interaction.ai_auto_summary or "",
                ]
                if part
            ).strip()
            if len(evidence) > 220:
                evidence = f"{evidence[:217]}..."
            reason = (
                "Generic voice memo contact contains a named client that should be reviewed before merge/archive."
                if candidate_name
                else "Generic voice memo contact needs manual review because no reliable client name was extracted."
            )
            action = (
                f"Review whether this interaction belongs under {existing.name}, then move notes manually before archiving the generic contact."
                if existing
                else "Review the transcript, create or select the correct contact, then move notes manually before archiving the generic contact."
            )
            items.append(
                schemas.LegacyVoiceMemoReviewItem(
                    contact_id=contact.id,
                    contact_name=contact.name,
                    interaction_id=interaction.id,
                    interaction_date=interaction.date,
                    suggested_name=candidate_name,
                    suggested_existing_contact_id=existing.id if existing else None,
                    suggested_existing_contact_name=existing.name if existing else None,
                    reason=reason,
                    evidence_snippet=evidence or "No transcript text available.",
                    action_required=action,
                    safety_note="No automatic merge, deletion, Gmail draft, or outbound action is performed by this review report.",
                )
            )

    message = (
        f"{len(items)} legacy voice memo item(s) need manual review before cleanup."
        if items
        else "No legacy generic voice memo contacts need cleanup review."
    )
    return schemas.LegacyVoiceMemoReviewResponse(count=len(items), items=items, message=message)

def create_contact(db: Session, contact: schemas.ContactCreate):
    # Basic lead scoring on creation
    score = calculate_initial_score(contact)

    db_contact = models.Contact(**contact.model_dump(), lead_score=score)
    apply_lead_qualification(db, db_contact, commit=False)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def update_contact(db: Session, contact_id: int, contact: schemas.ContactUpdate):
    db_contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not db_contact:
        return None

    update_data = contact.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_contact, key, value)
        
    apply_lead_qualification(db, db_contact, commit=False)
    db_contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_contact)
    return db_contact

def delete_contact(db: Session, contact_id: int):
    db_contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if db_contact:
        db.delete(db_contact)
        db.commit()
    return db_contact

# --- Interactions ---
def create_contact_interaction(db: Session, contact_id: int, interaction: schemas.InteractionCreate):
    db_interaction = models.Interaction(**interaction.model_dump(), contact_id=contact_id)
    db.add(db_interaction)

    # Update lead score and last_contacted_at
    db_contact = get_contact(db, contact_id)
    if db_contact:
        db_contact.lead_score = update_score_with_interaction(db_contact.lead_score, interaction)
        db_contact.last_contacted_at = datetime.utcnow()
        apply_lead_qualification(db, db_contact, commit=False)
        db_contact.updated_at = datetime.utcnow()
        
    db.commit()
    db.refresh(db_interaction)
    return db_interaction

def get_contact_interactions(db: Session, contact_id: int):
    return db.query(models.Interaction).filter(models.Interaction.contact_id == contact_id).order_by(models.Interaction.date.desc()).all()

def update_contact_stage(db: Session, contact_id: int, stage_id: int):
    db_contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not db_contact:
        return None
    db_contact.stage_id = stage_id
    db_contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_contact)
    return db_contact

# --- AI Logic (Mocked + Heuristics for now) ---
def calculate_initial_score(contact: schemas.ContactCreate) -> float:
    score = 10.0 # Base score
    if contact.email: score += 10.0
    if contact.phone: score += 15.0
    if contact.company: score += 5.0
    if contact.notes and len(contact.notes) > 50: score += 10.0
    return min(score, 100.0)

def update_score_with_interaction(current_score: float, interaction: schemas.InteractionCreate) -> float:
    boost = 0.0
    if interaction.interaction_type == "meeting":
        boost = 25.0
    elif interaction.interaction_type == "call":
        boost = 15.0
    elif interaction.interaction_type == "email":
        boost = 5.0
        
    return min(current_score + boost, 100.0)


def _lead_text_blob(contact: models.Contact, interactions: list[models.Interaction] | None = None) -> str:
    parts = [
        contact.name,
        contact.name_zh,
        contact.email,
        contact.phone,
        contact.company,
        contact.client_type,
        contact.source,
        contact.investment_focus,
        contact.preferred_areas,
        contact.property_preferences,
        contact.notes,
        contact.ai_summary,
    ]
    for interaction in interactions or []:
        parts.extend([
            interaction.notes,
            interaction.ai_parsed_intent,
            interaction.ai_parsed_entities,
            interaction.ai_auto_summary,
            interaction.ai_suggested_action,
        ])
    return " ".join(str(part or "") for part in parts).lower()


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _infer_lead_intent(contact: models.Contact, text: str) -> tuple[str, list[str]]:
    signals: list[tuple[str, str]] = []
    client_type = str(contact.client_type or "").lower()

    if "buyer" in client_type or _has_any(text, ["buyer", "buying", "purchase", "looking to buy", "買", "買家"]):
        signals.append(("buyer", "buyer intent"))
    if "seller" in client_type or _has_any(text, ["seller", "sell", "listing", "sold comps", "賣", "賣家"]):
        signals.append(("seller", "seller/listing intent"))
    if "tenant" in client_type or _has_any(text, ["tenant", "lease", "rent", "rental", "looking to rent", "租客", "租"]):
        signals.append(("tenant", "tenant/rental intent"))
    if "landlord" in client_type or _has_any(text, ["landlord", "leased comp", "rent out", "rented comp", "房東", "出租"]):
        signals.append(("landlord", "landlord/rental market intent"))
    if "investor" in client_type or _has_any(text, ["investor", "roi", "cash flow", "cap rate", "投資"]):
        signals.append(("investor", "investment intent"))
    if _has_any(text, ["repair", "maintenance", "leak", "broken", "維修", "漏水"]):
        signals.append(("maintenance", "maintenance/service intent"))
    if _has_any(text, ["spam", "unsubscribe", "casino", "crypto bonus", "lottery"]):
        signals.append(("spam", "spam or irrelevant signal"))

    if not signals:
        return "unknown", []
    if any(intent == "spam" for intent, _reason in signals):
        return "spam", [reason for _intent, reason in signals]
    return signals[0][0], [reason for _intent, reason in signals]


def _lead_has_area_signal(contact: models.Contact, text: str) -> bool:
    preferred_areas = str(contact.preferred_areas or "").strip()
    if preferred_areas and preferred_areas not in {"[]", "null"}:
        return True
    return _has_any(
        text,
        [
            "toronto",
            "mississauga",
            "markham",
            "richmond hill",
            "thornhill",
            "north york",
            "oakville",
            "halton",
            "milton",
            "scarborough",
            "downtown",
            "york region",
        ],
    )


def _lead_has_budget_signal(contact: models.Contact, text: str) -> bool:
    if contact.budget_min or contact.budget_max or contact.expected_roi:
        return True
    return bool(re.search(r"\$?\s?\d{3,}(?:,\d{3})*(?:\s?(k|m|million))?", text)) or _has_any(
        text,
        ["budget", "pre-approved", "preapproval", "roi", "cap rate", "rent", "monthly"],
    )


def _lead_timeline_signal(text: str) -> tuple[str, list[str]]:
    if _has_any(text, ["urgent", "asap", "immediately", "this week", "2-3 weeks", "two weeks", "now", "盡快", "馬上"]):
        return "high", ["urgent timeline"]
    if _has_any(text, ["next month", "30 days", "60 days", "soon", "spring", "summer", "fall", "winter"]):
        return "medium", ["near-term timeline"]
    return "low", []


def build_lead_qualification(
    contact: models.Contact,
    interactions: list[models.Interaction] | None = None,
) -> schemas.LeadQualification:
    text = _lead_text_blob(contact, interactions)
    intent, evidence = _infer_lead_intent(contact, text)
    urgency, timeline_evidence = _lead_timeline_signal(text)
    evidence.extend(timeline_evidence)

    has_contact_method = bool(contact.email or contact.phone)
    has_area = _lead_has_area_signal(contact, text)
    has_budget = _lead_has_budget_signal(contact, text)
    has_notes = bool(contact.notes and len(contact.notes.strip()) >= 30)
    has_interaction = bool(interactions)

    missing_fields: list[str] = []
    if not has_contact_method:
        missing_fields.append("email_or_phone")
    if intent in {"buyer", "tenant", "seller", "landlord"} and not has_area:
        missing_fields.append("target_area")
    if intent in {"buyer", "tenant", "investor"} and not has_budget:
        missing_fields.append("budget_or_price_signal")
    if intent == "unknown" and not has_notes:
        missing_fields.append("clear_real_estate_need")

    score = 20
    if has_contact_method:
        score += 15
        evidence.append("contact method present")
    if has_area:
        score += 15
        evidence.append("area signal present")
    if has_budget:
        score += 15
        evidence.append("budget or price signal present")
    if has_notes:
        score += 10
        evidence.append("notes contain qualification detail")
    if has_interaction:
        score += 10
        evidence.append("interaction history present")
    if urgency == "high":
        score += 15
    elif urgency == "medium":
        score += 8
    if intent in {"buyer", "seller", "tenant", "landlord", "investor"}:
        score += 10
    if intent == "spam":
        score = min(score, 15)

    score = max(0, min(100, score))
    confidence = 0.35
    confidence += 0.2 if intent != "unknown" else 0
    confidence += 0.15 if has_contact_method else 0
    confidence += 0.15 if has_area else 0
    confidence += 0.1 if has_budget else 0
    confidence += 0.05 if has_interaction else 0
    confidence = round(min(confidence, 0.95), 2)

    safe_defaults: list[str] = []
    if intent == "unknown":
        safe_defaults.append("intent_unknown_routes_to_manual_review")
    if not has_contact_method:
        safe_defaults.append("missing_contact_method_blocks_direct_client_delivery")

    if intent == "spam":
        route = "archive_low_intent"
        status = "low_intent"
        routing_reason = "Lead shows spam or irrelevant signals."
    elif not has_contact_method:
        route = "clarification_draft"
        status = "needs_clarification"
        routing_reason = "Client delivery needs an email or phone before routing can advance."
    elif intent in {"buyer", "seller", "tenant", "landlord"} and has_area and (has_budget or intent in {"seller", "landlord"}):
        route = "watchlist_ready"
        status = "qualified"
        routing_reason = "Real-estate intent and core matching criteria are present."
    elif intent in {"buyer", "seller", "tenant", "landlord", "investor"}:
        route = "needs_clarification"
        status = "needs_clarification"
        routing_reason = "Intent is present, but one or more routing fields are missing."
    elif score >= 50:
        route = "pipeline_only"
        status = "manual_review"
        routing_reason = "Lead has enough engagement to keep in pipeline, but intent is not precise."
    else:
        route = "manual_review"
        status = "manual_review"
        routing_reason = "Lead needs human review before any automated route."

    next_actions = []
    if route == "watchlist_ready":
        next_actions.append("Create or refresh the matching Watchlist criteria before relying on scheduled alerts.")
        next_actions.append("Keep Gmail delivery review-gated unless Kevin explicitly approves sending.")
    elif route == "clarification_draft":
        next_actions.append("Draft a short clarification note and keep it unsent for Kevin review.")
    elif route == "needs_clarification":
        next_actions.append("Collect the missing fields before creating a Watchlist or source task.")
    elif route == "pipeline_only":
        next_actions.append("Keep the contact in Pipeline and log the next real interaction.")
    elif route == "archive_low_intent":
        next_actions.append("Keep this out of active follow-up unless Kevin manually reopens it.")
    else:
        next_actions.append("Review the raw notes/interactions before routing.")

    if missing_fields:
        next_actions.append("Fill missing fields: " + ", ".join(missing_fields) + ".")

    summary_intent = intent.replace("_", " ")
    summary = (
        f"{contact.name} is classified as {summary_intent} with {urgency} urgency "
        f"and route {route}."
    )

    return schemas.LeadQualification(
        score=score,
        intent=intent,
        client_type_guess=intent if intent != "unknown" else (contact.client_type or "unknown"),
        urgency=urgency,
        confidence=confidence,
        recommended_route=route,
        status=status,
        summary=summary,
        routing_reason=routing_reason,
        evidence=sorted(set(evidence)),
        missing_fields=missing_fields,
        next_actions=next_actions,
        safe_defaults_applied=safe_defaults,
    )


def apply_lead_qualification(
    db: Session,
    contact: models.Contact,
    commit: bool = True,
) -> schemas.LeadQualification:
    interactions = []
    if contact.id:
        interactions = (
            db.query(models.Interaction)
            .filter(models.Interaction.contact_id == contact.id)
            .order_by(models.Interaction.date.desc())
            .limit(5)
            .all()
        )
    qualification = build_lead_qualification(contact, interactions)
    payload = qualification.model_dump(mode="json")
    contact.lead_score = float(qualification.score)
    contact.qualification_status = qualification.status
    contact.qualification_route = qualification.recommended_route
    contact.qualification_json = json.dumps(payload, ensure_ascii=False)
    contact.qualification_updated_at = datetime.utcnow()
    contact.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(contact)
    return qualification


def qualify_contact(db: Session, contact_id: int) -> schemas.LeadQualificationResponse | None:
    contact = get_contact(db, contact_id)
    if not contact:
        return None
    qualification = apply_lead_qualification(db, contact)
    return schemas.LeadQualificationResponse(contact=contact, qualification=qualification)

def perform_smart_search(db: Session, query: str):
    q_lower = query.lower()
    interpreted = "Keyword matching: "

    base_query = db.query(models.Contact)
    
    # Naive NLP using regex
    if "warm" in q_lower or "hot" in q_lower:
        interpreted += "High lead score. "
        base_query = base_query.filter(models.Contact.lead_score > 60)
        
    if "cold" in q_lower:
        interpreted += "Low lead score. "
        base_query = base_query.filter(models.Contact.lead_score < 30)

    # Extract potential keywords
    keywords = [w for w in q_lower.split() if w not in ["show", "me", "find", "all", "the", "in", "with", "a", "an", "warm", "hot", "cold", "leads", "contacts"]]
    
    if keywords:
        interpreted += f"Searching for: {', '.join(keywords)}"
        keyword_filters = []
        for kw in keywords:
            search_filter = (models.Contact.notes.ilike(f"%{kw}%")) | \
                            (models.Contact.company.ilike(f"%{kw}%")) | \
                            (models.Contact.name.ilike(f"%{kw}%"))
            keyword_filters.append(search_filter)
        
        from sqlalchemy import or_
        if keyword_filters:
            base_query = base_query.filter(or_(*keyword_filters))

    results = base_query.all()
    
    return schemas.SmartSearchResult(
        query=query,
        interpreted_intent=interpreted.strip(),
        results=results
    )

def draft_follow_up_email(db: Session, contact_id: int):
    contact = get_contact(db, contact_id)
    if not contact:
        return None
        
    prompt = f"""
    Write a highly personalized, professional follow-up email for this lead:
    Name: {contact.name}
    Company: {contact.company}
    Pipeline Stage: {contact.stage.name if contact.stage else 'Unknown'}
    Notes: {contact.notes}
    
    Return ONLY a JSON object with two keys: "subject" and "body". Do not wrap in markdown blocks, just the raw JSON.
    """
    
    raw = _call_llm(prompt)
    try:
        data = json.loads(raw)
        return schemas.EmailDraftResponse(subject=data.get("subject", "Follow up"), body=data.get("body", ""))
    except Exception as e:
        return schemas.EmailDraftResponse(subject="Error drafting email", body=str(e))

def enrich_contact_profile(db: Session, contact_id: int):
    contact = get_contact(db, contact_id)
    if not contact:
        return None
        
    prompt = f"""Research and provide a brief professional summary about: {contact.company or contact.name}.
Include recent news, products, and company overview. Keep it under 200 words."""
    
    raw = _call_llm(prompt)
    if not raw or raw == "{}":
        return schemas.EnrichProfileResponse(summary="AI unavailable", updated_notes=contact.notes or "")
        
    try:
        new_notes = (contact.notes or "") + f"\n\n--- AI Enrichment ---\n{raw}"
        contact.notes = new_notes
        db.commit()
        db.refresh(contact)
        return schemas.EnrichProfileResponse(summary="Successfully enriched profile.", updated_notes=new_notes)
    except Exception as e:
        return schemas.EnrichProfileResponse(summary=f"Enrichment failed: {str(e)}", updated_notes=contact.notes or "")

def scout_leads(db: Session, query: str):
    prompt = f"""You are a lead generation assistant. Generate 3 realistic potential business contacts that match this search criteria: "{query}".

For each contact, provide realistic details.
Return ONLY a JSON array of objects with keys: "name" (string), "company" (string), "notes" (string describing the company/lead).
Do not wrap in markdown blocks."""
    
    raw = _call_llm(prompt)
    if not raw or raw == "{}":
        return schemas.ScoutResponse(message="AI not available.", new_contacts=[])
    
    try:
        new_leads_data = json.loads(raw)
        
        lead_stage = db.query(models.PipelineStage).filter(models.PipelineStage.name == "Lead").first()
        stage_id = lead_stage.id if lead_stage else None
        
        new_contacts = []
        for lead_data in new_leads_data:
            company_name = lead_data.get("company", "Unknown Company")
            domain_guess = re.sub(r'[^a-zA-Z0-9]', '', company_name.lower()) + ".com"
            contact = models.Contact(
                name=lead_data.get("name", "Unknown Contact"),
                company=company_name,
                email=f"hello@{domain_guess}",
                phone="",
                notes=lead_data.get("notes", ""),
                stage_id=stage_id
            )
            score = 40
            if contact.notes and len(contact.notes) > 50: score += 20
            contact.lead_score = score
            
            db.add(contact)
            db.commit()
            db.refresh(contact)
            new_contacts.append(contact)
            
        return schemas.ScoutResponse(message=f"Successfully scouted {len(new_contacts)} new leads.", new_contacts=new_contacts)
    except Exception as e:
        print(f"Scout error: {e}")
        return schemas.ScoutResponse(message=f"Error scouting leads: {str(e)}", new_contacts=[])


# --- AI Dashboard Intelligence ---

def _days_since(dt: datetime | None) -> int:
    """Calculate days since a datetime. Returns 999 if None."""
    if not dt:
        return 999
    return (datetime.utcnow() - dt).days


def calculate_health_score(contact, interactions_count: int) -> float:
    """RFM-based health score: Recency + Frequency + Momentum."""
    score = 0.0
    
    # Recency (0-40 points): how recently contacted
    days = _days_since(contact.last_contacted_at)
    if days <= 1:
        score += 40
    elif days <= 3:
        score += 30
    elif days <= 7:
        score += 20
    elif days <= 14:
        score += 10
    elif days <= 30:
        score += 5
    # >30 days: 0 points
    
    # Frequency (0-30 points): total interactions
    if interactions_count >= 10:
        score += 30
    elif interactions_count >= 5:
        score += 20
    elif interactions_count >= 2:
        score += 15
    elif interactions_count >= 1:
        score += 10
    # 0: 0 points
    
    # Completeness (0-15 points): data quality
    if contact.email:
        score += 5
    if contact.phone:
        score += 5
    if contact.company:
        score += 3
    if contact.notes and len(contact.notes) > 30:
        score += 2
    
    # Pipeline momentum (0-15 points): later stage = higher
    stage_id = contact.stage_id or 0
    score += min(stage_id * 3, 15)
    
    return min(score, 100.0)


def generate_smart_nudges(db: Session) -> schemas.NudgesResponse:
    """Analyze all contacts and produce actionable AI nudges."""
    contacts = db.query(models.Contact).all()
    nudges = []
    now = datetime.utcnow()
    
    for contact in contacts:
        days_since_contact = _days_since(contact.last_contacted_at)
        interaction_count = db.query(func.count(models.Interaction.id)).filter(
            models.Interaction.contact_id == contact.id
        ).scalar() or 0
        
        # Rule 1: No contact in 7+ days for active leads
        added_nudge_for_contact = False
        if days_since_contact >= 7 and contact.lead_score >= 30:
            urgency = "high" if days_since_contact >= 14 else "medium"
            message = (
                f"{contact.name} has no logged contact yet. Start with a check-in call and record the interaction."
                if not contact.last_contacted_at
                else f"{contact.name} hasn't been contacted in {days_since_contact} days. Follow up to maintain the relationship."
            )
            nudges.append(schemas.Nudge(
                contact_id=contact.id,
                contact_name=contact.name,
                company=contact.company,
                urgency=urgency,
                message=message,
                action="call" if days_since_contact >= 14 else "email"
            ))
            added_nudge_for_contact = True
        
        # Rule 2: High score but early stage → ready to advance
        if contact.lead_score >= 60 and contact.stage_id and contact.stage_id <= 2:
            nudges.append(schemas.Nudge(
                contact_id=contact.id,
                contact_name=contact.name,
                company=contact.company,
                urgency="medium",
                message=f"{contact.name} has a high score ({int(contact.lead_score)}) but is still in early pipeline. Consider advancing to the next stage.",
                action="advance"
            ))
        
        # Rule 3: Stale in pipeline (created 30+ days ago, no interactions)
        days_in_system = (now - contact.created_at).days if contact.created_at else 0
        if days_in_system >= 30 and interaction_count == 0 and not added_nudge_for_contact:
            nudges.append(schemas.Nudge(
                contact_id=contact.id,
                contact_name=contact.name,
                company=contact.company,
                urgency="low",
                message=f"{contact.name} has been in the system for {days_in_system} days with no interactions. Re-engage means manually reach out again, then log the result or archive the contact.",
                action="re-engage"
            ))
    
    # Sort by urgency: high > medium > low
    urgency_order = {"high": 0, "medium": 1, "low": 2}
    nudges.sort(key=lambda n: urgency_order.get(n.urgency, 3))
    
    return schemas.NudgesResponse(
        nudges=nudges[:10],  # Top 10
        generated_at=now
    )


def auto_segment_contacts(db: Session) -> schemas.SegmentsResponse:
    """Classify contacts into segments based on RFM analysis."""
    contacts = db.query(models.Contact).all()
    
    segments = {
        "iron_fan": {"label": "🔥 Iron Fan", "contacts": []},
        "high_potential": {"label": "⚡ High Potential", "contacts": []},
        "sleeping": {"label": "😴 Sleeping", "contacts": []},
        "cold": {"label": "❄️ Cold", "contacts": []},
    }
    
    for contact in contacts:
        interaction_count = db.query(func.count(models.Interaction.id)).filter(
            models.Interaction.contact_id == contact.id
        ).scalar() or 0
        
        days_since = _days_since(contact.last_contacted_at)
        score = contact.lead_score
        
        # Classify
        if score >= 60 and interaction_count >= 3 and days_since <= 14:
            seg_key = "iron_fan"
        elif score >= 50 and days_since <= 30:
            seg_key = "high_potential"
        elif days_since >= 30 or (days_since >= 14 and interaction_count == 0):
            seg_key = "sleeping"
        else:
            seg_key = "cold"
        
        # Update contact tags in DB
        tag = segments[seg_key]["label"]
        if contact.tags != tag:
            contact.tags = tag
        
        segments[seg_key]["contacts"].append(contact)
    
    db.commit()
    
    result = []
    for key, data in segments.items():
        result.append(schemas.SegmentGroup(
            label=data["label"],
            key=key,
            count=len(data["contacts"]),
            contacts=data["contacts"]
        ))
    
    return schemas.SegmentsResponse(segments=result)


def generate_pipeline_insights(db: Session) -> schemas.PipelineInsightsResponse:
    """Generate pipeline analytics and AI recommendations."""
    contacts = db.query(models.Contact).all()
    stages = db.query(models.PipelineStage).order_by(models.PipelineStage.order).all()
    total = len(contacts)
    
    if total == 0:
        return schemas.PipelineInsightsResponse(
            total_contacts=0,
            stage_breakdown=[],
            avg_score=0,
            conversion_summary="No contacts in the system yet. Use the AI Prospector to find leads!",
            bottleneck=None,
            recommendations=["Start by adding contacts or using AI Prospector to scout leads."]
        )
    
    # Stage breakdown
    stage_breakdown = []
    max_count = 0
    bottleneck_stage = None
    
    for stage in stages:
        count = len([c for c in contacts if c.stage_id == stage.id])
        pct = round(count / total * 100, 1) if total > 0 else 0
        stage_breakdown.append({"name": stage.name, "count": count, "percentage": pct})
        if count > max_count:
            max_count = count
            bottleneck_stage = stage.name
    
    # Unassigned
    unassigned = len([c for c in contacts if not c.stage_id])
    if unassigned > 0:
        stage_breakdown.append({"name": "Unassigned", "count": unassigned, "percentage": round(unassigned / total * 100, 1)})
    
    avg_score = round(sum(c.lead_score for c in contacts) / total, 1)
    
    # Generate recommendations
    recommendations = []
    
    # Check for too many leads stuck in early stage
    lead_count = len([c for c in contacts if c.stage_id and c.stage_id <= 1])
    if lead_count > total * 0.6:
        recommendations.append(f"{int(lead_count/total*100)}% of contacts are still in 'Lead' stage. Focus on qualifying them or removing dead leads.")
    
    # Check for contacts without interactions
    no_interaction = 0
    for c in contacts:
        ix_count = db.query(func.count(models.Interaction.id)).filter(models.Interaction.contact_id == c.id).scalar() or 0
        if ix_count == 0:
            no_interaction += 1
    if no_interaction > 0:
        recommendations.append(f"{no_interaction} contacts have zero interactions. Prioritize outreach to engage them.")
    
    # Check avg score
    if avg_score < 30:
        recommendations.append("Average lead score is low. Consider enriching contact profiles or scouting higher-quality leads.")
    
    if not recommendations:
        recommendations.append("Pipeline looks healthy! Keep up the momentum.")
    
    # Conversion summary
    closed = len([c for c in contacts if c.stage_id and c.stage_id >= 5])
    conversion_rate = round(closed / total * 100, 1) if total > 0 else 0
    conversion_summary = f"{total} total contacts | {conversion_rate}% conversion rate | Avg score: {avg_score}"
    
    bottleneck = f"Most contacts ({max_count}) are concentrated in '{bottleneck_stage}'" if bottleneck_stage and max_count > total * 0.4 else None
    
    return schemas.PipelineInsightsResponse(
        total_contacts=total,
        stage_breakdown=stage_breakdown,
        avg_score=avg_score,
        conversion_summary=conversion_summary,
        bottleneck=bottleneck,
        recommendations=recommendations
    )


# --- Properties CRUD ---
def get_properties(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Property).offset(skip).limit(limit).all()

def get_property(db: Session, property_id: int):
    return db.query(models.Property).filter(models.Property.id == property_id).first()

def create_property(db: Session, prop: schemas.PropertyCreate):
    db_prop = models.Property(**prop.model_dump())
    db.add(db_prop)
    db.commit()
    db.refresh(db_prop)
    return db_prop

def update_property(db: Session, property_id: int, prop: schemas.PropertyUpdate):
    db_prop = db.query(models.Property).filter(models.Property.id == property_id).first()
    if not db_prop:
        return None
    update_data = prop.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_prop, key, value)
    db_prop.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_prop)
    return db_prop

def delete_property(db: Session, property_id: int):
    db_prop = db.query(models.Property).filter(models.Property.id == property_id).first()
    if db_prop:
        db.delete(db_prop)
        db.commit()
    return db_prop


def _normalize_csv_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _first_nonempty(row: dict, *keys: str) -> str | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    normalized = {_normalize_csv_key(key): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(str(key).strip().lower())
        if value is None:
            value = normalized.get(_normalize_csv_key(key))
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_float(value) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace("$", "").replace(",", "").strip().lower()
    if not text:
        return None
    multiplier = 1
    if text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1].strip()
    elif text.endswith("k"):
        multiplier = 1_000
        text = text[:-1].strip()
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _parse_int(value) -> int | None:
    parsed = _parse_float(value)
    return int(parsed) if parsed is not None else None


def _parse_import_date(value) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None

    iso_date_prefix = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T\s].*)?$", text)
    if iso_date_prefix:
        text = iso_date_prefix.group(1)

    text = re.sub(r"\b(?:listed|list|sold|leased|rented|date|at|on)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" :-")
    if not text:
        return None

    for fmt in [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%b %d %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
    ]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    numeric = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", text)
    if numeric:
        first, second, year = numeric.groups()
        first_num = int(first)
        second_num = int(second)
        year_num = int(year)
        if year_num < 100:
            year_num += 2000
        month, day = (second_num, first_num) if first_num > 12 else (first_num, second_num)
        try:
            return datetime(year_num, month, day)
        except ValueError:
            return None

    return None


def _format_source_date(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def _source_age_days(value: datetime | None, now: datetime | None = None) -> int | None:
    if not value:
        return None
    reference = now or _utcnow()
    return max(0, (reference.date() - value.date()).days)


def _property_source_datetime(prop: models.Property) -> datetime | None:
    if prop.status == "sold":
        return prop.sold_at or prop.listed_at or prop.updated_at or prop.created_at
    if prop.status == "rented":
        return prop.leased_at or prop.listed_at or prop.updated_at or prop.created_at
    if prop.status in {"listed_for_sale", "listed_for_rent"}:
        return prop.listed_at or prop.updated_at or prop.created_at
    return prop.updated_at or prop.created_at


def _property_recency_sort_key(prop: models.Property) -> tuple[datetime, datetime, int]:
    source_dt = _property_source_datetime(prop) or datetime.min
    updated_dt = prop.updated_at or prop.created_at or source_dt
    return source_dt, updated_dt or datetime.min, prop.id or 0


def _sort_properties_by_recency(properties: list[models.Property]) -> list[models.Property]:
    return sorted(properties, key=_property_recency_sort_key, reverse=True)


def _alert_source_datetime(alert: models.WatchlistAlert) -> datetime | None:
    if alert.property:
        return _property_source_datetime(alert.property)

    payload = _json_object(alert.payload_json)
    source_date = str(payload.get("source_date") or "").strip()
    if source_date:
        return _parse_import_date(source_date)
    return alert.created_at


def _alert_recency_sort_key(alert: models.WatchlistAlert) -> tuple[datetime, datetime, int]:
    source_dt = _alert_source_datetime(alert) or datetime.min
    created_dt = alert.created_at or source_dt
    return source_dt, created_dt or datetime.min, alert.id or 0


def _sort_alerts_by_recency(alerts: list[models.WatchlistAlert]) -> list[models.WatchlistAlert]:
    return sorted(alerts, key=_alert_recency_sort_key, reverse=True)


def _property_freshness_payload(prop: models.Property) -> dict[str, object | None]:
    source_dt = _property_source_datetime(prop)
    age_days = _source_age_days(source_dt)
    if age_days is None:
        return {
            "source_age_days": None,
            "freshness_status": "unknown",
            "freshness_note": "Source date is missing; confirm whether this is a new update before presenting it as current.",
        }

    if age_days == 0:
        return {
            "source_age_days": age_days,
            "freshness_status": "same_day",
            "freshness_note": "Source date is today.",
        }

    active_row = prop.status in {"listed_for_sale", "listed_for_rent"}
    fresh_limit = WATCHLIST_ACTIVE_FRESH_DAYS if active_row else WATCHLIST_OUTCOME_FRESH_DAYS
    status = "recent" if age_days <= fresh_limit else "stale"
    row_label = "listing" if active_row else "sold/leased comp"
    if status == "recent":
        note = f"Source date is {age_days} day(s) old; treat this as a recent {row_label}, not necessarily a same-day update."
    else:
        note = f"Source date is {age_days} day(s) old; treat this as older {row_label} context unless REALM/TRREB confirms it is still current."
    return {
        "source_age_days": age_days,
        "freshness_status": status,
        "freshness_note": note,
    }


def _normalize_property_status(value: str | None) -> str:
    text = (value or "").strip().lower().replace("-", " ").replace("_", " ")
    status_aliases = {
        "for sale": "listed_for_sale",
        "listed for sale": "listed_for_sale",
        "sale": "listed_for_sale",
        "active": "listed_for_sale",
        "a": "listed_for_sale",
        "available": "listed_for_sale",
        "new": "listed_for_sale",
        "new listing": "listed_for_sale",
        "sold": "sold",
        "sld": "sold",
        "sold firm": "sold",
        "leased": "rented",
        "lsd": "rented",
        "rented": "rented",
        "for rent": "listed_for_rent",
        "for lease": "listed_for_rent",
        "listed for rent": "listed_for_rent",
        "listed for lease": "listed_for_rent",
        "lease": "listed_for_rent",
        "rent": "listed_for_rent",
    }
    return status_aliases.get(text, text.replace(" ", "_") if text else "off_market")


def _normalize_import_property_type(value: str | None) -> str:
    normalized = _normalize_property_type(value)
    return normalized or "unknown"


def _street_from_csv_row(row: dict) -> str | None:
    direct = _first_nonempty(
        row,
        "street",
        "address",
        "addr",
        "address1",
        "address line 1",
        "full address",
        "street address",
        "property address",
        "listing address",
        "prop address",
    )
    if direct:
        return direct

    parts = [
        _first_nonempty(row, "street number", "street no", "street #", "st num", "streetnum"),
        _first_nonempty(row, "street name", "streetname"),
        _first_nonempty(row, "street type", "street suffix", "street abbreviation", "street dir suffix"),
    ]
    joined = " ".join(part for part in parts if part)
    return joined or None


SOURCE_COVERAGE_RULES = {
    "buyer_listing_match": {
        "label": "Buyer listing matches",
        "statuses": ["listed_for_sale"],
        "price_fields": ["listing_price"],
        "next_step": "Import active for-sale listing rows with address, city, property type, list price, beds, baths, and parking.",
    },
    "seller_listing_and_sold": {
        "label": "Seller listings and sold comps",
        "statuses": ["listed_for_sale", "sold"],
        "price_fields": ["listing_price", "sold_price"],
        "next_step": "Import active competing listings plus sold comparable rows with list/sold prices near the subject property.",
    },
    "tenant_rental_match": {
        "label": "Tenant rental matches",
        "statuses": ["listed_for_rent"],
        "price_fields": ["monthly_rent"],
        "next_step": "Import active rental listing rows with address, city, property type, monthly rent, beds, baths, and parking.",
    },
    "landlord_rental_market": {
        "label": "Landlord rental market comps",
        "statuses": ["listed_for_rent", "rented"],
        "price_fields": ["monthly_rent"],
        "next_step": "Import active rental listings and leased comparable rows with monthly rent and core property details.",
    },
}


def _source_missing_fields(prop: models.Property, price_fields: list[str]) -> list[str]:
    missing = []
    if not prop.street or not prop.city:
        missing.append("address")
    if not prop.property_type or prop.property_type == "unknown":
        missing.append("property_type")
    if not any(getattr(prop, field, None) is not None for field in price_fields):
        missing.append("price")
    return missing


SUPPORTED_IMPORT_STATUSES = {"listed_for_sale", "sold", "listed_for_rent", "rented"}


def _property_import_warnings(row_data: dict, row_label: str) -> list[str]:
    warnings: list[str] = []
    status = row_data.get("status") or "off_market"
    if status not in SUPPORTED_IMPORT_STATUSES:
        warnings.append(
            f"{row_label}: unrecognized status '{status}'. Use For Sale, Sold, For Rent, or Leased/Rented."
        )

    property_type = row_data.get("property_type")
    if not property_type or property_type == "unknown":
        warnings.append(f"{row_label}: missing or unknown property_type; matching may be weak.")

    if status == "listed_for_sale" and row_data.get("listing_price") is None:
        warnings.append(f"{row_label}: listed_for_sale row is missing list price.")
    elif status == "sold" and row_data.get("sold_price") is None:
        warnings.append(f"{row_label}: sold row is missing sold price.")
    elif status in {"listed_for_rent", "rented"} and row_data.get("monthly_rent") is None:
        warnings.append(f"{row_label}: rental row is missing monthly rent.")

    missing_details = [
        label
        for label in ["bedrooms", "bathrooms", "parking"]
        if row_data.get(label) is None
    ]
    if missing_details:
        warnings.append(f"{row_label}: missing {', '.join(missing_details)}; criteria matching may be incomplete.")
    return warnings


def _property_source_coverage_rows(properties: list[models.Property]) -> tuple[list[dict], list[str], str | None]:
    coverage = []
    issues: list[str] = []
    recommended_next_import: str | None = None
    for watch_type, rule in SOURCE_COVERAGE_RULES.items():
        relevant = [prop for prop in properties if prop.status in set(rule["statuses"])]
        missing_counts: dict[str, int] = {}
        usable_rows = 0
        for prop in relevant:
            missing = _source_missing_fields(prop, rule["price_fields"])
            if missing:
                for field in missing:
                    missing_counts[field] = missing_counts.get(field, 0) + 1
            else:
                usable_rows += 1

        if usable_rows:
            readiness = "ready"
        elif relevant:
            readiness = "needs_fields"
        else:
            readiness = "missing_rows"

        row = {
            "watch_type": watch_type,
            "label": rule["label"],
            "required_statuses": rule["statuses"],
            "matching_rows": len(relevant),
            "usable_rows": usable_rows,
            "readiness": readiness,
            "missing_fields": sorted(missing_counts),
            "missing_field_counts": missing_counts,
            "next_step": rule["next_step"],
        }
        coverage.append(row)
        if readiness != "ready":
            issues.append(f"{rule['label']}: {readiness}")
            recommended_next_import = recommended_next_import or rule["next_step"]

    return coverage, issues, recommended_next_import


def _watchlist_csv_drop_folder_path() -> Path:
    configured = os.getenv("WATCHLIST_CSV_IMPORT_DIR")
    default_path = "/Users/kevinchou/SKC Agent OS/backend/watchlist-imports"
    return Path(configured or default_path).expanduser()


def _watchlist_csv_import_state_path() -> Path:
    configured = os.getenv("WATCHLIST_CSV_IMPORT_STATE_PATH")
    default_path = "/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/imported_csv_state.json"
    return Path(configured or default_path).expanduser()


def _watchlist_automation_config_path() -> Path:
    configured = os.getenv("WATCHLIST_AUTOMATION_CONFIG_PATH")
    default_path = "/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/automation.toml"
    return Path(configured or default_path).expanduser()


def _watchlist_automation_latest_summary_path() -> Path:
    configured = os.getenv("WATCHLIST_AUTOMATION_SUMMARY_PATH")
    default_path = "/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/artifacts/latest-summary.json"
    return Path(configured or default_path).expanduser()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _watchlist_csv_import_state_hashes(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    hashes = payload.get("hashes")
    return set(hashes) if isinstance(hashes, dict) else set()


def _read_json_object_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_object_file(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _watchlist_importable_csv_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        [path for path in folder.rglob("*.csv") if path.is_file()],
        key=lambda item: (item.stat().st_mtime, str(item.relative_to(folder))),
    )


def _watchlist_importable_source_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        [
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in {".csv", ".json"}
        ],
        key=lambda item: (item.stat().st_mtime, str(item.relative_to(folder))),
    )


def _watchlist_csv_drop_folder_status() -> dict[str, object]:
    folder = _watchlist_csv_drop_folder_path()
    state_path = _watchlist_csv_import_state_path()
    all_files = sorted(path for path in folder.rglob("*") if path.is_file()) if folder.exists() else []
    files = _watchlist_importable_source_files(folder)
    importable_file_paths = {path.resolve() for path in files}
    disabled_templates = [
        path
        for path in all_files
        if path.name.endswith(".csv.disabled") or path.name.endswith(".json.disabled")
    ]
    instruction_files = [
        path
        for path in all_files
        if path.resolve() not in importable_file_paths and path.suffix.lower() in {".md", ".txt"}
    ]
    imported_hashes = _watchlist_csv_import_state_hashes(state_path)
    pending_count = 0
    processed_count = 0
    for file_path in files:
        try:
            file_hash = _sha256_file(file_path)
        except OSError:
            pending_count += 1
            continue
        if file_hash not in imported_hashes:
            pending_count += 1
        else:
            processed_count += 1
    return {
        "csv_drop_folder": str(folder),
        "csv_drop_folder_exists": folder.exists(),
        "csv_drop_folder_file_count": len(files),
        "csv_drop_folder_importable_count": len(files),
        "csv_drop_folder_pending_count": pending_count,
        "csv_drop_folder_processed_count": processed_count,
        "csv_drop_folder_total_file_count": len(all_files),
        "csv_drop_folder_non_importable_count": max(0, len(all_files) - len(files)),
        "csv_drop_folder_disabled_template_count": len(disabled_templates),
        "csv_drop_folder_instruction_file_count": len(instruction_files),
        "csv_drop_folder_state_path": str(state_path),
    }


WATCHLIST_OPERATOR_HELPER_FILES = [
    {
        "key": "next_actions",
        "label": "Next actions",
        "filename": "watchlist-next-actions.md",
        "description": "Human-readable operator checklist generated by the scheduled Codex automation.",
    },
    {
        "key": "client_email_template",
        "label": "Client email template",
        "filename": "client-email-tasks.template.csv.disabled",
        "description": "Disabled CSV template for missing client emails; fill client_email and save as client-email-tasks.csv when ready to import.",
    },
    {
        "key": "gmail_saved_search_setup",
        "label": "Gmail saved-search setup",
        "filename": "gmail-saved-search-feed-setup.txt",
        "description": "Review-only setup guide for using authorized REALM/TRREB saved-search emails as a listing source.",
    },
]


WATCHLIST_OPERATOR_DYNAMIC_HELPER_PATTERNS = [
    {
        "key_prefix": "saved_search",
        "label": "Saved search handoff",
        "pattern": "saved-searches/*.txt",
        "description": "Per-client REALM/TRREB saved-search setup instructions generated by the scheduled automation.",
    },
    {
        "key_prefix": "source_template",
        "label": "Source template",
        "pattern": "source-templates/*.csv.disabled",
        "description": "Per-client source CSV template ignored by automation until it is completed and saved as .csv.",
    },
    {
        "key_prefix": "reso_source_template",
        "label": "RESO source template",
        "pattern": "source-templates/*.json.disabled",
        "description": "Per-client RESO/OData JSON template ignored by automation until it is completed and saved as .json.",
    },
]


WATCHLIST_SOURCE_KIT_FILES = [
    {
        "key": "readme",
        "label": "README",
        "filename": "README.txt",
        "importable": False,
        "description": "Overview, required import flow, active watchlists, and safety notes.",
    },
    {
        "key": "source_tasks_csv",
        "label": "Source tasks CSV",
        "filename": "source-tasks.csv",
        "importable": False,
        "description": "One row per active watchlist showing missing source rows and the first action.",
    },
    {
        "key": "source_tasks_json",
        "label": "Source tasks JSON",
        "filename": "source-tasks.json",
        "importable": False,
        "description": "Structured source-task snapshot for audit and automation handoff.",
    },
    {
        "key": "source_status_json",
        "label": "Source status",
        "filename": "source-status.json",
        "importable": False,
        "description": "Current property source, drop-folder, Gmail feed, and RESO connector state.",
    },
    {
        "key": "launch_action_pack",
        "label": "Launch pack",
        "filename": "launch-action-pack.txt",
        "importable": False,
        "description": "Current launch checklist, preflight status, and client-by-client next actions.",
    },
    {
        "key": "gmail_saved_search_setup",
        "label": "Gmail saved-search setup",
        "filename": "gmail-saved-search-feed-setup.txt",
        "importable": False,
        "description": "How to use authorized REALM/TRREB saved-search emails as a review-gated listing feed.",
    },
    {
        "key": "client_email_tasks",
        "label": "Client email CSV",
        "filename": "client-email-tasks.csv",
        "importable": True,
        "description": "Missing client-email tasks; completed rows can be imported to update contacts.",
    },
    {
        "key": "saved_searches",
        "label": "Saved searches",
        "filename": "saved-searches/*.txt",
        "importable": False,
        "description": "Per-client REALM/TRREB saved-search setup instructions and Gmail query.",
    },
    {
        "key": "property_template",
        "label": "Property CSV template",
        "filename": "skc-watchlist-import-template.csv",
        "importable": True,
        "description": "Generic authorized listing, sold, rental, or leased-comp import template.",
    },
    {
        "key": "client_templates",
        "label": "Client source templates",
        "filename": "skc-watchlist-source-template-*.csv / *.json.disabled",
        "importable": False,
        "description": "Client-specific placeholder-safe CSV and disabled RESO/OData JSON templates.",
    },
]


def _watchlist_source_kit_manifest() -> list[schemas.WatchlistSourceKitFile]:
    return [
        schemas.WatchlistSourceKitFile(
            key=item["key"],
            label=item["label"],
            filename=item["filename"],
            included=True,
            importable=bool(item["importable"]),
            description=item["description"],
        )
        for item in WATCHLIST_SOURCE_KIT_FILES
    ]


def _read_toml_string_value(path: Path, key: str, default: str = "unknown") -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\"([^\"]*)\"", text)
    return match.group(1).strip() if match else default


def _operator_helper_file_status(drop_folder: Path, spec: dict[str, str]) -> schemas.WatchlistOperatorHelperFile:
    path = drop_folder / spec["filename"]
    exists = path.exists()
    size_bytes = 0
    updated_at = None
    if exists:
        try:
            file_stat = path.stat()
            size_bytes = int(file_stat.st_size)
            updated_at = datetime.fromtimestamp(file_stat.st_mtime, UTC)
        except OSError:
            exists = False
    return schemas.WatchlistOperatorHelperFile(
        key=spec["key"],
        label=spec["label"],
        filename=spec["filename"],
        path=str(path),
        exists=exists,
        size_bytes=size_bytes,
        updated_at=updated_at,
        importable_csv=path.suffix.lower() in {".csv", ".json"},
        description=spec["description"],
    )


def _operator_dynamic_helper_file_statuses(drop_folder: Path) -> list[schemas.WatchlistOperatorHelperFile]:
    files: list[schemas.WatchlistOperatorHelperFile] = []
    if not drop_folder.exists():
        return files

    for pattern_spec in WATCHLIST_OPERATOR_DYNAMIC_HELPER_PATTERNS:
        for path in sorted(drop_folder.glob(pattern_spec["pattern"])):
            if not path.is_file():
                continue
            relative_name = str(path.relative_to(drop_folder))
            files.append(
                _operator_helper_file_status(
                    drop_folder,
                    {
                        "key": f"{pattern_spec['key_prefix']}_{_csv_filename_slug(relative_name)}",
                        "label": pattern_spec["label"],
                        "filename": relative_name,
                        "description": pattern_spec["description"],
                    },
                )
            )
    return files


def get_watchlist_operator_handoff_status() -> schemas.WatchlistOperatorHandoffStatus:
    drop_folder = _watchlist_csv_drop_folder_path()
    automation_path = _watchlist_automation_config_path()
    drop_status = _watchlist_csv_drop_folder_status()
    base_files = [_operator_helper_file_status(drop_folder, spec) for spec in WATCHLIST_OPERATOR_HELPER_FILES]
    files = [*base_files, *_operator_dynamic_helper_file_statuses(drop_folder)]
    helper_files_ready = all(file.exists and file.size_bytes > 0 for file in base_files)
    automation_id = _read_toml_string_value(automation_path, "id", "skc-crm-watchlist-check")
    automation_status = _read_toml_string_value(automation_path, "status", "unknown")
    schedule_summary = "09:00, 15:00, 18:00 America/Toronto"
    importable_csv_count = int(drop_status.get("csv_drop_folder_importable_count") or 0)
    pending_csv_count = int(drop_status.get("csv_drop_folder_pending_count") or 0)
    processed_csv_count = int(drop_status.get("csv_drop_folder_processed_count") or 0)
    non_importable_file_count = int(drop_status.get("csv_drop_folder_non_importable_count") or 0)
    disabled_template_count = int(drop_status.get("csv_drop_folder_disabled_template_count") or 0)
    instruction_file_count = int(drop_status.get("csv_drop_folder_instruction_file_count") or 0)

    if helper_files_ready:
        dynamic_count = max(0, len(files) - len(base_files))
        suffix = f" {dynamic_count} per-client source handoff file(s) are also available." if dynamic_count else ""
        if pending_csv_count:
            queue = f" {pending_csv_count} importable source file(s) are waiting for review/import."
            next_step = "Use Import Folder to preview pending CSV or RESO JSON files from the drop folder or source-templates subfolder before matching; keep using saved-searches/*.txt for new source tasks."
        else:
            queue = f" {non_importable_file_count} helper/template file(s) are present but ignored by import until completed and saved as .csv or .json."
            next_step = "Use watchlist-next-actions.md plus saved-searches/*.txt for source tasks; fill disabled templates only when real authorized rows or client emails are known, then save completed source files as .csv or .json in the same source-templates folder or the drop folder root."
        message = f"Codex automation handoff files are present in the watchlist import folder.{suffix}{queue}"
    elif drop_folder.exists():
        missing = ", ".join(file.filename for file in files if not file.exists)
        message = "Codex automation helper files have not all been generated yet."
        next_step = f"Run the watchlist automation once to create: {missing or 'the helper files'}."
    else:
        message = "The watchlist import folder does not exist yet."
        next_step = "Run the watchlist automation or import workflow once so the drop folder and helper files can be created."

    return schemas.WatchlistOperatorHandoffStatus(
        automation_id=automation_id,
        automation_status=automation_status,
        automation_config_path=str(automation_path),
        schedule_summary=schedule_summary,
        drop_folder=str(drop_folder),
        drop_folder_exists=drop_folder.exists(),
        helper_files_ready=helper_files_ready,
        importable_csv_count=importable_csv_count,
        pending_csv_count=pending_csv_count,
        processed_csv_count=processed_csv_count,
        non_importable_file_count=non_importable_file_count,
        disabled_template_count=disabled_template_count,
        instruction_file_count=instruction_file_count,
        files=files,
        source_kit_files=_watchlist_source_kit_manifest(),
        message=message,
        next_step=next_step,
    )


def _parse_artifact_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def get_watchlist_latest_automation_summary() -> schemas.WatchlistAutomationLatestSummary:
    artifact_path = _watchlist_automation_latest_summary_path()
    if not artifact_path.exists():
        return schemas.WatchlistAutomationLatestSummary(
            available=False,
            artifact_path=str(artifact_path),
            message="Latest Codex automation summary has not been generated yet.",
        )

    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return schemas.WatchlistAutomationLatestSummary(
            available=False,
            artifact_path=str(artifact_path),
            message=f"Latest Codex automation summary could not be read: {exc}",
        )

    check_result = payload.get("check_result") if isinstance(payload.get("check_result"), dict) else {}
    source = payload.get("property_source") if isinstance(payload.get("property_source"), dict) else {}
    readiness = payload.get("readiness_report") if isinstance(payload.get("readiness_report"), dict) else {}
    launch_pack = payload.get("launch_action_pack") if isinstance(payload.get("launch_action_pack"), dict) else {}
    gmail_feed = payload.get("gmail_feed_import") if isinstance(payload.get("gmail_feed_import"), dict) else {}
    summary = str(payload.get("codex_notification_summary") or "").strip() or None
    message = (
        summary.splitlines()[1]
        if summary and len(summary.splitlines()) > 1
        else str(readiness.get("message") or payload.get("error") or "Latest Codex automation summary is available.")
    )

    return schemas.WatchlistAutomationLatestSummary(
        available=bool(payload.get("ok", True)),
        artifact_path=str(artifact_path),
        updated_at=_parse_artifact_datetime(payload.get("artifact_written_at")),
        checked_at=_parse_artifact_datetime(payload.get("checked_at")),
        overall_status=readiness.get("overall_status"),
        created_alerts=int(check_result.get("created_alerts") or 0),
        checked_count=int(check_result.get("checked") or 0),
        source_rows=int(source.get("properties_count") or launch_pack.get("source_rows") or 0),
        pending_csv_count=int(source.get("csv_drop_folder_pending_count") or launch_pack.get("pending_csv_count") or 0),
        missing_email_count=int(launch_pack.get("missing_email_count") or 0),
        gmail_feed_enabled=bool(gmail_feed.get("enabled") or launch_pack.get("gmail_feed_enabled")),
        auto_send_server_enabled=bool(launch_pack.get("auto_send_server_enabled")),
        summary=summary,
        message=message,
        next_actions=[str(action) for action in (launch_pack.get("next_actions") or readiness.get("next_actions") or [])[:8]],
    )


def _decode_csv_file(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _csv_header_keys(csv_text: str) -> set[str]:
    reader = csv.DictReader(StringIO(csv_text))
    return {_normalize_csv_key(field or "") for field in (reader.fieldnames or [])}


def _is_contact_email_task_csv(csv_text: str) -> bool:
    keys = _csv_header_keys(csv_text)
    return "contactid" in keys and bool({"clientemail", "email", "contactemail"} & keys)


def _row_email_value(row: dict) -> str | None:
    return _first_nonempty(row, "client_email", "client email", "email", "contact_email", "contact email")


def import_contact_email_tasks_csv(db: Session, csv_text: str, dry_run: bool = False) -> schemas.PropertyImportResult:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        return schemas.PropertyImportResult(
            success=False,
            message="Contact email CSV has no header row.",
            dry_run=dry_run,
            created=0,
            updated=0,
            skipped=0,
            total_rows=0,
            errors=["missing_header"],
        )

    updated = 0
    skipped = 0
    errors: list[str] = []
    warnings: list[str] = []
    preview_rows: list[dict] = []
    total_rows = 0
    now = _utcnow()

    for index, row in enumerate(reader, start=2):
        total_rows += 1
        contact_id = _parse_int(_first_nonempty(row, "contact_id", "contact id", "id"))
        email = _row_email_value(row)
        if not contact_id:
            skipped += 1
            errors.append(f"row_{index}: missing contact_id")
            continue
        if not email:
            skipped += 1
            warnings.append(f"row_{index}: client_email is blank")
            continue
        if "@" not in email:
            skipped += 1
            errors.append(f"row_{index}: invalid client_email")
            continue

        contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
        if not contact:
            skipped += 1
            errors.append(f"row_{index}: contact_id {contact_id} not found")
            continue

        current_email = str(contact.email or "").strip()
        if current_email and current_email.lower() != email.lower():
            skipped += 1
            warnings.append(
                f"row_{index}: contact_id {contact_id} already has a different email; update it manually if this replacement is intended"
            )
            continue
        if current_email.lower() == email.lower():
            skipped += 1
            warnings.append(f"row_{index}: contact_id {contact_id} already has this email")
            continue

        if len(preview_rows) < 25:
            preview_rows.append(
                {
                    "action": "update_contact_email",
                    "contact_id": contact.id,
                    "contact_name": contact.name,
                    "email": email,
                }
            )
        if not dry_run:
            contact.email = email
            contact.updated_at = now
            db.add(contact)
        updated += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    action = "Previewed" if dry_run else "Updated"
    return schemas.PropertyImportResult(
        success=updated > 0 or not errors,
        message=f"{action} {updated} contact email update(s).",
        dry_run=dry_run,
        created=0,
        updated=updated,
        skipped=skipped,
        total_rows=total_rows,
        errors=errors[:20],
        warnings=warnings[:50],
        preview_rows=preview_rows,
    )


def import_properties_csv_drop_folder(
    db: Session,
    dry_run: bool = False,
    max_files: int = 10,
) -> schemas.CsvDropFolderImportResult:
    folder = _watchlist_csv_drop_folder_path()
    state_path = _watchlist_csv_import_state_path()
    folder.mkdir(parents=True, exist_ok=True)
    max_files = max(1, min(int(max_files or 10), 50))
    files = _watchlist_importable_source_files(folder)
    state = _read_json_object_file(state_path)
    hashes = state.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        hashes = {}
        state["hashes"] = hashes

    imported: list[schemas.CsvDropFolderImportFile] = []
    skipped: list[schemas.CsvDropFolderImportFile] = []
    failed: list[schemas.CsvDropFolderImportFile] = []
    pending_before = 0

    for source_file in files:
        try:
            sha = _sha256_file(source_file)
        except OSError as exc:
            failed.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    status="read_failed",
                    error=str(exc),
                )
            )
            continue

        if sha in hashes:
            skipped.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    sha256=sha,
                    status="already_imported",
                )
            )
            continue

        pending_before += 1
        if len(imported) + len(failed) >= max_files:
            skipped.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    sha256=sha,
                    status="over_limit",
                )
            )
            continue

        try:
            if source_file.suffix.lower() == ".json":
                json_payload = json.loads(source_file.read_text(encoding="utf-8"))
                result = import_properties_reso_json(db, json_payload, dry_run=dry_run)
                success_status = "reso_json_previewed" if dry_run else "reso_json_imported"
            else:
                csv_text = _decode_csv_file(source_file)
                if _is_contact_email_task_csv(csv_text):
                    result = import_contact_email_tasks_csv(db, csv_text, dry_run=dry_run)
                    success_status = "contact_email_previewed" if dry_run else "contact_email_imported"
                else:
                    result = import_properties_csv(db, csv_text, dry_run=dry_run)
                    success_status = "previewed" if dry_run else "imported"
        except Exception as exc:
            failed.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    sha256=sha,
                    status="import_failed",
                    error=str(exc),
                )
            )
            continue

        if result.success:
            imported.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    sha256=sha,
                    status=success_status,
                    result=result,
                )
            )
            if not dry_run:
                hashes[sha] = {
                    "file": str(source_file),
                    "source_type": "reso_json" if source_file.suffix.lower() == ".json" else "csv",
                    "imported_at": _utcnow().isoformat(),
                    "result": {
                        "success": result.success,
                        "created": result.created,
                        "updated": result.updated,
                        "skipped": result.skipped,
                        "message": result.message,
                    },
                }
                _write_json_object_file(state_path, state)
        else:
            failed.append(
                schemas.CsvDropFolderImportFile(
                    file=str(source_file),
                    sha256=sha,
                    status="import_rejected",
                    result=result,
                    error=result.message,
                )
            )

    if dry_run:
        pending_after = pending_before
    else:
        imported_hashes = set(hashes)
        pending_after = 0
        for source_file in files:
            try:
                if _sha256_file(source_file) not in imported_hashes:
                    pending_after += 1
            except OSError:
                pending_after += 1

    processed_count = len(imported)
    mode = "Previewed" if dry_run else "Imported"
    message = (
        f"{mode} {processed_count} source file(s) from the drop folder and source subfolders. "
        f"Skipped {len([item for item in skipped if item.status == 'already_imported'])} already imported file(s); "
        f"{len(failed)} file(s) need attention."
    )
    return schemas.CsvDropFolderImportResult(
        success=len(failed) == 0,
        message=message,
        dry_run=dry_run,
        drop_dir=str(folder),
        state_path=str(state_path),
        imported=imported,
        skipped=skipped,
        failed=failed,
        processed_count=processed_count,
        pending_before=pending_before,
        pending_after=pending_after,
    )


def get_property_source_status(db: Session) -> schemas.PropertySourceStatus:
    properties_count = db.query(func.count(models.Property.id)).scalar() or 0
    properties = db.query(models.Property).all()
    status_rows = (
        db.query(models.Property.status, func.count(models.Property.id))
        .group_by(models.Property.status)
        .all()
    )
    latest_property_update = db.query(func.max(models.Property.updated_at)).scalar()
    reso_connector = _watchlist_reso_connector_status()
    external_ready = (
        _env_flag_enabled("MLS_CONNECTOR_ENABLED")
        or _env_flag_enabled("TRREB_CONNECTOR_ENABLED")
        or reso_connector.ready
    )
    coverage, data_quality_issues, recommended_next_import = _property_source_coverage_rows(properties)
    drop_status = _watchlist_csv_drop_folder_status()
    pending_csv_count = int(drop_status.get("csv_drop_folder_pending_count") or 0)
    non_importable_count = int(drop_status.get("csv_drop_folder_non_importable_count") or 0)
    if properties_count:
        message = f"{properties_count} imported/internal property rows are available for watchlist matching."
    elif pending_csv_count:
        message = f"No property/listing rows are loaded yet. {pending_csv_count} importable REALM/TRREB CSV or RESO JSON source file(s) are waiting in the drop folder or source subfolders."
    elif non_importable_count:
        message = f"No property/listing rows are loaded yet. {non_importable_count} helper/template file(s) are present, but no importable REALM/TRREB CSV or RESO JSON source file is pending."
    else:
        message = "No property/listing rows are loaded. Import a REALM/TRREB CSV export, import authorized RESO/OData JSON, or connect an MLS adapter."
    return schemas.PropertySourceStatus(
        properties_count=properties_count,
        status_counts={status or "unknown": count for status, count in status_rows},
        latest_property_update=latest_property_update,
        internal_properties_ready=properties_count > 0,
        csv_import_ready=True,
        **drop_status,
        external_mls_connector_ready=external_ready,
        reso_connector=reso_connector,
        watch_type_coverage=coverage,
        data_quality_issues=data_quality_issues,
        recommended_next_import=recommended_next_import,
        message=message,
    )


def _property_feed_config_schema(row: models.PropertyFeedConfig) -> schemas.PropertyFeedConfig:
    return schemas.PropertyFeedConfig(
        id=row.id,
        gmail_feed_enabled=bool(row.gmail_feed_enabled),
        gmail_query=row.gmail_query or DEFAULT_GMAIL_FEED_QUERY,
        gmail_max_results=row.gmail_max_results or 10,
        last_import_at=row.last_import_at,
        last_import_message=row.last_import_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_property_feed_config_row(db: Session) -> models.PropertyFeedConfig:
    row = db.query(models.PropertyFeedConfig).order_by(models.PropertyFeedConfig.id.asc()).first()
    if row:
        return row

    row = models.PropertyFeedConfig(
        gmail_feed_enabled=False,
        gmail_query=DEFAULT_GMAIL_FEED_QUERY,
        gmail_max_results=10,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_property_feed_config(db: Session) -> schemas.PropertyFeedConfig:
    return _property_feed_config_schema(get_property_feed_config_row(db))


def update_property_feed_config(db: Session, update: schemas.PropertyFeedConfigUpdate) -> schemas.PropertyFeedConfig:
    row = get_property_feed_config_row(db)
    data = update.model_dump(exclude_unset=True)
    if "gmail_feed_enabled" in data and data["gmail_feed_enabled"] is not None:
        next_enabled = bool(data["gmail_feed_enabled"])
        if next_enabled and not bool(row.gmail_feed_enabled) and not _gmail_feed_confirmation_valid(data.get("gmail_feed_confirmation")):
            raise ValueError("gmail_feed_confirmation_required")
        row.gmail_feed_enabled = next_enabled
    if "gmail_query" in data and data["gmail_query"] is not None:
        from . import gmail_service

        row.gmail_query = gmail_service.validate_property_feed_query(data["gmail_query"])
    if "gmail_max_results" in data and data["gmail_max_results"] is not None:
        row.gmail_max_results = max(1, min(int(data["gmail_max_results"]), 50))
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return _property_feed_config_schema(row)


def gmail_feed_read_authorized(db: Session, confirmation: str | None = None) -> bool:
    row = get_property_feed_config_row(db)
    return (
        bool(row.gmail_feed_enabled)
        or _env_flag_enabled("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED")
        or _gmail_feed_confirmation_valid(confirmation)
    )


def record_property_feed_import_result(db: Session, result: schemas.PropertyImportResult):
    row = get_property_feed_config_row(db)
    row.last_import_at = _utcnow()
    row.last_import_message = result.message
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return _property_feed_config_schema(row)


def _find_existing_import_property(db: Session, row_data: dict):
    mls_number = row_data.get("mls_number")
    if mls_number:
        existing = db.query(models.Property).filter(models.Property.mls_number == mls_number).first()
        if existing:
            return existing

    street = row_data.get("street")
    city = row_data.get("city")
    if not street or not city:
        return None

    return (
        db.query(models.Property)
        .filter(models.Property.street.ilike(street))
        .filter(models.Property.city.ilike(city))
        .filter(models.Property.status == row_data.get("status"))
        .first()
    )


def _property_import_preview_row(row_data: dict, action: str) -> dict:
    fields = [
        "mls_number",
        "street",
        "city",
        "neighborhood",
        "status",
        "property_type",
        "listing_price",
        "sold_price",
        "monthly_rent",
        "listed_at",
        "sold_at",
        "leased_at",
        "bedrooms",
        "bathrooms",
        "parking",
        "listing_url",
    ]
    return {
        "action": action,
        **{
            field: _format_source_date(row_data.get(field)) if field in {"listed_at", "sold_at", "leased_at"} else row_data.get(field)
            for field in fields
            if row_data.get(field) not in (None, "", [])
        },
    }


def _property_import_values_changed(existing: models.Property, row_data: dict) -> bool:
    for key, value in row_data.items():
        existing_value = getattr(existing, key, None)
        if isinstance(existing_value, datetime) or isinstance(value, datetime):
            if _format_source_date(existing_value) != _format_source_date(value):
                return True
            continue
        if existing_value != value:
            return True
    return False


def _is_template_placeholder_csv_row(row: dict) -> bool:
    values = " ".join(str(value or "") for value in row.values()).lower()
    return any(
        marker in values
        for marker in [
            "template only",
            "template_only",
            "replace_with_",
            "replace this row",
        ]
    )


def _build_watchlist_match_preview(db: Session, rows: list[dict], limit: int = 50) -> list[dict]:
    if not rows:
        return []

    watchlists = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    if not watchlists:
        return []

    previews: list[dict] = []
    preview_pairs = sorted(
        [(models.Property(**row_data), row_data) for row_data in rows],
        key=lambda item: _property_recency_sort_key(item[0]),
        reverse=True,
    )
    for prop, row_data in preview_pairs:
        property_preview = _property_import_preview_row(row_data, "match")
        for watchlist in watchlists:
            score, reasons = _score_property_match(prop, watchlist, _json_object(watchlist.criteria_json))
            if score < WATCHLIST_MATCH_SCORE_THRESHOLD:
                continue
            previews.append(
                {
                    "watchlist_id": watchlist.id,
                    "watchlist_name": watchlist.name,
                    "contact_id": watchlist.contact_id,
                    "contact_name": watchlist.contact.name if watchlist.contact else None,
                    "watch_type": watchlist.watch_type,
                    "match_score": score,
                    "reasons": reasons,
                    "analysis": _build_alert_analysis(watchlist.contact, watchlist, prop, reasons) if watchlist.contact else "",
                    "property": property_preview,
                }
            )
            if len(previews) >= limit:
                return previews
    return previews


def _readiness_preview_status_label(status: str) -> str:
    return status.replace("_", " ")


def _source_ready_for_counts(required_statuses: list[str], counts: dict[str, int]) -> bool:
    return all(counts.get(status, 0) > 0 for status in required_statuses)


def _source_missing_for_counts(required_statuses: list[str], counts: dict[str, int]) -> list[str]:
    return [status for status in required_statuses if counts.get(status, 0) == 0]


def _build_watchlist_readiness_preview(db: Session, rows: list[dict], limit: int = 25) -> list[dict]:
    watchlists = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    if not watchlists:
        return []

    preview_properties = _sort_properties_by_recency([models.Property(**row_data) for row_data in rows])
    previews: list[dict] = []
    for watchlist in watchlists[:limit]:
        required_statuses = sorted(_watchlist_statuses(watchlist.watch_type))
        criteria = _json_object(watchlist.criteria_json)
        current_counts = {status: 0 for status in required_statuses}
        preview_counts = {status: 0 for status in required_statuses}

        for prop in db.query(models.Property).filter(models.Property.status.in_(required_statuses)).all():
            score, _reasons = _score_property_match(prop, watchlist, criteria)
            if score >= WATCHLIST_MATCH_SCORE_THRESHOLD and prop.status in current_counts:
                current_counts[prop.status] += 1

        for prop in preview_properties:
            score, _reasons = _score_property_match(prop, watchlist, criteria)
            if score >= WATCHLIST_MATCH_SCORE_THRESHOLD and prop.status in preview_counts:
                preview_counts[prop.status] += 1

        projected_counts = {
            status: current_counts.get(status, 0) + preview_counts.get(status, 0)
            for status in required_statuses
        }
        missing_before = _source_missing_for_counts(required_statuses, current_counts)
        missing_after = _source_missing_for_counts(required_statuses, projected_counts)
        source_ready_before = _source_ready_for_counts(required_statuses, current_counts)
        source_ready_after = _source_ready_for_counts(required_statuses, projected_counts)
        current_matching_rows = sum(current_counts.values())
        preview_matching_rows = sum(preview_counts.values())
        projected_matching_rows = sum(projected_counts.values())

        if source_ready_before:
            readiness_delta = "unchanged_ready"
            primary_next_step = "Source rows are already complete for this watchlist."
        elif source_ready_after:
            readiness_delta = "becomes_ready"
            primary_next_step = "Import this data, then run Check All to create reviewable alerts and drafts."
        elif preview_matching_rows > 0 or len(missing_after) < len(missing_before):
            readiness_delta = "improves"
            missing_text = ", ".join(_readiness_preview_status_label(status) for status in missing_after)
            primary_next_step = f"This import helps, but still needs: {missing_text}."
        else:
            readiness_delta = "still_missing"
            missing_text = ", ".join(_readiness_preview_status_label(status) for status in missing_after)
            primary_next_step = (
                f"No matching rows in this import. Still needs: {missing_text}."
                if missing_text
                else "No matching rows in this import."
            )

        review_mode = watchlist.review_mode or "manual_review"
        notification_channel = _watchlist_notification_channel_or_default(watchlist.notification_channel)
        contact_email_present = bool(watchlist.contact and str(watchlist.contact.email or "").strip())
        needs_gmail_recipient = review_mode in {"auto_gmail_draft", "auto_send_approved"}
        auto_send_server_enabled = _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED")
        delivery_blockers_after: list[str] = []
        if not source_ready_after:
            delivery_state_after = "source_not_ready"
            delivery_blockers_after.append("Source rows would still be incomplete after this import.")
            delivery_next_step = primary_next_step
        elif review_mode == "manual_review":
            delivery_state_after = "manual_review_after_import"
            delivery_next_step = "Import this data, then review alerts before creating any draft or client email."
        elif review_mode == "auto_create_draft":
            delivery_state_after = "crm_draft_after_import"
            delivery_next_step = "Import this data, then run Check All to create CRM review drafts."
        elif needs_gmail_recipient and not contact_email_present:
            delivery_state_after = "email_required_after_import"
            delivery_blockers_after.append("Contact email is missing; Gmail drafts cannot be addressed.")
            delivery_next_step = "Add the client's email before relying on Gmail Draft or Auto Send."
        elif review_mode == "auto_send_approved" and not auto_send_server_enabled:
            delivery_state_after = "auto_send_armed_draft_only_after_import"
            delivery_blockers_after.append("Auto Send server switch is off; this would stay Gmail draft-only.")
            delivery_next_step = "Import this data, then review the Gmail draft unless the server auto-send switch is explicitly enabled later."
        elif review_mode == "auto_send_approved":
            delivery_state_after = "auto_send_ready_after_import"
            delivery_next_step = "Import this data, then run Check All; matching alerts can auto-send only because this client and server are both armed."
        elif review_mode == "auto_gmail_draft":
            delivery_state_after = "gmail_draft_recipient_ready_after_import"
            delivery_next_step = "Import this data, then run Check All to create Gmail drafts for review if Gmail remains connected."
        else:
            delivery_state_after = "unknown_review_mode_after_import"
            delivery_blockers_after.append("Review mode is unknown.")
            delivery_next_step = "Choose Manual Review, CRM Draft, Gmail Draft, or Auto Send Armed before trusting delivery automation."

        previews.append(
            {
                "watchlist_id": watchlist.id,
                "watchlist_name": watchlist.name,
                "contact_id": watchlist.contact_id,
                "contact_name": watchlist.contact.name if watchlist.contact else None,
                "watch_type": watchlist.watch_type,
                "required_statuses": required_statuses,
                "current_status_counts": current_counts,
                "preview_status_counts": preview_counts,
                "projected_status_counts": projected_counts,
                "missing_before": missing_before,
                "missing_after": missing_after,
                "current_matching_rows": current_matching_rows,
                "preview_matching_rows": preview_matching_rows,
                "projected_matching_rows": projected_matching_rows,
                "source_ready_before": source_ready_before,
                "source_ready_after": source_ready_after,
                "readiness_delta": readiness_delta,
                "primary_next_step": primary_next_step,
                "review_mode": review_mode,
                "notification_channel": notification_channel,
                "contact_email_present": contact_email_present,
                "needs_gmail_recipient": needs_gmail_recipient,
                "auto_send_server_enabled": auto_send_server_enabled,
                "draft_recipient_ready_after": bool(source_ready_after and (not needs_gmail_recipient or contact_email_present)),
                "can_auto_send_after": bool(source_ready_after and review_mode == "auto_send_approved" and contact_email_present and auto_send_server_enabled),
                "delivery_state_after": delivery_state_after,
                "delivery_blockers_after": delivery_blockers_after,
                "delivery_next_step": delivery_next_step,
            }
        )
    return previews


def build_property_csv_template() -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(PROPERTY_CSV_TEMPLATE_COLUMNS)
    writer.writerows(PROPERTY_CSV_TEMPLATE_ROWS)
    return output.getvalue()


def _csv_status_label(status: str) -> str:
    return {
        "listed_for_sale": "For Sale",
        "sold": "Sold",
        "listed_for_rent": "For Rent",
        "rented": "Rented",
    }.get(status, status.replace("_", " ").title())


def _template_title(value: str | None, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else fallback


def _first_criteria_value(criteria: dict, key: str, fallback: str) -> str:
    values = _coerce_string_list(criteria.get(key))
    return values[0] if values else fallback


def _template_numeric(value) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _watchlist_template_rows(row: models.ClientWatchlist) -> list[list[str]]:
    criteria = _json_object(row.criteria_json)
    statuses = sorted(_watchlist_statuses(row.watch_type))
    city = _first_criteria_value(criteria, "areas", "REPLACE_WITH_CITY")
    property_type = _template_title(
        _normalize_property_type(_first_criteria_value(criteria, "types", "")),
        "REPLACE_WITH_PROPERTY_TYPE",
    )
    bedrooms = _template_numeric(criteria.get("bedrooms_min"))
    bathrooms = _template_numeric(criteria.get("bathrooms_min"))
    parking = _template_numeric(criteria.get("parking_min"))
    max_price = _template_numeric(criteria.get("max_price"))
    contact_name = row.contact.name if row.contact else row.name

    rows: list[list[str]] = []
    for index, status in enumerate(statuses, start=1):
        list_price = ""
        sold_price = ""
        rent = ""
        if status in {"listed_for_sale", "sold"}:
            list_price = max_price or "REPLACE_WITH_LIST_PRICE"
        if status == "sold":
            sold_price = "REPLACE_WITH_SOLD_PRICE"
        if status in {"listed_for_rent", "rented"}:
            rent = _template_numeric(criteria.get("max_rent") or criteria.get("monthly_rent")) or "REPLACE_WITH_MONTHLY_RENT"

        rows.append(
            [
                f"TEMPLATE_ONLY_{row.id}_{index}",
                "REPLACE_WITH_REALM_STREET",
                city,
                city,
                _csv_status_label(status),
                property_type,
                list_price,
                sold_price,
                rent,
                bedrooms,
                bathrooms,
                parking,
                "REPLACE_WITH_LISTING_URL",
                f"TEMPLATE ONLY - replace this row with authorized REALM/TRREB data for {contact_name}.",
            ]
        )
    return rows


def _watchlist_reso_json_template(row: models.ClientWatchlist) -> str:
    criteria = _json_object(row.criteria_json)
    statuses = sorted(_watchlist_statuses(row.watch_type))
    city = _first_criteria_value(criteria, "areas", "REPLACE_WITH_CITY")
    property_type = _template_title(
        _normalize_property_type(_first_criteria_value(criteria, "types", "")),
        "REPLACE_WITH_PROPERTY_TYPE",
    )
    contact_name = row.contact.name if row.contact else row.name
    records: list[dict[str, object | None]] = []
    for index, status in enumerate(statuses, start=1):
        lease_like = status in {"listed_for_rent", "rented"}
        sold_like = status in {"sold", "rented"}
        records.append(
            {
                "ListingKey": f"TEMPLATE_ONLY_{row.id}_{index}",
                "UnparsedAddress": f"REPLACE_WITH_STREET_ADDRESS, {city}, ON REPLACE_WITH_POSTAL_CODE",
                "City": city,
                "CityRegion": city,
                "StandardStatus": "Closed" if sold_like else "Active",
                "TransactionType": "Lease" if lease_like else "For Sale",
                "PropertySubType": property_type,
                "ListPrice": "REPLACE_WITH_LIST_PRICE" if not lease_like else None,
                "ClosePrice": "REPLACE_WITH_SOLD_OR_LEASED_PRICE" if sold_like else None,
                "LeaseAmount": "REPLACE_WITH_MONTHLY_RENT" if lease_like else None,
                "BedroomsTotal": _template_numeric(criteria.get("bedrooms_min")) or "REPLACE_WITH_BEDS",
                "BathroomsTotalInteger": _template_numeric(criteria.get("bathrooms_min")) or "REPLACE_WITH_BATHS",
                "ParkingTotal": _template_numeric(criteria.get("parking_min")) or "REPLACE_WITH_PARKING",
                "ListingContractDate": "YYYY-MM-DD",
                "CloseDate": "YYYY-MM-DD" if sold_like else None,
                "ListingURL": "REPLACE_WITH_SOURCE_URL",
                "PublicRemarks": f"TEMPLATE ONLY - replace this object with authorized RESO/OData MLS data for {contact_name} before saving as .json.",
            }
        )
    return json.dumps({"value": records}, ensure_ascii=False, indent=2)


def _csv_filename_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "watchlist"


def build_watchlist_property_csv_template(db: Session, watchlist_id: int) -> tuple[str, str] | None:
    row = get_watchlist(db, watchlist_id)
    if not row:
        return None

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(PROPERTY_CSV_TEMPLATE_COLUMNS)
    writer.writerows(_watchlist_template_rows(row))
    filename = f"skc-watchlist-source-template-{row.id}-{_csv_filename_slug(row.name)}.csv"
    return filename, output.getvalue()


def _source_setup_text(setup: schemas.WatchlistSourceSetup) -> str:
    lines = [
        f"{setup.contact_name or setup.watchlist_name} - REALM/TRREB Saved Search Setup",
        "",
        f"Watchlist: {setup.watchlist_name}",
        f"Type: {setup.watch_type}",
        f"Readiness: {setup.readiness}",
        f"Current matching rows: {setup.current_matching_rows}",
        f"Saved search name: {setup.saved_search_name}",
        f"Gmail query: {setup.gmail_query}",
        f"Recommended method: {setup.recommended_method}",
        "",
        "Required export statuses:",
        *[f"- {status.replace('_', ' ')}" for status in setup.export_statuses],
        "",
        "Required fields:",
        *[f"- {field}" for field in setup.required_fields],
        "",
        "REALM/TRREB criteria:",
        *[f"- {line}" for line in setup.realm_criteria],
        "",
        "Setup steps:",
        *[f"{index}. {step}" for index, step in enumerate(setup.realm_steps, start=1)],
        "",
        "After export:",
        *[f"- {action}" for action in setup.next_actions],
    ]
    return "\n".join(lines) + "\n"


def _source_tasks_csv(setups: list[schemas.WatchlistSourceSetup], drop_folder: str | None) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "contact_name",
            "watchlist_name",
            "watch_type",
            "readiness",
            "current_matching_rows",
            "missing_required_statuses",
            "saved_search_name",
            "gmail_query",
            "drop_folder",
            "recommended_method",
            "next_action",
        ]
    )
    for setup in setups:
        writer.writerow(
            [
                setup.contact_name or "",
                setup.watchlist_name,
                setup.watch_type,
                setup.readiness,
                setup.current_matching_rows,
                ", ".join(status.replace("_", " ") for status in setup.missing_required_statuses),
                setup.saved_search_name,
                setup.gmail_query,
                drop_folder or "",
                setup.recommended_method,
                setup.next_actions[0] if setup.next_actions else "",
            ]
        )
    return output.getvalue()


def _client_email_tasks_csv(tasks: list[schemas.WatchlistSourceTask]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "contact_id",
            "contact_name",
            "client_email",
            "watchlist_id",
            "watchlist_name",
            "review_mode_blocker",
            "client_email_needed",
            "next_action",
        ]
    )
    for task in tasks:
        if not task.client_email_needed:
            continue
        contact = task.contact_name or task.watchlist_name
        writer.writerow(
            [
                task.contact_id,
                task.contact_name or "",
                "",
                task.watchlist_id,
                task.watchlist_name,
                "Gmail Draft or Auto Send cannot be addressed without this email.",
                "yes",
                f"Add {contact}'s client email in Watchlists or Contacts before relying on Gmail Draft or Auto Send.",
            ]
        )
    return output.getvalue()


def _schema_json_text(value) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif hasattr(value, "dict"):
        payload = value.dict()
    else:
        payload = value
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"


def _gmail_saved_search_feed_setup_text(
    source: schemas.PropertySourceStatus,
    setups: list[schemas.WatchlistSourceSetup],
    feed_config: schemas.PropertyFeedConfig,
) -> str:
    lines = [
        "SKC CRM Gmail Saved-Search Feed Setup",
        "",
        "Purpose:",
        "Use authorized REALM/TRREB saved-search emails as the listing/comparable source before building a formal RESO/OData connector.",
        "This is the preferred short-term method because it avoids scraping MLS pages and keeps the broker/source system as the source of truth.",
        "",
        "Current state:",
        f"- Gmail feed import: {'enabled' if feed_config.gmail_feed_enabled else 'disabled'}",
        f"- Global Gmail query: {feed_config.gmail_query}",
        f"- Max emails per run: {feed_config.gmail_max_results}",
        f"- Last Gmail import: {feed_config.last_import_at or 'never'}",
        f"- Property source rows now loaded: {source.properties_count}",
        f"- Drop folder: {source.csv_drop_folder or 'not configured'}",
        "",
        "Recommended setup flow:",
        "1. In REALM/TRREB, create or update the saved search listed for each client below.",
        "2. Configure that saved search to email new matching results to Kevin's connected Gmail account.",
        "3. In the CRM Watchlists page, use Preview Gmail for one client first; preview must show parsed rows and readiness impact before import.",
        "4. If preview is correct, use Import Gmail + Check for that client, or type READ GMAIL in the CRM feed settings to allow scheduled Gmail feed imports.",
        "5. Keep client delivery review-gated: matches create Codex notifications and Gmail drafts, but do not send unless Kevin reviews or explicitly arms auto-send later.",
        "",
        "Safety:",
        "- Do not scrape MLS/REALM/TRREB pages.",
        "- Do not paste MLS passwords, PINs, SMS codes, cookies, or private session URLs into the CRM.",
        "- Gmail feed import reads listing/source emails only after explicit READ GMAIL authorization; it does not approve alerts or send client email.",
        "- Auto-send still requires both a client-level Auto Send Armed setting and WATCHLIST_AUTO_SEND_ENABLED=true on the backend.",
        "",
        "Per-client saved-search feed setup:",
    ]
    if not setups:
        lines.append("- No active watchlists exist yet.")
    for setup in setups:
        lines.extend(
            [
                "",
                f"{setup.contact_name or setup.watchlist_name}",
                f"- Watchlist: {setup.watchlist_name}",
                f"- Saved search name: {setup.saved_search_name}",
                f"- Required statuses: {', '.join(status.replace('_', ' ') for status in setup.required_statuses)}",
                f"- Gmail query to preview/import: {setup.gmail_query}",
                f"- Current source rows: {setup.current_matching_rows}",
                f"- Missing statuses: {', '.join(status.replace('_', ' ') for status in setup.missing_required_statuses) or 'none'}",
                "- REALM/TRREB criteria:",
                *[f"  - {item}" for item in setup.realm_criteria],
                "- First setup steps:",
                *[f"  {index}. {step}" for index, step in enumerate(setup.realm_steps[:6], start=1)],
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_watchlist_source_kit(db: Session) -> tuple[str, bytes]:
    active = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    source = get_property_source_status(db)
    setups = [_source_setup_for_watchlist(db, row) for row in active]
    source_tasks = get_watchlist_source_tasks(db)
    launch_action_pack = get_watchlist_launch_action_pack(db)
    feed_config = get_property_feed_config(db)
    missing_email_count = sum(1 for task in source_tasks.tasks if task.client_email_needed)
    readme_lines = [
        "SKC CRM Watchlist Source Kit",
        "",
        "Purpose:",
        "Use these files as field guides for authorized REALM/TRREB CSV exports or approved RESO/OData JSON.",
        "Replace TEMPLATE_ONLY rows with real listing, sold, rental, or leased rows before importing.",
        "",
        f"CSV drop folder: {source.csv_drop_folder or 'not configured'}",
        "Automation schedule: 09:00, 15:00, 18:00 America/Toronto when configured on the client watchlist.",
        "",
        "Required import flow:",
        "1. Export authorized rows from REALM/TRREB, saved searches, or approved RESO/OData MLS data.",
        "2. Open source-tasks.csv to see every active client's missing rows and first next action.",
        "3. Open client-email-tasks.csv, fill the client_email column, then save it back into the drop folder or add the email in Watchlists.",
        "4. Use the saved-searches/*.txt file for each client while setting up REALM/TRREB.",
        "5. Match the columns in the relevant CSV template, or replace every placeholder in the RESO/OData JSON template.",
        "6. Put the completed CSV/JSON in the drop folder root, or save it beside the per-client disabled template in source-templates/.",
        "7. Preview before import when possible.",
        "8. Run Check Now or wait for scheduled automation.",
        "9. Review Codex notifications and Gmail drafts before sending unless that client is explicitly armed for auto-send.",
        "",
        f"Missing client emails: {missing_email_count}",
        "",
        "Files in this kit:",
        "- README.txt: this overview.",
        "- source-tasks.csv: one row per active watchlist, including missing statuses and first next action.",
        "- source-tasks.json: structured version of the current source tasks for audit and automation handoff.",
        "- source-status.json: current property source, drop-folder, and RESO/OData connector status.",
        "- launch-action-pack.txt: current launch checklist, preflight status, and client-by-client next actions.",
        "- gmail-saved-search-feed-setup.txt: safer short-term Gmail saved-search source setup; requires explicit READ GMAIL before scheduled imports.",
        "- client-email-tasks.csv: client email gaps that block Gmail Draft or Auto Send delivery; fill client_email and place it in the drop folder root to update CRM contacts.",
        "- saved-searches/*.txt: per-client REALM/TRREB setup instructions and Gmail query.",
        "- skc-watchlist-import-template.csv: generic import template.",
        "- skc-watchlist-source-template-*.csv: client-specific placeholder-safe CSV templates.",
        "- skc-watchlist-source-template-*.json.disabled: client-specific RESO/OData JSON templates; rename/save as .json only after replacing placeholders with authorized data.",
        "",
        "Active watchlists:",
    ]
    if not active:
        readme_lines.append("- No active watchlists exist yet.")
    for setup in setups:
        readme_lines.extend(
            [
                f"- {setup.contact_name or setup.watchlist_name}: {setup.watchlist_name}",
                f"  Type: {setup.watch_type}",
                f"  Saved search name: {setup.saved_search_name}",
                f"  Required statuses: {', '.join(setup.required_statuses)}",
                f"  Required fields: {', '.join(setup.required_fields)}",
                f"  Gmail query: {setup.gmail_query}",
                "  REALM/TRREB criteria:",
                *[f"    - {line}" for line in setup.realm_criteria],
                "  Setup steps:",
                *[f"    {index}. {step}" for index, step in enumerate(setup.realm_steps, start=1)],
            ]
        )

    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", "\n".join(readme_lines) + "\n")
        bundle.writestr("source-tasks.csv", _source_tasks_csv(setups, source.csv_drop_folder))
        bundle.writestr("source-tasks.json", _schema_json_text(source_tasks))
        bundle.writestr("source-status.json", _schema_json_text(source))
        bundle.writestr("launch-action-pack.txt", launch_action_pack.copy_text + "\n")
        bundle.writestr("gmail-saved-search-feed-setup.txt", _gmail_saved_search_feed_setup_text(source, setups, feed_config))
        bundle.writestr("client-email-tasks.csv", _client_email_tasks_csv(source_tasks.tasks))
        for setup in setups:
            setup_filename = f"saved-searches/{setup.watchlist_id}-{_csv_filename_slug(setup.saved_search_name)}.txt"
            bundle.writestr(setup_filename, _source_setup_text(setup))
        bundle.writestr("skc-watchlist-import-template.csv", build_property_csv_template())
        for row in active:
            template = build_watchlist_property_csv_template(db, row.id)
            if template is None:
                continue
            filename, csv_text = template
            bundle.writestr(filename, csv_text)
            json_filename = filename.replace(".csv", ".json.disabled")
            bundle.writestr(json_filename, _watchlist_reso_json_template(row))

    return "skc-watchlist-source-kit.zip", archive.getvalue()


def build_client_email_tasks_csv(db: Session) -> tuple[str, bytes]:
    source_tasks = get_watchlist_source_tasks(db)
    csv_text = _client_email_tasks_csv(source_tasks.tasks)
    return "client-email-tasks.csv", csv_text.encode("utf-8")


def import_properties_csv(db: Session, csv_text: str, dry_run: bool = False) -> schemas.PropertyImportResult:
    if _is_contact_email_task_csv(csv_text):
        return import_contact_email_tasks_csv(db, csv_text, dry_run=dry_run)

    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        return schemas.PropertyImportResult(
            success=False,
            message="CSV has no header row.",
            dry_run=dry_run,
            created=0,
            updated=0,
            skipped=0,
            total_rows=0,
            errors=["missing_header"],
        )

    created = 0
    updated = 0
    unchanged = 0
    skipped = 0
    errors: list[str] = []
    warnings: list[str] = []
    preview_rows: list[dict] = []
    parsed_rows: list[dict] = []
    total_rows = 0
    now = _utcnow()

    for index, row in enumerate(reader, start=2):
        total_rows += 1
        if total_rows > 2000:
            skipped += 1
            errors.append("row_limit_2000_reached")
            break

        if _is_template_placeholder_csv_row(row):
            skipped += 1
            errors.append(f"row_{index}: template placeholder row skipped")
            continue

        street = _street_from_csv_row(row)
        city = _first_nonempty(row, "city", "municipality", "municipality district", "munic", "area municipality", "town", "community name")
        if not street or not city:
            skipped += 1
            errors.append(f"row_{index}: missing street/address or city")
            continue

        status = _normalize_property_status(
            _first_nonempty(row, "status", "listing status", "transaction status", "mls status", "last status", "lst status", "mlsstatus", "status code")
        )
        listing_price = _parse_float(
            _first_nonempty(row, "listing_price", "list price", "list_price", "listprice", "lp_dol", "lp dol", "lp", "l_price", "asking price", "price")
        )
        sold_price = _parse_float(
            _first_nonempty(row, "sold_price", "sold price", "soldprice", "sale price", "saleprice", "close price", "closed price", "sold amount", "sp_dol", "sp")
        )
        monthly_rent = _parse_float(
            _first_nonempty(row, "monthly_rent", "rent", "lease price", "leaseprice", "leased price", "leasedprice", "rental price", "monthly rent", "monthly lease", "lease amount")
        )
        listed_at = _parse_import_date(
            _first_nonempty(row, "listed_at", "list date", "listed date", "listing date", "date listed", "mls date", "input date")
        )
        sold_at = _parse_import_date(
            _first_nonempty(row, "sold_at", "sold date", "sold_date", "sale date", "sale_date", "close date", "closed date", "closing date", "contract date")
        )
        leased_at = _parse_import_date(
            _first_nonempty(row, "leased_at", "leased date", "leased_date", "lease date", "rented date", "rental date")
        )
        row_data = {
            "unit": _first_nonempty(row, "unit", "apt", "suite"),
            "street": street,
            "city": city,
            "province": _first_nonempty(row, "province", "prov") or "ON",
            "postal_code": _first_nonempty(row, "postal_code", "postal code", "zip"),
            "neighborhood": _first_nonempty(row, "neighborhood", "community", "area", "district"),
            "property_type": _normalize_import_property_type(
                _first_nonempty(row, "property_type", "type", "style", "building type", "buildingtype", "type own1 out", "typeown1out", "property style", "class")
            ),
            "status": status,
            "bedrooms": _parse_int(_first_nonempty(row, "bedrooms", "beds", "br", "br_plus", "brplus", "bed rooms", "num bedrooms")),
            "bathrooms": _parse_int(_first_nonempty(row, "bathrooms", "baths", "washrooms", "washroom", "wr", "bath", "num bathrooms")),
            "sqft": _parse_int(_first_nonempty(row, "sqft", "sq ft", "square feet", "approx sqft", "approx square footage")),
            "parking": _parse_int(_first_nonempty(row, "parking", "parking spaces", "garage spaces", "garage", "gar spaces", "garspaces", "parking total", "total parking spaces")),
            "listing_price": listing_price,
            "sold_price": sold_price,
            "monthly_rent": monthly_rent,
            "listed_at": listed_at,
            "sold_at": sold_at,
            "leased_at": leased_at,
            "mls_number": _first_nonempty(row, "mls_number", "mls", "mls#", "mls no", "mls number", "ml num", "ml_num", "mls num", "mlsnumber"),
            "listing_url": _first_nonempty(row, "listing_url", "url", "link", "virtual tour url", "listing link", "public url"),
            "notes": _first_nonempty(row, "notes", "remarks", "description") or "Imported listing row.",
        }
        warnings.extend(_property_import_warnings(row_data, f"row_{index}"))
        parsed_rows.append(row_data)

        existing = _find_existing_import_property(db, row_data)
        if existing:
            changed = _property_import_values_changed(existing, row_data)
            if len(preview_rows) < 25:
                preview_rows.append(_property_import_preview_row(row_data, "update" if changed else "unchanged"))
            if changed and not dry_run:
                for key, value in row_data.items():
                    setattr(existing, key, value)
                existing.updated_at = now
            if changed:
                updated += 1
            else:
                unchanged += 1
        else:
            if len(preview_rows) < 25:
                preview_rows.append(_property_import_preview_row(row_data, "create"))
            if not dry_run:
                db.add(models.Property(**row_data))
            created += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()
    action = "Previewed" if dry_run else "Imported"
    message = f"{action} {created} new and {updated} updated property row(s)."
    if unchanged:
        message += f" {unchanged} unchanged row(s) were ignored."
    return schemas.PropertyImportResult(
        success=not errors or created > 0 or updated > 0 or unchanged > 0,
        message=message,
        dry_run=dry_run,
        created=created,
        updated=updated,
        unchanged=unchanged,
        skipped=skipped,
        total_rows=total_rows,
        errors=errors[:20],
        warnings=warnings[:50],
        preview_rows=preview_rows,
        watchlist_match_preview=_build_watchlist_match_preview(db, parsed_rows) if dry_run else [],
        watchlist_readiness_preview=_build_watchlist_readiness_preview(db, parsed_rows) if dry_run else [],
    )


RESO_IMPORT_COLUMNS = [
    "mls_number",
    "unit",
    "street",
    "city",
    "province",
    "postal_code",
    "community",
    "status",
    "property_type",
    "list price",
    "sold price",
    "rent",
    "list date",
    "sold date",
    "leased date",
    "beds",
    "baths",
    "sqft",
    "parking",
    "url",
    "remarks",
]


def _nonempty_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _source_value(row: dict, *keys: str):
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    normalized = {_normalize_csv_key(key): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = lowered.get(str(key).strip().lower())
        if value is None:
            value = normalized.get(_normalize_csv_key(key))
        value = _nonempty_value(value)
        if value is not None:
            return value
    return None


def _source_text(row: dict, *keys: str) -> str | None:
    value = _source_value(row, *keys)
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    return str(value).strip() or None


def _source_number(row: dict, *keys: str) -> float | None:
    value = _source_value(row, *keys)
    return _parse_float(value)


def _source_int(row: dict, *keys: str) -> int | None:
    value = _source_value(row, *keys)
    return _parse_int(value)


def _reso_json_records(data) -> tuple[list[dict], list[str]]:
    payload = data
    errors: list[str] = []
    if isinstance(payload, str):
        if not payload.strip():
            return [], ["reso_json_empty"]
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return [], [f"invalid_reso_json: {exc.msg}"]

    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            raw_records = payload["value"]
        elif isinstance(payload.get("data"), list):
            raw_records = payload["data"]
        elif isinstance(payload.get("properties"), list):
            raw_records = payload["properties"]
        elif isinstance(payload.get("results"), list):
            raw_records = payload["results"]
        elif isinstance(payload.get("d"), dict) and isinstance(payload["d"].get("results"), list):
            raw_records = payload["d"]["results"]
        else:
            raw_records = []
            errors.append("reso_json_missing_records_array")
    else:
        raw_records = []
        errors.append("reso_json_must_be_array_or_object")

    records: list[dict] = []
    for index, record in enumerate(raw_records, start=1):
        if isinstance(record, dict):
            records.append(record)
        else:
            errors.append(f"reso_record_{index}: record is not an object")
    return records, errors


def _reso_split_unparsed_address(value: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    if not value:
        return None, None, None, None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    street = parts[0] if parts else value.strip()
    city = parts[1] if len(parts) > 1 else None
    province = None
    postal_code = None
    if len(parts) > 2:
        province_match = re.match(r"^([A-Za-z]{2})\b\s*(.*)$", parts[2])
        if province_match:
            province = province_match.group(1).upper()
            postal_code = province_match.group(2).strip() or None
        else:
            province = parts[2]
    if len(parts) > 3 and not postal_code:
        postal_code = parts[3]
    return street, city, province, postal_code


def _reso_address_parts(record: dict) -> tuple[str | None, str | None, str | None, str | None]:
    unparsed = _source_text(
        record,
        "UnparsedAddress",
        "FullAddress",
        "Address",
        "StreetAddress",
        "PropertyAddress",
    )
    parsed_street, parsed_city, parsed_province, parsed_postal = _reso_split_unparsed_address(unparsed)
    street = parsed_street
    if not street:
        parts = [
            _source_text(record, "StreetNumber", "StreetNumberNumeric"),
            _source_text(record, "StreetDirPrefix"),
            _source_text(record, "StreetName"),
            _source_text(record, "StreetSuffix", "StreetType"),
            _source_text(record, "StreetDirSuffix"),
        ]
        street = " ".join(part for part in parts if part) or None

    city = _source_text(record, "City", "Municipality", "CityRegion", "CountyOrParish") or parsed_city
    province = _source_text(record, "StateOrProvince", "Province", "State") or parsed_province or "ON"
    postal = _source_text(record, "PostalCode", "Postal Code", "Zip", "ZipCode") or parsed_postal
    return street, city, province, postal


def _reso_status_label(record: dict) -> str:
    status = " ".join(
        text for text in [
            _source_text(record, "StandardStatus", "MlsStatus", "MLSStatus", "Status"),
            _source_text(record, "CloseStatus", "ContractStatus", "LastStatus"),
        ]
        if text
    ).lower()
    transaction = " ".join(
        text for text in [
            _source_text(record, "TransactionType", "ListingType", "LeaseConsideredYN", "PropertyClass"),
            _source_text(record, "PropertySubType", "PropertyType"),
        ]
        if text
    ).lower()
    lease_like = bool(re.search(r"\b(lease|leased|rent|rental)\b", f"{status} {transaction}"))

    if re.search(r"\b(leased|rented)\b", status):
        return "Leased"
    if re.search(r"\b(sold|closed)\b", status):
        return "Leased" if lease_like else "Sold"
    if lease_like:
        return "For Rent"
    if re.search(r"\b(active|available|new|coming soon)\b", status):
        return "For Sale"
    if status:
        return status.title()
    return "For Sale"


def _reso_listing_url(record: dict) -> str | None:
    direct = _source_text(
        record,
        "ListingURL",
        "ListingUrl",
        "URL",
        "Url",
        "VirtualTourURLUnbranded",
        "VirtualTourURLBranded",
        "VirtualTourUrlUnbranded",
        "VirtualTourUrlBranded",
    )
    if direct:
        return direct
    media = _source_value(record, "Media")
    if isinstance(media, list):
        for item in media:
            if not isinstance(item, dict):
                continue
            url = _source_text(item, "MediaURL", "MediaUrl", "URL", "Url")
            if url:
                return url
    return None


def _reso_row_to_csv_row(record: dict) -> dict[str, object | None]:
    street, city, province, postal_code = _reso_address_parts(record)
    status = _reso_status_label(record)
    rent = _source_number(
        record,
        "LeaseAmount",
        "LeaseAmountFrequency",
        "MonthlyRent",
        "Rent",
        "RentalPrice",
        "LeasePrice",
    )
    if rent is None and status in {"For Rent", "Leased"}:
        rent = _source_number(record, "ClosePrice", "ListPrice", "CurrentPrice", "OriginalListPrice")

    close_price = _source_number(
        record,
        "ClosePrice",
        "SoldPrice",
        "PurchaseContractPrice",
        "SalePrice",
        "ClosePriceAmount",
    )
    list_price = _source_number(record, "ListPrice", "CurrentPrice", "OriginalListPrice", "ListPriceLow")
    sold_price = None if status == "Leased" else close_price

    remarks = _source_text(record, "PublicRemarks", "PublicRemarksExtras", "Remarks", "Description")
    if not remarks:
        mls_number = _source_text(record, "ListingKey", "ListingId", "MlsNumber", "MLSNumber")
        remarks = f"Imported from RESO/MLS JSON{f' for {mls_number}' if mls_number else ''}."

    return {
        "mls_number": _source_text(record, "ListingKey", "ListingId", "MlsNumber", "MLSNumber", "MLS", "MlNum"),
        "unit": _source_text(record, "UnitNumber", "ApartmentNumber", "Suite", "AptUnit"),
        "street": street,
        "city": city,
        "province": province,
        "postal_code": postal_code,
        "community": _source_text(record, "CityRegion", "Community", "SubdivisionName", "Neighborhood", "Neighbourhood") or city,
        "status": status,
        "property_type": _source_text(record, "PropertySubType", "PropertyType", "PropertyTypeLabel", "StructureType", "ArchitecturalStyle"),
        "list price": list_price if status not in {"For Rent", "Leased"} else None,
        "sold price": sold_price,
        "rent": rent,
        "list date": _source_text(record, "ListingContractDate", "OnMarketDate", "OriginalEntryTimestamp", "ModificationTimestamp"),
        "sold date": _source_text(record, "CloseDate", "PurchaseContractDate", "SoldDate") if status == "Sold" else None,
        "leased date": _source_text(record, "CloseDate", "LeasedDate", "LeaseDate", "RentedDate") if status == "Leased" else None,
        "beds": _source_int(record, "BedroomsTotal", "BedroomsAboveGrade", "Bedrooms", "Beds"),
        "baths": _source_int(record, "BathroomsTotalInteger", "BathroomsTotal", "BathroomsFull", "Bathrooms", "Baths"),
        "sqft": _source_int(record, "LivingArea", "BuildingAreaTotal", "AboveGradeFinishedArea", "SquareFeet"),
        "parking": _source_int(record, "ParkingTotal", "ParkingSpaces", "GarageParkingSpaces", "CoveredSpaces", "GarageSpaces"),
        "url": _reso_listing_url(record),
        "remarks": remarks,
    }


def import_properties_reso_json(db: Session, data, dry_run: bool = True) -> schemas.PropertyImportResult:
    records, record_errors = _reso_json_records(data)
    if not records:
        return schemas.PropertyImportResult(
            success=False,
            message="RESO/MLS JSON did not contain any property records.",
            dry_run=dry_run,
            created=0,
            updated=0,
            unchanged=0,
            skipped=0,
            total_rows=0,
            errors=(record_errors or ["missing_records"])[:20],
        )

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=RESO_IMPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow(_reso_row_to_csv_row(record))

    result = import_properties_csv(db, output.getvalue(), dry_run=dry_run)
    result.errors = (record_errors + list(result.errors or []))[:20]
    action = "Previewed" if dry_run else "Imported"
    result.message = f"{action} {result.created} new and {result.updated} updated property row(s) from RESO/MLS JSON."
    if result.unchanged:
        result.message += f" {result.unchanged} unchanged row(s) were ignored."
    return result


_MLS_NUMBER_RE = re.compile(r"(?<![A-Z0-9/])([A-Z]\d{6,8})(?![A-Z0-9])", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\")]+", re.IGNORECASE)
_MONEY_RE = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?\s*[mk]?"
    r"|\b\d+(?:\.\d+)?\s*[mk]\b"
    r"|\b\d{3,}(?:,\d{3})+(?:\.\d+)?\b",
    re.IGNORECASE,
)
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9' .-]+?\s+"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Circle|Crescent|Cres|Court|Ct|Crt|Lane|"
    r"Trail|Way|Gate|Gardens|Garden|Gdns|Grove|Grv|Heights|Hts|Mews|Square|Sq|"
    r"Boulevard|Blvd|Place|Pl|Terrace|Terr|Line|Path|Parkway|Pkwy)\b(?:[^\n]*)",
    re.IGNORECASE,
)


def _clean_feed_text(text: str | None) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"</p>|</div>|</li>|</tr>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _feed_labeled_value(block: str, *labels: str) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    pattern = rf"(?im)^\s*(?:{label_pattern})\s*(?:#|:|-)?\s*(.+?)\s*$"
    match = re.search(pattern, block)
    if not match:
        return None
    value = re.split(r"\s{2,}|\|", match.group(1), maxsplit=1)[0].strip(" -:")
    return value or None


def _feed_money_after(block: str, *labels: str) -> float | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?i)(?:{label_pattern})\s*(?:#|:|-)?\s*({_MONEY_RE.pattern})", block)
    return _parse_float(match.group(1)) if match else None


def _feed_int_after(block: str, *labels: str) -> int | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?i)(?:{label_pattern})\s*(?:#|:|-)?\s*(\d+)", block)
    return _parse_int(match.group(1)) if match else None


def _feed_date_after(block: str, *labels: str) -> datetime | None:
    return _parse_import_date(_feed_labeled_value(block, *labels))


def _feed_status(block: str) -> str:
    labeled = _feed_labeled_value(
        block,
        "status",
        "listing status",
        "transaction status",
        "last status",
        "lst status",
        "mls status",
        "mlsstatus",
        "status code",
    )
    if labeled:
        return _normalize_property_status(labeled)
    lowered = block.lower()
    if re.search(r"\bsold\b|sold price|sale price", lowered):
        return "sold"
    if re.search(r"\bleased\b|\brented\b|leased price", lowered):
        return "rented"
    if re.search(r"for rent|for lease|lease price|monthly rent", lowered):
        return "listed_for_rent"
    return "listed_for_sale"


def _feed_property_type(block: str) -> str:
    labeled = _feed_labeled_value(
        block,
        "property type",
        "type",
        "style",
        "building type",
        "type own1 out",
        "typeown1out",
        "property style",
        "class",
    )
    if labeled:
        return _normalize_import_property_type(labeled)
    lowered = block.lower()
    type_aliases = [
        ("semi-detached", "semi-detached"),
        ("semi detached", "semi-detached"),
        ("townhouse", "townhouse"),
        ("townhome", "townhouse"),
        ("freehold townhouse", "townhouse"),
        ("detached", "detached"),
        ("condo townhouse", "townhouse"),
        ("condo", "condo"),
        ("apartment", "condo"),
    ]
    for needle, value in type_aliases:
        if needle in lowered:
            return value
    return "unknown"


def _feed_address_parts(block: str) -> tuple[str | None, str | None, str | None]:
    address = _feed_labeled_value(
        block,
        "address",
        "addr",
        "address1",
        "address line 1",
        "full address",
        "street address",
        "property address",
        "listing address",
        "prop address",
    )
    city = _feed_labeled_value(
        block,
        "city",
        "municipality",
        "municipality district",
        "munic",
        "area municipality",
        "town",
        "community name",
    )
    neighborhood = _feed_labeled_value(block, "community", "neighborhood", "area", "district")
    if not address:
        match = _STREET_RE.search(block)
        address = match.group(0).strip(" -|") if match else None

    if address:
        address = re.sub(_MLS_NUMBER_RE, "", address).strip(" -|")
        address = re.sub(_URL_RE, "", address).strip(" -|")
        address = _MONEY_RE.sub("", address).strip(" -|")
        if "," in address:
            street_part, rest = address.split(",", 1)
            address = street_part.strip()
            if not city:
                city = re.split(r"\s+-\s+|\s+\|\s+", rest.strip(), maxsplit=1)[0].strip()
        else:
            address = re.split(r"\s+-\s+|\s+\|\s+", address, maxsplit=1)[0].strip()

    if city:
        city = re.split(r"\s+-\s+|\s+\|\s+|,", city, maxsplit=1)[0].strip()
    if neighborhood:
        neighborhood = re.split(r"\s+-\s+|\s+\|\s+|,", neighborhood, maxsplit=1)[0].strip()
    return address or None, city or None, neighborhood or city


def _split_property_feed_blocks(text: str) -> list[str]:
    cleaned = _clean_feed_text(text)
    if not cleaned:
        return []

    matches = list(_MLS_NUMBER_RE.finditer(cleaned))
    if len(matches) > 1:
        blocks: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
            block = cleaned[match.start():end].strip()
            if block:
                blocks.append(block)
        return blocks

    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", cleaned) if chunk.strip()]
    blocks = [
        chunk for chunk in chunks
        if _MLS_NUMBER_RE.search(chunk) or _STREET_RE.search(chunk) or _MONEY_RE.search(chunk)
    ]
    return blocks or [cleaned]


def _property_rows_from_feed_text(text: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    errors: list[str] = []
    for index, block in enumerate(_split_property_feed_blocks(text), start=1):
        street, city, neighborhood = _feed_address_parts(block)
        if not street or not city:
            errors.append(f"feed_block_{index}: missing street/address or city")
            continue

        status = _feed_status(block)
        mls_match = _MLS_NUMBER_RE.search(block)
        url_match = _URL_RE.search(block)
        listing_price = _feed_money_after(
            block,
            "list price",
            "listing price",
            "listprice",
            "lp_dol",
            "lp dol",
            "lp",
            "asking price",
            "price",
        )
        sold_price = _feed_money_after(
            block,
            "sold price",
            "soldprice",
            "sale price",
            "saleprice",
            "close price",
            "closed price",
            "sp_dol",
            "sp dol",
            "sp",
        )
        monthly_rent = _feed_money_after(
            block,
            "rent",
            "monthly rent",
            "monthly lease",
            "lease price",
            "leaseprice",
            "leased price",
            "leasedprice",
            "lease amount",
            "rental price",
        )
        listed_at = _feed_date_after(block, "list date", "listed date", "listing date", "date listed", "mls date", "input date")
        sold_at = _feed_date_after(block, "sold date", "sale date", "close date", "closed date", "closing date", "contract date")
        leased_at = _feed_date_after(block, "leased date", "lease date", "rented date", "rental date")

        if listing_price is None and sold_price is None and monthly_rent is None:
            prices = [_parse_float(item) for item in _MONEY_RE.findall(block)]
            prices = [price for price in prices if price is not None]
            if prices:
                if status == "sold":
                    sold_price = prices[-1]
                    listing_price = prices[0] if len(prices) > 1 else None
                elif status in {"rented", "listed_for_rent"}:
                    monthly_rent = prices[-1]
                else:
                    listing_price = prices[0]

        row_data = {
            "unit": _feed_labeled_value(block, "unit", "apt", "suite"),
            "street": street,
            "city": city,
            "province": _feed_labeled_value(block, "province", "prov") or "ON",
            "postal_code": _feed_labeled_value(block, "postal code", "postal_code", "zip"),
            "neighborhood": neighborhood,
            "property_type": _feed_property_type(block),
            "status": status,
            "bedrooms": _feed_int_after(block, "bedrooms", "beds", "br", "br_plus", "bed"),
            "bathrooms": _feed_int_after(block, "bathrooms", "baths", "washrooms", "washroom", "wr", "bath"),
            "sqft": _feed_int_after(block, "sqft", "square feet", "approx sqft"),
            "parking": _feed_int_after(
                block,
                "parking",
                "parking spaces",
                "parking total",
                "total parking spaces",
                "garage spaces",
                "gar spaces",
                "garspaces",
                "garage",
            ),
            "listing_price": listing_price,
            "sold_price": sold_price,
            "monthly_rent": monthly_rent,
            "listed_at": listed_at,
            "sold_at": sold_at,
            "leased_at": leased_at,
            "mls_number": mls_match.group(0).upper() if mls_match else None,
            "listing_url": url_match.group(0) if url_match else None,
            "notes": f"Imported from listing feed. Raw excerpt: {block[:900]}",
        }
        rows.append(row_data)
    return rows, errors


def import_properties_feed_text(db: Session, text: str, dry_run: bool = True) -> schemas.PropertyImportResult:
    rows, errors = _property_rows_from_feed_text(text)
    created = 0
    updated = 0
    skipped = 0
    warnings: list[str] = []
    preview_rows: list[dict] = []
    now = _utcnow()

    for index, row_data in enumerate(rows, start=1):
        warnings.extend(_property_import_warnings(row_data, f"feed_block_{index}"))
        existing = _find_existing_import_property(db, row_data)
        if existing:
            if len(preview_rows) < 25:
                preview_rows.append(_property_import_preview_row(row_data, "update"))
            if not dry_run:
                for key, value in row_data.items():
                    setattr(existing, key, value)
                existing.updated_at = now
            updated += 1
        else:
            if len(preview_rows) < 25:
                preview_rows.append(_property_import_preview_row(row_data, "create"))
            if not dry_run:
                db.add(models.Property(**row_data))
            created += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    skipped += len(errors)
    action = "Previewed" if dry_run else "Imported"
    return schemas.PropertyImportResult(
        success=bool(rows) and (not errors or created > 0 or updated > 0),
        message=f"{action} {created} new and {updated} updated property row(s) from listing feed.",
        dry_run=dry_run,
        created=created,
        updated=updated,
        skipped=skipped,
        total_rows=len(rows) + len(errors),
        errors=errors[:20],
        warnings=warnings[:50],
        preview_rows=preview_rows,
        watchlist_match_preview=_build_watchlist_match_preview(db, rows) if dry_run else [],
        watchlist_readiness_preview=_build_watchlist_readiness_preview(db, rows) if dry_run else [],
    )


# --- Client Watchlists / Listing Alerts ---
WATCHLIST_REVIEW_MODES = {
    "manual_review",
    "auto_create_draft",
    "auto_gmail_draft",
    "auto_send_approved",
}
WATCHLIST_STATUSES = {"active", "paused"}
WATCHLIST_TYPES = {
    "buyer_listing_match",
    "seller_listing_and_sold",
    "tenant_rental_match",
    "landlord_rental_market",
}
WATCHLIST_NOTIFICATION_CHANNELS = {"codex_app", "app_push", "in_app"}
AUTO_SEND_CONFIRMATION_VALUES = {"auto send", "auto approve", "直接寄出", "自動寄出", "自动寄出"}
GMAIL_FEED_CONFIRMATION_VALUES = {"read gmail", "enable gmail feed", "啟用gmail", "启用gmail", "讀gmail", "读gmail"}


def _auto_send_confirmation_valid(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in AUTO_SEND_CONFIRMATION_VALUES


def _gmail_feed_confirmation_valid(value: str | None) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return normalized in GMAIL_FEED_CONFIRMATION_VALUES


def _json_dumps(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_object(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_watchlist_review_mode(value: str | None) -> str:
    review_mode = (value or "auto_gmail_draft").strip()
    return review_mode if review_mode in WATCHLIST_REVIEW_MODES else "auto_gmail_draft"


def _normalize_watchlist_status(value: str | None) -> str:
    status = (value or "active").strip()
    return status if status in WATCHLIST_STATUSES else "active"


def _normalize_watchlist_notification_channel(value: str | None) -> str:
    channel = str(value or "").strip()
    if not channel:
        return "codex_app"
    if channel not in WATCHLIST_NOTIFICATION_CHANNELS:
        raise ValueError("invalid_notification_channel")
    return channel


def _watchlist_notification_channel_or_default(value: str | None) -> str:
    try:
        return _normalize_watchlist_notification_channel(value)
    except ValueError:
        return "codex_app"


def _clean_source_query(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_watch_type(value: str | None, contact: models.Contact | None = None) -> str:
    if value in WATCHLIST_TYPES:
        return value

    client_type = (contact.client_type if contact else "") or ""
    if "seller" in client_type:
        return "seller_listing_and_sold"
    if "landlord" in client_type:
        return "landlord_rental_market"
    if "tenant" in client_type:
        return "tenant_rental_match"
    return "buyer_listing_match"


def _parse_schedule(raw: str | dict | None) -> dict:
    schedule = raw if isinstance(raw, dict) else _json_object(raw if isinstance(raw, str) else None)
    times = schedule.get("times")
    if isinstance(times, str):
        times = [times]
    if not isinstance(times, list):
        times = ["09:00"]

    cleaned_times = []
    for item in times:
        text = str(item).strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            hour, minute = [int(part) for part in text.split(":", 1)]
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                cleaned_times.append(f"{hour:02d}:{minute:02d}")

    timezone = str(schedule.get("timezone") or "America/Toronto").strip()
    try:
        ZoneInfo(timezone)
    except Exception:
        timezone = "America/Toronto"
    return {
        "times": sorted(set(cleaned_times)) or ["09:00"],
        "timezone": timezone or "America/Toronto",
    }


def _next_scheduled_check(schedule: dict | str | None, after: datetime | None = None) -> datetime:
    schedule_data = _parse_schedule(schedule)
    after_utc = after or _utcnow()

    try:
        zone = ZoneInfo(schedule_data["timezone"])
    except Exception:
        zone = ZoneInfo("America/Toronto")

    local_after = after_utc.replace(tzinfo=UTC).astimezone(zone)
    candidates = []
    for day_offset in range(0, 8):
        candidate_date = local_after.date() + timedelta(days=day_offset)
        for text in schedule_data["times"]:
            hour, minute = [int(part) for part in text.split(":", 1)]
            candidate = datetime.combine(candidate_date, time(hour=hour, minute=minute), tzinfo=zone)
            if candidate > local_after + timedelta(minutes=1):
                candidates.append(candidate)

    next_local = min(candidates) if candidates else local_after + timedelta(days=1)
    return next_local.astimezone(UTC).replace(tzinfo=None)


def _watchlist_match_coverage(db: Session | None, row: models.ClientWatchlist) -> dict:
    required_statuses = sorted(_watchlist_statuses(row.watch_type))
    status_counts = {status: 0 for status in required_statuses}
    matches: list[models.Property] = []
    if db is not None:
        matches = _matching_properties_for_watchlist(db, row)
        for prop in matches:
            if prop.status in status_counts:
                status_counts[prop.status] += 1

    missing_statuses = [
        status
        for status in required_statuses
        if status_counts.get(status, 0) == 0
    ]
    return {
        "matches": matches,
        "matching_source_rows": len(matches),
        "required_statuses": required_statuses,
        "matching_status_counts": status_counts,
        "missing_required_statuses": missing_statuses,
    }


def _watchlist_readiness(db: Session | None, row: models.ClientWatchlist) -> dict:
    criteria = _json_object(row.criteria_json)
    data_source = row.data_source or "internal_properties"
    notification_channel = _watchlist_notification_channel_or_default(row.notification_channel)
    coverage = _watchlist_match_coverage(db, row)
    required_statuses = list(coverage["required_statuses"])
    matching_status_counts = dict(coverage["matching_status_counts"])
    missing_required_statuses = list(coverage["missing_required_statuses"])
    matching_source_rows = int(coverage["matching_source_rows"])
    issues: list[str] = []
    next_steps: list[str] = []
    delivery_issues: list[str] = []
    push_subscriptions = 0

    if db is not None:
        push_subscriptions = db.query(func.count(models.PushSubscription.id)).scalar() or 0

    if data_source != "internal_properties":
        issues.append("External MLS connector is not connected in this local CRM yet.")
        next_steps.append("Use CSV, pasted feed, or Gmail saved-search feed until the MLS adapter is approved.")
    elif matching_source_rows == 0:
        issues.append("No matching property rows exist for the statuses this watchlist needs.")
        next_steps.append("Import matching REALM/TRREB listing, sold, rental, or leased rows.")
    elif missing_required_statuses:
        missing_text = ", ".join(status.replace("_", " ") for status in missing_required_statuses)
        issues.append(f"Missing matching source rows for required statuses: {missing_text}.")
        next_steps.append(f"Import matching REALM/TRREB rows for: {missing_text}.")

    has_targeting = any(
        criteria.get(key)
        for key in ["areas", "types", "property_address", "max_price", "min_price"]
    )
    if not has_targeting:
        issues.append("Criteria are too broad for client-safe automated matching.")
        next_steps.append("Add at least an area, property type, address, or price range.")

    if notification_channel == "app_push" and push_subscriptions == 0:
        issues.append("No browser/app push subscription is saved.")
        next_steps.append("Enable Notifications in the CRM from the device that should receive alerts.")

    needs_gmail_recipient = row.review_mode in {"auto_gmail_draft", "auto_send_approved"}
    has_contact_email = bool(row.contact and str(row.contact.email or "").strip())
    if needs_gmail_recipient and not has_contact_email:
        delivery_issues.append("Contact email is missing; Gmail drafts cannot be addressed to the client.")
        issues.extend(delivery_issues)
        next_steps.append("Fill client_email in client-email-tasks.csv and place it in the drop folder, or add the client's email in Watchlists before relying on Auto Gmail Draft or Auto Send.")

    if row.review_mode == "auto_send_approved" and not _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED"):
        issues.append("Auto Send is armed on this watchlist, but server sending is still disabled.")
        next_steps.append("Keep Gmail drafts for review, or explicitly enable WATCHLIST_AUTO_SEND_ENABLED=true later.")

    source_ready = (
        data_source == "internal_properties"
        and matching_source_rows > 0
        and not missing_required_statuses
    )
    criteria_ready = has_targeting
    notification_ready = notification_channel != "app_push" or push_subscriptions > 0
    recipient_ready = not needs_gmail_recipient or has_contact_email
    review_ready = (
        recipient_ready
        and (row.review_mode != "auto_send_approved" or _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED"))
    )
    if not source_ready or not criteria_ready:
        severity = "blocked"
    elif not notification_ready or not review_ready:
        severity = "warning"
    else:
        severity = "ready"

    return {
        "ready": severity == "ready",
        "severity": severity,
        "issues": issues,
        "next_steps": next_steps,
        "required_statuses": required_statuses,
        "matching_source_rows": matching_source_rows,
        "matching_status_counts": matching_status_counts,
        "missing_required_statuses": missing_required_statuses,
        "push_subscriptions": push_subscriptions,
        "notification_channel": notification_channel,
        "data_source": data_source,
        "contact_email_present": has_contact_email,
        "delivery_ready": recipient_ready,
        "delivery_issues": delivery_issues,
    }


def _gmail_query_term(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return None
    text = text.replace('"', "")
    if " " in text:
        return f'"{text}"'
    return text


def _default_source_query_for_watchlist(watch_type: str, criteria: dict) -> str:
    base_terms = ["REALM", "TRREB", "MLS", "listing"]
    if watch_type == "seller_listing_and_sold":
        intent_terms = ["sold", "sale", "active"]
    elif watch_type == "tenant_rental_match":
        intent_terms = ["rent", "lease", "available"]
    elif watch_type == "landlord_rental_market":
        intent_terms = ["rent", "lease", "leased", "rented"]
    else:
        intent_terms = ["sale", "active", "new"]

    location_terms = [
        term for term in (
            _gmail_query_term(item)
            for item in _coerce_string_list(criteria.get("areas"))
        )
        if term
    ]
    if criteria.get("property_address"):
        address_term = _gmail_query_term(str(criteria.get("property_address")))
        if address_term:
            location_terms.insert(0, address_term)

    type_terms = [
        term for term in (
            _gmail_query_term(_normalize_property_type(item) or str(item))
            for item in _coerce_string_list(criteria.get("types"))
        )
        if term and term != "unknown"
    ]

    parts = [
        "newer_than:14d",
        f"({' OR '.join(base_terms)})",
        f"({' OR '.join(intent_terms)})",
    ]
    if location_terms:
        parts.append(f"({' OR '.join(location_terms[:6])})")
    if type_terms:
        parts.append(f"({' OR '.join(type_terms[:4])})")
    return " ".join(parts)


def _watchlist_source_query(row: models.ClientWatchlist) -> str:
    custom_query = str(row.source_query or "").strip()
    if custom_query:
        return custom_query
    return _default_source_query_for_watchlist(row.watch_type, _json_object(row.criteria_json))


def _watchlist_schema(row: models.ClientWatchlist, db: Session | None = None) -> schemas.ClientWatchlist:
    return schemas.ClientWatchlist(
        id=row.id,
        contact_id=row.contact_id,
        contact_name=row.contact.name if row.contact else None,
        name=row.name,
        watch_type=row.watch_type,
        status=row.status,
        criteria=_json_object(row.criteria_json),
        schedule=_parse_schedule(row.schedule_json),
        notification_channel=_watchlist_notification_channel_or_default(row.notification_channel),
        review_mode=row.review_mode or "manual_review",
        data_source=row.data_source or "internal_properties",
        source_query=_watchlist_source_query(row),
        readiness=_watchlist_readiness(db, row),
        last_checked_at=row.last_checked_at,
        next_check_at=row.next_check_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _required_fields_for_watchlist(watch_type: str) -> list[str]:
    if watch_type in {"tenant_rental_match", "landlord_rental_market"}:
        return ["street", "city", "status", "property_type", "monthly_rent", "bedrooms", "bathrooms", "parking"]
    if watch_type == "seller_listing_and_sold":
        return ["street", "city", "status", "property_type", "listing_price", "sold_price", "bedrooms", "bathrooms", "parking"]
    return ["street", "city", "status", "property_type", "listing_price", "bedrooms", "bathrooms", "parking"]


def _watchlist_saved_search_name(row: models.ClientWatchlist) -> str:
    contact_name = row.contact.name if row.contact else row.name
    label = {
        "buyer_listing_match": "Buyer Active Listings",
        "seller_listing_and_sold": "Seller Active + Sold Comps",
        "tenant_rental_match": "Tenant Rental Listings",
        "landlord_rental_market": "Landlord Rental + Leased Comps",
    }.get(row.watch_type, "Listing Watch")
    return f"SKC {contact_name} - {label}"


def _criteria_number(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _watchlist_realm_criteria(row: models.ClientWatchlist) -> list[str]:
    criteria = _json_object(row.criteria_json)
    areas = _coerce_string_list(criteria.get("areas"))
    types = _coerce_string_list(criteria.get("types"))
    must_haves = _coerce_string_list(criteria.get("must_haves"))
    deal_breakers = _coerce_string_list(criteria.get("deal_breakers"))
    required_statuses = sorted(_watchlist_statuses(row.watch_type))
    lines: list[str] = []

    if areas:
        lines.append(f"Area/community/city: {', '.join(areas)}")
    if criteria.get("property_address"):
        lines.append(f"Subject/reference address: {criteria.get('property_address')}")
    if types:
        normalized_types = [_normalize_property_type(item) or item for item in types]
        lines.append(f"Property type: {', '.join(normalized_types)}")
    if required_statuses:
        lines.append(f"Export status rows: {', '.join(status.replace('_', ' ') for status in required_statuses)}")

    max_price = _criteria_number(criteria.get("max_price"))
    min_price = _criteria_number(criteria.get("min_price"))
    max_rent = _criteria_number(criteria.get("max_rent") or criteria.get("monthly_rent"))
    if row.watch_type in {"buyer_listing_match", "seller_listing_and_sold"}:
        if min_price and max_price:
            lines.append(f"Price range: ${min_price} to ${max_price}")
        elif max_price:
            lines.append(f"Maximum list price: ${max_price}")
    elif max_rent:
        lines.append(f"Maximum monthly rent: ${max_rent}")

    bedrooms = _criteria_number(criteria.get("bedrooms_min"))
    bathrooms = _criteria_number(criteria.get("bathrooms_min"))
    parking = _criteria_number(criteria.get("parking_min"))
    if bedrooms:
        lines.append(f"Bedrooms: at least {bedrooms}")
    if bathrooms:
        lines.append(f"Bathrooms: at least {bathrooms}")
    if parking:
        lines.append(f"Parking/garage: at least {parking}")
    if must_haves:
        lines.append(f"Must-haves: {', '.join(must_haves)}")
    if deal_breakers:
        lines.append(f"Exclude/deal-breakers: {', '.join(deal_breakers)}")

    return lines or ["Use the saved CRM criteria for this client and export authorized matching rows."]


def _watchlist_realm_steps(row: models.ClientWatchlist, query: str) -> list[str]:
    saved_search_name = _watchlist_saved_search_name(row)
    statuses = sorted(_watchlist_statuses(row.watch_type))
    status_text = ", ".join(status.replace("_", " ") for status in statuses)
    steps = [
        f"Create or update a REALM/TRREB saved search named: {saved_search_name}.",
        "Apply the criteria below in REALM/TRREB, then review the result count before exporting.",
        f"Export authorized rows for: {status_text}.",
        "Use CSV/Excel export columns that include address, community/city, status, property type, price/rent, beds, baths, parking, MLS number, URL, and remarks.",
        "Drop the CSV into the CRM watchlist-imports folder or upload it in Watchlists, then run Preview before Import.",
        f"If using saved-search email import, preview with this Gmail query first: {query}",
    ]
    if row.review_mode == "auto_send_approved":
        steps.append("Auto Send is a delivery setting only; source rows still need preview/import and server auto-send must remain explicitly enabled.")
    else:
        steps.append("Matches should create Codex notifications and reviewable Gmail drafts; do not send automatically.")
    return steps


def _source_setup_for_watchlist(db: Session, row: models.ClientWatchlist) -> schemas.WatchlistSourceSetup:
    coverage = _watchlist_match_coverage(db, row)
    required_statuses = list(coverage["required_statuses"])
    current_matching_rows = int(coverage["matching_source_rows"])
    matching_status_counts = dict(coverage["matching_status_counts"])
    missing_required_statuses = list(coverage["missing_required_statuses"])
    if current_matching_rows > 0 and not missing_required_statuses:
        readiness = "ready"
    elif current_matching_rows > 0:
        readiness = "missing_statuses"
    else:
        readiness = "missing_rows"
    contact_name = row.contact.name if row.contact else None
    query = _watchlist_source_query(row)
    watch_label = {
        "buyer_listing_match": "buyer listing matches",
        "seller_listing_and_sold": "seller listings and sold comps",
        "tenant_rental_match": "tenant rental matches",
        "landlord_rental_market": "landlord rental market comps",
    }.get(row.watch_type, "listing matches")
    saved_search_name = _watchlist_saved_search_name(row)
    realm_criteria = _watchlist_realm_criteria(row)
    realm_steps = _watchlist_realm_steps(row, query)
    next_actions = [
        f"Create or confirm a REALM/TRREB saved search named {saved_search_name} covering {watch_label}.",
        f"Use this Gmail query to preview saved-search emails before importing: {query}",
        "If using CSV, include the required fields shown here and run Preview CSV before Import CSV.",
        "After import, run Check Now; the CRM will create reviewable alerts and draft recommendations without sending email.",
    ]
    return schemas.WatchlistSourceSetup(
        watchlist_id=row.id,
        contact_id=row.contact_id,
        contact_name=contact_name,
        watchlist_name=row.name,
        watch_type=row.watch_type,
        readiness=readiness,
        current_matching_rows=current_matching_rows,
        required_statuses=required_statuses,
        matching_status_counts=matching_status_counts,
        missing_required_statuses=missing_required_statuses,
        required_fields=_required_fields_for_watchlist(row.watch_type),
        csv_columns=PROPERTY_CSV_TEMPLATE_COLUMNS,
        gmail_query=query,
        saved_search_name=saved_search_name,
        realm_criteria=realm_criteria,
        realm_steps=realm_steps,
        export_statuses=required_statuses,
        recommended_method="Use authorized REALM/TRREB saved-search emails or CSV exports first; use a formal MLS connector later.",
        next_actions=next_actions,
    )


def get_watchlist_source_setups(db: Session, contact_id: int | None = None):
    query = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.status == "active")
    if contact_id is not None:
        query = query.filter(models.ClientWatchlist.contact_id == contact_id)
    rows = query.order_by(models.ClientWatchlist.created_at.asc()).all()
    return [_source_setup_for_watchlist(db, row) for row in rows]


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _data_intake_primary_next_step(
    source_ready: bool,
    delivery_ready: bool,
    setup: schemas.WatchlistSourceSetup,
    readiness: dict,
) -> str:
    if not source_ready:
        missing_statuses = list(setup.missing_required_statuses or setup.required_statuses)
        if missing_statuses:
            labels = ", ".join(status.replace("_", " ") for status in missing_statuses)
            return f"Import authorized REALM/TRREB rows for: {labels}."
        return "Import authorized REALM/TRREB listing or comparable rows for this watchlist."
    if not delivery_ready:
        return "Fill client_email in client-email-tasks.csv and place it in the drop folder, or add the client's email in Watchlists."
    if readiness.get("next_steps"):
        return str(readiness["next_steps"][0])
    return "Ready for scheduled matching and review-gated Gmail drafting."


def get_watchlist_data_intake_checklist(db: Session) -> schemas.WatchlistDataIntakeChecklist:
    source = get_property_source_status(db)
    rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    items: list[schemas.WatchlistDataIntakeItem] = []
    ready_count = 0
    warning_count = 0
    blocked_count = 0

    for row in rows:
        setup = _source_setup_for_watchlist(db, row)
        readiness = _watchlist_readiness(db, row)
        source_ready = setup.readiness == "ready"
        delivery_ready = bool(readiness.get("delivery_ready"))
        severity = str(readiness.get("severity") or "blocked")
        blockers = _unique_nonempty([str(issue) for issue in readiness.get("issues") or []])
        next_actions = _unique_nonempty([
            *[str(action) for action in setup.next_actions or []],
            *[str(step) for step in readiness.get("next_steps") or []],
        ])
        primary_next_step = _data_intake_primary_next_step(source_ready, delivery_ready, setup, readiness)

        if source_ready and delivery_ready and severity == "ready":
            ready_count += 1
            item_readiness = "ready"
        elif not source_ready:
            blocked_count += 1
            item_readiness = "blocked"
        else:
            warning_count += 1
            item_readiness = "warning"

        items.append(
            schemas.WatchlistDataIntakeItem(
                watchlist_id=row.id,
                contact_id=row.contact_id,
                contact_name=setup.contact_name,
                watchlist_name=setup.watchlist_name,
                watch_type=setup.watch_type,
                readiness=item_readiness,
                source_ready=source_ready,
                delivery_ready=delivery_ready,
                contact_email_present=bool(readiness.get("contact_email_present")),
                current_matching_rows=setup.current_matching_rows,
                required_statuses=setup.required_statuses,
                missing_required_statuses=setup.missing_required_statuses,
                matching_status_counts=setup.matching_status_counts,
                required_fields=setup.required_fields,
                gmail_query=setup.gmail_query,
                saved_search_name=setup.saved_search_name,
                realm_criteria=setup.realm_criteria,
                realm_steps=setup.realm_steps,
                export_statuses=setup.export_statuses,
                recommended_method=setup.recommended_method,
                primary_next_step=primary_next_step,
                blockers=blockers,
                next_actions=next_actions,
            )
        )

    if not rows:
        overall_status = "empty"
        message = "No active client watchlists exist yet."
        recommended_next_action = "Create a watchlist from a voice memo or from a contact profile."
    elif blocked_count:
        overall_status = "blocked"
        if source.properties_count == 0:
            message = "Active watchlists exist, but no authorized listing, sold, rental, or leased source rows are loaded yet."
            recommended_next_action = (
                f"Export authorized REALM/TRREB CSV rows or RESO/OData JSON and place them in "
                f"{source.csv_drop_folder or 'the watchlist import folder'}."
            )
        elif source.csv_drop_folder_pending_count > 0:
            message = "CSV files are waiting in the drop folder and should be imported before matching."
            recommended_next_action = "Use Import Folder, then run Check All."
        else:
            message = "Some watchlists still need matching source statuses or delivery details before they are ready."
            recommended_next_action = next((item.primary_next_step for item in items if item.readiness != "ready"), None)
    elif warning_count:
        overall_status = "warning"
        message = "Listing source data is ready, but at least one watchlist still needs delivery or review-mode attention."
        recommended_next_action = next((item.primary_next_step for item in items if item.readiness != "ready"), None)
    else:
        overall_status = "ready"
        message = "Watchlists have matching source rows and delivery details for review-gated drafting."
        recommended_next_action = "Let the scheduled checks run, or use Check All after each new authorized import."

    return schemas.WatchlistDataIntakeChecklist(
        overall_status=overall_status,
        active_count=len(rows),
        ready_count=ready_count,
        blocked_count=blocked_count,
        warning_count=warning_count,
        source_rows=int(source.properties_count or 0),
        pending_csv_count=int(source.csv_drop_folder_pending_count or 0),
        recommended_next_action=recommended_next_action,
        message=message,
        items=items,
    )


def _source_goal_for_watchlist(watch_type: str) -> str:
    return {
        "buyer_listing_match": "Active for-sale listings matching the buyer's saved area, property type, budget, beds, baths, parking, and must-haves.",
        "seller_listing_and_sold": "Active competing listings plus sold comparable rows near the seller's subject property.",
        "tenant_rental_match": "Active rental listings matching the tenant's saved rent, area, property type, beds, baths, parking, and availability criteria.",
        "landlord_rental_market": "Active rental listings plus recently leased comparable rows near the landlord's property.",
    }.get(watch_type, "Authorized listing or comparable rows matching this client's saved criteria.")


def _source_task_priority(source_ready: bool, delivery_ready: bool, pending_csv_count: int) -> str:
    if not source_ready:
        return "import_pending_csv" if pending_csv_count > 0 else "source_required"
    if not delivery_ready:
        return "client_email_required"
    return "ready"


def _source_task_steps(
    setup: schemas.WatchlistSourceSetup,
    *,
    source_ready: bool,
    delivery_ready: bool,
    drop_folder: str | None,
    pending_csv_count: int,
) -> list[str]:
    contact = setup.contact_name or setup.watchlist_name
    missing_statuses = setup.missing_required_statuses or setup.required_statuses
    missing_text = ", ".join(status.replace("_", " ") for status in missing_statuses)
    steps: list[str] = []

    if not source_ready:
        if pending_csv_count > 0:
            steps.append("Import the pending CSV/JSON source file(s) from the CRM drop folder, then run Check All.")
        steps.extend(
            [
                f"In REALM/TRREB, run or create the saved search for {contact}.",
                f"Export rows for: {missing_text or 'the required statuses'}.",
                f"Use columns compatible with: {', '.join(setup.csv_columns)}.",
                f"Drop the CSV into {drop_folder or 'the configured watchlist-imports folder'} or upload it in Watchlists.",
                "Preview the import before final import; the preview should show this watchlist moving toward ready.",
            ]
        )
    else:
        steps.append("Source rows are present; run Check Now or wait for the next scheduled check.")

    if not delivery_ready:
        steps.append(f"Fill {contact}'s client_email in client-email-tasks.csv and place it in the drop folder, or add the email in Watchlists.")

    steps.append("Keep client delivery review-gated unless this client is explicitly armed for auto-send and the server flag is enabled.")
    return _unique_nonempty(steps)


def get_watchlist_source_tasks(db: Session) -> schemas.WatchlistSourceTaskList:
    source = get_property_source_status(db)
    checklist = get_watchlist_data_intake_checklist(db)
    setup_by_id = {setup.watchlist_id: setup for setup in get_watchlist_source_setups(db)}
    tasks: list[schemas.WatchlistSourceTask] = []

    for item in checklist.items:
        setup = setup_by_id.get(item.watchlist_id)
        if not setup:
            continue
        priority = _source_task_priority(item.source_ready, item.delivery_ready, source.csv_drop_folder_pending_count)
        task_id = f"watchlist-{item.watchlist_id}-{priority}"
        tasks.append(
            schemas.WatchlistSourceTask(
                task_id=task_id,
                watchlist_id=item.watchlist_id,
                contact_id=item.contact_id,
                contact_name=item.contact_name,
                watchlist_name=item.watchlist_name,
                watch_type=item.watch_type,
                priority=priority,
                source_ready=item.source_ready,
                delivery_ready=item.delivery_ready,
                client_email_needed=not item.delivery_ready,
                source_goal=_source_goal_for_watchlist(item.watch_type),
                required_statuses=item.required_statuses,
                missing_required_statuses=item.missing_required_statuses,
                required_fields=item.required_fields,
                csv_columns=setup.csv_columns,
                gmail_query=item.gmail_query,
                saved_search_name=setup.saved_search_name,
                realm_criteria=setup.realm_criteria,
                realm_steps=setup.realm_steps,
                export_statuses=setup.export_statuses,
                drop_folder=source.csv_drop_folder,
                recommended_method=item.recommended_method,
                steps=_source_task_steps(
                    setup,
                    source_ready=item.source_ready,
                    delivery_ready=item.delivery_ready,
                    drop_folder=source.csv_drop_folder,
                    pending_csv_count=source.csv_drop_folder_pending_count,
                ),
            )
        )

    priority_rank = {
        "import_pending_csv": 0,
        "source_required": 1,
        "client_email_required": 2,
        "ready": 3,
    }
    tasks.sort(key=lambda task: (priority_rank.get(task.priority, 9), task.contact_name or task.watchlist_name))
    ready_count = sum(1 for task in tasks if task.priority == "ready")

    if not tasks:
        overall_status = "empty"
        message = "No active watchlists need source tasks yet."
    elif ready_count == len(tasks):
        overall_status = "ready"
        message = "All active watchlists have source rows and delivery details."
    elif any(task.priority in {"import_pending_csv", "source_required"} for task in tasks):
        overall_status = "blocked"
        message = "Source import tasks are still required before live matching is reliable."
    else:
        overall_status = "warning"
        message = "Source rows exist, but delivery details still need attention."

    return schemas.WatchlistSourceTaskList(
        overall_status=overall_status,
        task_count=len(tasks),
        ready_count=ready_count,
        source_rows=source.properties_count,
        pending_csv_count=source.csv_drop_folder_pending_count,
        message=message,
        tasks=tasks,
    )


def _launch_action_priority(task: schemas.WatchlistSourceTask) -> str:
    if task.priority == "import_pending_csv":
        return "Import pending source"
    if task.priority == "source_required":
        return "Create/export source"
    if task.priority == "client_email_required":
        return "Add client email"
    return "Ready"


def _launch_action_copy_text(task: schemas.WatchlistSourceTask) -> str:
    contact = task.contact_name or task.watchlist_name
    missing_statuses = task.missing_required_statuses or task.required_statuses
    missing_text = ", ".join(status.replace("_", " ") for status in missing_statuses) or "none"
    lines = [
        f"{contact} - {task.watchlist_name}",
        f"Priority: {_launch_action_priority(task)}",
        f"Saved search: {task.saved_search_name}",
        f"Goal: {task.source_goal}",
        f"Missing statuses: {missing_text}",
        f"Gmail query: {task.gmail_query}",
    ]
    if task.drop_folder:
        lines.append(f"CSV drop folder: {task.drop_folder}")
    if task.client_email_needed:
        lines.append("Client email: missing; Gmail draft delivery is blocked until email is added.")
    if task.realm_criteria:
        lines.extend(["REALM/TRREB criteria:", *[f"- {item}" for item in task.realm_criteria]])
    if task.steps:
        lines.extend(["Next actions:", *[f"- {step}" for step in task.steps]])
    return "\n".join(lines)


def _launch_preflight_check(
    key: str,
    label: str,
    status: str,
    detail: str,
    next_step: str | None = None,
) -> schemas.WatchlistLaunchPreflightCheck:
    return schemas.WatchlistLaunchPreflightCheck(
        key=key,
        label=label,
        status=status,
        detail=detail,
        next_step=next_step,
    )


def _watchlist_launch_preflight_checks(
    readiness: schemas.WatchlistReadinessReport,
    source_task_count: int,
    missing_email_count: int,
    feed_config: models.PropertyFeedConfig,
    safety: schemas.WatchlistSafetyStatus,
    reso_connector: schemas.ResoConnectorStatus,
) -> list[schemas.WatchlistLaunchPreflightCheck]:
    if readiness.active_count <= 0:
        source_status = "warning"
        source_detail = "No active watchlists are configured yet."
        source_next_step = "Create or activate a client watchlist before relying on scheduled matching."
    elif source_task_count == 0:
        source_status = "passed"
        source_detail = f"{readiness.property_rows} source row(s) cover the required statuses for active watchlists."
        source_next_step = None
    else:
        source_status = "blocked"
        source_detail = (
            f"{readiness.property_rows} source row(s); {source_task_count} active watchlist"
            f"{'s' if source_task_count != 1 else ''} still need matching required statuses."
        )
        source_next_step = "Import authorized REALM/TRREB CSV rows, authorized RESO/OData JSON, pasted listing feed text, Gmail saved-search feed rows, or an approved connector before expecting reliable matches."

    if readiness.active_count <= 0:
        readiness_status = "warning"
        readiness_detail = "There are no active watchlists to run."
        readiness_next_step = "Create or activate watchlists for seller, buyer, tenant, or landlord clients."
    elif readiness.ready_count == readiness.active_count:
        readiness_status = "passed"
        readiness_detail = f"All {readiness.active_count} active watchlist(s) are ready for scheduled checks."
        readiness_next_step = None
    elif readiness.ready_count > 0:
        readiness_status = "warning"
        readiness_detail = f"{readiness.ready_count}/{readiness.active_count} active watchlist(s) are ready."
        readiness_next_step = "Fix the blocked watchlists listed below before treating the whole CRM as launched."
    else:
        readiness_status = "blocked"
        readiness_detail = f"0/{readiness.active_count} active watchlist(s) are ready."
        readiness_next_step = "Start with source data import and missing client email tasks shown below."

    if missing_email_count == 0:
        email_status = "passed"
        email_detail = "All active watchlists have client emails when Gmail delivery needs a recipient."
        email_next_step = None
    else:
        email_status = "blocked"
        email_detail = (
            f"{missing_email_count} active watchlist"
            f"{'s' if missing_email_count != 1 else ''} need client email before Gmail drafts or auto-send can be addressed."
        )
        email_next_step = "Fill client_email in client-email-tasks.csv and place it in the drop folder, or add the missing email(s) in this page or Contacts."

    if safety.gmail_connected:
        gmail_status = "passed"
        gmail_detail = f"Gmail is connected{f' as {safety.gmail_account_email}' if safety.gmail_account_email else ''}."
        gmail_next_step = None
    else:
        gmail_status = "blocked"
        gmail_detail = "Gmail is not connected, so the CRM can create internal review drafts only."
        gmail_next_step = "Connect Gmail before relying on Gmail Draft, Send Now, or Auto Send Armed workflows."

    if feed_config.gmail_feed_enabled:
        feed_status = "passed"
        feed_detail = "Scheduled Gmail saved-search feed import is enabled."
        feed_next_step = None
    else:
        feed_status = "warning"
        feed_detail = "Gmail saved-search feed import is disabled; CSV/manual imports can still be used."
        feed_next_step = "Type READ GMAIL in the CRM only if Kevin wants scheduled Gmail saved-search imports."

    if reso_connector.ready:
        connector_status = "passed"
        connector_detail = "Formal RESO/OData connector is configured for scheduled authorized JSON import."
        connector_next_step = "Confirm imported rows appear in Source Status after the next scheduled run."
    elif reso_connector.enabled:
        connector_status = "warning"
        connector_detail = reso_connector.message
        connector_next_step = "Add WATCHLIST_RESO_CONNECTOR_URL or turn the connector off until an authorized URL is available."
    else:
        connector_status = "info"
        connector_detail = reso_connector.message
        connector_next_step = "Use REALM/TRREB CSV or manual RESO JSON now; configure this connector later when the authorized endpoint is available."

    if safety.can_auto_send:
        auto_send_status = "passed"
        auto_send_detail = "Server auto-send is enabled and Gmail is connected for Auto Send Armed watchlists."
        auto_send_next_step = None
    elif safety.auto_send_armed_count:
        auto_send_status = "warning"
        auto_send_detail = (
            f"{safety.auto_send_armed_count} watchlist(s) are Auto Send Armed, but server auto-send is off; matches stay draft-only."
        )
        auto_send_next_step = "Keep this as draft-only until Kevin explicitly enables the server auto-send switch."
    else:
        auto_send_status = "info"
        auto_send_detail = "Auto-send server switch is off, so scheduled matches stay review-gated or draft-only."
        auto_send_next_step = "This is the recommended starting mode until the workflow is proven with real source rows."

    return [
        _launch_preflight_check("authorized_source_data", "Authorized Source Data", source_status, source_detail, source_next_step),
        _launch_preflight_check("watchlist_readiness", "Watchlist Readiness", readiness_status, readiness_detail, readiness_next_step),
        _launch_preflight_check("client_delivery_emails", "Client Delivery Emails", email_status, email_detail, email_next_step),
        _launch_preflight_check("gmail_draft_connection", "Gmail Draft Connection", gmail_status, gmail_detail, gmail_next_step),
        _launch_preflight_check("gmail_saved_search_feed", "Gmail Saved-Search Feed", feed_status, feed_detail, feed_next_step),
        _launch_preflight_check("reso_odata_connector", "RESO/OData Connector", connector_status, connector_detail, connector_next_step),
        _launch_preflight_check("auto_send_safety", "Auto-Send Safety", auto_send_status, auto_send_detail, auto_send_next_step),
    ]


def get_watchlist_launch_action_pack(
    db: Session,
    gmail_status: schemas.GmailOAuthStatusResponse | None = None,
) -> schemas.WatchlistLaunchActionPack:
    tasks = get_watchlist_source_tasks(db)
    readiness = get_watchlist_readiness_report(db, gmail_status=gmail_status)
    feed_config = get_property_feed_config(db)
    safety = readiness.safety
    reso_connector = _watchlist_reso_connector_status()
    missing_email_count = sum(1 for task in tasks.tasks if task.client_email_needed)
    source_task_count = sum(1 for task in tasks.tasks if not task.source_ready)
    preflight_checks = _watchlist_launch_preflight_checks(
        readiness=readiness,
        source_task_count=source_task_count,
        missing_email_count=missing_email_count,
        feed_config=feed_config,
        safety=safety,
        reso_connector=reso_connector,
    )
    recommended_method = (
        "Use authorized REALM/TRREB saved-search emails or CSV exports first; "
        "use a formal MLS/IDX/VOW/TRREB connector later. Do not scrape MLS pages."
    )

    next_actions = _unique_nonempty(
        [
            *(readiness.next_actions or []),
            *(tasks.tasks[0].steps if tasks.tasks else []),
        ]
    )
    if not feed_config.gmail_feed_enabled:
        next_actions.append("Gmail saved-search feed import is disabled until Kevin explicitly types READ GMAIL in the CRM.")
    if not reso_connector.ready:
        next_actions.append("Formal RESO/OData connector is not configured yet; use CSV/manual RESO JSON now, then enable the connector after an authorized endpoint is available.")
    if not safety.auto_send_server_enabled:
        next_actions.append("Auto-send server switch is off; matches create notifications/drafts for review only.")
    next_actions = _unique_nonempty(next_actions)

    items: list[schemas.WatchlistLaunchActionItem] = []
    for task in tasks.tasks:
        action_lines = _unique_nonempty(
            [
                *task.steps,
                "Preview imported CSV/Gmail rows before final import.",
            ]
        )
        if task.client_email_needed:
            action_lines.insert(0, f"Fill {task.contact_name or task.watchlist_name}'s client_email in client-email-tasks.csv, place it in the drop folder, or add it in Watchlists.")
        item = schemas.WatchlistLaunchActionItem(
            watchlist_id=task.watchlist_id,
            contact_id=task.contact_id,
            contact_name=task.contact_name,
            watchlist_name=task.watchlist_name,
            watch_type=task.watch_type,
            priority=task.priority,
            source_ready=task.source_ready,
            delivery_ready=task.delivery_ready,
            client_email_needed=task.client_email_needed,
            required_statuses=task.required_statuses,
            missing_required_statuses=task.missing_required_statuses,
            saved_search_name=task.saved_search_name,
            gmail_query=task.gmail_query,
            drop_folder=task.drop_folder,
            source_goal=task.source_goal,
            actions=action_lines,
            copy_text=_launch_action_copy_text(task),
        )
        items.append(item)

    summary = (
        f"{readiness.overall_status}: {readiness.ready_count}/{readiness.active_count} watchlists ready; "
        f"{readiness.property_rows} source row(s); {missing_email_count} client email(s) missing; "
        f"Gmail feed {'enabled' if feed_config.gmail_feed_enabled else 'disabled'}; "
        f"RESO connector {reso_connector.status}; "
        f"auto-send server {'enabled' if safety.auto_send_server_enabled else 'off'}."
    )
    copy_lines = [
        "SKC CRM Launch Action Pack",
        summary,
        f"Generated: {_utcnow().isoformat()}",
        f"Recommended method: {recommended_method}",
        f"CSV drop folder: {tasks.tasks[0].drop_folder if tasks.tasks and tasks.tasks[0].drop_folder else _watchlist_csv_drop_folder_path()}",
        f"RESO connector: {reso_connector.status}. {reso_connector.message}",
        f"RESO connector endpoint: {reso_connector.endpoint or 'not configured'}",
        f"Gmail feed: {'enabled' if feed_config.gmail_feed_enabled else 'disabled'}",
        f"Gmail connected: {'yes' if safety.gmail_connected else 'no'}",
        (
            "Auto-send server switch is enabled."
            if safety.auto_send_server_enabled
            else "Auto-send server switch is off; matches create notifications/drafts for review only."
        ),
        "",
        "Top next actions:",
        *[f"- {action}" for action in next_actions[:12]],
        "",
        "Preflight checks:",
        *[
            f"- {check.label}: {check.status}. {check.detail}"
            + (f" Next: {check.next_step}" if check.next_step else "")
            for check in preflight_checks
        ],
        "",
        "Client tasks:",
    ]
    for item in items:
        copy_lines.extend(["", item.copy_text])

    return schemas.WatchlistLaunchActionPack(
        overall_status=readiness.overall_status,
        generated_at=_utcnow(),
        summary=summary,
        source_rows=readiness.property_rows,
        pending_csv_count=readiness.pending_csv_count,
        ready_count=readiness.ready_count,
        active_count=readiness.active_count,
        missing_email_count=missing_email_count,
        source_task_count=source_task_count,
        gmail_feed_enabled=bool(feed_config.gmail_feed_enabled),
        auto_send_server_enabled=bool(safety.auto_send_server_enabled),
        gmail_connected=bool(safety.gmail_connected),
        reso_connector=reso_connector,
        recommended_method=recommended_method,
        next_actions=next_actions,
        preflight_checks=preflight_checks,
        copy_text="\n".join(copy_lines),
        items=items,
    )


def _alert_schema(row: models.WatchlistAlert) -> schemas.WatchlistAlert:
    notification_statuses: dict[str, str] = {}
    for notification in sorted(row.notifications or [], key=lambda item: item.created_at or datetime.min):
        notification_statuses[notification.channel] = notification.status
    draft_status = None
    gmail_draft_id = None
    gmail_message_id = None
    if row.interaction:
        draft_status = row.interaction.generated_response_status
        draft_payload = _json_object(row.interaction.generated_response_content)
        gmail_meta = draft_payload.get("gmail") if isinstance(draft_payload.get("gmail"), dict) else {}
        gmail_draft_id = gmail_meta.get("draft_id")
        gmail_message_id = gmail_meta.get("message_id") or gmail_meta.get("sent_message_id")

    return schemas.WatchlistAlert(
        id=row.id,
        watchlist_id=row.watchlist_id,
        contact_id=row.contact_id,
        contact_name=row.contact.name if row.contact else None,
        property_id=row.property_id,
        interaction_id=row.interaction_id,
        draft_status=draft_status,
        gmail_draft_id=gmail_draft_id,
        gmail_message_id=gmail_message_id,
        alert_type=row.alert_type,
        title=row.title,
        summary=row.summary,
        analysis=row.analysis,
        source=row.source or "internal_properties",
        source_url=row.source_url,
        payload=_json_object(row.payload_json),
        notification_statuses=notification_statuses,
        status=row.status,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _notification_schema(row: models.WatchlistNotification) -> schemas.WatchlistNotification:
    return schemas.WatchlistNotification(
        id=row.id,
        alert_id=row.alert_id,
        watchlist_id=row.watchlist_id,
        contact_id=row.contact_id,
        channel=row.channel,
        status=row.status,
        title=row.title,
        body=row.body,
        error=row.error,
        delivered_at=row.delivered_at,
        created_at=row.created_at,
    )


_RUN_LOG_SECRET_KEYS = {"token", "secret", "password", "authorization", "cookie", "refresh", "api_key", "client_secret"}


def _sanitize_run_log_payload(value, depth: int = 0):
    if depth > 6:
        return "[truncated_depth]"
    if isinstance(value, dict):
        sanitized = {}
        for key, item in list(value.items())[:100]:
            key_text = str(key)
            lowered = key_text.lower()
            if any(secret_key in lowered for secret_key in _RUN_LOG_SECRET_KEYS):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = _sanitize_run_log_payload(item, depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_run_log_payload(item, depth + 1) for item in value[:100]]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = str(value) if isinstance(value, str) else value
        if isinstance(text, str) and len(text) > 4000:
            return f"{text[:4000]}...[truncated]"
        return text
    return str(value)


def _watchlist_run_log_schema(row: models.WatchlistRunLog) -> schemas.WatchlistRunLog:
    return schemas.WatchlistRunLog(
        id=row.id,
        run_type=row.run_type or "manual",
        status=row.status or "success",
        started_at=row.started_at,
        finished_at=row.finished_at,
        checked_count=row.checked_count or 0,
        created_alerts=row.created_alerts or 0,
        matched_properties=row.matched_properties or 0,
        active_count=row.active_count or 0,
        due_count=row.due_count or 0,
        not_due_count=row.not_due_count or 0,
        pending_alert_count=row.pending_alert_count or 0,
        draft_alert_count=row.draft_alert_count or 0,
        sent_alert_count=row.sent_alert_count or 0,
        source_status=row.source_status,
        message=row.message,
        error=row.error,
        payload=_json_object(row.payload_json),
        created_at=row.created_at,
    )


def create_watchlist_run_log(db: Session, entry: schemas.WatchlistRunLogCreate) -> schemas.WatchlistRunLog:
    payload = _sanitize_run_log_payload(entry.payload)
    row = models.WatchlistRunLog(
        run_type=(entry.run_type or "manual")[:64],
        status=(entry.status or "success")[:32],
        started_at=entry.started_at,
        finished_at=entry.finished_at or _utcnow(),
        checked_count=max(0, int(entry.checked_count or 0)),
        created_alerts=max(0, int(entry.created_alerts or 0)),
        matched_properties=max(0, int(entry.matched_properties or 0)),
        active_count=max(0, int(entry.active_count or 0)),
        due_count=max(0, int(entry.due_count or 0)),
        not_due_count=max(0, int(entry.not_due_count or 0)),
        pending_alert_count=max(0, int(entry.pending_alert_count or 0)),
        draft_alert_count=max(0, int(entry.draft_alert_count or 0)),
        sent_alert_count=max(0, int(entry.sent_alert_count or 0)),
        source_status=entry.source_status,
        message=entry.message,
        error=entry.error,
        payload_json=_json_dumps(payload),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _watchlist_run_log_schema(row)


def get_watchlist_run_logs(db: Session, limit: int = 20) -> list[schemas.WatchlistRunLog]:
    rows = (
        db.query(models.WatchlistRunLog)
        .order_by(models.WatchlistRunLog.created_at.desc())
        .limit(max(1, min(int(limit or 20), 100)))
        .all()
    )
    return [_watchlist_run_log_schema(row) for row in rows]


def get_watchlist_notifications(
    db: Session,
    alert_id: int | None = None,
    channel: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    query = db.query(models.WatchlistNotification).order_by(models.WatchlistNotification.created_at.desc())
    if alert_id is not None:
        query = query.filter(models.WatchlistNotification.alert_id == alert_id)
    if channel:
        query = query.filter(models.WatchlistNotification.channel == channel)
    if status:
        query = query.filter(models.WatchlistNotification.status == status)
    return [_notification_schema(row) for row in query.limit(limit).all()]


def mark_codex_notifications_reported(
    db: Session,
    ids: list[int] | None = None,
) -> schemas.WatchlistNotificationMarkReportedResponse:
    query = (
        db.query(models.WatchlistNotification)
        .filter(models.WatchlistNotification.channel == "codex_app")
        .filter(models.WatchlistNotification.status == "queued_for_codex_report")
    )
    if ids:
        query = query.filter(models.WatchlistNotification.id.in_(ids))

    rows = query.order_by(models.WatchlistNotification.created_at.asc()).all()
    for row in rows:
        row.status = "reported_in_codex"
    db.commit()
    for row in rows:
        db.refresh(row)
    return schemas.WatchlistNotificationMarkReportedResponse(
        updated=len(rows),
        notifications=[_notification_schema(row) for row in rows],
    )


def get_watchlist_safety_status(
    db: Session,
    gmail_status: schemas.GmailOAuthStatusResponse | None = None,
) -> schemas.WatchlistSafetyStatus:
    auto_send_server_enabled = _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED")
    armed_watchlists = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .filter(models.ClientWatchlist.review_mode == "auto_send_approved")
        .order_by(models.ClientWatchlist.id.asc())
        .all()
    )
    armed_count = len(armed_watchlists)
    gmail_connected = bool(
        gmail_status
        and gmail_status.status == "connected"
        and gmail_status.has_refresh_token
    )
    can_auto_send = auto_send_server_enabled and gmail_connected
    armed_items: list[schemas.WatchlistAutoSendArmedItem] = []
    for row in armed_watchlists:
        contact_email_present = bool(row.contact and str(row.contact.email or "").strip())
        action_required: str | None = None
        if not contact_email_present:
            action_required = "Add the client's email before Auto Send can be used."
        elif not gmail_connected:
            action_required = "Connect Gmail before Auto Send can be used."
        elif not auto_send_server_enabled:
            action_required = "Server auto-send is off; matches stay Gmail draft-only."
        armed_items.append(
            schemas.WatchlistAutoSendArmedItem(
                watchlist_id=row.id,
                contact_id=row.contact_id,
                contact_name=row.contact.name if row.contact else None,
                watchlist_name=row.name,
                contact_email_present=contact_email_present,
                can_auto_send=bool(can_auto_send and contact_email_present),
                action_required=action_required,
            )
        )
    if can_auto_send:
        message = "Auto-send is fully enabled for armed watchlists. Matching alerts can be sent through Gmail without manual review."
    elif auto_send_server_enabled and not gmail_connected:
        message = "Server auto-send is enabled, but Gmail is not connected. Armed watchlists can only create drafts until Gmail is connected."
    elif armed_count:
        message = "Some watchlists are Auto Send Armed, but server auto-send is off. Matching alerts will create Gmail drafts for review only."
    else:
        message = "Auto-send server switch is off. Watchlist matches require review or create drafts only."
    return schemas.WatchlistSafetyStatus(
        auto_send_server_enabled=auto_send_server_enabled,
        gmail_connected=gmail_connected,
        gmail_account_email=gmail_status.account_email if gmail_status else None,
        auto_send_armed_count=armed_count,
        auto_send_armed_watchlists=armed_items,
        can_auto_send=can_auto_send,
        draft_only=not can_auto_send,
        message=message,
    )


def _delivery_gate_for_watchlist(
    db: Session,
    row: models.ClientWatchlist,
    safety: schemas.WatchlistSafetyStatus,
) -> schemas.WatchlistDeliveryGate:
    review_mode = row.review_mode or "manual_review"
    notification_channel = _watchlist_notification_channel_or_default(row.notification_channel)
    contact_email_present = bool(row.contact and str(row.contact.email or "").strip())
    push_subscriptions = db.query(func.count(models.PushSubscription.id)).scalar() or 0
    notification_ready = notification_channel != "app_push" or push_subscriptions > 0
    can_create_gmail_draft = False
    can_auto_send = False
    action_required: str | None = None

    if review_mode == "manual_review":
        delivery_state = "manual_review_queue"
        safety_note = "Matches create reviewable alerts. Kevin must create or send any Gmail draft manually."
    elif review_mode == "auto_create_draft":
        delivery_state = "crm_draft_only"
        safety_note = "Matches create CRM review drafts only. No Gmail draft or send happens automatically."
    elif review_mode == "auto_gmail_draft":
        if not contact_email_present:
            delivery_state = "email_required"
            action_required = "Add the client's email before Auto Gmail Draft can address a draft."
            safety_note = "Automation can still notify Kevin, but Gmail draft creation is blocked until the contact has an email."
        elif not safety.gmail_connected:
            delivery_state = "gmail_connection_required"
            action_required = "Connect Gmail before Auto Gmail Draft can create drafts."
            safety_note = "No client email will be sent; Gmail is not connected."
        else:
            delivery_state = "gmail_draft_ready"
            can_create_gmail_draft = True
            safety_note = "Matches can create Gmail drafts for Kevin to review. Sending still requires explicit approval."
    elif review_mode == "auto_send_approved":
        if not contact_email_present:
            delivery_state = "email_required"
            action_required = "Add the client's email before Auto Send can be used."
            safety_note = "Auto Send is armed for this watchlist, but the missing email blocks delivery."
        elif not safety.gmail_connected:
            delivery_state = "gmail_connection_required"
            action_required = "Connect Gmail before Auto Send can be used."
            safety_note = "Auto Send is armed, but Gmail is not connected."
        elif not safety.auto_send_server_enabled:
            delivery_state = "auto_send_armed_draft_only"
            can_create_gmail_draft = True
            action_required = "Server auto-send is off; leave this as draft-only or explicitly enable WATCHLIST_AUTO_SEND_ENABLED later."
            safety_note = "Auto Send is armed, but server safety keeps it draft-only."
        else:
            delivery_state = "auto_send_ready"
            can_create_gmail_draft = True
            can_auto_send = True
            safety_note = "Matches can create and send through Gmail because this client is armed and the server switch is enabled."
    else:
        delivery_state = "unknown_review_mode"
        action_required = "Choose Manual, CRM Draft, Gmail Draft, or Auto Send Armed."
        safety_note = "Unknown review mode; no automated delivery should be trusted."

    if not notification_ready:
        action_required = action_required or "Enable browser/app push notifications or switch to Codex App notifications."

    return schemas.WatchlistDeliveryGate(
        watchlist_id=row.id,
        contact_id=row.contact_id,
        contact_name=row.contact.name if row.contact else None,
        watchlist_name=row.name,
        review_mode=review_mode,
        notification_channel=notification_channel,
        delivery_state=delivery_state,
        contact_email_present=contact_email_present,
        gmail_connected=safety.gmail_connected,
        auto_send_server_enabled=safety.auto_send_server_enabled,
        can_create_gmail_draft=can_create_gmail_draft,
        can_auto_send=can_auto_send,
        notification_ready=notification_ready,
        action_required=action_required,
        safety_note=safety_note,
    )


def get_watchlist_delivery_gates(
    db: Session,
    gmail_status: schemas.GmailOAuthStatusResponse | None = None,
) -> schemas.WatchlistDeliveryGateList:
    safety = get_watchlist_safety_status(db, gmail_status=gmail_status)
    rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    items = [_delivery_gate_for_watchlist(db, row, safety) for row in rows]
    ready_states = {"manual_review_queue", "crm_draft_only", "gmail_draft_ready", "auto_send_ready"}
    warning_states = {"auto_send_armed_draft_only"}
    ready_count = sum(1 for item in items if item.delivery_state in ready_states and item.notification_ready)
    warning_count = sum(1 for item in items if item.delivery_state in warning_states or not item.notification_ready)
    blocked_count = max(0, len(items) - ready_count - warning_count)

    if not items:
        overall_status = "empty"
        message = "No active watchlists exist yet."
    elif blocked_count:
        overall_status = "blocked"
        message = "Some watchlists cannot create the intended Gmail drafts or delivery actions yet."
    elif warning_count:
        overall_status = "warning"
        message = "Delivery is draft-safe, but at least one watchlist has a safety gate or notification warning."
    else:
        overall_status = "ready"
        message = "Delivery gates are ready for the configured review modes."

    return schemas.WatchlistDeliveryGateList(
        overall_status=overall_status,
        active_count=len(items),
        ready_count=ready_count,
        blocked_count=blocked_count,
        warning_count=warning_count,
        message=message,
        items=items,
    )


def get_watchlist_readiness_report(
    db: Session,
    gmail_status: schemas.GmailOAuthStatusResponse | None = None,
) -> schemas.WatchlistReadinessReport:
    safety = get_watchlist_safety_status(db, gmail_status=gmail_status)
    source = get_property_source_status(db)
    active = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    items: list[schemas.WatchlistReadinessReportItem] = []
    blockers: list[str] = []
    next_actions: list[str] = []
    ready_count = 0
    warning_count = 0
    blocked_count = 0

    for row in active:
        readiness = _watchlist_readiness(db, row)
        severity = str(readiness.get("severity") or "blocked")
        is_ready = bool(readiness.get("ready"))
        if is_ready:
            ready_count += 1
        elif severity == "warning":
            warning_count += 1
        else:
            blocked_count += 1

        contact_name = row.contact.name if row.contact else None
        label = contact_name or row.name
        steps = [str(step) for step in readiness.get("next_steps") or []]
        for step in steps:
            action = f"{label}: {step}"
            if action not in next_actions:
                next_actions.append(action)
        if not is_ready:
            blockers.append(f"{label}: {', '.join(steps) if steps else 'Readiness incomplete.'}")

        items.append(
            schemas.WatchlistReadinessReportItem(
                watchlist_id=row.id,
                contact_name=contact_name,
                watchlist_name=row.name,
                ready=is_ready,
                severity=severity,
                matching_source_rows=int(readiness.get("matching_source_rows") or 0),
                required_statuses=list(readiness.get("required_statuses") or []),
                matching_status_counts=dict(readiness.get("matching_status_counts") or {}),
                missing_required_statuses=list(readiness.get("missing_required_statuses") or []),
                notification_channel=_watchlist_notification_channel_or_default(row.notification_channel),
                review_mode=row.review_mode or "manual_review",
                contact_email_present=bool(readiness.get("contact_email_present")),
                delivery_ready=bool(readiness.get("delivery_ready")),
                delivery_issues=list(readiness.get("delivery_issues") or []),
                next_steps=steps,
            )
        )

    pending_csv_count = int(source.csv_drop_folder_pending_count or 0)
    if not active:
        blockers.append("No active client watchlists exist.")
        next_actions.append("Create a watchlist for each buyer, seller, tenant, or landlord client.")
    if source.properties_count == 0 and pending_csv_count == 0:
        next_actions.insert(
            0,
            f"Export authorized REALM/TRREB CSV rows or RESO/OData JSON and place them in {source.csv_drop_folder or 'the watchlist import folder'}.",
        )
    elif pending_csv_count > 0:
        next_actions.insert(0, "Use Import Folder to ingest pending CSV/JSON source files, then run Check All.")
    if safety.draft_only:
        next_actions.append("Review Gmail drafts manually unless you explicitly enable WATCHLIST_AUTO_SEND_ENABLED=true later.")

    if blocked_count or not active or source.properties_count == 0:
        overall_status = "blocked"
    elif warning_count:
        overall_status = "warning"
    else:
        overall_status = "ready"

    if overall_status == "ready":
        message = "All active watchlists have matching source rows and can run with the current safety settings."
    elif pending_csv_count > 0:
        message = f"{pending_csv_count} CSV/JSON source file(s) are waiting in the drop folder before watchlists can be fully checked."
    else:
        message = "Watchlists are configured, but source listing/comparable rows are still missing."

    return schemas.WatchlistReadinessReport(
        overall_status=overall_status,
        active_count=len(active),
        ready_count=ready_count,
        blocked_count=blocked_count,
        warning_count=warning_count,
        property_rows=source.properties_count,
        pending_csv_count=pending_csv_count,
        safety=safety,
        blockers=blockers[:20],
        next_actions=next_actions[:20],
        items=items,
        message=message,
    )


def _default_watch_type_for_contact(contact: models.Contact) -> str:
    return _normalize_watch_type(None, contact)


def _default_watchlist_name(contact: models.Contact, watch_type: str) -> str:
    labels = {
        "buyer_listing_match": "Buyer listing match",
        "seller_listing_and_sold": "Seller listing + sold comps",
        "tenant_rental_match": "Tenant rental match",
        "landlord_rental_market": "Landlord rental market",
    }
    return f"{contact.name} - {labels.get(watch_type, 'Market watch')}"


def _criteria_from_contact(contact: models.Contact) -> dict:
    prefs = _safe_json_dict(contact.property_preferences)
    areas = _safe_json_list(contact.preferred_areas)
    must_haves = _coerce_string_list(prefs.get("must_haves"))
    parking_min = prefs.get("parking_min") or prefs.get("parking_spaces") or prefs.get("total_parking_spaces")
    if parking_min is None and any(re.search(r"garage|parking|車庫|停車", item, flags=re.IGNORECASE) for item in must_haves):
        parking_min = 1
    criteria = {
        "areas": areas,
        "types": _coerce_string_list(prefs.get("types")),
        "must_haves": must_haves,
        "deal_breakers": _coerce_string_list(prefs.get("deal_breakers")),
        "min_price": contact.budget_min,
        "max_price": contact.budget_max,
        "bedrooms_min": prefs.get("bedrooms_min"),
        "bathrooms_min": prefs.get("bathrooms_min"),
        "parking_min": parking_min,
        "property_address": prefs.get("property_address"),
        "available_after": prefs.get("available_after"),
    }
    return {key: value for key, value in criteria.items() if value not in (None, "", [], {})}


def get_watchlists(db: Session, contact_id: int | None = None):
    query = db.query(models.ClientWatchlist).order_by(models.ClientWatchlist.created_at.desc())
    if contact_id is not None:
        query = query.filter(models.ClientWatchlist.contact_id == contact_id)
    return [_watchlist_schema(row, db=db) for row in query.all()]


def get_watchlist(db: Session, watchlist_id: int):
    return db.query(models.ClientWatchlist).filter(models.ClientWatchlist.id == watchlist_id).first()


def create_watchlist(db: Session, watchlist: schemas.ClientWatchlistCreate):
    contact = get_contact(db, watchlist.contact_id)
    if not contact:
        return None

    watch_type = _normalize_watch_type(watchlist.watch_type, contact)
    review_mode = _normalize_watchlist_review_mode(watchlist.review_mode)
    if review_mode == "auto_send_approved" and not _auto_send_confirmation_valid(watchlist.auto_send_confirmation):
        raise ValueError("auto_send_confirmation_required")
    schedule = _parse_schedule(watchlist.schedule)
    row = models.ClientWatchlist(
        contact_id=contact.id,
        name=watchlist.name or _default_watchlist_name(contact, watch_type),
        watch_type=watch_type,
        status=_normalize_watchlist_status(watchlist.status),
        criteria_json=_json_dumps(watchlist.criteria),
        schedule_json=_json_dumps(schedule),
        notification_channel=_normalize_watchlist_notification_channel(watchlist.notification_channel),
        review_mode=review_mode,
        data_source=watchlist.data_source or "internal_properties",
        source_query=_clean_source_query(watchlist.source_query),
        next_check_at=_next_scheduled_check(schedule),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _watchlist_schema(row, db=db)


def _upsert_default_watchlist_for_contact_row(db: Session, contact: models.Contact) -> models.ClientWatchlist:
    watch_type = _default_watch_type_for_contact(contact)
    schedule = {"times": ["09:00", "15:00", "18:00"], "timezone": "America/Toronto"}
    criteria = _criteria_from_contact(contact)

    existing = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.contact_id == contact.id)
        .filter(models.ClientWatchlist.watch_type == watch_type)
        .first()
    )
    row = existing or models.ClientWatchlist(contact_id=contact.id, watch_type=watch_type)
    row.name = row.name or _default_watchlist_name(contact, watch_type)
    row.status = "active"
    row.criteria_json = _json_dumps(criteria)
    row.schedule_json = _json_dumps(schedule)
    row.notification_channel = _watchlist_notification_channel_or_default(row.notification_channel)
    row.review_mode = _normalize_watchlist_review_mode(row.review_mode or "auto_gmail_draft")
    row.data_source = row.data_source or "internal_properties"
    row.source_query = row.source_query or _default_source_query_for_watchlist(watch_type, criteria)
    row.next_check_at = row.next_check_at or _next_scheduled_check(schedule)
    row.updated_at = _utcnow()
    if not existing:
        db.add(row)
    return row


def create_default_watchlist_for_contact(db: Session, contact_id: int):
    contact = get_contact(db, contact_id)
    if not contact:
        return None

    row = _upsert_default_watchlist_for_contact_row(db, contact)
    db.commit()
    db.refresh(row)
    return _watchlist_schema(row, db=db)


def update_watchlist(db: Session, watchlist_id: int, update: schemas.ClientWatchlistUpdate):
    row = get_watchlist(db, watchlist_id)
    if not row:
        return None

    data = update.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        row.name = data["name"]
    if "watch_type" in data and data["watch_type"] is not None:
        row.watch_type = _normalize_watch_type(data["watch_type"], row.contact)
    if "status" in data and data["status"] is not None:
        row.status = _normalize_watchlist_status(data["status"])
    if "criteria" in data and data["criteria"] is not None:
        row.criteria_json = _json_dumps(data["criteria"])
    if "schedule" in data and data["schedule"] is not None:
        schedule = _parse_schedule(data["schedule"])
        row.schedule_json = _json_dumps(schedule)
        row.next_check_at = _next_scheduled_check(schedule)
    if "notification_channel" in data and data["notification_channel"] is not None:
        row.notification_channel = _normalize_watchlist_notification_channel(data["notification_channel"])
    if "review_mode" in data and data["review_mode"] is not None:
        review_mode = _normalize_watchlist_review_mode(data["review_mode"])
        if (
            review_mode == "auto_send_approved"
            and row.review_mode != "auto_send_approved"
            and not _auto_send_confirmation_valid(data.get("auto_send_confirmation"))
        ):
            raise ValueError("auto_send_confirmation_required")
        row.review_mode = review_mode
    if "data_source" in data and data["data_source"] is not None:
        row.data_source = data["data_source"]
    if "source_query" in data:
        row.source_query = _clean_source_query(data["source_query"])
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return _watchlist_schema(row, db=db)


def update_contact_watchlist_review_mode(
    db: Session,
    contact_id: int,
    update: schemas.ContactWatchlistReviewModeUpdate,
):
    contact = get_contact(db, contact_id)
    if not contact:
        return None

    review_mode = _normalize_watchlist_review_mode(update.review_mode)
    if review_mode == "auto_send_approved" and not _auto_send_confirmation_valid(update.auto_send_confirmation):
        raise ValueError("auto_send_confirmation_required")

    rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.contact_id == contact_id)
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    now = _utcnow()
    for row in rows:
        row.review_mode = review_mode
        row.updated_at = now
        db.add(row)
    db.commit()
    return [_watchlist_schema(row, db=db) for row in rows]


def update_contact_watchlist_schedule(
    db: Session,
    contact_id: int,
    update: schemas.ContactWatchlistScheduleUpdate,
):
    contact = get_contact(db, contact_id)
    if not contact:
        return None

    schedule = _parse_schedule(update.schedule)
    next_check_at = _next_scheduled_check(schedule)
    rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.contact_id == contact_id)
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    now = _utcnow()
    for row in rows:
        row.schedule_json = _json_dumps(schedule)
        row.next_check_at = next_check_at
        row.updated_at = now
        db.add(row)
    db.commit()
    return [_watchlist_schema(row, db=db) for row in rows]


def update_contact_watchlist_notification_channel(
    db: Session,
    contact_id: int,
    update: schemas.ContactWatchlistNotificationChannelUpdate,
):
    contact = get_contact(db, contact_id)
    if not contact:
        return None

    notification_channel = _normalize_watchlist_notification_channel(update.notification_channel)
    rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.contact_id == contact_id)
        .order_by(models.ClientWatchlist.created_at.asc())
        .all()
    )
    now = _utcnow()
    for row in rows:
        row.notification_channel = notification_channel
        row.updated_at = now
        db.add(row)
    db.commit()
    return [_watchlist_schema(row, db=db) for row in rows]


def get_watchlist_alerts(db: Session, status: str | None = None, contact_id: int | None = None):
    query = db.query(models.WatchlistAlert).order_by(models.WatchlistAlert.created_at.desc())
    if status:
        query = query.filter(models.WatchlistAlert.status == status)
    if contact_id is not None:
        query = query.filter(models.WatchlistAlert.contact_id == contact_id)
    return [_alert_schema(row) for row in query.all()]


def update_watchlist_alert(db: Session, alert_id: int, update: schemas.WatchlistAlertUpdate):
    row = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert_id).first()
    if not row:
        return None
    allowed = {"pending_review", "draft_created", "dismissed", "sent"}
    if update.status not in allowed:
        return None
    row.status = update.status
    row.reviewed_at = _utcnow() if update.status in {"dismissed", "draft_created"} else None
    db.commit()
    db.refresh(row)
    return _alert_schema(row)


def _property_address(prop: models.Property) -> str:
    parts = [prop.unit, prop.street, prop.city, prop.province]
    return ", ".join(str(part) for part in parts if part)


def _price_for_property(prop: models.Property, watch_type: str) -> float | None:
    if watch_type in {"tenant_rental_match", "landlord_rental_market"}:
        return prop.monthly_rent
    return prop.sold_price if prop.status == "sold" else prop.listing_price


def _watchlist_statuses(watch_type: str) -> set[str]:
    if watch_type == "buyer_listing_match":
        return {"listed_for_sale"}
    if watch_type == "seller_listing_and_sold":
        return {"listed_for_sale", "sold"}
    if watch_type == "tenant_rental_match":
        return {"listed_for_rent"}
    if watch_type == "landlord_rental_market":
        return {"listed_for_rent", "rented"}
    return {"listed_for_sale"}


def _property_alert_type(prop: models.Property, watch_type: str) -> str:
    if prop.status == "sold":
        return "sold_comp"
    if prop.status == "rented":
        return "leased_comp"
    if prop.status == "listed_for_rent":
        return "new_rental_listing"
    return "new_listing"


def _normalize_property_type(value: str | None) -> str:
    text = (value or "").lower().replace("-", " ").replace("_", " ")
    if "town" in text or "twn" in text:
        return "townhouse"
    if "detach" in text:
        return "detached"
    if "semi" in text:
        return "semi"
    if "condo" in text or "apartment" in text:
        return "condo"
    return text.strip()


def _matches_text_area(prop: models.Property, areas: list[str]) -> tuple[bool, str | None]:
    if not areas:
        return True, None
    haystack = " ".join(
        str(value or "")
        for value in [prop.street, prop.city, prop.neighborhood, prop.postal_code, prop.notes]
    ).lower()
    for area in areas:
        if area.lower() in haystack:
            return True, area
    return False, None


def _deal_breaker_matches(deal_breaker: str, searchable: str) -> bool:
    text = deal_breaker.lower()
    if text in searchable:
        return True

    # Deal breakers are often written as a sentence. Extract meaningful place or
    # feature tokens so "Mississauga properties in Malton (excluded)" excludes
    # Malton even when the full sentence is not present in the listing notes.
    in_place = re.search(r"\bin\s+([a-zA-Z][a-zA-Z0-9-]{2,})", text)
    if in_place:
        return in_place.group(1) in searchable

    ignored = {
        "properties", "property", "excluded", "exclude", "without", "with",
        "listing", "listings", "area", "areas", "in", "the", "and", "or",
        "not", "no", "counting", "basement",
    }
    tokens = [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text)
        if token not in ignored
    ]
    return any(token in searchable for token in tokens)


def _score_property_match(prop: models.Property, watchlist: models.ClientWatchlist, criteria: dict) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0

    allowed_statuses = _watchlist_statuses(watchlist.watch_type)
    if prop.status not in allowed_statuses:
        return 0, []
    score += 20

    types = [_normalize_property_type(item) for item in _coerce_string_list(criteria.get("types"))]
    prop_type = _normalize_property_type(prop.property_type)
    if types:
        if prop_type not in types:
            return 0, []
        score += 25
        reasons.append(f"property type matches {prop.property_type}")

    areas = _coerce_string_list(criteria.get("areas"))
    area_match, matched_area = _matches_text_area(prop, areas)
    if not area_match:
        return 0, []
    if matched_area:
        score += 25
        reasons.append(f"area matches {matched_area}")

    price = _price_for_property(prop, watchlist.watch_type)
    min_price = criteria.get("min_price")
    max_price = criteria.get("max_price")
    if price is not None:
        if min_price is not None and price < float(min_price):
            return 0, []
        if max_price is not None and price > float(max_price):
            return 0, []
        if min_price is not None or max_price is not None:
            score += 20
            reasons.append("price is within client range")

    bedrooms_min = criteria.get("bedrooms_min")
    if bedrooms_min is not None and prop.bedrooms is not None:
        if prop.bedrooms < int(bedrooms_min):
            return 0, []
        score += 8
        reasons.append("bedrooms meet minimum")

    parking_min = criteria.get("parking_min")
    if parking_min is not None and prop.parking is not None:
        if prop.parking < int(parking_min):
            return 0, []
        score += 8
        reasons.append("parking meets minimum")

    bathrooms_min = criteria.get("bathrooms_min")
    if bathrooms_min is not None and prop.bathrooms is not None:
        if prop.bathrooms < int(bathrooms_min):
            return 0, []
        score += 6
        reasons.append("bathrooms meet minimum")

    must_haves = _coerce_string_list(criteria.get("must_haves"))
    searchable = " ".join(str(value or "") for value in [prop.street, prop.neighborhood, prop.notes, prop.property_type]).lower()
    deal_breakers = _coerce_string_list(criteria.get("deal_breakers"))
    for deal_breaker in deal_breakers:
        if _deal_breaker_matches(deal_breaker, searchable):
            return 0, []

    for must_have in must_haves:
        if must_have.lower() in searchable:
            score += 4
            reasons.append(f"mentions {must_have}")

    if watchlist.watch_type in {"seller_listing_and_sold", "landlord_rental_market"} and prop.status in {"sold", "rented"}:
        score += 15
        reasons.append("recent comparable outcome")

    return min(score, 100), reasons


def _property_evidence_payload(
    prop: models.Property,
    watchlist: models.ClientWatchlist,
    criteria: dict,
    reasons: list[str],
    score: int,
) -> dict:
    price = _price_for_property(prop, watchlist.watch_type)
    freshness = _property_freshness_payload(prop)
    source_date = None
    if prop.status == "sold":
        source_date = _format_source_date(prop.sold_at)
    elif prop.status == "rented":
        source_date = _format_source_date(prop.leased_at)
    elif prop.status in {"listed_for_sale", "listed_for_rent"}:
        source_date = _format_source_date(prop.listed_at)
    matched: list[str] = list(reasons)
    cautions: list[str] = []
    review_items: list[str] = []

    if source_date:
        matched.append(f"date: {source_date}")
    if freshness.get("freshness_note"):
        matched.append(f"freshness: {freshness['freshness_note']}")
    if prop.mls_number:
        matched.append(f"MLS/reference: {prop.mls_number}")
    if prop.status:
        matched.append(f"status: {prop.status.replace('_', ' ')}")
    if price is not None:
        rent = watchlist.watch_type in {"tenant_rental_match", "landlord_rental_market"}
        matched.append(f"price/rent: {_format_money(price, rent=rent)}")

    must_haves = _coerce_string_list(criteria.get("must_haves"))
    searchable = " ".join(str(value or "") for value in [prop.street, prop.neighborhood, prop.notes, prop.property_type]).lower()
    missing_must_haves = [item for item in must_haves if item.lower() not in searchable]
    if missing_must_haves:
        cautions.append(f"Not explicitly confirmed in source row: {', '.join(missing_must_haves[:4])}.")

    if not prop.listing_url:
        review_items.append("Open the original REALM/TRREB row before sending because no source URL was imported.")
    if prop.bedrooms is None:
        review_items.append("Confirm bedroom count from the source sheet.")
    if prop.bathrooms is None:
        review_items.append("Confirm bathroom count from the source sheet.")
    if prop.parking is None and criteria.get("parking_min") is not None:
        review_items.append("Confirm parking/garage count from the source sheet.")
    if price is None:
        review_items.append("Confirm price/rent from the source sheet.")
    if freshness.get("freshness_status") == "stale":
        cautions.append(str(freshness["freshness_note"]))
        review_items.append("Verify the original source date before calling this a new market update.")
    elif freshness.get("freshness_status") == "unknown":
        cautions.append(str(freshness["freshness_note"]))
        review_items.append("Confirm the source date before calling this a new market update.")

    if watchlist.watch_type == "seller_listing_and_sold":
        review_items.append("Use this as pricing context only after confirming condition, lot, upgrades, and timing in REALM/TRREB.")
    elif watchlist.watch_type == "landlord_rental_market":
        review_items.append("Use this as rental positioning context after confirming lease date, inclusions, and condition.")
    elif watchlist.watch_type == "tenant_rental_match":
        review_items.append("Confirm availability, showing access, lease term, and tenant restrictions before recommending.")
    else:
        review_items.append("Confirm listing availability, offer date, and any exclusions before recommending.")

    if not cautions:
        cautions.append("No obvious mismatch from the imported source row; still verify the original listing before sending.")

    return {
        "match_score": score,
        "matched_criteria": _unique_nonempty(matched),
        "cautions": _unique_nonempty(cautions),
        "kevin_review_items": _unique_nonempty(review_items),
        "source_date": source_date,
        **freshness,
    }


def _localize_evidence_item(item: str, language: str) -> str:
    if language != "zh-tw":
        return item
    text = str(item)
    lower = text.lower()
    replacements = [
        ("property type matches", "房型符合"),
        ("area matches", "區域符合"),
        ("price is within client range", "價格在客戶條件範圍內"),
        ("bedrooms meet minimum", "房間數符合最低需求"),
        ("bathrooms meet minimum", "衛浴數符合最低需求"),
        ("parking meets minimum", "停車位/車庫符合最低需求"),
        ("recent comparable outcome", "近期成交/租出結果可作參考"),
        ("status:", "狀態："),
        ("date:", "日期："),
        ("price/rent:", "價格/租金："),
        ("MLS/reference:", "MLS/來源編號："),
    ]
    for source, target in replacements:
        if lower.startswith(source.lower()):
            return target + text[len(source):]
        if lower == source.lower():
            return target
    if lower.startswith("mentions "):
        return "來源資料提到：" + text[len("mentions "):]
    if lower.startswith("freshness:"):
        return "資料新鮮度：" + _localize_evidence_item(text.split(":", 1)[1].strip(), language)
    if lower.startswith("source date is today"):
        return "來源日期是今天。"
    if lower.startswith("source date is") and "old; treat this as a recent listing" in lower:
        age = re.search(r"source date is\s+(\d+)\s+day", lower)
        days = age.group(1) if age else ""
        return f"來源日期距今 {days} 天；可作為近期房源，但不一定是今天新上。" if days else "來源日期屬於近期房源，但不一定是今天新上。"
    if lower.startswith("source date is") and "old; treat this as a recent sold/leased comp" in lower:
        age = re.search(r"source date is\s+(\d+)\s+day", lower)
        days = age.group(1) if age else ""
        return f"來源日期距今 {days} 天；可作為近期成交/租出參考，但不一定是今天更新。" if days else "來源日期屬於近期成交/租出參考，但不一定是今天更新。"
    if lower.startswith("source date is") and "older listing context" in lower:
        age = re.search(r"source date is\s+(\d+)\s+day", lower)
        days = age.group(1) if age else ""
        return f"來源日期距今 {days} 天；除非 REALM/TRREB 確認仍有效，否則只能當作較舊房源參考。" if days else "來源日期較舊；除非 REALM/TRREB 確認仍有效，否則只能當作較舊房源參考。"
    if lower.startswith("source date is") and "older sold/leased comp context" in lower:
        age = re.search(r"source date is\s+(\d+)\s+day", lower)
        days = age.group(1) if age else ""
        return f"來源日期距今 {days} 天；除非 REALM/TRREB 確認，否則只能當作較舊成交/租出參考。" if days else "來源日期較舊；除非 REALM/TRREB 確認，否則只能當作較舊成交/租出參考。"
    if lower.startswith("source date is missing"):
        return "來源日期缺失；寄出前要確認是否真的是新的市場更新。"
    if lower.startswith("not explicitly confirmed in source row:"):
        return "來源資料未明確確認：" + text.split(":", 1)[1].strip()
    if lower.startswith("no obvious mismatch"):
        return "來源資料沒有顯示明顯不符，但寄出前仍要確認原始 listing。"
    if lower.startswith("open the original realm/trreb row"):
        return "因為沒有匯入來源 URL，寄出前要打開原始 REALM/TRREB 資料確認。"
    if lower.startswith("confirm bedroom count"):
        return "寄出前確認房間數。"
    if lower.startswith("confirm bathroom count"):
        return "寄出前確認衛浴數。"
    if lower.startswith("confirm parking/garage count"):
        return "寄出前確認停車位/車庫數。"
    if lower.startswith("confirm price/rent"):
        return "寄出前確認價格/租金。"
    if lower.startswith("use this as pricing context"):
        return "這只能作為定價參考，寄出前仍要確認屋況、地段、升級、時間點。"
    if lower.startswith("use this as rental positioning"):
        return "這只能作為租金定位參考，寄出前仍要確認租出日期、包含項目與屋況。"
    if lower.startswith("confirm availability"):
        return "寄出前確認可租狀態、看房安排、租期與限制。"
    if lower.startswith("confirm listing availability"):
        return "寄出前確認 listing 是否仍有效、offer date 與 exclusions。"
    if lower.startswith("matched the saved"):
        return "符合 CRM 裡儲存的客戶條件。"
    if lower.startswith("verify the original source date"):
        return "寄出前確認原始來源日期，避免把舊資料說成新消息。"
    if lower.startswith("verify the original source"):
        return "寄出前確認原始來源資料。"
    if lower.startswith("confirm the source date"):
        return "寄出前確認來源日期，避免把未確認日期的資料說成新消息。"
    if lower.startswith("confirm details in the original"):
        return "寄出前在原始 REALM/TRREB 來源確認細節。"
    return text


def _matching_properties_for_watchlist(
    db: Session,
    watchlist: models.ClientWatchlist,
) -> list[models.Property]:
    criteria = _json_object(watchlist.criteria_json)
    statuses = _watchlist_statuses(watchlist.watch_type)
    candidates = (
        db.query(models.Property)
        .filter(models.Property.status.in_(statuses))
        .all()
    )
    matches: list[models.Property] = []
    for prop in _sort_properties_by_recency(candidates):
        score, _reasons = _score_property_match(prop, watchlist, criteria)
        if score >= WATCHLIST_MATCH_SCORE_THRESHOLD:
            matches.append(prop)
    return matches


def _format_money(value: float | None, rent: bool = False) -> str:
    if value is None:
        return "price not available"
    suffix = "/mo" if rent else ""
    return f"${value:,.0f}{suffix}"


def _build_alert_summary(prop: models.Property, watch_type: str) -> str:
    price = _price_for_property(prop, watch_type)
    rent = watch_type in {"tenant_rental_match", "landlord_rental_market"}
    details = [
        _property_address(prop),
        prop.status.replace("_", " "),
        prop.property_type,
        _format_money(price, rent=rent),
    ]
    if prop.bedrooms is not None:
        details.append(f"{prop.bedrooms} bed")
    if prop.parking is not None:
        details.append(f"{prop.parking} parking")
    return " | ".join(str(item) for item in details if item)


def _client_language(contact: models.Contact) -> str:
    return "zh-tw" if (contact.preferred_language or "").lower().startswith("zh") else "en"


def _build_alert_analysis(contact: models.Contact, watchlist: models.ClientWatchlist, prop: models.Property, reasons: list[str]) -> str:
    summary = _build_alert_summary(prop, watchlist.watch_type)
    criteria = _json_object(watchlist.criteria_json)
    score, _scored_reasons = _score_property_match(prop, watchlist, criteria)
    evidence = _property_evidence_payload(prop, watchlist, criteria, reasons, score)
    caution_text = "；".join(evidence["cautions"][:2])
    if _client_language(contact) == "zh-tw":
        localized_reasons = [_localize_evidence_item(item, "zh-tw") for item in reasons]
        localized_cautions = [_localize_evidence_item(item, "zh-tw") for item in evidence["cautions"][:2]]
        reason_text = "、".join(localized_reasons) if localized_reasons else "符合目前儲存的條件"
        caution_text = "；".join(localized_cautions)
        if watchlist.watch_type == "seller_listing_and_sold":
            return (
                f"這筆資料值得給 {contact.name} 參考，因為它和目前要觀察的房型/區域條件接近，"
                f"可用來判斷附近競爭房源或成交行情。比對分數：{score}/100。"
                f"比對原因：{reason_text}。需要確認：{caution_text}。資料摘要：{summary}。"
            )
        if watchlist.watch_type == "tenant_rental_match":
            return (
                f"這筆租盤符合 {contact.name} 的租屋條件，可以先放入 draft 給你確認。"
                f"比對分數：{score}/100。比對原因：{reason_text}。需要確認：{caution_text}。資料摘要：{summary}。"
            )
        if watchlist.watch_type == "landlord_rental_market":
            return (
                f"這筆租賃市場資料可協助 {contact.name} 判斷同社區附近租金與競爭狀況。"
                f"比對分數：{score}/100。比對原因：{reason_text}。需要確認：{caution_text}。資料摘要：{summary}。"
            )
        return (
            f"這筆房源符合 {contact.name} 目前儲存的買房條件，可以先給你 review。"
            f"比對分數：{score}/100。比對原因：{reason_text}。需要確認：{caution_text}。資料摘要：{summary}。"
        )

    reason_text = ", ".join(reasons) if reasons else "it matches the saved criteria"
    caution_text_en = " ".join(evidence["cautions"][:2])
    return (
        f"This item is relevant for {contact.name} because {reason_text}. "
        f"Match score: {score}/100. Check before sending: {caution_text_en} Summary: {summary}."
    )


def _alert_title(prop: models.Property, alert_type: str) -> str:
    labels = {
        "new_listing": "New listing match",
        "sold_comp": "Sold comparable",
        "new_rental_listing": "New rental match",
        "leased_comp": "Leased comparable",
    }
    return f"{labels.get(alert_type, 'Watchlist alert')}: {_property_address(prop)}"


def _dedupe_alert_exists(db: Session, watchlist_id: int, property_id: int | None, alert_type: str, source: str) -> bool:
    query = (
        db.query(models.WatchlistAlert)
        .filter(models.WatchlistAlert.watchlist_id == watchlist_id)
        .filter(models.WatchlistAlert.alert_type == alert_type)
        .filter(models.WatchlistAlert.source == source)
    )
    if property_id is None:
        query = query.filter(models.WatchlistAlert.property_id == None)
    else:
        query = query.filter(models.WatchlistAlert.property_id == property_id)
    return query.first() is not None


def _create_watchlist_alert(
    db: Session,
    watchlist: models.ClientWatchlist,
    prop: models.Property,
    score: int,
    reasons: list[str],
) -> models.WatchlistAlert | None:
    alert_type = _property_alert_type(prop, watchlist.watch_type)
    source = watchlist.data_source or "internal_properties"
    if _dedupe_alert_exists(db, watchlist.id, prop.id, alert_type, source):
        return None

    criteria = _json_object(watchlist.criteria_json)
    evidence = _property_evidence_payload(prop, watchlist, criteria, reasons, score)
    alert = models.WatchlistAlert(
        watchlist_id=watchlist.id,
        contact_id=watchlist.contact_id,
        property_id=prop.id,
        alert_type=alert_type,
        title=_alert_title(prop, alert_type),
        summary=_build_alert_summary(prop, watchlist.watch_type),
        analysis=_build_alert_analysis(watchlist.contact, watchlist, prop, reasons),
        source=source,
        source_url=prop.listing_url,
        payload_json=_json_dumps({
            **evidence,
            "reasons": reasons,
            "mls_number": prop.mls_number,
            "property_status": prop.status,
        }),
        status="pending_review",
    )
    db.add(alert)
    db.flush()
    return alert


def _record_watchlist_notification(
    db: Session,
    alert: models.WatchlistAlert,
    channel: str,
    status: str,
    error: str | None = None,
    body: str | None = None,
    title: str | None = None,
) -> models.WatchlistNotification:
    notification = models.WatchlistNotification(
        alert_id=alert.id,
        watchlist_id=alert.watchlist_id,
        contact_id=alert.contact_id,
        channel=channel,
        status=status,
        title=title or alert.title,
        body=body or alert.summary,
        error=error,
        delivered_at=_utcnow() if status in {"sent", "queued_for_codex_report", "queued_in_app"} else None,
    )
    db.add(notification)
    db.flush()
    return notification


def _draft_state_for_notification(contact: models.Contact | None, interaction: models.Interaction | None) -> str:
    if not interaction:
        return "Draft: not created yet."

    status = interaction.generated_response_status or "pending_review"
    status_text = status.replace("_", " ")
    payload = _json_object(interaction.generated_response_content)
    gmail_meta = payload.get("gmail") if isinstance(payload.get("gmail"), dict) else {}
    gmail_draft_id = str(gmail_meta.get("draft_id") or "").strip()
    gmail_message_id = str(gmail_meta.get("sent_message_id") or gmail_meta.get("message_id") or "").strip()

    if status == "gmail_draft_created":
        suffix = f" Gmail draft id: {gmail_draft_id}." if gmail_draft_id else ""
        return f"Draft: Gmail draft created and waiting for Kevin review.{suffix}"
    if status == "sent":
        suffix = f" Gmail message id: {gmail_message_id}." if gmail_message_id else ""
        return f"Delivery: Gmail message marked sent in CRM.{suffix}"
    if contact and not str(contact.email or "").strip():
        return "Draft: CRM review draft prepared, but Gmail draft creation is blocked until the client email is added."
    return f"Draft: CRM review draft prepared. Status: {status_text}."


def _watchlist_review_path(
    contact_id: int | None = None,
    alert_id: int | None = None,
    watchlist_id: int | None = None,
) -> str:
    params: list[str] = []
    if contact_id:
        params.append(f"contact_id={contact_id}")
    if alert_id:
        params.append(f"alert_id={alert_id}")
    if watchlist_id:
        params.append(f"watchlist_id={watchlist_id}")
    return f"/watchlists?{'&'.join(params)}" if params else "/watchlists"


def _watchlist_notification_body(alert: models.WatchlistAlert) -> str:
    draft_state = _draft_state_for_notification(alert.contact, alert.interaction)
    payload = _json_object(alert.payload_json)

    delivery_line = None
    if alert.contact and not str(alert.contact.email or "").strip():
        delivery_line = "Delivery: client email is missing, so Gmail draft creation is blocked until the email is added."

    source_line = f"Source: {alert.source or 'internal_properties'}."
    if alert.source_url:
        source_line = f"{source_line} URL: {alert.source_url}"
    freshness_note = str(payload.get("freshness_note") or "").strip()
    freshness_line = f"Freshness: {freshness_note}" if freshness_note else None

    lines = [
        f"Property: {alert.summary}",
        f"Why it matches: {alert.analysis}",
        draft_state,
    ]
    if delivery_line:
        lines.append(delivery_line)
    if freshness_line:
        lines.append(freshness_line)
    lines.extend(
        [
            source_line,
            f"Review in CRM: {_watchlist_review_path(alert.contact_id, alert.id, alert.watchlist_id)}",
            "Next: review the alert and draft before sending any client email.",
        ]
    )
    return "\n".join(lines)[:1800]


def _watchlist_digest_notification_body(
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
) -> str:
    alerts = _sort_alerts_by_recency(alerts)
    primary_alert = alerts[0] if alerts else None
    contact = watchlist.contact
    interaction = next((alert.interaction for alert in alerts if alert.interaction), None)
    active_count = sum(1 for alert in alerts if alert.alert_type in {"new_listing", "new_rental_listing"})
    outcome_count = sum(1 for alert in alerts if alert.alert_type in {"sold_comp", "leased_comp"})
    source_names = sorted({alert.source or "internal_properties" for alert in alerts})
    freshness_notes = _unique_nonempty(
        str(_json_object(alert.payload_json).get("freshness_note") or "").strip()
        for alert in alerts
    )
    items = []
    for index, alert in enumerate(alerts[:5], start=1):
        items.append(f"{index}. {alert.summary}\n   Why: {alert.analysis}")
    remaining = len(alerts) - len(items)
    if remaining > 0:
        items.append(f"...and {remaining} more item(s) in the CRM alert queue.")

    if contact:
        why_line = _digest_market_snapshot(contact, watchlist, alerts)
    else:
        why_line = f"The watchlist matched {len(alerts)} new market item(s)."

    lines = [
        f"Digest: {len(alerts)} matching item(s) for {contact.name if contact else watchlist.name}.",
        f"Breakdown: {active_count} active/new item(s), {outcome_count} sold/leased comp(s).",
        f"Why notify: {why_line}",
        _draft_state_for_notification(contact, interaction),
    ]
    if contact and not str(contact.email or "").strip():
        lines.append("Delivery: client email is missing, so Gmail draft creation is blocked until the email is added.")
    if freshness_notes:
        lines.append(f"Freshness: {' | '.join(freshness_notes[:3])}")
    lines.extend(
        [
            f"Source: {', '.join(source_names)}.",
            f"Review in CRM: {_watchlist_review_path(watchlist.contact_id, primary_alert.id if primary_alert else None, watchlist.id)}",
            "Items:",
            "\n".join(items),
            "Next: review the digest draft and source rows before sending any client email.",
        ]
    )
    return "\n".join(lines)[:3000]


def _notify_watchlist_alert(db: Session, watchlist: models.ClientWatchlist, alert: models.WatchlistAlert):
    channel = _watchlist_notification_channel_or_default(watchlist.notification_channel)
    body = _watchlist_notification_body(alert)

    if channel == "codex_app":
        _record_watchlist_notification(db, alert, channel, "queued_for_codex_report", body=body)
        return 1

    if channel == "in_app":
        _record_watchlist_notification(db, alert, channel, "queued_in_app", body=body)
        return 1

    if channel != "app_push":
        _record_watchlist_notification(db, alert, channel, "unsupported_channel", f"Unsupported channel: {channel}")
        return 0

    subscriptions = db.query(models.PushSubscription).all()
    if not subscriptions:
        _record_watchlist_notification(db, alert, channel, "no_subscriptions", "No browser/app push subscriptions are saved.")
        return 0

    payload = {
        "title": alert.title,
        "body": body,
        "tag": "watchlist-alert",
        "data": {
            "url": _watchlist_review_path(alert.contact_id, alert.id, alert.watchlist_id),
            "alertId": alert.id,
            "contactId": alert.contact_id,
        },
    }
    sent = 0
    failed = 0
    for sub in subscriptions:
        if _send_push(sub, payload):
            sent += 1
        else:
            failed += 1

    if sent:
        status = "sent" if failed == 0 else "partial"
        _record_watchlist_notification(db, alert, channel, status, body=body)
    else:
        _record_watchlist_notification(db, alert, channel, "failed", "All saved push subscriptions failed.")
    return sent


def _notify_watchlist_digest(
    db: Session,
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
) -> int:
    if not alerts:
        return 0

    alerts = _sort_alerts_by_recency(alerts)
    channel = _watchlist_notification_channel_or_default(watchlist.notification_channel)
    alert = alerts[0]
    title = f"{watchlist.contact.name if watchlist.contact else watchlist.name}: {len(alerts)} watchlist update(s)"
    body = _watchlist_digest_notification_body(watchlist, alerts)

    if channel == "codex_app":
        _record_watchlist_notification(
            db,
            alert,
            channel,
            "queued_for_codex_report",
            body=body,
            title=title,
        )
        return 1

    if channel == "in_app":
        _record_watchlist_notification(db, alert, channel, "queued_in_app", body=body, title=title)
        return 1

    if channel != "app_push":
        _record_watchlist_notification(
            db,
            alert,
            channel,
            "unsupported_channel",
            f"Unsupported channel: {channel}",
            title=title,
        )
        return 0

    subscriptions = db.query(models.PushSubscription).all()
    if not subscriptions:
        _record_watchlist_notification(
            db,
            alert,
            channel,
            "no_subscriptions",
            "No browser/app push subscriptions are saved.",
            title=title,
        )
        return 0

    payload = {
        "title": title,
        "body": body,
        "tag": f"watchlist-digest-{watchlist.id}",
        "data": {
            "url": _watchlist_review_path(alert.contact_id, alert.id, watchlist.id),
            "alertId": alert.id,
            "contactId": alert.contact_id,
            "watchlistId": watchlist.id,
        },
    }
    sent = 0
    failed = 0
    for sub in subscriptions:
        if _send_push(sub, payload):
            sent += 1
        else:
            failed += 1

    if sent:
        status = "sent" if failed == 0 else "partial"
        _record_watchlist_notification(db, alert, channel, status, body=body, title=title)
    else:
        _record_watchlist_notification(db, alert, channel, "failed", "All saved push subscriptions failed.", title=title)
    return sent


def _watchlist_no_source_status(watchlist: models.ClientWatchlist, property_count: int) -> str:
    if (watchlist.data_source or "internal_properties") == "internal_properties" and property_count == 0:
        return "internal_property_source_empty"
    if (watchlist.data_source or "") != "internal_properties":
        return "external_source_not_connected"
    return "ok"


def run_watchlist_check(db: Session, watchlist_id: int):
    watchlist = get_watchlist(db, watchlist_id)
    if not watchlist:
        return None

    all_properties = db.query(models.Property).all()
    properties = _sort_properties_by_recency(all_properties)
    criteria = _json_object(watchlist.criteria_json)
    created_alerts: list[models.WatchlistAlert] = []
    matched_properties = 0

    for prop in properties:
        score, reasons = _score_property_match(prop, watchlist, criteria)
        if score < WATCHLIST_MATCH_SCORE_THRESHOLD:
            continue
        matched_properties += 1
        alert = _create_watchlist_alert(db, watchlist, prop, score, reasons)
        if alert:
            created_alerts.append(alert)

    watchlist.last_checked_at = _utcnow()
    watchlist.next_check_at = _next_scheduled_check(watchlist.schedule_json, after=watchlist.last_checked_at)
    watchlist.updated_at = _utcnow()

    auto_review_modes = {"auto_create_draft", "auto_gmail_draft", "auto_send_approved"}
    auto_interaction_id: int | None = None
    if created_alerts and watchlist.review_mode in auto_review_modes:
        if len(created_alerts) > 1:
            digest_result = _create_digest_draft_for_alert_rows(db, watchlist, created_alerts, commit=False)
            if digest_result and digest_result.success:
                auto_interaction_id = digest_result.interaction_id
        else:
            draft_result = create_draft_from_watchlist_alert(db, created_alerts[0].id, commit=False)
            if draft_result:
                auto_interaction_id = draft_result.interaction_id

    db.commit()
    db.refresh(watchlist)

    contact_email_present = bool(watchlist.contact and str(watchlist.contact.email or "").strip())
    if auto_interaction_id and watchlist.review_mode in {"auto_gmail_draft", "auto_send_approved"} and contact_email_present:
        try:
            from . import gmail_service

            draft_action = gmail_service.create_gmail_draft_for_interaction(db, auto_interaction_id)
            if watchlist.review_mode == "auto_send_approved":
                if not _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED"):
                    raise ValueError("watchlist_auto_send_disabled_gmail_draft_created")

                send_action = gmail_service.send_gmail_draft_for_interaction(
                    db,
                    auto_interaction_id,
                    confirm_send=True,
                )
                if send_action and send_action.status == "sent":
                    for alert in created_alerts:
                        refreshed = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert.id).first()
                        if refreshed:
                            refreshed.status = "sent"
                            refreshed.reviewed_at = _utcnow()
                            db.add(refreshed)
                    db.commit()
        except ValueError as exc:
            db.rollback()
            logger.warning(
                "Could not process Gmail action for watchlist %s interaction %s: %s",
                watchlist.id,
                auto_interaction_id,
                exc,
            )
    elif auto_interaction_id and watchlist.review_mode in {"auto_gmail_draft", "auto_send_approved"}:
        logger.info(
            "Skipped Gmail draft for watchlist %s interaction %s because the contact email is missing.",
            watchlist.id,
            auto_interaction_id,
        )

    refreshed_alerts = [
        db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert.id).first()
        for alert in created_alerts
    ]
    live_alerts = _sort_alerts_by_recency([alert for alert in refreshed_alerts if alert])
    if len(live_alerts) > 1:
        _notify_watchlist_digest(db, watchlist, live_alerts)
    else:
        for alert in live_alerts:
            _notify_watchlist_alert(db, watchlist, alert)
    if live_alerts:
        db.commit()
        db.refresh(watchlist)
        refreshed_alerts = [
            db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert.id).first()
            for alert in created_alerts
            if alert.id
        ]
        refreshed_alerts = _sort_alerts_by_recency([alert for alert in refreshed_alerts if alert])

    data_source_status = _watchlist_no_source_status(watchlist, len(all_properties))
    if created_alerts:
        message = f"Created {len(created_alerts)} new watchlist alert(s)."
    elif matched_properties:
        message = "Matching properties were already alerted earlier."
    elif data_source_status == "internal_property_source_empty":
        message = "No internal property/listing data is loaded yet. Connect MLS/REALM/TRREB or import properties before live matching."
    elif data_source_status == "external_source_not_connected":
        message = "External listing data source is not connected yet."
    else:
        message = "No matching properties found in the current source."

    return schemas.WatchlistCheckResponse(
        watchlist=_watchlist_schema(watchlist, db=db),
        alerts=[
            _alert_schema(alert)
            for alert in _sort_alerts_by_recency([alert for alert in refreshed_alerts if alert])
        ],
        created_count=len(created_alerts),
        matched_properties=matched_properties,
        data_source_status=data_source_status,
        message=message,
    )


def run_due_watchlists(db: Session, limit: int = 20):
    now = _utcnow()
    active = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.next_check_at.asc())
        .all()
    )

    initialized_schedule = False
    for watchlist in active:
        if watchlist.next_check_at is None:
            watchlist.next_check_at = _next_scheduled_check(watchlist.schedule_json, after=now)
            db.add(watchlist)
            initialized_schedule = True
    if initialized_schedule:
        db.commit()
        active = (
            db.query(models.ClientWatchlist)
            .filter(models.ClientWatchlist.status == "active")
            .order_by(models.ClientWatchlist.next_check_at.asc())
            .all()
        )

    due = [
        watchlist
        for watchlist in active
        if watchlist.next_check_at is not None and watchlist.next_check_at <= now
    ][:limit]
    results = []
    for watchlist in due:
        result = run_watchlist_check(db, watchlist.id)
        if result:
            results.append(result)

    checked_ids = {item.watchlist.id for item in results}
    next_watchlists = [
        {
            "id": watchlist.id,
            "name": watchlist.name,
            "contact_name": watchlist.contact.name if watchlist.contact else None,
            "schedule": _parse_schedule(watchlist.schedule_json),
            "last_checked_at": watchlist.last_checked_at,
            "next_check_at": watchlist.next_check_at,
            "notification_channel": _watchlist_notification_channel_or_default(watchlist.notification_channel),
            "review_mode": watchlist.review_mode or "manual_review",
        }
        for watchlist in active
        if watchlist.id not in checked_ids
    ][:10]
    return {
        "checked": len(results),
        "created_alerts": sum(item.created_count for item in results),
        "matched_properties": sum(item.matched_properties for item in results),
        "active_count": len(active),
        "due_count": len(due),
        "not_due_count": max(0, len(active) - len(due)),
        "checked_watchlists": [
            {
                "id": item.watchlist.id,
                "name": item.watchlist.name,
                "created_count": item.created_count,
                "matched_properties": item.matched_properties,
                "data_source_status": item.data_source_status,
                "message": item.message,
                "next_check_at": item.watchlist.next_check_at,
            }
            for item in results
        ],
        "next_watchlists": next_watchlists,
        "watchlists": [item.watchlist.name for item in results],
    }


def run_all_active_watchlists(db: Session, limit: int = 100):
    active = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.status == "active")
        .order_by(models.ClientWatchlist.created_at.asc())
        .limit(limit)
        .all()
    )
    results = []
    for watchlist in active:
        result = run_watchlist_check(db, watchlist.id)
        if result:
            results.append(result)

    return {
        "checked": len(results),
        "created_alerts": sum(item.created_count for item in results),
        "matched_properties": sum(item.matched_properties for item in results),
        "watchlists": [
            {
                "id": item.watchlist.id,
                "name": item.watchlist.name,
                "created_count": item.created_count,
                "matched_properties": item.matched_properties,
                "data_source_status": item.data_source_status,
                "message": item.message,
            }
            for item in results
        ],
    }


def _draft_subject_for_alert(contact: models.Contact, alert: models.WatchlistAlert) -> str:
    if _client_language(contact) == "zh-tw":
        if alert.alert_type == "sold_comp":
            return f"{contact.name}，附近類似房子的最新成交參考"
        if alert.alert_type == "leased_comp":
            return f"{contact.name}，附近類似房子的最新租出參考"
        if alert.alert_type == "new_rental_listing":
            return f"{contact.name}，幫你看到一個符合條件的租盤"
        return f"{contact.name}，幫你看到一個符合條件的房源"
    if alert.alert_type in {"sold_comp", "leased_comp"}:
        return f"{contact.name}, a comparable market update"
    return f"{contact.name}, a property that matches your criteria"


def _alert_evidence_payload(alert: models.WatchlistAlert) -> dict:
    payload = _json_object(alert.payload_json)
    return {
        "match_score": payload.get("match_score"),
        "matched_criteria": _coerce_string_list(payload.get("matched_criteria")),
        "cautions": _coerce_string_list(payload.get("cautions")),
        "kevin_review_items": _coerce_string_list(payload.get("kevin_review_items")),
        "source_date": payload.get("source_date"),
    }


def _draft_evidence_block(alert: models.WatchlistAlert, language: str) -> str:
    evidence = _alert_evidence_payload(alert)
    matched = [
        _localize_evidence_item(item, language)
        for item in (evidence["matched_criteria"] or ["Matched the saved CRM watchlist criteria."])
    ]
    cautions = [
        _localize_evidence_item(item, language)
        for item in (evidence["cautions"] or ["Verify the original source row before sending."])
    ]
    review_items = [
        _localize_evidence_item(item, language)
        for item in (evidence["kevin_review_items"] or ["Confirm details in the original REALM/TRREB source."])
    ]
    score = evidence.get("match_score")

    if language == "zh-tw":
        lines = []
        if score is not None:
            lines.append(f"比對分數：{score}/100")
        lines.extend(
            [
                "符合條件：",
                *[f"- {item}" for item in matched[:6]],
                "寄出前我會再確認：",
                *[f"- {item}" for item in [*cautions[:3], *review_items[:3]]],
            ]
        )
        return "\n".join(lines)

    lines = []
    if score is not None:
        lines.append(f"Match score: {score}/100")
    lines.extend(
        [
            "Matched criteria:",
            *[f"- {item}" for item in matched[:6]],
            "I will confirm before sending:",
            *[f"- {item}" for item in [*cautions[:3], *review_items[:3]]],
        ]
    )
    return "\n".join(lines)


def _draft_body_for_alert(contact: models.Contact, alert: models.WatchlistAlert) -> str:
    language = _client_language(contact)
    evidence_block = _draft_evidence_block(alert, language)
    if language == "zh-tw":
        return f"""Hi {contact.name},

我幫你留意到一筆和你目前需求接近的市場資料：

{alert.summary}

為什麼我覺得值得給你參考：
{alert.analysis}

{evidence_block}

這封信我先整理成重點，等你確認有興趣後，我可以再幫你看更完整的細節、安排下一步，或拿它來和附近類似房子的行情做比較。

Regards,
Kevin Chou
"""
    return f"""Hi {contact.name},

I found a market update that is close to your current criteria:

{alert.summary}

Why I think it is relevant:
{alert.analysis}

{evidence_block}

I wanted to send you the key points first. If it looks interesting, I can review the full details and compare it with similar nearby properties.

Regards,
Kevin Chou
"""


def _draft_subject_for_watchlist_digest(
    contact: models.Contact,
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
) -> str:
    count = len(alerts)
    if _client_language(contact) == "zh-tw":
        if watchlist.watch_type == "seller_listing_and_sold":
            return f"{contact.name}，附近房源與成交參考整理（{count} 筆）"
        if watchlist.watch_type == "tenant_rental_match":
            return f"{contact.name}，符合條件的租盤整理（{count} 筆）"
        if watchlist.watch_type == "landlord_rental_market":
            return f"{contact.name}，附近租賃市場參考整理（{count} 筆）"
        return f"{contact.name}，符合條件的房源整理（{count} 筆）"
    if watchlist.watch_type in {"seller_listing_and_sold", "landlord_rental_market"}:
        return f"{contact.name}, comparable market update ({count} items)"
    return f"{contact.name}, matching property shortlist ({count} items)"


def _criteria_phrase(criteria: dict) -> str:
    parts: list[str] = []
    areas = _coerce_string_list(criteria.get("areas"))
    types = _coerce_string_list(criteria.get("types"))
    must_haves = _coerce_string_list(criteria.get("must_haves"))
    if areas:
        parts.append(", ".join(areas))
    if types:
        parts.append(", ".join(types))
    if criteria.get("property_address"):
        parts.append(str(criteria.get("property_address")))
    if criteria.get("max_price"):
        parts.append(f"max {_format_money(float(criteria['max_price']))}")
    if criteria.get("bedrooms_min"):
        parts.append(f"{criteria.get('bedrooms_min')}+ bed")
    if criteria.get("parking_min"):
        parts.append(f"{criteria.get('parking_min')}+ parking")
    if must_haves:
        parts.append(", ".join(must_haves[:3]))
    return "; ".join(parts)


def _alert_price_values(alerts: list[models.WatchlistAlert], watch_type: str) -> list[float]:
    values: list[float] = []
    for alert in alerts:
        prop = alert.property
        if not prop:
            continue
        price = _price_for_property(prop, watch_type)
        if price is not None:
            values.append(float(price))
    return values


def _price_range_text(values: list[float], rent: bool = False) -> str:
    if not values:
        return "price details are still being verified"
    low = min(values)
    high = max(values)
    if low == high:
        return _format_money(low, rent=rent)
    return f"{_format_money(low, rent=rent)} to {_format_money(high, rent=rent)}"


def _digest_source_date_text(alerts: list[models.WatchlistAlert], language: str) -> str:
    dates = [
        _format_source_date(source_dt)
        for source_dt in (_alert_source_datetime(alert) for alert in alerts)
        if source_dt
    ]
    dates = sorted({date for date in dates if date})
    if not dates:
        return "資料日期仍需以原始來源確認。" if language == "zh-tw" else "Source dates still need to be confirmed from the original source."
    if len(dates) == 1:
        return f"最新資料日期：{dates[-1]}。" if language == "zh-tw" else f"Latest source date: {dates[-1]}."
    if language == "zh-tw":
        return f"最新資料日期：{dates[-1]}；資料期間：{dates[0]} 至 {dates[-1]}。"
    return f"Latest source date: {dates[-1]}; source date range: {dates[0]} to {dates[-1]}."


def _digest_market_snapshot(
    contact: models.Contact,
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
) -> str:
    criteria = _json_object(watchlist.criteria_json)
    criteria_text = _criteria_phrase(criteria)
    active_count = sum(1 for alert in alerts if alert.alert_type in {"new_listing", "new_rental_listing"})
    outcome_count = sum(1 for alert in alerts if alert.alert_type in {"sold_comp", "leased_comp"})
    rent = watchlist.watch_type in {"tenant_rental_match", "landlord_rental_market"}
    price_range = _price_range_text(_alert_price_values(alerts, watchlist.watch_type), rent=rent)
    date_text = _digest_source_date_text(alerts, _client_language(contact))

    if _client_language(contact) == "zh-tw":
        criteria_sentence = f"目前條件：{criteria_text}。" if criteria_text else "目前依照已儲存的客戶條件比對。"
        if watchlist.watch_type == "seller_listing_and_sold":
            return (
                f"這次值得寄給你，因為系統找到 {len(alerts)} 筆和賣方標的接近的資料，"
                f"其中 {active_count} 筆是附近競爭房源，{outcome_count} 筆是成交參考。"
                f"價格範圍約 {price_range}。{date_text}{criteria_sentence} "
                "這些資料可以幫我們判斷定價、上市時間，以及是否需要先做最基本但能提升呈現效果的整理。"
            )
        if watchlist.watch_type == "landlord_rental_market":
            return (
                f"這次值得寄給你，因為系統找到 {len(alerts)} 筆附近租賃市場資料，"
                f"其中 {active_count} 筆是競爭租盤，{outcome_count} 筆是已租出參考。"
                f"租金範圍約 {price_range}。{date_text}{criteria_sentence} "
                "這些資料可以幫我們判斷租金定位與市場競爭狀況。"
            )
        if watchlist.watch_type == "tenant_rental_match":
            return (
                f"這次值得寄給你，因為系統找到 {len(alerts)} 筆符合租屋條件的租盤，"
                f"租金範圍約 {price_range}。{date_text}{criteria_sentence} "
                "我會先挑出原因清楚、條件接近的物件給你確認，再決定是否安排下一步。"
            )
        return (
            f"這次值得寄給你，因為系統找到 {len(alerts)} 筆符合買房條件的房源，"
            f"價格範圍約 {price_range}。{date_text}{criteria_sentence} "
            "我會先把符合條件的原因整理給你，讓你不用自己從一堆 listing 裡面慢慢篩。"
        )

    criteria_sentence = f"Saved criteria: {criteria_text}." if criteria_text else "Matched against the saved client criteria."
    if watchlist.watch_type == "seller_listing_and_sold":
        return (
            f"I am sending this because the system found {len(alerts)} nearby comparable item(s): "
            f"{active_count} competing active listing(s) and {outcome_count} sold comp(s). "
            f"The price range is about {price_range}. {date_text} {criteria_sentence} "
            "These help frame pricing, timing, and presentation strategy."
        )
    if watchlist.watch_type == "landlord_rental_market":
        return (
            f"I am sending this because the system found {len(alerts)} nearby rental market item(s): "
            f"{active_count} competing rental listing(s) and {outcome_count} leased comp(s). "
            f"The rent range is about {price_range}. {date_text} {criteria_sentence} "
            "These help frame rent positioning and market competition."
        )
    if watchlist.watch_type == "tenant_rental_match":
        return (
            f"I am sending this because the system found {len(alerts)} rental listing(s) that match the saved criteria. "
            f"The rent range is about {price_range}. {date_text} {criteria_sentence}"
        )
    return (
        f"I am sending this because the system found {len(alerts)} listing(s) that match the saved buying criteria. "
        f"The price range is about {price_range}. {date_text} {criteria_sentence}"
    )


def _draft_body_for_watchlist_digest(
    contact: models.Contact,
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
) -> str:
    alerts = _sort_alerts_by_recency(alerts)
    language = _client_language(contact)
    lines = []
    for index, alert in enumerate(alerts, start=1):
        evidence_block = _draft_evidence_block(alert, language)
        label = "原因" if language == "zh-tw" else "Reason"
        lines.append(f"{index}. {alert.summary}\n   {label}: {alert.analysis}\n{evidence_block}")

    items_text = "\n\n".join(lines)
    market_snapshot = _digest_market_snapshot(contact, watchlist, alerts)
    if language == "zh-tw":
        intro = "我幫你整理了幾筆和目前條件接近的市場資料："
        if watchlist.watch_type == "seller_listing_and_sold":
            intro = "我幫你整理了幾筆附近競爭房源或成交參考，可用來判斷目前市場位置："
        elif watchlist.watch_type == "tenant_rental_match":
            intro = "我幫你整理了幾筆符合租屋條件的租盤："
        elif watchlist.watch_type == "landlord_rental_market":
            intro = "我幫你整理了幾筆附近租賃市場參考，可用來判斷租金和競爭狀況："

        return f"""Hi {contact.name},

{intro}

{market_snapshot}

{items_text}

我先把重點整理給你。若你對其中任何一筆有興趣，我可以再幫你看完整 listing 細節、比較附近行情，或安排下一步。

Regards,
Kevin Chou
"""

    return f"""Hi {contact.name},

I put together a short market update based on your current criteria:

{market_snapshot}

{items_text}

I wanted to send the key points first. If any item looks interesting, I can review the full details, compare it with nearby activity, or arrange the next step.

Regards,
Kevin Chou
"""


def create_draft_from_watchlist_alert(db: Session, alert_id: int, commit: bool = True):
    alert = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert_id).first()
    if not alert:
        return None
    if alert.interaction_id:
        return schemas.WatchlistDraftResponse(
            success=True,
            message="Draft already exists for this alert.",
            alert=_alert_schema(alert),
            interaction_id=alert.interaction_id,
        )

    contact = alert.contact
    if not contact:
        return None

    subject = _draft_subject_for_alert(contact, alert)
    body = _draft_body_for_alert(contact, alert)
    interaction = models.Interaction(
        contact_id=contact.id,
        property_id=alert.property_id,
        channel="email",
        direction="outbound",
        interaction_type="listing_alert",
        notes=f"Watchlist alert #{alert.id}: {alert.summary}",
        ai_parsed_intent="listing_alert_recommendation",
        ai_auto_summary=alert.summary,
        ai_suggested_action="Review the listing alert draft before creating a Gmail draft or sending.",
        generated_response_type="email_draft",
        generated_response_content=json.dumps(
            {
                "subject": subject,
                "body": body,
                "watchlist_alert_id": alert.id,
                "source": alert.source,
            },
            ensure_ascii=False,
        ),
        generated_response_status="pending_review",
    )
    db.add(interaction)
    db.flush()
    alert.interaction_id = interaction.id
    alert.status = "draft_created"
    alert.reviewed_at = _utcnow()
    if commit:
        db.commit()
        db.refresh(alert)
        db.refresh(interaction)
    return schemas.WatchlistDraftResponse(
        success=True,
        message="Pending-review email draft created. No email was sent.",
        alert=_alert_schema(alert),
        interaction_id=interaction.id,
    )


def _create_digest_draft_for_alert_rows(
    db: Session,
    watchlist: models.ClientWatchlist,
    alerts: list[models.WatchlistAlert],
    commit: bool = True,
) -> schemas.WatchlistDigestDraftResponse:
    if not alerts:
        return schemas.WatchlistDigestDraftResponse(
            success=False,
            message="No alerts are available for a digest draft.",
            watchlist=_watchlist_schema(watchlist, db=db),
            alert_ids=[],
            alert_count=0,
        )

    alerts = _sort_alerts_by_recency(alerts)
    contact = watchlist.contact
    if not contact:
        return schemas.WatchlistDigestDraftResponse(
            success=False,
            message="Watchlist contact is missing.",
            watchlist=_watchlist_schema(watchlist, db=db),
            alert_ids=[alert.id for alert in alerts if alert.id],
            alert_count=len(alerts),
        )

    subject = _draft_subject_for_watchlist_digest(contact, watchlist, alerts)
    body = _draft_body_for_watchlist_digest(contact, watchlist, alerts)
    alert_ids = [alert.id for alert in alerts]
    interaction = models.Interaction(
        contact_id=contact.id,
        property_id=None,
        channel="email",
        direction="outbound",
        interaction_type="listing_alert_digest",
        notes=f"Watchlist digest for watchlist #{watchlist.id}: alerts {alert_ids}",
        ai_parsed_intent="listing_alert_digest_recommendation",
        ai_auto_summary=f"{len(alerts)} watchlist alert(s) summarized for {contact.name}.",
        ai_suggested_action="Review the digest draft before creating a Gmail draft or sending.",
        generated_response_type="email_draft",
        generated_response_content=json.dumps(
            {
                "subject": subject,
                "body": body,
                "watchlist_id": watchlist.id,
                "watchlist_alert_ids": alert_ids,
                "source": watchlist.data_source or "internal_properties",
            },
            ensure_ascii=False,
        ),
        generated_response_status="pending_review",
    )
    db.add(interaction)
    db.flush()

    for alert in alerts:
        alert.interaction_id = interaction.id
        alert.status = "draft_created"
        alert.reviewed_at = _utcnow()

    if commit:
        db.commit()
        db.refresh(watchlist)
        db.refresh(interaction)

    return schemas.WatchlistDigestDraftResponse(
        success=True,
        message=f"Digest draft created for {len(alerts)} alert(s). No email was sent.",
        watchlist=_watchlist_schema(watchlist, db=db),
        interaction_id=interaction.id,
        alert_ids=alert_ids,
        alert_count=len(alerts),
        subject=subject,
        body=body,
    )


def create_digest_draft_from_watchlist_alerts(
    db: Session,
    watchlist_id: int,
    commit: bool = True,
) -> schemas.WatchlistDigestDraftResponse | None:
    watchlist = get_watchlist(db, watchlist_id)
    if not watchlist:
        return None

    alerts = (
        db.query(models.WatchlistAlert)
        .filter(models.WatchlistAlert.watchlist_id == watchlist.id)
        .filter(models.WatchlistAlert.status == "pending_review")
        .order_by(models.WatchlistAlert.created_at.desc())
        .all()
    )
    if not alerts:
        return schemas.WatchlistDigestDraftResponse(
            success=False,
            message="No pending-review alerts are available for a digest draft.",
            watchlist=_watchlist_schema(watchlist, db=db),
            alert_ids=[],
            alert_count=0,
        )

    return _create_digest_draft_for_alert_rows(db, watchlist, alerts, commit=commit)


def create_gmail_digest_draft_from_watchlist_alerts(db: Session, watchlist_id: int):
    digest_result = create_digest_draft_from_watchlist_alerts(db, watchlist_id)
    if digest_result is None:
        return None
    if not digest_result.success or digest_result.interaction_id is None:
        raise ValueError("no_pending_watchlist_alerts_for_digest")

    from . import gmail_service

    return gmail_service.create_gmail_draft_for_interaction(db, digest_result.interaction_id)


def create_gmail_draft_from_watchlist_alert(db: Session, alert_id: int):
    draft_result = create_draft_from_watchlist_alert(db, alert_id)
    if draft_result is None or draft_result.interaction_id is None:
        return None

    from . import gmail_service

    return gmail_service.create_gmail_draft_for_interaction(db, draft_result.interaction_id)


def _mark_watchlist_alerts_sent_for_interaction(db: Session, interaction_id: int) -> int:
    alerts = (
        db.query(models.WatchlistAlert)
        .filter(models.WatchlistAlert.interaction_id == interaction_id)
        .all()
    )
    now = _utcnow()
    for alert in alerts:
        alert.status = "sent"
        alert.reviewed_at = now
        db.add(alert)
    return len(alerts)


def _require_existing_gmail_draft_for_alert(
    db: Session,
    alert_id: int,
) -> tuple[models.WatchlistAlert, int]:
    alert = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert_id).first()
    if not alert:
        raise ValueError("watchlist_alert_not_found")
    if not alert.interaction_id or not alert.interaction:
        raise ValueError("gmail_draft_required_before_send")

    draft_payload = _json_object(alert.interaction.generated_response_content)
    gmail_meta = draft_payload.get("gmail") if isinstance(draft_payload.get("gmail"), dict) else {}
    gmail_draft_id = str(gmail_meta.get("draft_id") or "").strip()
    if alert.interaction.generated_response_status != "gmail_draft_created" or not gmail_draft_id:
        raise ValueError("gmail_draft_required_before_send")
    return alert, alert.interaction_id


def auto_send_gmail_from_watchlist_alert(db: Session, alert_id: int):
    draft_result = create_draft_from_watchlist_alert(db, alert_id)
    if draft_result is None or draft_result.interaction_id is None:
        return None

    from . import gmail_service

    draft_action = gmail_service.create_gmail_draft_for_interaction(db, draft_result.interaction_id)
    if not _env_flag_enabled("WATCHLIST_AUTO_SEND_ENABLED"):
        raise ValueError("watchlist_auto_send_disabled_gmail_draft_created")

    send_action = gmail_service.send_gmail_draft_for_interaction(
        db,
        draft_result.interaction_id,
        confirm_send=True,
        bypass_review_confirmation=True,
    )
    alert = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert_id).first()
    if alert and send_action and send_action.status == "sent":
        _mark_watchlist_alerts_sent_for_interaction(db, draft_result.interaction_id)
        db.commit()
    return send_action or draft_action


def send_gmail_from_watchlist_alert(
    db: Session,
    alert_id: int,
    *,
    confirm_send: bool,
    review_confirmation: str | None = None,
    subject_override: str | None = None,
    body_override: str | None = None,
):
    try:
        alert, interaction_id = _require_existing_gmail_draft_for_alert(db, alert_id)
    except ValueError as exc:
        if str(exc) == "watchlist_alert_not_found":
            return None
        raise

    from . import gmail_service

    send_action = gmail_service.send_gmail_draft_for_interaction(
        db,
        interaction_id,
        confirm_send=confirm_send,
        review_confirmation=review_confirmation,
        subject_override=subject_override,
        body_override=body_override,
    )
    if not send_action or send_action.status != "sent":
        return send_action

    _mark_watchlist_alerts_sent_for_interaction(db, interaction_id)
    db.commit()
    return send_action


# ============================================================
# WORKFLOW 1: Voice Memo → Entity Extraction → CRM Update
# ============================================================

def _call_llm(prompt: str) -> str:
    """Optional Gemini helper. Returns empty JSON unless ENABLE_GEMINI=true."""
    if not gemini_model:
        return "{}"
    try:
        response = gemini_model.generate_content(prompt)
        content = response.text
        return content.replace("```json", "").replace("```", "").strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return "{}"

def _normalize_voice_memo_transcript(text: str) -> str:
    """Clean common GTA real-estate voice transcription errors."""
    replacements = [
        (r"miss\s*saga", "Mississauga"),
        (r"mississaga", "Mississauga"),
        (r"miss\s*sauga", "Mississauga"),
        (r"\bthom\s*hill\b", "Thornhill"),
        (r"\bthorn\s*hill\b", "Thornhill"),
        (r"\bholden\s*hills?\b", "Halton Hills"),
        (r"\bhalton\s*hill\b", "Halton Hills"),
        (r"\bbronzo\s+circle\b", "Brownstone Circle"),
        (r"\bbronzon?\s+circle\b", "Brownstone Circle"),
        (r"squay\s*1", "Square One"),
        (r"square\s*1", "Square One"),
        (r"squar\s*one", "Square One"),
        (r"1\s*加\s*1", "1+1"),
        (r"one\s*plus\s*one", "1+1"),
    ]
    cleaned = text.strip()
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

VOICE_MEMO_GENERIC_NAMES = {"", "unknown", "unknown contact", "voice memo lead", "lead"}


def _is_generic_voice_memo_name(value) -> bool:
    return str(value or "").strip().lower() in VOICE_MEMO_GENERIC_NAMES


def _clean_spelled_name(value: str) -> str:
    value = re.split(
        r"[,，、。:：]|\b(?:buyer|seller|landlord|tenant|investor)\b|買家|賣家|房東|租客|投資客",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" 。,.，、:：")
    letter_tokens = re.findall(r"[A-Za-z]", value)
    if len(letter_tokens) >= 2 and re.fullmatch(r"[A-Za-z][A-Za-z\-\s]*", value):
        parts = [part for part in re.split(r"[\s\-]+", value) if part]
        if parts and any(len(part) > 1 for part in parts):
            return " ".join(part[:1].upper() + part[1:].lower() for part in parts)
        joined = "".join(letter_tokens)
        return joined.title()
    return value.strip()


def _looks_like_person_name(value: str) -> bool:
    value = value.strip()
    if not value or len(value) > 45:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", value):
        return True

    blocked_words = {
        "freehold", "townhouse", "townhome", "condo", "detached", "semi",
        "circle", "street", "road", "drive", "avenue", "thornhill",
        "vaughan", "toronto", "markham", "ontario",
    }
    words = value.split()
    if not 1 <= len(words) <= 4:
        return False
    if any(word.lower().strip(".,") in blocked_words for word in words):
        return False
    return all(re.fullmatch(r"[A-Za-z][A-Za-z'\-.]*", word) for word in words)


def _extract_leading_voice_memo_name(text: str) -> str | None:
    role_pattern = r"(?:賣家|買家|房東|租客|投資客|seller|buyer|landlord|tenant|investor)"
    name_pattern = r"([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,3}|[\u4e00-\u9fff]{2,6})"

    role_first_match = re.search(
        rf"^\s*{role_pattern}\s*(?:是|為|:|：|,|，)?\s*{name_pattern}",
        text,
        flags=re.IGNORECASE,
    )
    if role_first_match:
        return _clean_spelled_name(role_first_match.group(1))

    role_name_match = re.search(
        rf"^\s*{name_pattern}\s*(?:[,，、]\s*)?(?:是|為|as\s+a\s+)?{role_pattern}",
        text,
        flags=re.IGNORECASE,
    )
    if role_name_match:
        return _clean_spelled_name(role_name_match.group(1))

    first_segment = re.split(r"[,，、。]", text, maxsplit=1)[0].strip()
    first_segment = EMAIL_RE.sub("", first_segment).strip()
    first_segment = re.split(r"\b(?:email|e-mail)\b|電郵|電子郵件|郵箱|邮箱", first_segment, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if _looks_like_person_name(first_segment):
        return _clean_spelled_name(first_segment)

    return None


def _detect_voice_memo_client_type(text: str) -> tuple[str, str]:
    if re.search(r"賣家|要賣|想賣|賣房|出售|seller|selling|list(?:ing)?\s+for\s+sale", text, flags=re.IGNORECASE):
        return "seller", "selling"
    if re.search(r"房東|landlord", text, flags=re.IGNORECASE):
        return "landlord", "renting"
    if re.search(r"租客|tenant|租房|lease|rent", text, flags=re.IGNORECASE):
        return "tenant", "renting"
    if re.search(r"投資|investor|investment", text, flags=re.IGNORECASE):
        return "investor", "investing"
    if re.search(r"買家|買房|想買|buyer|buying", text, flags=re.IGNORECASE):
        return "buyer", "buying"
    return "buyer", "inquiry"


def _extract_voice_memo_property_address(text: str) -> str | None:
    match = re.search(
        r"\b(\d{1,6}\s+[A-Za-z][A-Za-z0-9'\-.\s]{2,80}\s+(?:Circle|Cir|Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Crescent|Cres|Boulevard|Blvd|Way))\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip().title()


def _extract_voice_memo_available_after(text: str) -> str | None:
    match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号]", text)
    if not match:
        return None
    return f"{int(match.group(1))}月{int(match.group(2))}日後"


def _parse_voice_memo_small_number(value: str | None) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "一": 1,
        "二": 2,
        "兩": 2,
        "俩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
    }
    return numbers.get(text)


def _extract_voice_memo_min_count(text: str, noun_pattern: str) -> int | None:
    number_pattern = r"(\d+|one|two|three|four|five|一|二|兩|俩|三|四|五)"
    patterns = [
        rf"(?:至少|最少|minimum|min\.?|at\s+least)\s*(?:要有)?\s*{number_pattern}\s*(?:個|間)?\s*(?:{noun_pattern})",
        rf"{number_pattern}\s*(?:個|間)?\s*(?:{noun_pattern})(?:以上|起|\+|plus)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _parse_voice_memo_small_number(match.group(1))
    return None


def _extract_voice_memo_budget(text: str, client_type: str | None = None) -> float | None:
    budget_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:萬|万)", text)
    if budget_match:
        return float(budget_match.group(1)) * 10000

    normalized_text = text.replace(",", "")
    budget_match = re.search(r"\$?\s*(\d{5,8})", normalized_text)
    if budget_match:
        return float(budget_match.group(1))

    is_rental_context = (
        client_type in {"tenant", "landlord"}
        or re.search(r"租金|月租|rent|lease|monthly", text, flags=re.IGNORECASE)
    )
    if not is_rental_context:
        return None

    rental_patterns = [
        r"(?:租金|月租|rent|lease|monthly|budget|預算).{0,16}?\$?\s*(\d{3,5})",
        r"\$?\s*(\d{3,5})\s*(?:以內|以下|左右|per\s*month|/month|monthly|max|under)",
    ]
    for pattern in rental_patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _coerce_string_list(value) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, str) and value.strip():
        raw_values = [value]
    else:
        raw_values = []

    cleaned = []
    seen = set()
    for item in raw_values:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned


def _merge_string_lists(*values) -> list[str]:
    merged = []
    seen = set()
    for value in values:
        for item in _coerce_string_list(value):
            key = item.lower()
            if key not in seen:
                merged.append(item)
                seen.add(key)
    return merged


def _safe_json_list(value) -> list:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _safe_json_dict(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_voice_memo_summary(extracted: dict, text: str) -> str:
    parts = []
    if not _is_generic_voice_memo_name(extracted.get("client_name")):
        parts.append(str(extracted.get("client_name")))
    if extracted.get("client_type"):
        parts.append(f"{extracted['client_type']} lead")
    if extracted.get("property_type"):
        parts.append(str(extracted["property_type"]))
    if extracted.get("property_address"):
        parts.append(str(extracted["property_address"]))
    if extracted.get("areas"):
        parts.append(", ".join(_coerce_string_list(extracted["areas"])))
    if extracted.get("budget"):
        parts.append(f"budget up to {extracted['budget']}")
    if extracted.get("bedrooms_min"):
        parts.append(f"minimum {extracted['bedrooms_min']} bedrooms")
    if extracted.get("parking_min"):
        parts.append(f"minimum {extracted['parking_min']} parking")
    if extracted.get("available_after"):
        parts.append(f"available after {extracted['available_after']}")

    summary = "; ".join(parts)
    if summary:
        return f"{summary}. Memo: {text}"
    return text


def _merge_client_types(current: str | None, new_type: str | None) -> str:
    if not new_type:
        return current or "buyer"
    existing = [item.strip() for item in (current or "").split(",") if item.strip()]
    if not existing:
        return new_type
    if new_type not in existing:
        existing.append(new_type)
    return ",".join(existing)


EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)


def _clean_voice_memo_email(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("＠", "@").replace("。", ".").replace("．", ".")
    direct_match = EMAIL_RE.search(text)
    if direct_match:
        return direct_match.group(0).strip(".,;:，。；：").lower()

    text = re.sub(r"\s*\(?at\)?\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(?dot\)?\s*", ".", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(?:點|点)\s*", ".", text)
    text = re.sub(r"\s+", "", text)
    match = EMAIL_RE.search(text)
    if not match:
        return None
    return match.group(0).strip(".,;:，。；：").lower()


def _extract_voice_memo_email(text: str) -> str | None:
    direct_match = EMAIL_RE.search(str(text or "").replace("＠", "@"))
    if direct_match:
        return direct_match.group(0).strip(".,;:，。；：").lower()

    email_context = re.search(
        r"(?:email|e-mail|電郵|電子郵件|郵箱|邮箱)\s*(?:是|:|：)?\s*([A-Za-z0-9._%+\-\s@＠()]+(?:\.|dot|點|点)[A-Za-z]{2,})\b",
        text,
        flags=re.IGNORECASE,
    )
    if email_context:
        return _clean_voice_memo_email(email_context.group(1))
    return None


def _normalize_voice_memo_extraction(extracted, audio_text: str) -> dict:
    fallback = _fallback_extract_voice_memo(audio_text)
    normalized = extracted if isinstance(extracted, dict) else {}
    normalized = dict(normalized)

    if _is_generic_voice_memo_name(normalized.get("client_name")) and not _is_generic_voice_memo_name(fallback.get("client_name")):
        normalized["client_name"] = fallback["client_name"]

    if not normalized.get("client_name_zh") and fallback.get("client_name_zh"):
        normalized["client_name_zh"] = fallback["client_name_zh"]

    for list_key in ("areas", "likes", "dislikes"):
        normalized[list_key] = _merge_string_lists(normalized.get(list_key), fallback.get(list_key))

    for key in (
        "property_type",
        "budget",
        "bedrooms_min",
        "bathrooms_min",
        "parking_min",
        "property_address",
        "available_after",
        "client_email",
        "language",
        "suggested_followup",
    ):
        if not normalized.get(key) and fallback.get(key):
            normalized[key] = fallback[key]
    normalized["client_email"] = _clean_voice_memo_email(normalized.get("client_email"))

    if normalized.get("intent") in (None, "", "inquiry") and fallback.get("intent") != "inquiry":
        normalized["intent"] = fallback["intent"]
    if not normalized.get("client_type") and fallback.get("client_type"):
        normalized["client_type"] = fallback["client_type"]
    if not normalized.get("key_notes") or normalized.get("key_notes") == "{}":
        normalized["key_notes"] = fallback["key_notes"]

    if _is_generic_voice_memo_name(normalized.get("client_name")):
        normalized["client_name"] = "Voice Memo Lead"

    normalized["key_notes"] = _build_voice_memo_summary(normalized, audio_text)
    return normalized

def _fallback_extract_voice_memo(audio_text: str) -> dict:
    """Best-effort local extraction when Gemini is not configured."""
    text = _normalize_voice_memo_transcript(audio_text)
    client_type, intent = _detect_voice_memo_client_type(text)
    extracted: dict = {
        "client_name": None,
        "client_name_zh": None,
        "areas": [],
        "property_type": None,
        "budget": None,
        "bedrooms_min": None,
        "bathrooms_min": None,
        "parking_min": None,
        "likes": [],
        "dislikes": [],
        "mood": 5,
        "intent": intent,
        "client_type": client_type,
        "property_address": None,
        "available_after": None,
        "client_email": _extract_voice_memo_email(text),
        "key_notes": text,
        "suggested_followup": "Review the voice memo, confirm the client's name and criteria, then follow up manually.",
        "language": "zh-tw" if re.search(r"[\u4e00-\u9fff]", text) else "en",
    }

    leading_name = _extract_leading_voice_memo_name(text)
    if leading_name:
        extracted["client_name"] = leading_name

    name_match = re.search(
        r"(?:名字是|姓名是|客戶(?:名字|姓名)?是|叫做|叫|name is|client name is)\s*([A-Za-z][A-Za-z\-\s]{1,40}|[\u4e00-\u9fff]{2,6})",
        text,
        flags=re.IGNORECASE,
    )
    if name_match:
        extracted["client_name"] = _clean_spelled_name(name_match.group(1))

    area_aliases = {
        "Mississauga": [r"Mississauga", r"密西沙加"],
        "Square One": [r"Square One"],
        "Markham": [r"Markham", r"萬錦"],
        "Richmond Hill": [r"Richmond Hill", r"列治文山"],
        "Thornhill": [r"Thornhill", r"湯山"],
        "Halton Hills": [r"Halton Hills?", r"Holden Hills?", r"荷頓山"],
        "Vaughan": [r"Vaughan", r"旺市"],
        "Toronto": [r"Toronto", r"多倫多"],
        "North York": [r"North York", r"北約克"],
        "Scarborough": [r"Scarborough", r"士嘉堡"],
    }
    for area, patterns in area_aliases.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            extracted["areas"].append(area)

    property_types = [
        ("condo", [r"condo", r"公寓"]),
        ("townhouse", [r"town\s*house", r"townhome", r"townhouse", r"鎮屋", r"湯\s*house"]),
        ("detached", [r"detached", r"獨立屋"]),
        ("semi", [r"semi", r"半獨立"]),
    ]
    for property_type, patterns in property_types:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            extracted["property_type"] = property_type
            break

    extracted["budget"] = _extract_voice_memo_budget(text, extracted["client_type"])

    bedrooms_min = _extract_voice_memo_min_count(text, r"bedrooms?|beds?|房間|睡房|臥室")
    if bedrooms_min:
        extracted["bedrooms_min"] = bedrooms_min

    bathrooms_min = _extract_voice_memo_min_count(text, r"bathrooms?|baths?|廁所|洗手間|衛浴|浴室")
    if bathrooms_min:
        extracted["bathrooms_min"] = bathrooms_min

    parking_min = _extract_voice_memo_min_count(text, r"parking|garage|車庫|停車位|車位")
    if parking_min:
        extracted["parking_min"] = parking_min

    if re.search(r"停車|parking", text, flags=re.IGNORECASE):
        extracted["likes"].append("parking")
    if re.search(r"車庫|garage", text, flags=re.IGNORECASE):
        extracted["likes"].append("garage")
        extracted["parking_min"] = extracted["parking_min"] or 1
    if re.search(r"1\+1", text, flags=re.IGNORECASE):
        extracted["likes"].append("1+1 layout")
    if re.search(r"freehold", text, flags=re.IGNORECASE):
        extracted["likes"].append("freehold")

    extracted["property_address"] = _extract_voice_memo_property_address(text)
    extracted["available_after"] = _extract_voice_memo_available_after(text)

    if extracted["client_type"] == "seller":
        extracted["suggested_followup"] = "Confirm tenant move-out timing, inspect the property after vacancy, and prepare a light make-ready plan before listing."
    elif extracted["client_type"] == "tenant":
        extracted["suggested_followup"] = "Set up a rental match watchlist, monitor new listings against budget and parking needs, and prepare reviewable rental recommendations."
    elif extracted["client_type"] == "landlord":
        extracted["suggested_followup"] = "Monitor active rental competition and recently leased comps, then prepare a market update draft for the landlord."

    if not extracted["client_name"]:
        extracted["client_name"] = "Voice Memo Lead"

    extracted["key_notes"] = _build_voice_memo_summary(extracted, text)
    return extracted

def transcribe_voice_memo_audio(audio_bytes: bytes, filename: str = "voice-memo.webm") -> schemas.VoiceMemoTranscriptionResponse:
    """Transcribe an uploaded voice memo locally with Whisper."""
    if not audio_bytes:
        return schemas.VoiceMemoTranscriptionResponse(
            success=False,
            text="",
            message="No audio was received.",
        )

    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        transcription_path = tmp.name

        wav_tmp = None
        if shutil.which("ffmpeg"):
            wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=True)
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        tmp.name,
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-af",
                        "highpass=f=80,lowpass=f=8000,loudnorm",
                        wav_tmp.name,
                    ],
                    check=True,
                )
                transcription_path = wav_tmp.name
            except Exception:
                logger.exception("Audio normalization failed; falling back to uploaded audio")

        try:
            import whisper

            global _whisper_model
            if _whisper_model is None:
                model_name = os.getenv("WHISPER_MODEL", "small")
                _whisper_model = whisper.load_model(model_name)

            result = _whisper_model.transcribe(
                transcription_path,
                fp16=False,
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt=(
                    "GTA real estate CRM voice memo in Traditional Chinese and English. "
                    "Common terms: Mississauga, Square One, Markham, Richmond Hill, Toronto, "
                    "North York, Scarborough, 1+1 condo, parking, budget."
                ),
            )
        except Exception as e:
            logger.exception("Voice memo transcription failed")
            return schemas.VoiceMemoTranscriptionResponse(
                success=False,
                text="",
                message=f"Transcription failed: {e}",
            )
        finally:
            if wav_tmp is not None:
                wav_tmp.close()

    text = _normalize_voice_memo_transcript(str(result.get("text", "")))
    return schemas.VoiceMemoTranscriptionResponse(
        success=bool(text),
        text=text,
        message="Transcription completed." if text else "No speech was detected in the recording.",
        language=result.get("language"),
        duration=result.get("duration"),
    )


def _fuzzy_match_client(db: Session, name: str):
    """Find a client by fuzzy name matching."""
    # Exact match first
    client = db.query(models.Contact).filter(
        (models.Contact.name.ilike(f"%{name}%")) |
        (models.Contact.name_zh.ilike(f"%{name}%"))
    ).first()
    return client


def workflow_voice_memo(db: Session, audio_text: str) -> schemas.VoiceMemoResponse:
    """
    Workflow 1: Frictionless Data Entry
    Voice memo → LLM entity extraction → DB upsert → Follow-up email draft
    """
    audio_text = _normalize_voice_memo_transcript(audio_text)

    # Step 1: Entity Extraction via LLM
    extraction_prompt = f"""You are a real estate CRM assistant for a Toronto GTA agent.
Extract structured data from this agent's voice memo. Return ONLY a JSON object with these keys:
- client_name (string)
- client_name_zh (string or null if not Chinese)
- client_email (string or null if mentioned)
- areas (array of strings, e.g. ["Markham", "Richmond Hill"])
- property_type (string: condo/townhouse/semi/detached/commercial or null)
- budget (number or null)
- bedrooms_min (number or null)
- bathrooms_min (number or null)
- parking_min (number or null)
- likes (array of strings)
- dislikes (array of strings)
- mood (integer 1-10, 10=very happy, infer from tone)
- intent (string: buying/selling/investing/renting/inquiry)
- client_type (string: buyer/seller/investor/tenant/landlord)
- property_address (string or null)
- available_after (string or null)
- key_notes (string: one-sentence summary)
- suggested_followup (string: what action to take next)
- language (string: en/zh-tw/zh-cn - detect from the memo)

Voice memo: "{audio_text}"
"""

    raw_json = _call_llm(extraction_prompt)
    try:
        extracted = json.loads(raw_json)
    except json.JSONDecodeError:
        extracted = {}

    extracted = _normalize_voice_memo_extraction(extracted, audio_text)

    client_name = extracted.get("client_name") or "Voice Memo Lead"
    client_type = extracted.get("client_type") or _detect_voice_memo_client_type(audio_text)[0]
    client_email = _clean_voice_memo_email(extracted.get("client_email"))
    email_conflict = False

    # Step 2: Find or create client
    client = _fuzzy_match_client(db, client_name)
    is_new = client is None

    if is_new:
        # Create new client
        lead_stage = db.query(models.PipelineStage).filter(models.PipelineStage.name == "Lead").first()
        client = models.Contact(
            name=client_name,
            name_zh=extracted.get("client_name_zh"),
            email=client_email,
            preferred_language=extracted.get("language", "en"),
            client_type=client_type,
            source="voice_memo",
            stage_id=lead_stage.id if lead_stage else None,
            lead_score=30.0,
        )
        db.add(client)
        db.flush()  # Get ID
    else:
        client.client_type = _merge_client_types(client.client_type, client_type)
        if not client.source:
            client.source = "voice_memo"
        if client_email and not client.email:
            client.email = client_email
        elif client_email and client.email.lower() != client_email:
            email_conflict = True
    extracted["client_email"] = client_email
    if email_conflict:
        extracted["client_email_conflict"] = True

    # Update client fields from extraction
    areas = _coerce_string_list(extracted.get("areas", []))
    extracted["areas"] = areas
    if areas:
        existing_areas = _safe_json_list(client.preferred_areas)
        merged_areas = _merge_string_lists(existing_areas, areas)
        client.preferred_areas = json.dumps(merged_areas, ensure_ascii=False)

    if extracted.get("budget"):
        client.budget_max = extracted["budget"]

    # Update preferences
    prefs = _safe_json_dict(client.property_preferences)
    if extracted.get("property_type"):
        prefs["types"] = _merge_string_lists(prefs.get("types", []), [extracted["property_type"]])
    if extracted.get("likes"):
        prefs["must_haves"] = _merge_string_lists(prefs.get("must_haves", []), extracted["likes"])
    if extracted.get("dislikes"):
        prefs["deal_breakers"] = _merge_string_lists(prefs.get("deal_breakers", []), extracted["dislikes"])
    if extracted.get("property_address"):
        prefs["property_address"] = extracted["property_address"]
    if extracted.get("available_after"):
        prefs["available_after"] = extracted["available_after"]
    for numeric_pref in ("bedrooms_min", "bathrooms_min", "parking_min"):
        if extracted.get(numeric_pref) is not None:
            prefs[numeric_pref] = extracted[numeric_pref]
    client.property_preferences = json.dumps(prefs, ensure_ascii=False)

    if extracted.get("mood"):
        client.mood_score = extracted["mood"]

    # Update tags
    existing_tags = [t.strip() for t in (client.tags or "").split(",") if t.strip()]
    for area in areas:
        tag = f"看過{area}"
        if tag not in existing_tags:
            existing_tags.append(tag)
    client.tags = ", ".join(existing_tags)

    # Set followup
    client.next_followup_at = datetime.utcnow() + timedelta(days=2)
    client.followup_priority = "normal"
    client.last_contacted_at = datetime.utcnow()
    client.updated_at = datetime.utcnow()

    # AI summary
    client.ai_summary = extracted.get("key_notes", "")
    memo_note = extracted.get("key_notes") or audio_text
    existing_notes = (client.notes or "").strip()
    if memo_note and memo_note not in existing_notes:
        dated_note = f"Voice memo ({datetime.utcnow():%Y-%m-%d}): {memo_note}"
        client.notes = f"{existing_notes}\n\n{dated_note}".strip() if existing_notes else dated_note

    default_watchlist = _upsert_default_watchlist_for_contact_row(db, client)

    # Step 3: Save interaction log
    interaction = models.Interaction(
        contact_id=client.id,
        channel="voice_memo",
        direction="inbound",
        interaction_type="voice_memo",
        notes=audio_text,
        ai_parsed_intent=extracted.get("intent", "inquiry"),
        ai_parsed_sentiment="neutral",
        ai_parsed_entities=json.dumps(extracted, ensure_ascii=False),
        ai_auto_summary=extracted.get("key_notes", ""),
        ai_suggested_action=extracted.get("suggested_followup", ""),
    )
    db.add(interaction)

    # Step 4: Generate follow-up email
    lang_instruction = "用繁體中文" if extracted.get("language", "en").startswith("zh") else "in English"

    email_prompt = f"""You are a warm, empathetic real estate agent in Toronto.
Write a follow-up email for your client based on this context:
- Client name: {client_name}
- They visited: {', '.join(areas)} area
- Property type: {extracted.get('property_type', 'property')}
- They liked: {', '.join(extracted.get('likes', []))}
- They didn't like: {', '.join(extracted.get('dislikes', []))}
- Their mood: {extracted.get('mood', 5)}/10

Write {lang_instruction}. Tone should be like a caring friend, NOT salesy.
Acknowledge their feelings, and mention you'll keep looking for properties that match their wishes.
Return ONLY a JSON with "subject" and "body" keys.
"""

    email_json = _call_llm(email_prompt)
    email_draft = None
    try:
        email_data = json.loads(email_json)
        email_draft = schemas.EmailDraftResponse(
            subject=email_data.get("subject", "Follow up"),
            body=email_data.get("body", "")
        )
        # Save draft to interaction
        interaction.generated_response_type = "email_draft"
        interaction.generated_response_content = email_json
        interaction.generated_response_status = "pending_review"
    except json.JSONDecodeError:
        pass

    db.commit()
    db.refresh(interaction)
    db.refresh(client)

    action = "created" if is_new else "updated"
    return schemas.VoiceMemoResponse(
        success=True,
        message=f"✅ Successfully {action} {client_name}'s profile + watchlist + email draft generated",
        client_name=client_name,
        client_id=client.id,
        interaction_id=interaction.id,
        extracted_data={
            **extracted,
            "watchlist_id": default_watchlist.id,
            "watch_type": default_watchlist.watch_type,
        },
        email_draft=email_draft
    )


# ============================================================
# WORKFLOW 2: Market Trigger → Investor Batch Outreach
# ============================================================

def workflow_market_trigger(db: Session, trigger: str, source: str = None) -> schemas.MarketTriggerResponse:
    """
    Workflow 2: Market Trigger → Filter investors → Batch personalized messages
    """
    # Step 1: Filter investor clients
    investors = db.query(models.Contact).filter(
        models.Contact.client_type.ilike("%investor%"),
        models.Contact.status == "active"
    ).all()
    
    if not investors:
        return schemas.MarketTriggerResponse(
            success=True,
            message="No active investors found in the system.",
            investors_count=0,
            drafts_generated=0
        )
    
    drafts_count = 0
    
    # Step 2: Generate personalized message for each investor
    for investor in investors:
        areas = json.loads(investor.preferred_areas or "[]")
        lang_instruction = "用繁體中文" if investor.preferred_language.startswith("zh") else "in English"
        
        msg_prompt = f"""You are a professional real estate investment advisor in Toronto GTA.
Based on this market event and client profile, write a SHORT (3-5 sentences) personalized market insight and action suggestion.

Market Event: {trigger}
Source: {source or 'Market News'}

Client Profile:
- Name: {investor.name}
- Focus areas: {', '.join(areas) if areas else 'GTA general'}
- Budget: ${investor.budget_min or 'N/A'} - ${investor.budget_max or 'N/A'}
- Investment focus: {investor.investment_focus or 'general'}
- Previous notes: {(investor.notes or '')[:200]}

Write {lang_instruction}. Be professional but warm, not overly salesy.
Focus on how this event impacts their specific areas and investment strategy.
Return ONLY a JSON with "subject" and "body" keys.
"""
        
        msg_json = _call_llm(msg_prompt)
        
        try:
            msg_data = json.loads(msg_json)
            # Save interaction log
            interaction = models.Interaction(
                contact_id=investor.id,
                channel="email",
                direction="outbound",
                interaction_type="email",
                notes=f"Market trigger: {trigger}",
                ai_parsed_intent="market_update",
                ai_auto_summary=f"Auto-generated market analysis re: {trigger}",
                generated_response_type="email_draft",
                generated_response_content=json.dumps(msg_data, ensure_ascii=False),
                generated_response_status="pending_review"
            )
            db.add(interaction)
            
            investor.next_followup_at = datetime.utcnow() + timedelta(days=3)
            investor.updated_at = datetime.utcnow()
            drafts_count += 1
        except json.JSONDecodeError:
            continue
    
    db.commit()
    
    return schemas.MarketTriggerResponse(
        success=True,
        message=f"🎯 Generated {drafts_count} personalized market analyses for investors",
        investors_count=len(investors),
        drafts_generated=drafts_count
    )


# ============================================================
# WORKFLOW 3: Maintenance Report Autopilot
# ============================================================

def workflow_maintenance_report(db: Session, tenant_email: str, message: str, photos: list) -> schemas.MaintenanceReportResponse:
    """
    Workflow 3: Tenant complaint → AI analysis → Auto-reply → Vendor dispatch
    """
    # Step A: Find tenant and property
    tenant = db.query(models.Contact).filter(
        models.Contact.email.ilike(tenant_email)
    ).first()
    
    if not tenant:
        return schemas.MaintenanceReportResponse(
            success=False,
            message=f"Tenant with email {tenant_email} not found in system.",
            tenant_reply_sent=False,
            vendor_notified=False
        )
    
    # Find property where this tenant lives
    prop = db.query(models.Property).filter(
        models.Property.tenant_client_id == tenant.id
    ).first()
    
    address_str = "unknown property"
    vendor_info = None
    if prop:
        address_str = f"{prop.unit + ' ' if prop.unit else ''}{prop.street}, {prop.city}"
        # Get maintenance contacts
        try:
            vendors = json.loads(prop.maintenance_contacts or "[]")
            if vendors:
                vendor_info = vendors[0]  # First available vendor
        except json.JSONDecodeError:
            pass
    
    # Step A: AI sentiment and issue analysis
    analysis_prompt = f"""Analyze this tenant maintenance complaint:

Message: "{message}"
Photos attached: {len(photos)} image(s)

Return ONLY a JSON with:
- sentiment: "positive" | "neutral" | "negative" | "angry" | "anxious"
- sentiment_score: number from -1.0 to 1.0
- issue_type: what's the problem (e.g., "water_leak", "electrical", "hvac", "plumbing", "structural", "pest", "appliance", "general")
- urgency: "low" | "medium" | "high" | "critical"
- issue_summary: one sentence summary in English
"""
    
    analysis_json = _call_llm(analysis_prompt)
    try:
        analysis = json.loads(analysis_json)
    except json.JSONDecodeError:
        analysis = {
            "sentiment": "negative",
            "sentiment_score": -0.5,
            "issue_type": "general",
            "urgency": "medium",
            "issue_summary": message[:100]
        }
    
    issue_type = analysis.get("issue_type", "general")
    urgency = analysis.get("urgency", "medium")
    sentiment = analysis.get("sentiment", "negative")
    
    # Step B: Generate empathetic auto-reply to tenant
    lang_instruction = "用繁體中文" if tenant.preferred_language.startswith("zh") else "in English"
    
    reply_prompt = f"""You are a property manager. A tenant reported: {issue_type}.
Their emotional state: {sentiment}.
Address: {address_str}

Write a caring auto-reply {lang_instruction}:
1. Acknowledge their concern with empathy
2. Confirm you've received the report and are acting immediately
3. Estimate response within 24 hours
4. If applicable, suggest a temporary measure (e.g., "place a bucket under the leak")

Keep it concise (4-6 sentences). Be warm and professional.
Return ONLY a JSON with "subject" and "body" keys.
"""
    
    reply_json = _call_llm(reply_prompt)
    tenant_reply_sent = False
    try:
        reply_data = json.loads(reply_json)
        tenant_reply_sent = True
    except json.JSONDecodeError:
        reply_data = {"subject": "Maintenance Request Received", "body": "We have received your request and will respond shortly."}
    
    # Step C: Generate vendor dispatch notification
    vendor_dispatch = None
    vendor_notified = False
    if vendor_info:
        vendor_dispatch = f"""🔧 Maintenance Dispatch Notice

Property: {address_str}
Issue: {issue_type}
Urgency: {urgency}
Tenant: {tenant.name} ({tenant.phone or tenant.email})

Description: {message}

Photos: {len(photos)} attached

Please reply with your earliest available time and quote.
"""
        vendor_notified = True
    
    # Step D: Save everything
    interaction = models.Interaction(
        contact_id=tenant.id,
        property_id=prop.id if prop else None,
        channel="photo_report",
        direction="inbound",
        interaction_type="maintenance_request",
        notes=message,
        raw_attachments=json.dumps(photos),
        ai_parsed_intent="maintenance_request",
        ai_parsed_sentiment=sentiment,
        ai_parsed_sentiment_score=analysis.get("sentiment_score", -0.5),
        ai_parsed_entities=json.dumps(analysis, ensure_ascii=False),
        ai_auto_summary=analysis.get("issue_summary", ""),
        ai_suggested_action=f"Dispatch {issue_type} repair, urgency: {urgency}",
        generated_response_type="email_draft",
        generated_response_content=json.dumps(reply_data, ensure_ascii=False),
        generated_response_status="sent" if tenant_reply_sent else "pending_review"
    )
    db.add(interaction)
    
    # Update tenant mood
    mood_map = {"positive": 8, "neutral": 6, "negative": 4, "angry": 2, "anxious": 3}
    tenant.mood_score = mood_map.get(sentiment, 5)
    tenant.last_contacted_at = datetime.utcnow()
    tenant.next_followup_at = datetime.utcnow() + timedelta(days=1)
    tenant.followup_priority = "urgent" if urgency in ["high", "critical"] else "normal"
    
    # Update property status
    if prop:
        prop.status = "pending_repair"
        prop.updated_at = datetime.utcnow()
    
    db.commit()
    
    return schemas.MaintenanceReportResponse(
        success=True,
        message=f"🚨 {address_str} — {issue_type} report processed. Tenant notified + {'vendor dispatched' if vendor_notified else 'no vendor on file'}",
        tenant_reply_sent=tenant_reply_sent,
        vendor_notified=vendor_notified,
        issue_type=issue_type,
        urgency=urgency
    )


# --- Push Notifications ---
def save_push_subscription(db: Session, sub: schemas.PushSubscriptionRequest):
    existing = db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == sub.endpoint
    ).first()
    if existing:
        existing.p256dh = sub.keys.p256dh
        existing.auth = sub.keys.auth
    else:
        existing = models.PushSubscription(
            endpoint=sub.endpoint,
            p256dh=sub.keys.p256dh,
            auth=sub.keys.auth,
        )
        db.add(existing)
    db.commit()
    return existing


def remove_push_subscription(db: Session, endpoint: str):
    sub = db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == endpoint
    ).first()
    if sub:
        db.delete(sub)
        db.commit()
        return True
    return False


def _send_push(subscription_row: models.PushSubscription, payload: dict):
    vapid_private = os.getenv("VAPID_PRIVATE_KEY")
    vapid_claims_email = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")
    if not vapid_private:
        logger.warning("VAPID_PRIVATE_KEY not set, skipping push")
        return False

    sub_info = {
        "endpoint": subscription_row.endpoint,
        "keys": {
            "p256dh": subscription_row.p256dh,
            "auth": subscription_row.auth,
        },
    }
    try:
        webpush(
            subscription_info=sub_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_private,
            vapid_claims={"sub": vapid_claims_email},
        )
        return True
    except WebPushException as e:
        logger.error(f"Push failed for {subscription_row.endpoint[:40]}...: {e}")
        return False


def check_and_send_followup_nudges(db: Session):
    """Check for contacts needing follow-up and push notifications."""
    now = datetime.utcnow()
    upcoming = now + timedelta(hours=2)

    due_contacts = db.query(models.Contact).filter(
        models.Contact.next_followup_at != None,
        models.Contact.next_followup_at <= upcoming,
        models.Contact.status == "active",
    ).all()

    if not due_contacts:
        return {"sent": 0, "contacts": []}

    subscriptions = db.query(models.PushSubscription).all()
    if not subscriptions:
        return {"sent": 0, "contacts": [c.name for c in due_contacts]}

    sent_count = 0
    contact_names = []
    for contact in due_contacts:
        display_name = contact.name_zh or contact.name
        priority = contact.followup_priority or "normal"
        tag = "urgent" if priority == "urgent" else "followup"

        payload = {
            "title": f"Follow-up: {display_name}",
            "body": f"{display_name} needs follow-up ({priority})",
            "tag": tag,
            "data": {
                "url": f"/contacts",
                "contactId": contact.id,
            },
        }

        for sub in subscriptions:
            if _send_push(sub, payload):
                sent_count += 1
        contact_names.append(display_name)

    return {"sent": sent_count, "contacts": contact_names}
