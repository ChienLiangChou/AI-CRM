from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


AgentType = Literal[
    "follow_up",
    "conversation_closer",
    "listing_cma",
    "buyer_match",
    "strategy_coordination",
]
TaskStatus = Literal[
    "queued",
    "waiting_approval",
    "executing",
    "completed",
    "failed",
]
RunStatus = Literal[
    "queued",
    "planning",
    "waiting_approval",
    "executing",
    "completed",
    "failed",
]
ApprovalStatus = Literal["pending", "approved", "rejected"]
RiskLevel = Literal["low", "medium", "high"]


class AgentTaskBase(BaseModel):
    agent_type: AgentType
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    payload: Optional[str] = None
    priority: Optional[str] = "normal"


class AgentTaskCreate(AgentTaskBase):
    pass


class AgentTask(AgentTaskBase):
    id: int
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True


class AgentRunBase(BaseModel):
    task_id: int
    summary: Optional[str] = None
    plan: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None


class AgentRunCreate(AgentRunBase):
    pass


class AgentRun(AgentRunBase):
    id: int
    status: RunStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        orm_mode = True
        from_attributes = True


class AgentApprovalBase(BaseModel):
    run_id: int
    action_type: str
    risk_level: RiskLevel = "medium"
    payload: Optional[str] = None


class AgentApprovalCreate(AgentApprovalBase):
    pass


class AgentApproval(AgentApprovalBase):
    id: int
    status: ApprovalStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True


class AgentAuditLogBase(BaseModel):
    run_id: Optional[int] = None
    task_id: Optional[int] = None
    actor_type: str = "agent"
    action: str
    details: Optional[str] = None


class AgentAuditLogCreate(AgentAuditLogBase):
    pass


class AgentAuditLog(AgentAuditLogBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True


class FollowUpRecommendationItem(BaseModel):
    contact_id: int
    contact_name: Optional[str] = None
    company: Optional[str] = None
    urgency: Optional[str] = None
    message: Optional[str] = None
    suggested_action: Optional[str] = None


class FollowUpDraftItem(BaseModel):
    contact_id: int
    approval_id: int
    subject: str
    body: str


class FollowUpRecommendationsResponse(BaseModel):
    recommendations: list[FollowUpRecommendationItem]
    drafts: list[FollowUpDraftItem]
    run_id: Optional[int] = None


class ConversationCloserRunRequest(BaseModel):
    contact_id: int
    message: str
    channel: Optional[str] = "email"
    interaction_id: Optional[int] = None
    property_id: Optional[int] = None
    operator_goal: Optional[str] = None
    desired_outcome: Optional[str] = None
    context_notes: Optional[str] = None


class ConversationCloserAnalysis(BaseModel):
    primary_type: str
    secondary_types: list[str] = []
    sentiment: str
    confidence: float
    urgency: str
    requires_manual_escalation: bool = False


class ConversationCloserStrategy(BaseModel):
    recommended_action: str
    goal: str
    tone: str
    rationale: str
    do_not_say: list[str] = []


class ConversationCloserDraftItem(BaseModel):
    variant: str
    channel: str
    subject: Optional[str] = None
    body: str
    approval_id: Optional[int] = None


class ConversationCloserResultResponse(BaseModel):
    summary: str
    objection_analysis: ConversationCloserAnalysis
    strategy: ConversationCloserStrategy
    talking_points: list[str]
    drafts: list[ConversationCloserDraftItem]
    risk_flags: list[str]
    operator_notes: list[str]


class ConversationCloserLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[ConversationCloserResultResponse] = None


class ListingCmaComparableInput(BaseModel):
    address: str
    status: str
    price: Optional[float] = None
    close_date: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    sqft: Optional[int] = None
    notes: Optional[str] = None


class ListingCmaRunRequest(BaseModel):
    contact_id: int
    property_id: Optional[int] = None
    meeting_goal: Optional[str] = "listing_appointment_prep"
    subject_property_notes: Optional[str] = None
    seller_context_notes: Optional[str] = None
    comparables: list[ListingCmaComparableInput] = []


class ListingCmaListingBrief(BaseModel):
    summary: str
    property_highlights: list[str] = []
    seller_context: list[str] = []


class ListingCmaSupport(BaseModel):
    internal_price_discussion_range: Optional[str] = None
    range_framing: str
    comparable_narrative: list[str] = []
    missing_data_flags: list[str] = []


class ListingCmaDraftItem(BaseModel):
    variant: str
    subject: Optional[str] = None
    body: str
    approval_id: Optional[int] = None


class ListingCmaResultResponse(BaseModel):
    listing_brief: ListingCmaListingBrief
    cma_support: ListingCmaSupport
    talking_points: list[str] = []
    seller_drafts: list[ListingCmaDraftItem] = []
    risk_flags: list[str] = []
    operator_notes: list[str] = []


class ListingCmaLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[ListingCmaResultResponse] = None


class BuyerMatchCriteriaInput(BaseModel):
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    areas: list[str] = []
    property_type: Optional[str] = None
    bedrooms_min: Optional[int] = None
    bathrooms_min: Optional[int] = None
    sqft_min: Optional[int] = None
    parking_required: bool = False
    timeline: Optional[str] = None
    must_haves: list[str] = []
    nice_to_haves: list[str] = []
    deal_breakers: list[str] = []


class BuyerMatchCandidateInput(BaseModel):
    property_id: Optional[int] = None
    address: Optional[str] = None
    list_price: Optional[float] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    sqft: Optional[int] = None
    area: Optional[str] = None
    parking: Optional[int] = None
    notes: Optional[str] = None


class BuyerMatchRunRequest(BaseModel):
    contact_id: int
    goal: Optional[str] = "shortlist_prep"
    criteria: BuyerMatchCriteriaInput = BuyerMatchCriteriaInput()
    buyer_context_notes: Optional[str] = None
    candidates: list[BuyerMatchCandidateInput] = []


class BuyerMatchNeedsSummary(BaseModel):
    summary: str
    must_haves: list[str] = []
    nice_to_haves: list[str] = []
    deal_breakers: list[str] = []


class BuyerMatchShortlistItem(BaseModel):
    rank: int
    title: str
    property_id: Optional[int] = None
    match_strength: str
    why_it_fits: list[str] = []
    tradeoffs: list[str] = []


class BuyerMatchDraftItem(BaseModel):
    variant: str
    subject: Optional[str] = None
    body: str
    approval_id: Optional[int] = None


class BuyerMatchResultResponse(BaseModel):
    buyer_needs_summary: BuyerMatchNeedsSummary
    shortlist_framing: str
    shortlist: list[BuyerMatchShortlistItem] = []
    tradeoff_summary: list[str] = []
    recommended_next_manual_action: str
    buyer_drafts: list[BuyerMatchDraftItem] = []
    risk_flags: list[str] = []
    missing_data_flags: list[str] = []
    operator_notes: list[str] = []


class BuyerMatchLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[BuyerMatchResultResponse] = None


StrategyCoordinationSourceType = Literal["external", "internal"]
StrategyCoordinationUrgency = Literal["low", "medium", "high"]
StrategyCoordinationImportance = Literal[
    "noise",
    "watchlist",
    "strategy_review_required",
]
StrategyCoordinationPerspectiveRelevance = Literal[
    "none",
    "low",
    "medium",
    "high",
]
StrategyCoordinationExecutionMode = Literal["internal_only_non_executable"]


class StrategyCoordinationListingReference(BaseModel):
    listing_ref: str
    property_id: Optional[int] = None
    label: Optional[str] = None


class StrategyCoordinationLinkedEntities(BaseModel):
    contacts: list[int] = []
    properties: list[int] = []
    listings: list[StrategyCoordinationListingReference] = []
    runs: list[int] = []
    approvals: list[int] = []


class StrategyCoordinationRunRequest(BaseModel):
    event_type: str
    source_type: StrategyCoordinationSourceType
    summary: str
    details: Optional[str] = None
    urgency: StrategyCoordinationUrgency = "medium"
    operator_goal: Optional[str] = None
    linked_entities: StrategyCoordinationLinkedEntities = (
        StrategyCoordinationLinkedEntities()
    )


class StrategyCoordinationEventSummary(BaseModel):
    event_type: str
    source_type: StrategyCoordinationSourceType
    summary: str
    details: Optional[str] = None
    urgency: StrategyCoordinationUrgency


class StrategyCoordinationImportanceAssessment(BaseModel):
    classification: StrategyCoordinationImportance
    reason: str
    confidence: float


class StrategyCoordinationPerspectiveBlock(BaseModel):
    relevance: StrategyCoordinationPerspectiveRelevance
    summary: str
    supporting_signals: list[str] = []
    risk_flags: list[str] = []


class StrategyCoordinationPerspectiveBlocks(BaseModel):
    follow_up: StrategyCoordinationPerspectiveBlock
    conversation_retention: StrategyCoordinationPerspectiveBlock
    listing_seller: StrategyCoordinationPerspectiveBlock
    operations_compliance: StrategyCoordinationPerspectiveBlock


class StrategyCoordinationExecutionPolicy(BaseModel):
    mode: StrategyCoordinationExecutionMode = "internal_only_non_executable"
    can_execute_actions: bool = False
    can_trigger_agents: bool = False
    can_create_client_outputs: bool = False


class StrategyCoordinationSynthesis(BaseModel):
    summary: str
    key_takeaways: list[str] = []


class StrategyCoordinationRecommendedActions(BaseModel):
    internal_actions: list[str] = []
    human_review_actions: list[str] = []


class StrategyCoordinationResultResponse(BaseModel):
    event_summary: StrategyCoordinationEventSummary
    importance_assessment: StrategyCoordinationImportanceAssessment
    affected_entities: StrategyCoordinationLinkedEntities
    execution_policy: StrategyCoordinationExecutionPolicy
    perspective_blocks: StrategyCoordinationPerspectiveBlocks
    strategy_synthesis: StrategyCoordinationSynthesis
    recommended_next_actions: StrategyCoordinationRecommendedActions
    risk_flags: list[str] = []
    operator_notes: list[str] = []


class StrategyCoordinationLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[StrategyCoordinationResultResponse] = None


class AgentOpsReviewModel(BaseModel):
    manual_only: bool
    no_send: bool
    tracked_agent_types: list[AgentType]


class AgentOpsOverviewAgentItem(BaseModel):
    agent_type: AgentType
    latest_run_id: Optional[int] = None
    latest_run_status: Optional[RunStatus] = None
    latest_run_created_at: Optional[datetime] = None
    latest_run_error: Optional[str] = None
    pending_approvals: int = 0
    failed_runs: int = 0
    runs_tracked: int = 0


class AgentOpsOverviewTotals(BaseModel):
    pending_approvals: int = 0
    recent_decisions: int = 0
    failed_runs: int = 0
    runs_tracked: int = 0


class AgentOpsOverviewResponse(BaseModel):
    agents: list[AgentOpsOverviewAgentItem]
    totals: AgentOpsOverviewTotals
    review_model: AgentOpsReviewModel


class AgentOpsApprovalPreview(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    body_excerpt: Optional[str] = None
    contact_id: Optional[int] = None
    property_id: Optional[int] = None
    review_mode: Optional[str] = None
    payload_text: Optional[str] = None


class AgentOpsApprovalItem(BaseModel):
    approval_id: int
    agent_type: AgentType
    run_id: int
    task_id: int
    action_type: str
    risk_level: RiskLevel
    status: ApprovalStatus
    created_at: datetime
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    decisioned_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    run_status: RunStatus
    run_summary: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    preview: AgentOpsApprovalPreview


class AgentOpsRunItem(BaseModel):
    run_id: int
    task_id: int
    agent_type: AgentType
    status: RunStatus
    summary: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    approval_count: int = 0
    pending_approval_count: int = 0
    has_pending_approvals: bool = False
    is_internal_only: bool = False


class AgentOpsAuditItem(BaseModel):
    id: int
    actor_type: str
    action: str
    details_json: Optional[Any] = None
    details_text: Optional[str] = None
    created_at: datetime


class AgentOpsRunAuditResponse(BaseModel):
    run: AgentOpsRunItem
    audit_logs: list[AgentOpsAuditItem]
