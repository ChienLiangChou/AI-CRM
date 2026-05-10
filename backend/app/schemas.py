from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal

# Interaction Schemas
class InteractionBase(BaseModel):
    interaction_type: str
    notes: str
    channel: Optional[str] = "email"
    direction: Optional[str] = "outbound"
    property_id: Optional[int] = None

class InteractionCreate(InteractionBase):
    pass

class Interaction(InteractionBase):
    id: int
    contact_id: int
    date: datetime
    ai_parsed_intent: Optional[str] = None
    ai_parsed_sentiment: Optional[str] = None
    ai_parsed_sentiment_score: Optional[float] = None
    ai_parsed_entities: Optional[str] = None
    ai_auto_summary: Optional[str] = None
    ai_suggested_action: Optional[str] = None
    generated_response_type: Optional[str] = None
    generated_response_content: Optional[str] = None
    generated_response_status: Optional[str] = None

    class Config:
        orm_mode = True
        from_attributes = True

# Contact Schemas
class ContactBase(BaseModel):
    name: str
    name_zh: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    preferred_language: Optional[str] = "en"
    client_type: Optional[str] = "buyer"
    status: Optional[str] = "active"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    expected_roi: Optional[float] = None
    investment_focus: Optional[str] = None
    preferred_areas: Optional[str] = "[]"
    property_preferences: Optional[str] = "{}"
    notes: Optional[str] = None
    source: Optional[str] = None
    stage_id: Optional[int] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(ContactBase):
    pass

class Contact(ContactBase):
    id: int
    tags: Optional[str] = ""
    lead_score: float
    mood_score: Optional[int] = None
    mood_notes: Optional[str] = None
    ai_summary: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    next_followup_at: Optional[datetime] = None
    followup_priority: Optional[str] = "normal"
    created_at: datetime
    updated_at: datetime
    interactions: List[Interaction] = []

    class Config:
        orm_mode = True
        from_attributes = True

# Property Schemas
class PropertyBase(BaseModel):
    unit: Optional[str] = None
    street: str
    city: str
    province: Optional[str] = "ON"
    postal_code: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: str
    status: Optional[str] = "off_market"
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    sqft: Optional[int] = None
    parking: Optional[int] = None
    year_built: Optional[int] = None
    listing_price: Optional[float] = None
    sold_price: Optional[float] = None
    monthly_rent: Optional[float] = None
    monthly_expenses: Optional[float] = None
    cap_rate: Optional[float] = None
    annual_roi: Optional[float] = None
    mls_number: Optional[str] = None
    listing_url: Optional[str] = None
    photos: Optional[str] = "[]"
    maintenance_contacts: Optional[str] = "[]"
    notes: Optional[str] = None
    owner_client_id: Optional[int] = None
    tenant_client_id: Optional[int] = None

class PropertyCreate(PropertyBase):
    pass

class PropertyUpdate(PropertyBase):
    pass

class Property(PropertyBase):
    id: int
    created_at: datetime
    updated_at: datetime

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

# AI Feature Schemas
class EmailDraftResponse(BaseModel):
    subject: str
    body: str

class EnrichProfileResponse(BaseModel):
    summary: str
    updated_notes: str

class ScoutRequest(BaseModel):
    query: str

class ScoutResponse(BaseModel):
    message: str
    new_contacts: List[Contact]

# Stage Update (for pipeline drag-and-drop)
class StageUpdateRequest(BaseModel):
    stage_id: int

# --- AI Dashboard Schemas ---
class Nudge(BaseModel):
    contact_id: int
    contact_name: str
    company: Optional[str] = None
    urgency: str
    message: str
    action: str

class NudgesResponse(BaseModel):
    nudges: List[Nudge]
    generated_at: datetime

class SegmentGroup(BaseModel):
    label: str
    key: str
    count: int
    contacts: List[Contact]

class SegmentsResponse(BaseModel):
    segments: List[SegmentGroup]

class PipelineInsightsResponse(BaseModel):
    total_contacts: int
    stage_breakdown: List[dict]
    avg_score: float
    conversion_summary: str
    bottleneck: Optional[str] = None
    recommendations: List[str]

# --- Workflow Schemas ---
class VoiceMemoRequest(BaseModel):
    audio_text: str
    agent_notes: Optional[str] = None

class VoiceMemoResponse(BaseModel):
    success: bool
    message: str
    client_name: Optional[str] = None
    client_id: Optional[int] = None
    extracted_data: Optional[Dict[str, Any]] = None
    email_draft: Optional[EmailDraftResponse] = None

class MarketTriggerRequest(BaseModel):
    trigger: str
    source: Optional[str] = None

class MarketTriggerResponse(BaseModel):
    success: bool
    message: str
    investors_count: int
    drafts_generated: int

class MaintenanceReportRequest(BaseModel):
    tenant_email: str
    message: str
    photos: List[str] = []

class MaintenanceReportResponse(BaseModel):
    success: bool
    message: str
    tenant_reply_sent: bool
    vendor_notified: bool
    issue_type: Optional[str] = None
    urgency: Optional[str] = None

# --- Push Notification Schemas ---
class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys

class PushUnsubscribeRequest(BaseModel):
    endpoint: str

class VapidPublicKeyResponse(BaseModel):
    public_key: str


# --- Agent Bridge Integration Schemas ---
class AgentBridgeCapability(BaseModel):
    key: str
    label: str
    status: str
    product_surface: str
    description: str
    guardrails: List[str]
    evidence: List[str]
    next_action: str


class AgentBridgeStatusResponse(BaseModel):
    product: str
    mode: str
    bridge_status: str
    direct_external_actions: bool
    safety_boundary: str
    capabilities: List[AgentBridgeCapability]


class AgentBridgeSessionRequest(BaseModel):
    workflow: str = Field(default="listing_research", min_length=2)
    source_context: str = Field(..., min_length=5)
    client_name: Optional[str] = None
    property_address: Optional[str] = None
    requested_outcome: Optional[str] = None
    include_openclaw: bool = True
    include_codex_chrome: bool = True


class AgentBridgeHandoff(BaseModel):
    target: str
    target_label: str
    status: str
    title: str
    instructions: List[str]
    prompt: str
    approval_required: bool


class AgentBridgeSessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: datetime
    workflow: str
    summary: str
    approvals_required: List[str]
    handoffs: List[AgentBridgeHandoff]
    audit_notes: List[str]


AgentBridgeTarget = Literal["openclaw", "codex_chrome_extension", "skc_agent_os"]


class AgentBridgeExecutionCreateRequest(BaseModel):
    target: AgentBridgeTarget
    workflow: str = Field(default="listing_research", min_length=2)
    execution_profile: Optional[str] = None
    source_context: str = Field(..., min_length=5)
    client_name: Optional[str] = None
    property_address: Optional[str] = None
    requested_outcome: Optional[str] = None
    approved_by_kevin: bool = False
    operator_notes: Optional[str] = None


class AgentBridgeExecutionApproveRequest(BaseModel):
    approved_by_kevin: bool = True
    operator_notes: Optional[str] = None


class AgentBridgeExecutionResultRequest(BaseModel):
    status: Literal["completed", "blocked", "needs_review"] = "completed"
    result_summary: str = Field(..., min_length=3)
    result_payload: Dict[str, Any] = {}


class AgentBridgeExecutionResponse(BaseModel):
    run_id: str
    target: AgentBridgeTarget
    target_label: str
    execution_profile: str
    status: str
    workflow: str
    summary: str
    safety_boundary: str
    approval_required: bool
    approved_by_kevin: bool
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None
    handoff_prompt: str
    execution_package: Dict[str, Any]
    command_text: Optional[str] = None
    audit_notes: List[str]
    result_summary: Optional[str] = None
    result_payload: Dict[str, Any] = {}
