from sqlalchemy.orm import Session
from sqlalchemy import func
from . import models, schemas
import re
import json
import os
from datetime import datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize Google Gemini
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
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

def create_contact(db: Session, contact: schemas.ContactCreate):
    # Basic lead scoring on creation
    score = calculate_initial_score(contact)
    
    db_contact = models.Contact(**contact.model_dump(), lead_score=score)
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
        if days_since_contact >= 7 and contact.lead_score >= 30:
            urgency = "high" if days_since_contact >= 14 else "medium"
            nudges.append(schemas.Nudge(
                contact_id=contact.id,
                contact_name=contact.name,
                company=contact.company,
                urgency=urgency,
                message=f"{contact.name} hasn't been contacted in {days_since_contact} days. Follow up to maintain the relationship.",
                action="call" if days_since_contact >= 14 else "email"
            ))
        
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
        if days_in_system >= 30 and interaction_count == 0:
            nudges.append(schemas.Nudge(
                contact_id=contact.id,
                contact_name=contact.name,
                company=contact.company,
                urgency="low",
                message=f"{contact.name} has been in the system for {days_in_system} days with no interactions. Re-engage or archive.",
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


# ============================================================
# WORKFLOW 1: Voice Memo → Entity Extraction → CRM Update
# ============================================================

def _call_llm(prompt: str) -> str:
    """Helper to call Gemini Flash-Lite."""
    if not gemini_model:
        return "{}"
    try:
        response = gemini_model.generate_content(prompt)
        content = response.text
        return content.replace("```json", "").replace("```", "").strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return "{}"


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
    # Step 1: Entity Extraction via LLM
    extraction_prompt = f"""You are a real estate CRM assistant for a Toronto GTA agent.
Extract structured data from this agent's voice memo. Return ONLY a JSON object with these keys:
- client_name (string)
- client_name_zh (string or null if not Chinese)
- areas (array of strings, e.g. ["Markham", "Richmond Hill"])
- property_type (string: condo/townhouse/semi/detached/commercial or null)
- budget (number or null)
- likes (array of strings)
- dislikes (array of strings)
- mood (integer 1-10, 10=very happy, infer from tone)
- intent (string: buying/selling/investing/renting/inquiry)
- key_notes (string: one-sentence summary)
- suggested_followup (string: what action to take next)
- language (string: en/zh-tw/zh-cn - detect from the memo)

Voice memo: "{audio_text}"
"""
    
    raw_json = _call_llm(extraction_prompt)
    try:
        extracted = json.loads(raw_json)
    except json.JSONDecodeError:
        return schemas.VoiceMemoResponse(
            success=False,
            message="Failed to parse LLM response. Raw text saved.",
            extracted_data={"raw": raw_json}
        )
    
    client_name = extracted.get("client_name", "Unknown")
    
    # Step 2: Find or create client
    client = _fuzzy_match_client(db, client_name)
    is_new = client is None
    
    if is_new:
        # Create new client
        lead_stage = db.query(models.PipelineStage).filter(models.PipelineStage.name == "Lead").first()
        client = models.Contact(
            name=client_name,
            name_zh=extracted.get("client_name_zh"),
            preferred_language=extracted.get("language", "en"),
            client_type="buyer",
            stage_id=lead_stage.id if lead_stage else None,
            lead_score=30.0,
        )
        db.add(client)
        db.flush()  # Get ID
    
    # Update client fields from extraction
    areas = extracted.get("areas", [])
    if areas:
        existing_areas = json.loads(client.preferred_areas or "[]")
        merged_areas = list(set(existing_areas + areas))
        client.preferred_areas = json.dumps(merged_areas)
    
    if extracted.get("budget"):
        client.budget_max = extracted["budget"]
    
    # Update preferences
    prefs = json.loads(client.property_preferences or "{}")
    if extracted.get("property_type"):
        prefs["types"] = list(set(prefs.get("types", []) + [extracted["property_type"]]))
    if extracted.get("likes"):
        prefs["must_haves"] = list(set(prefs.get("must_haves", []) + extracted["likes"]))
    if extracted.get("dislikes"):
        prefs["deal_breakers"] = list(set(prefs.get("deal_breakers", []) + extracted["dislikes"]))
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
    db.refresh(client)
    
    action = "created" if is_new else "updated"
    return schemas.VoiceMemoResponse(
        success=True,
        message=f"✅ Successfully {action} {client_name}'s profile + email draft generated",
        client_name=client_name,
        client_id=client.id,
        extracted_data=extracted,
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
