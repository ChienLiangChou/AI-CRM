from sqlalchemy.orm import Session
from . import models, schemas
import re
import json
import os
from datetime import datetime
from inferencesh import inference
from dotenv import load_dotenv

load_dotenv()

# Initialize the global inference.sh client
try:
    api_key = os.getenv("INFERENCE_API_KEY")
    if api_key:
        inf_client = inference(api_key=api_key)
    else:
        inf_client = None
except Exception:
    inf_client = None

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
    
    # Update lead score based on new interaction
    db_contact = get_contact(db, contact_id)
    if db_contact:
        db_contact.lead_score = update_score_with_interaction(db_contact.lead_score, interaction)
        db_contact.updated_at = datetime.utcnow()
        
    db.commit()
    db.refresh(db_interaction)
    return db_interaction

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
    
    if not inf_client:
        return schemas.EmailDraftResponse(subject="Unable to generate", body="inference.sh client not configured.")
        
    try:
        res = inf_client.run({
            "app": "openrouter/claude-sonnet-45",
            "input": {"prompt": prompt}
        })
        content = res["output"]["text"]
        # Basic cleanup if wrapped in markdown
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        return schemas.EmailDraftResponse(subject=data.get("subject", "Follow up"), body=data.get("body", ""))
    except Exception as e:
        return schemas.EmailDraftResponse(subject="Error drafting email", body=str(e))

def enrich_contact_profile(db: Session, contact_id: int):
    contact = get_contact(db, contact_id)
    if not contact:
        return None
        
    query = f"Latest news, products, and company overview for {contact.company or contact.name}"
    
    if not inf_client:
        return schemas.EnrichProfileResponse(summary="search unavailable", updated_notes=contact.notes)
        
    try:
        # Search web using Tavily
        search_res = inf_client.run({
            "app": "tavily/search-assistant",
            "input": {"query": query}
        })
        search_info = search_res["output"]["answer"]
        
        new_notes = (contact.notes or "") + f"\n\n--- AI Web Enrichment ---\n{search_info}"
        
        contact.notes = new_notes
        db.commit()
        db.refresh(contact)
        
        return schemas.EnrichProfileResponse(summary="Successfully enriched profile from web search.", updated_notes=new_notes)
    except Exception as e:
        return schemas.EnrichProfileResponse(summary=f"Search failed: {str(e)}", updated_notes=contact.notes or "")

def scout_leads(db: Session, query: str):
    if not inf_client:
        return schemas.ScoutResponse(message="inference.sh client not configured.", new_contacts=[])
        
    try:
        # Search the web for target companies
        search_res = inf_client.run({
            "app": "tavily/search-assistant",
            "input": {"query": f"Find companies matching this profile: {query}. Provide their names and detailed descriptions."}
        })
        search_data = search_res["output"]["answer"]
        
        # Extract into JSON array using Claude
        prompt = f"""
        Based on these web search results, extract up to 3 distinct companies that match the profile "{query}".
        For each company, invent a realistic contact person name (e.g., a founder or sales director), and summarize the company description into 'notes'.
        
        Search Results:
        {search_data}
        
        Return ONLY a JSON array of objects, where each object has the keys: "name" (string), "company" (string), "notes" (string).
        Do not wrap in markdown blocks, just return the raw JSON array.
        """
        
        llm_res = inf_client.run({
            "app": "openrouter/claude-sonnet-45",
            "input": {"prompt": prompt}
        })
        
        content = llm_res["output"]["text"].replace("```json", "").replace("```", "").strip()
        new_leads_data = json.loads(content)
        
        # Get the 'Lead' stage to assign them correctly
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
            # Baseline scoring
            score = 40
            if contact.notes and len(contact.notes) > 50: score += 20
            contact.lead_score = score
            
            db.add(contact)
            db.commit()
            db.refresh(contact)
            new_contacts.append(contact)
            
        return schemas.ScoutResponse(message=f"Successfully scouted {len(new_contacts)} new leads based on web research.", new_contacts=new_contacts)
    except Exception as e:
        print(f"Scout error: {e}")
        return schemas.ScoutResponse(message=f"Error scouting leads: {str(e)}", new_contacts=[])

