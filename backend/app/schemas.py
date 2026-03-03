from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

# Interaction Schemas
class InteractionBase(BaseModel):
    interaction_type: str
    notes: str

class InteractionCreate(InteractionBase):
    pass

class Interaction(InteractionBase):
    id: int
    contact_id: int
    date: datetime

    class Config:
        orm_mode = True
        from_attributes = True

# Contact Schemas
class ContactBase(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    stage_id: Optional[int] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(ContactBase):
    pass

class Contact(ContactBase):
    id: int
    lead_score: float
    created_at: datetime
    updated_at: datetime
    interactions: List[Interaction] = []

    class Config:
        orm_mode = True
        from_attributes = True

# Pipeline Stage Schemas
class PipelineStageBase(BaseModel):
    name: str
    order: int

class PipelineStageCreate(PipelineStageBase):
    pass

class PipelineStage(PipelineStageBase):
    id: int
    contacts: List[Contact] = []

    class Config:
        orm_mode = True
        from_attributes = True

# Search Result Schema
class SmartSearchResult(BaseModel):
    query: str
    interpreted_intent: str
    results: List[Contact]

# Phase 2 AI Schemas
class EmailDraftResponse(BaseModel):
    subject: str
    body: str

class EnrichProfileResponse(BaseModel):
    summary: str
    updated_notes: str

# Phase 3 AI Schemas
class ScoutRequest(BaseModel):
    query: str

class ScoutResponse(BaseModel):
    message: str
    new_contacts: List[Contact]

