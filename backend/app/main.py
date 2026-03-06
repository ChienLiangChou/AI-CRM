from contextlib import asynccontextmanager
import asyncio
import os
import logging

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

from . import crud, models, schemas
from .database import engine, get_db, SessionLocal

logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)


async def _nudge_loop():
    """Background task: check for follow-up nudges every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        try:
            db = SessionLocal()
            result = crud.check_and_send_followup_nudges(db)
            if result["sent"]:
                logger.info(f"Sent {result['sent']} push notifications for {result['contacts']}")
            db.close()
        except Exception as e:
            logger.error(f"Nudge loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_nudge_loop())
    yield
    task.cancel()

app = FastAPI(title="AI CRM API", lifespan=lifespan)

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to AI CRM API"}


# --- Pipeline Stages ---
@app.get("/api/stages", response_model=List[schemas.PipelineStage])
def read_stages(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    stages = crud.get_stages(db, skip=skip, limit=limit)
    return stages

@app.post("/api/stages", response_model=schemas.PipelineStage)
def create_stage(stage: schemas.PipelineStageCreate, db: Session = Depends(get_db)):
    return crud.create_stage(db=db, stage=stage)

# --- Contacts ---
@app.post("/api/contacts", response_model=schemas.Contact)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db)):
    return crud.create_contact(db=db, contact=contact)

@app.get("/api/contacts", response_model=List[schemas.Contact])
def read_contacts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    contacts = crud.get_contacts(db, skip=skip, limit=limit)
    return contacts

@app.get("/api/contacts/{contact_id}", response_model=schemas.Contact)
def read_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@app.put("/api/contacts/{contact_id}", response_model=schemas.Contact)
def update_contact(contact_id: int, contact: schemas.ContactUpdate, db: Session = Depends(get_db)):
    db_contact = crud.update_contact(db=db, contact_id=contact_id, contact=contact)
    if db_contact is None:
         raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@app.delete("/api/contacts/{contact_id}", response_model=schemas.Contact)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.delete_contact(db=db, contact_id=contact_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

# --- Interactions ---
@app.post("/api/contacts/{contact_id}/interactions", response_model=schemas.Interaction)
def create_contact_interaction(contact_id: int, interaction: schemas.InteractionCreate, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.create_contact_interaction(db=db, contact_id=contact_id, interaction=interaction)

@app.get("/api/contacts/{contact_id}/interactions", response_model=List[schemas.Interaction])
def read_contact_interactions(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.get_contact_interactions(db=db, contact_id=contact_id)

@app.patch("/api/contacts/{contact_id}/stage", response_model=schemas.Contact)
def update_contact_stage(contact_id: int, req: schemas.StageUpdateRequest, db: Session = Depends(get_db)):
    db_contact = crud.update_contact_stage(db=db, contact_id=contact_id, stage_id=req.stage_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

# --- AI Features ---
@app.get("/api/smart-search", response_model=schemas.SmartSearchResult)
def smart_search(q: str, db: Session = Depends(get_db)):
    return crud.perform_smart_search(db=db, query=q)

@app.post("/api/contacts/{contact_id}/draft-email", response_model=schemas.EmailDraftResponse)
def draft_email(contact_id: int, db: Session = Depends(get_db)):
    res = crud.draft_follow_up_email(db, contact_id)
    if not res:
        raise HTTPException(status_code=404, detail="Contact not found")
    return res

@app.post("/api/contacts/{contact_id}/enrich", response_model=schemas.EnrichProfileResponse)
def enrich_profile(contact_id: int, db: Session = Depends(get_db)):
    res = crud.enrich_contact_profile(db, contact_id)
    if not res:
         raise HTTPException(status_code=404, detail="Contact not found")
    return res

@app.post("/api/prospector/scout", response_model=schemas.ScoutResponse)
def scout_for_leads(req: schemas.ScoutRequest, db: Session = Depends(get_db)):
    return crud.scout_leads(db, req.query)

# --- AI Dashboard Intelligence ---
@app.get("/api/dashboard/nudges", response_model=schemas.NudgesResponse)
def get_smart_nudges(db: Session = Depends(get_db)):
    return crud.generate_smart_nudges(db)

@app.get("/api/dashboard/segments", response_model=schemas.SegmentsResponse)
def get_segments(db: Session = Depends(get_db)):
    return crud.auto_segment_contacts(db)

@app.get("/api/dashboard/insights", response_model=schemas.PipelineInsightsResponse)
def get_pipeline_insights(db: Session = Depends(get_db)):
    return crud.generate_pipeline_insights(db)

# --- Properties ---
@app.get("/api/properties", response_model=List[schemas.Property])
def read_properties(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_properties(db, skip=skip, limit=limit)

@app.get("/api/properties/{property_id}", response_model=schemas.Property)
def read_property(property_id: int, db: Session = Depends(get_db)):
    prop = crud.get_property(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

@app.post("/api/properties", response_model=schemas.Property)
def create_property(prop: schemas.PropertyCreate, db: Session = Depends(get_db)):
    return crud.create_property(db=db, prop=prop)

@app.put("/api/properties/{property_id}", response_model=schemas.Property)
def update_property(property_id: int, prop: schemas.PropertyUpdate, db: Session = Depends(get_db)):
    db_prop = crud.update_property(db=db, property_id=property_id, prop=prop)
    if not db_prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return db_prop

@app.delete("/api/properties/{property_id}", response_model=schemas.Property)
def delete_property(property_id: int, db: Session = Depends(get_db)):
    db_prop = crud.delete_property(db=db, property_id=property_id)
    if not db_prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return db_prop

# --- Workflows ---
@app.post("/api/workflow/voice-memo", response_model=schemas.VoiceMemoResponse)
def voice_memo_workflow(req: schemas.VoiceMemoRequest, db: Session = Depends(get_db)):
    return crud.workflow_voice_memo(db, req.audio_text)

@app.post("/api/workflow/market-trigger", response_model=schemas.MarketTriggerResponse)
def market_trigger_workflow(req: schemas.MarketTriggerRequest, db: Session = Depends(get_db)):
    return crud.workflow_market_trigger(db, req.trigger, req.source)

@app.post("/api/workflow/maintenance-report", response_model=schemas.MaintenanceReportResponse)
def maintenance_report_workflow(req: schemas.MaintenanceReportRequest, db: Session = Depends(get_db)):
    return crud.workflow_maintenance_report(db, req.tenant_email, req.message, req.photos)

# --- Push Notifications ---
@app.get("/api/push/vapid-public-key", response_model=schemas.VapidPublicKeyResponse)
def get_vapid_public_key():
    key = os.getenv("VAPID_PUBLIC_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="VAPID key not configured")
    return {"public_key": key}

@app.post("/api/push/subscribe")
def push_subscribe(sub: schemas.PushSubscriptionRequest, db: Session = Depends(get_db)):
    crud.save_push_subscription(db, sub)
    return {"ok": True}

@app.delete("/api/push/unsubscribe")
def push_unsubscribe(req: schemas.PushUnsubscribeRequest, db: Session = Depends(get_db)):
    crud.remove_push_subscription(db, req.endpoint)
    return {"ok": True}

@app.post("/api/push/test")
def push_test(db: Session = Depends(get_db)):
    """Send a test push notification to all subscribers."""
    subs = db.query(models.PushSubscription).all()
    if not subs:
        raise HTTPException(status_code=404, detail="No push subscriptions found")
    sent = 0
    for sub in subs:
        payload = {
            "title": "AI CRM Test",
            "body": "Push notifications are working!",
            "tag": "test",
            "data": {"url": "/dashboard"},
        }
        if crud._send_push(sub, payload):
            sent += 1
    return {"sent": sent, "total": len(subs)}

@app.post("/api/push/check-nudges")
def manual_check_nudges(db: Session = Depends(get_db)):
    """Manually trigger follow-up nudge check."""
    result = crud.check_and_send_followup_nudges(db)
    return result
