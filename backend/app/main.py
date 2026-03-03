from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

from . import crud, models, schemas
from .database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI CRM API")

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

