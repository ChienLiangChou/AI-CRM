from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


AgentType = Literal[
    "follow_up",
    "conversation_closer",
    "listing_cma",
    "buyer_match",
    "listing_alert_recommendation",
    "strategy_coordination",
    "daily_market_scan",
    "mls_auth",
    "transaction_paperwork",
    "event_strategy_review",
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


ListingAlertExecutionMode = Literal["manual", "automatic"]
ListingAlertMarketType = Literal["sale", "rent", "unknown"]
ListingAlertRepresentationIntent = Literal[
    "buyer_purchase",
    "renter_representation",
]
ListingAlertExecutionStatus = Literal[
    "packet_ready",
    "blocked_no_candidates",
    "blocked_no_client_match",
    "blocked_ambiguous_client_match",
    "blocked_ambiguous_intent",
    "blocked_intent_mismatch",
]
ListingAlertReviewOutcome = Literal[
    "waiting_approval",
    "completed_no_draft",
]
ListingAlertGmailImportStatus = Literal[
    "imported",
    "duplicate_skipped",
    "policy_skipped",
]
ListingAlertAssociationMethod = Literal[
    "expected_contact_id",
    "explicit_mapping",
    "deterministic_metadata",
    "heuristic_fallback",
    "blocked",
]
ListingAlertAssociationStatus = Literal[
    "matched",
    "blocked_no_match",
    "blocked_ambiguous",
    "blocked_ambiguous_intent",
    "blocked_intent_mismatch",
]


class ListingAlertGmailMessageInput(BaseModel):
    message_id: str
    thread_id: str
    received_at: Optional[datetime] = None
    subject: str
    from_address: Optional[str] = None
    to_addresses: list[str] = []
    cc_addresses: list[str] = []
    label_ids: list[str] = []
    snippet: Optional[str] = None
    plain_text_body: Optional[str] = None
    html_body: Optional[str] = None
    attachment_names: list[str] = []


class ListingAlertExplicitContactMappingInput(BaseModel):
    contact_id: int
    representation_intent: Optional[ListingAlertRepresentationIntent] = None
    recipient_address: Optional[str] = None
    sender_address: Optional[str] = None
    subject_contains: Optional[str] = None
    label_id: Optional[str] = None


class ListingAlertRunRequest(BaseModel):
    execution_mode: ListingAlertExecutionMode = "manual"
    gmail_alert: ListingAlertGmailMessageInput
    expected_contact_id: Optional[int] = None
    explicit_contact_mappings: list[ListingAlertExplicitContactMappingInput] = []
    operator_notes: Optional[str] = None
    provider_strategy: Optional[dict[str, Any]] = None
    manual_reasoning_surface: Optional[str] = "chatgpt_pro_gpt_5_4"


class ListingAlertGmailReadQueryPolicy(BaseModel):
    allowed_sender: str
    label_ids: list[str] = []
    subject_keywords: list[str] = []
    max_results: int = 10


class ListingAlertGmailReadConfig(BaseModel):
    access_token: str
    gmail_user_id: str = "me"
    query_policy: ListingAlertGmailReadQueryPolicy


class ListingAlertGmailMessageReference(BaseModel):
    message_id: str
    thread_id: str


class ListingAlertGmailImportOutcome(BaseModel):
    status: ListingAlertGmailImportStatus
    message_id: str
    thread_id: Optional[str] = None
    received_at: Optional[datetime] = None
    subject: Optional[str] = None
    normalized_message: Optional[ListingAlertGmailMessageInput] = None
    existing_task_id: Optional[int] = None
    existing_run_id: Optional[int] = None
    imported_task_id: Optional[int] = None
    imported_run_id: Optional[int] = None
    reason: Optional[str] = None


class ListingAlertGmailImportBatchResult(BaseModel):
    gmail_user_id: str
    query: str
    matched_message_count: int = 0
    outcomes: list[ListingAlertGmailImportOutcome] = []


class ListingAlertNormalizedListing(BaseModel):
    listing_ref: str
    address: str
    price: Optional[float] = None
    market_type: ListingAlertMarketType = "unknown"
    property_type: Optional[str] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    neighborhood: Optional[str] = None
    listing_url: Optional[str] = None
    source_excerpt: str
    match_notes: list[str] = []


class ListingAlertClientAssociationResponse(BaseModel):
    status: ListingAlertAssociationStatus
    method: ListingAlertAssociationMethod = "blocked"
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None
    representation_intent: Optional[ListingAlertRepresentationIntent] = None
    confidence: Optional[float] = None
    matched_on: list[str] = []
    blocked_reason: Optional[str] = None
    candidate_contact_ids: list[int] = []


class ListingAlertManualReviewPacket(BaseModel):
    packet_version: str = "listing_alert_manual_review_v1"
    workflow_mode: Literal["manual"] = "manual"
    manual_reasoning_surface: str = "chatgpt_pro_gpt_5_4"
    source_message: ListingAlertGmailMessageInput
    association: ListingAlertClientAssociationResponse
    contact_context: dict[str, Any] = Field(default_factory=dict)
    comparison_frame: dict[str, Any] = Field(default_factory=dict)
    extracted_listing_count: int
    extracted_listings: list[ListingAlertNormalizedListing] = []
    shortlist_cap: int = 3
    draft_output_cap: int = 1
    draft_constraints: list[str] = []
    recommended_prompt_context: list[str] = []
    return_contract: dict[str, Any] = Field(default_factory=dict)


class ListingAlertManualPacketResultResponse(BaseModel):
    execution_status: ListingAlertExecutionStatus
    association: ListingAlertClientAssociationResponse
    extracted_listings: list[ListingAlertNormalizedListing] = []
    manual_review_packet: Optional[ListingAlertManualReviewPacket] = None
    risk_flags: list[str] = []
    operator_notes: list[str] = []


class ListingAlertReviewedShortlistSubmissionItem(BaseModel):
    listing_ref: str
    rank: int
    why_selected: list[str] = []


class ListingAlertClientDraftSubmissionItem(BaseModel):
    variant: str = "shortlist_summary"
    subject: str
    body: str


class ListingAlertManualReviewSubmissionRequest(BaseModel):
    source_run_id: int
    shortlisted_listings: list[ListingAlertReviewedShortlistSubmissionItem] = []
    tradeoff_notes: list[str] = []
    recommendation_reasoning: str
    client_facing_drafts: list[ListingAlertClientDraftSubmissionItem] = []
    operator_notes: list[str] = []


class ListingAlertReviewedShortlistResultItem(BaseModel):
    listing_ref: str
    address: str
    rank: int
    why_selected: list[str] = []


class ListingAlertClientDraftResultItem(BaseModel):
    variant: str
    subject: str
    body: str
    approval_id: Optional[int] = None


class ListingAlertReviewedSubmissionResultResponse(BaseModel):
    source_run_id: int
    source_task_id: int
    packet_version: str
    association: ListingAlertClientAssociationResponse
    review_outcome: ListingAlertReviewOutcome
    shortlisted_listings: list[ListingAlertReviewedShortlistResultItem] = []
    tradeoff_notes: list[str] = []
    recommendation_reasoning: str
    client_facing_drafts: list[ListingAlertClientDraftResultItem] = []
    risk_flags: list[str] = []
    operator_notes: list[str] = []


ListingAlertRecommendationStoredResult = (
    ListingAlertManualPacketResultResponse
    | ListingAlertReviewedSubmissionResultResponse
)


class ListingAlertRecommendationLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[ListingAlertRecommendationStoredResult] = None


class ListingAlertRecommendationRunReportResponse(BaseModel):
    run_id: int
    task_id: int
    status: RunStatus
    summary: Optional[str] = None
    error: Optional[str] = None
    result: Optional[ListingAlertRecommendationStoredResult] = None


MlsAuthProviderKey = Literal["stratus_authenticated"]
MlsAuthState = Literal[
    "available",
    "unauthenticated",
    "auth_in_progress",
    "awaiting_otp",
    "expired",
    "failed",
]
MlsAuthFailureReason = Literal[
    "invalid_credentials",
    "otp_invalid",
    "otp_expired",
    "otp_timeout",
    "session_expired",
    "provider_unavailable",
    "login_page_changed",
    "network_error",
    "unknown_auth_failure",
]
MlsAuthMode = Literal["manual_simulated"]


class MlsAuthStartRequest(BaseModel):
    provider: MlsAuthProviderKey = "stratus_authenticated"
    mode: MlsAuthMode = "manual_simulated"


class MlsAuthSubmitOtpRequest(BaseModel):
    provider: MlsAuthProviderKey = "stratus_authenticated"
    attempt_reference: str
    session_reference: str
    otp_code: str


class MlsAuthStatusResponse(BaseModel):
    provider: MlsAuthProviderKey
    state: MlsAuthState = "unauthenticated"
    available: bool = False
    internal_only: bool = True
    mode: MlsAuthMode = "manual_simulated"
    last_checked_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    failure_reason: Optional[MlsAuthFailureReason] = None
    session_reference: Optional[str] = None
    active_attempt_reference: Optional[str] = None
    otp_requested_at: Optional[datetime] = None
    otp_timeout_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class MlsAuthAttemptRecord(BaseModel):
    attempt_reference: str
    provider: MlsAuthProviderKey
    state: MlsAuthState
    internal_only: bool = True
    mode: MlsAuthMode = "manual_simulated"
    session_reference: str
    started_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
    otp_required: bool = False
    otp_requested_at: Optional[datetime] = None
    otp_timeout_at: Optional[datetime] = None
    otp_submitted_at: Optional[datetime] = None
    failure_reason: Optional[MlsAuthFailureReason] = None


class MlsAuthStartResponse(BaseModel):
    status: MlsAuthStatusResponse
    attempt: MlsAuthAttemptRecord
    reused_existing_attempt: bool = False


class MlsAuthSubmitOtpResponse(BaseModel):
    status: MlsAuthStatusResponse
    attempt: MlsAuthAttemptRecord
    otp_accepted: bool = False


class MlsAuthHistoryResponse(BaseModel):
    current_status: MlsAuthStatusResponse
    attempts: list[MlsAuthAttemptRecord] = []


DailyMarketScanMode = Literal[
    "client_match",
    "competitor_watch",
    "full_daily_scan",
]
DailyMarketScanRunMode = Literal["manual_preview", "simulated_preview"]
DailyMarketScanSourcePreference = Literal[
    "auto",
    "authenticated_mls_browser_first",
    "public_only",
]
DailyMarketScanProviderKey = Literal[
    "authenticated_mls_browser",
    "public_listing",
]
DailyMarketScanProviderAuthState = Literal[
    "not_required",
    "authenticated",
    "unauthenticated",
    "expired",
    "failed",
]
DailyMarketScanProviderAvailability = Literal["available", "limited", "unavailable"]
DailyMarketScanProviderConfidence = Literal["high", "medium", "low"]
DailyMarketScanProviderAttemptStatus = Literal[
    "completed",
    "partial",
    "failed",
    "skipped",
    "unauthenticated",
    "expired",
]
DailyMarketScanWorkflowType = Literal["client_match", "competitor_watch"]
DailyMarketScanCompetitorMode = Literal[
    "condo_same_building",
    "area_nearby_non_condo",
]
DailyMarketScanWorkflowStatus = Literal[
    "completed",
    "partial",
    "failed",
    "no_providers",
    "no_findings",
]
DailyMarketScanExecutionMode = Literal["internal_logging_review_only"]
DailyMarketScanScopeDecision = Literal["accepted", "constrained", "rejected"]


class DailyMarketScanListingReference(BaseModel):
    listing_ref: str
    property_id: Optional[int] = None
    label: Optional[str] = None


class DailyMarketScanRunRequest(BaseModel):
    scan_mode: DailyMarketScanMode = "full_daily_scan"
    run_mode: DailyMarketScanRunMode = "manual_preview"
    source_preference: DailyMarketScanSourcePreference = "auto"
    contact_ids: list[int] = []
    property_ids: list[int] = []
    listing_refs: list[DailyMarketScanListingReference] = []
    max_subjects: int = 25


class DailyMarketScanProviderDescriptor(BaseModel):
    provider_key: DailyMarketScanProviderKey
    display_name: str
    authentication_required: bool
    auth_state: DailyMarketScanProviderAuthState
    availability: DailyMarketScanProviderAvailability
    detail_level: str
    confidence_level: DailyMarketScanProviderConfidence
    fallback_capable: bool = False
    notes: list[str] = []


class DailyMarketScanFailureMetadata(BaseModel):
    provider_key: Optional[DailyMarketScanProviderKey] = None
    code: str
    message: Optional[str] = None
    retryable: bool = False
    fallback_attempted: bool = False
    fallback_used: bool = False


class DailyMarketScanSourceAttempt(BaseModel):
    provider_key: DailyMarketScanProviderKey
    source_used: str
    status: DailyMarketScanProviderAttemptStatus
    auth_state: DailyMarketScanProviderAuthState
    fallback_used: bool = False
    failure_metadata: list[DailyMarketScanFailureMetadata] = []
    notes: list[str] = []


class DailyMarketScanFinding(BaseModel):
    address: str
    mls_number: Optional[str] = None
    property_id: Optional[int] = None
    listing_ref: Optional[str] = None
    source_used: str
    why_it_matches: list[str] = []
    tradeoffs: list[str] = []
    why_relevant: list[str] = []
    competitor_notes: list[str] = []


class DailyMarketScanProviderScanResult(BaseModel):
    provider_key: DailyMarketScanProviderKey
    source_used: str
    status: DailyMarketScanProviderAttemptStatus
    auth_state: DailyMarketScanProviderAuthState
    fallback_used: bool = False
    findings: list[DailyMarketScanFinding] = []
    failure_metadata: list[DailyMarketScanFailureMetadata] = []
    notes: list[str] = []


class DailyMarketScanClientMatchScan(BaseModel):
    workflow: Literal["client_match"] = "client_match"
    status: DailyMarketScanWorkflowStatus = "completed"
    contact_id: int
    criteria_summary: Optional[str] = None
    source_attempts: list[DailyMarketScanSourceAttempt] = []
    findings: list[DailyMarketScanFinding] = []
    fallback_used: bool = False
    failure_metadata: list[DailyMarketScanFailureMetadata] = []


class DailyMarketScanCompetitorSubject(BaseModel):
    contact_id: Optional[int] = None
    property_id: Optional[int] = None
    listing_ref: Optional[str] = None
    competitor_mode: DailyMarketScanCompetitorMode


class DailyMarketScanCompetitorWatchScan(BaseModel):
    workflow: Literal["competitor_watch"] = "competitor_watch"
    status: DailyMarketScanWorkflowStatus = "completed"
    subject: DailyMarketScanCompetitorSubject
    source_attempts: list[DailyMarketScanSourceAttempt] = []
    findings: list[DailyMarketScanFinding] = []
    fallback_used: bool = False
    failure_metadata: list[DailyMarketScanFailureMetadata] = []


class DailyMarketScanScopeSummary(BaseModel):
    requested_subject_count: int
    effective_subject_count: int
    max_subjects: int
    decision: DailyMarketScanScopeDecision
    notes: list[str] = []


class DailyMarketScanExecutionPolicy(BaseModel):
    mode: DailyMarketScanExecutionMode = "internal_logging_review_only"
    can_auto_send: bool = False
    can_auto_contact_clients: bool = False
    can_create_client_outputs_without_approval: bool = False


class DailyMarketScanSummary(BaseModel):
    scan_mode: DailyMarketScanMode
    run_mode: DailyMarketScanRunMode
    scope: DailyMarketScanScopeSummary
    provider_order: list[DailyMarketScanProviderKey] = []


class DailyMarketScanResultResponse(BaseModel):
    scan_summary: DailyMarketScanSummary
    execution_policy: DailyMarketScanExecutionPolicy
    provider_catalog: list[DailyMarketScanProviderDescriptor] = []
    client_match_scans: list[DailyMarketScanClientMatchScan] = []
    competitor_watch_scans: list[DailyMarketScanCompetitorWatchScan] = []
    risk_flags: list[str] = []
    failure_metadata: list[DailyMarketScanFailureMetadata] = []
    operator_notes: list[str] = []


class DailyMarketScanLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[DailyMarketScanResultResponse] = None


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


EventStrategyReviewSourceMode = Literal[
    "manual_summary",
    "manual_url_bundle",
    "curated_search_query",
]
EventStrategyReviewImportance = Literal[
    "noise",
    "watchlist",
    "strategy_review_required",
]
EventStrategyReviewSourceTrustTier = Literal[
    "tier_1_primary",
    "tier_2_reputable",
    "tier_3_trade",
    "untrusted",
]
EventStrategyReviewPerspectiveStatus = Literal["active", "placeholder", "skipped"]
EventStrategyReviewExecutionMode = Literal["internal_review_only_non_executable"]
EventStrategyReviewExecutionPath = Literal[
    "manual_summary_internal_report",
    "manual_url_bundle_internal_report",
    "curated_search_query_not_active_yet",
    "curated_search_query_constrained_retrieval",
]
EventStrategyReviewExecutionStatus = Literal[
    "report_generated",
    "not_active_yet",
    "retrieval_unavailable",
    "rate_limited",
    "no_credible_sources",
]
EventStrategyReviewRetrievalState = Literal[
    "not_requested",
    "retrieval_unavailable",
    "rate_limited",
    "no_credible_sources",
    "low_confidence_watchlist",
    "successful_retrieval",
]
EventStrategyReviewOutputMode = Literal[
    "internal_report_only",
    "html_report_package",
    "social_post_draft_pack",
    "email_newsletter_draft_pack",
    "client_summary_draft_pack",
]
EventStrategyReviewOutputModeStatus = Literal["first_class_v1", "planned_later"]
EventStrategyReviewPackageStatus = Literal[
    "not_generated",
    "draft_ready",
    "blocked",
]
EventStrategyReviewArtifactType = Literal[
    "static_html_bundle",
    "draft_pack",
    "json_report",
]


class EventStrategyReviewManualSummaryInput(BaseModel):
    headline: str
    summary: str
    source_label: Optional[str] = None
    event_date: Optional[str] = None


class EventStrategyReviewUrlSourceInput(BaseModel):
    url: str
    title: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None


class EventStrategyReviewManualUrlBundleInput(BaseModel):
    items: list[EventStrategyReviewUrlSourceInput] = Field(default_factory=list)
    submitted_item_count: int = 0


class EventStrategyReviewCuratedSearchQueryInput(BaseModel):
    query: str
    geography_hint: Optional[str] = None
    topic_hints: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    max_results: int = 10


class EventStrategyReviewRetrievalContract(BaseModel):
    source_mode: EventStrategyReviewSourceMode
    manual_summary_input: Optional[EventStrategyReviewManualSummaryInput] = None
    manual_url_bundle_input: Optional[EventStrategyReviewManualUrlBundleInput] = None
    curated_search_query_input: Optional[
        EventStrategyReviewCuratedSearchQueryInput
    ] = None
    live_retrieval_enabled: bool = False


class EventStrategyReviewRunRequest(BaseModel):
    retrieval_contract: EventStrategyReviewRetrievalContract
    operator_notes: Optional[str] = None
    topic_hints: list[str] = Field(default_factory=list)
    geo_focus: list[str] = Field(default_factory=list)


class EventStrategyReviewClusteredSource(BaseModel):
    source_kind: EventStrategyReviewSourceMode
    title: Optional[str] = None
    url: Optional[str] = None
    source_domain: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    observed_at: Optional[str] = None
    trust_tier: Optional[EventStrategyReviewSourceTrustTier] = None
    source_label: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class EventStrategyReviewEventCluster(BaseModel):
    source_mode: EventStrategyReviewSourceMode
    canonical_event_title: str
    canonical_summary: str
    taxonomy_tags: list[str] = Field(default_factory=list)
    geography_tags: list[str] = Field(default_factory=list)
    source_count: int = 0
    cluster_strength: int = 0
    duplicate_count: int = 0
    sources: list[EventStrategyReviewClusteredSource] = Field(default_factory=list)
    retrieval_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewScoreBreakdown(BaseModel):
    relevance_score: float = 0.0
    geography_score: float = 0.0
    recency_score: float = 0.0
    source_credibility_score: float = 0.0
    cluster_strength_score: float = 0.0
    operator_usefulness_score: float = 0.0
    total_score: float = 0.0
    selection_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewImportanceAssessment(BaseModel):
    classification: EventStrategyReviewImportance
    reason: str
    confidence: float


class EventStrategyReviewAffectedEntities(BaseModel):
    geographies: list[str] = Field(default_factory=list)
    market_segments: list[str] = Field(default_factory=list)
    business_functions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EventStrategyReviewPerspectiveBlock(BaseModel):
    status: EventStrategyReviewPerspectiveStatus = "placeholder"
    summary: str
    why_it_matters: list[str] = Field(default_factory=list)
    business_implications: list[str] = Field(default_factory=list)
    recommended_internal_actions: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class EventStrategyReviewPerspectiveBlocks(BaseModel):
    follow_up: EventStrategyReviewPerspectiveBlock
    conversation_retention: EventStrategyReviewPerspectiveBlock
    listing_seller: EventStrategyReviewPerspectiveBlock
    cma_market: EventStrategyReviewPerspectiveBlock
    ops_compliance: EventStrategyReviewPerspectiveBlock
    buyer_renter: EventStrategyReviewPerspectiveBlock


class EventStrategyReviewExecutionPolicy(BaseModel):
    mode: EventStrategyReviewExecutionMode = "internal_review_only_non_executable"
    can_auto_send: bool = False
    can_auto_publish: bool = False
    can_auto_execute: bool = False
    can_auto_deploy: bool = False


class EventStrategyReviewRetrievalMetadata(BaseModel):
    retrieval_state: EventStrategyReviewRetrievalState = "not_requested"
    adapter_key: str = "none"
    raw_candidate_cap: int = 8
    raw_candidate_count: int = 0
    fetched_source_cap: int = 3
    fetched_source_count: int = 0
    independent_source_count: int = 0
    allowed_domains_applied: list[str] = Field(default_factory=list)
    default_trusted_domain_policy_applied: bool = False
    has_tier_one_or_two_support: bool = False
    notes: list[str] = Field(default_factory=list)


class EventStrategyReviewExecutionPlan(BaseModel):
    source_mode: EventStrategyReviewSourceMode
    execution_path: EventStrategyReviewExecutionPath
    accepted_for_execution: bool = False
    live_retrieval_enabled: bool = False
    deduped_source_count: int = 0
    duplicate_source_count: int = 0
    retrieval_metadata: EventStrategyReviewRetrievalMetadata = Field(
        default_factory=EventStrategyReviewRetrievalMetadata
    )
    operator_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewRecommendedActions(BaseModel):
    internal_actions: list[str] = Field(default_factory=list)
    human_review_actions: list[str] = Field(default_factory=list)


class EventStrategyReviewSynthesis(BaseModel):
    summary: str
    key_takeaways: list[str] = Field(default_factory=list)


class EventStrategyReviewOutputModeOption(BaseModel):
    mode: EventStrategyReviewOutputMode
    status: EventStrategyReviewOutputModeStatus
    reason: Optional[str] = None


class EventStrategyReviewReportResponse(BaseModel):
    report_title: str
    retrieval_contract: EventStrategyReviewRetrievalContract
    event_cluster: EventStrategyReviewEventCluster
    score_breakdown: EventStrategyReviewScoreBreakdown
    importance_assessment: EventStrategyReviewImportanceAssessment
    affected_entities: EventStrategyReviewAffectedEntities
    execution_policy: EventStrategyReviewExecutionPolicy
    perspective_blocks: EventStrategyReviewPerspectiveBlocks
    strategy_synthesis: EventStrategyReviewSynthesis
    recommended_next_actions: EventStrategyReviewRecommendedActions
    output_mode_options: list[EventStrategyReviewOutputModeOption] = Field(
        default_factory=list
    )
    operator_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewExecutionResult(BaseModel):
    source_mode: EventStrategyReviewSourceMode
    execution_status: EventStrategyReviewExecutionStatus
    execution_plan: EventStrategyReviewExecutionPlan
    report: Optional[EventStrategyReviewReportResponse] = None
    inactive_reason: Optional[str] = None
    operator_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[EventStrategyReviewExecutionResult] = None


class EventStrategyReviewPackageRequest(BaseModel):
    source_run_id: Optional[int] = None
    selected_output_mode: EventStrategyReviewOutputMode
    title_override: Optional[str] = None
    audience_label: Optional[str] = None
    operator_notes: Optional[str] = None


class EventStrategyReviewPackageArtifact(BaseModel):
    artifact_type: EventStrategyReviewArtifactType = "static_html_bundle"
    file_name: Optional[str] = None
    path: Optional[str] = None
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    is_entrypoint: bool = False
    label: Optional[str] = None


class EventStrategyReviewPackageResult(BaseModel):
    source_run_id: Optional[int] = None
    selected_output_mode: EventStrategyReviewOutputMode
    status: EventStrategyReviewPackageStatus
    requires_explicit_operator_step: bool = True
    package_directory_path: Optional[str] = None
    artifacts: list[EventStrategyReviewPackageArtifact] = Field(default_factory=list)
    operator_notes: list[str] = Field(default_factory=list)


class EventStrategyReviewPackageLatestResponse(BaseModel):
    source_run_id: int
    package_run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[EventStrategyReviewPackageResult] = None


TransactionPaperworkSourceDocType = Literal[
    "aps",
    "agreement_to_lease",
    "transaction_related_document",
]
TransactionPaperworkConfirmationState = Literal[
    "not_required",
    "required",
    "confirmed",
]
TransactionPaperworkQuestionReason = Literal[
    "commission_confirmation_required",
    "split_confirmation_required",
    "referral_fee_confirmation_required",
    "marketing_fee_confirmation_required",
    "missing_field",
    "low_confidence_field",
    "conflicting_field",
]
TransactionPaperworkIntakeIssueCode = Literal[
    "missing_file",
    "unreadable_pdf",
    "textless_pdf",
    "missing_text",
    "unsupported_document_type",
]
TransactionPaperworkMappedFieldValueSource = Literal[
    "auto_extracted",
    "kevin_confirmed",
    "unresolved",
]
TransactionPaperworkPdfLoadStatus = Literal["loaded", "blocked"]
TransactionPaperworkRenderStatus = Literal["rendered", "blocked"]
TransactionPaperworkValueType = Literal[
    "text",
    "date",
    "currency",
    "boolean",
    "multiline",
    "selection",
]
TransactionPaperworkTemplateFieldType = TransactionPaperworkValueType
TransactionPaperworkTemplateFillMode = Literal[
    "fill_pdf_fields",
    "overlay_coordinates",
]


class TransactionPaperworkEvidenceReference(BaseModel):
    source_doc_type: TransactionPaperworkSourceDocType
    source_page: int
    evidence_anchor: Optional[str] = None
    evidence_snippet: Optional[str] = None
    document_label: Optional[str] = None


class TransactionPaperworkSourcePage(BaseModel):
    page_number: int
    text: str


class TransactionPaperworkSourceDocument(BaseModel):
    document_label: str
    file_name: Optional[str] = None
    pages: list[TransactionPaperworkSourcePage] = Field(default_factory=list)
    raw_text: Optional[str] = None


class TransactionPaperworkSourceDocumentIntake(BaseModel):
    document_label: str
    file_name: Optional[str] = None
    source_doc_type: TransactionPaperworkSourceDocType = (
        "transaction_related_document"
    )
    supported: bool = False
    confidence: float = 0.0
    classification_basis: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkIntakeIssue(BaseModel):
    document_label: str
    issue_code: TransactionPaperworkIntakeIssueCode
    detail: str


class TransactionPaperworkCanonicalDealFact(BaseModel):
    field_key: str
    section_key: str
    label: str
    value: Optional[str] = None
    source_doc_type: Optional[TransactionPaperworkSourceDocType] = None
    confidence: float = 0.0
    confirmation_state: TransactionPaperworkConfirmationState = "not_required"
    requires_kevin_confirmation: bool = False
    evidence: list[TransactionPaperworkEvidenceReference] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkCanonicalDealFacts(BaseModel):
    facts: list[TransactionPaperworkCanonicalDealFact] = Field(
        default_factory=list
    )
    unresolved_field_keys: list[str] = Field(default_factory=list)
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkFieldTraceability(BaseModel):
    template_field_key: str
    final_value: Optional[str] = None
    source_doc_type: Optional[TransactionPaperworkSourceDocType] = None
    source_page: Optional[int] = None
    evidence_anchor: Optional[str] = None
    evidence_snippet: Optional[str] = None
    confidence: float = 0.0
    transform_used: Optional[str] = None
    confirmed_by_kevin: bool = False


class TransactionPaperworkQuestionItem(BaseModel):
    field_key: str
    prompt: str
    reason: TransactionPaperworkQuestionReason
    required: bool = True
    suggested_value: Optional[str] = None
    confidence: Optional[float] = None
    evidence: list[TransactionPaperworkEvidenceReference] = Field(
        default_factory=list
    )


class TransactionPaperworkQuestionPacket(BaseModel):
    questions: list[TransactionPaperworkQuestionItem] = Field(default_factory=list)
    blocking_field_keys: list[str] = Field(default_factory=list)
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkKevinAnswer(BaseModel):
    field_key: str
    value: str
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkKevinAnswerPacket(BaseModel):
    answers: list[TransactionPaperworkKevinAnswer] = Field(default_factory=list)


class TransactionPaperworkPdfSourceInput(BaseModel):
    file_path: str
    document_label: Optional[str] = None


class TransactionPaperworkPdfSourceResult(BaseModel):
    document_label: str
    file_path: str
    file_name: str
    load_status: TransactionPaperworkPdfLoadStatus
    extraction_method: str = "pdftotext"
    page_count: int = 0
    extracted_text_present: bool = False
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkRunInputSnapshot(BaseModel):
    source_pdfs: list[TransactionPaperworkPdfSourceInput] = Field(
        default_factory=list
    )
    kevin_answer_packet: TransactionPaperworkKevinAnswerPacket = Field(
        default_factory=TransactionPaperworkKevinAnswerPacket
    )
    template_id: str
    template_version: str
    requested_fill_mode: TransactionPaperworkTemplateFillMode = (
        "overlay_coordinates"
    )


class TransactionPaperworkPreparationResult(BaseModel):
    source_documents: list[TransactionPaperworkSourceDocumentIntake] = Field(
        default_factory=list
    )
    canonical_deal_facts: TransactionPaperworkCanonicalDealFacts = Field(
        default_factory=TransactionPaperworkCanonicalDealFacts
    )
    question_packet: TransactionPaperworkQuestionPacket = Field(
        default_factory=TransactionPaperworkQuestionPacket
    )
    intake_issues: list[TransactionPaperworkIntakeIssue] = Field(
        default_factory=list
    )
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkMappedField(BaseModel):
    template_field_key: str
    label: str
    section_key: str
    final_value: Optional[str] = None
    value_source_category: TransactionPaperworkMappedFieldValueSource = "unresolved"
    confidence: float = 0.0
    confirmation_state: TransactionPaperworkConfirmationState = "not_required"
    requires_kevin_confirmation: bool = False
    evidence: list[TransactionPaperworkEvidenceReference] = Field(
        default_factory=list
    )
    traceability: TransactionPaperworkFieldTraceability
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkReviewPackage(BaseModel):
    template_id: str
    template_version: str
    mapped_fields: dict[str, TransactionPaperworkMappedField] = Field(
        default_factory=dict
    )
    unresolved_field_keys: list[str] = Field(default_factory=list)
    blocking_unresolved_field_keys: list[str] = Field(default_factory=list)
    review_ready: bool = False
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkOverlayCoordinate(BaseModel):
    page_number: int = 1
    x: float
    y: float
    max_width: float
    font_name: str = "Helvetica"
    font_size: float = 9.0
    line_height: float = 10.5
    max_lines: int = 1


class TransactionPaperworkRenderedArtifactMetadata(BaseModel):
    output_pdf_path: str
    file_size_bytes: int
    checksum_sha256: str
    page_count: int


class TransactionPaperworkRenderResult(BaseModel):
    template_id: str
    template_version: str
    fill_mode: TransactionPaperworkTemplateFillMode
    output_status: TransactionPaperworkRenderStatus
    artifact: Optional[TransactionPaperworkRenderedArtifactMetadata] = None
    rendered_field_count: int = 0
    skipped_unresolved_field_count: int = 0
    unresolved_blocking_field_keys: list[str] = Field(default_factory=list)
    rendered_field_keys: list[str] = Field(default_factory=list)
    traceability_by_field_key: dict[str, TransactionPaperworkFieldTraceability] = Field(
        default_factory=dict
    )
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkOrchestrationResult(BaseModel):
    pdf_sources: list[TransactionPaperworkPdfSourceResult] = Field(
        default_factory=list
    )
    preparation_result: TransactionPaperworkPreparationResult = Field(
        default_factory=TransactionPaperworkPreparationResult
    )
    review_package: TransactionPaperworkReviewPackage
    render_result: TransactionPaperworkRenderResult
    output_status: TransactionPaperworkRenderStatus
    operator_notes: list[str] = Field(default_factory=list)


class TransactionPaperworkRunRequest(BaseModel):
    source_pdfs: list[TransactionPaperworkPdfSourceInput] = Field(
        default_factory=list
    )
    kevin_answer_packet: TransactionPaperworkKevinAnswerPacket = Field(
        default_factory=TransactionPaperworkKevinAnswerPacket
    )
    template_id: str = "trade_record_sheet"
    template_version: str = "trade_record_sheet_blank_v1"
    requested_fill_mode: TransactionPaperworkTemplateFillMode = (
        "overlay_coordinates"
    )


class TransactionPaperworkLatestResponse(BaseModel):
    run_id: Optional[int] = None
    status: Optional[RunStatus] = None
    error: Optional[str] = None
    result: Optional[TransactionPaperworkOrchestrationResult] = None


class TransactionPaperworkTemplateFieldDescriptor(BaseModel):
    key: str
    label: str
    section_key: str
    field_type: TransactionPaperworkTemplateFieldType = "text"
    canonical_fact_keys: list[str] = Field(default_factory=list)
    requires_kevin_confirmation: bool = False
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkTemplateSection(BaseModel):
    key: str
    label: str
    fields: list[TransactionPaperworkTemplateFieldDescriptor] = Field(
        default_factory=list
    )


class TransactionPaperworkTemplateMetadata(BaseModel):
    template_id: str
    display_name: str
    template_version: str
    source_template_path: str
    source_template_checksum_sha256: str
    preserve_original_layout: bool = True
    preferred_fill_order: list[TransactionPaperworkTemplateFillMode] = Field(
        default_factory=lambda: ["fill_pdf_fields", "overlay_coordinates"]
    )
    sections: list[TransactionPaperworkTemplateSection] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)


class TransactionPaperworkTemplateInspection(BaseModel):
    template_id: str
    display_name: str
    template_version: str
    source_template_path: str
    source_template_checksum_sha256: str
    template_present: bool
    inspection_method: str
    page_count: Optional[int] = None
    pdf_version: Optional[str] = None
    pdf_form_type: Optional[str] = None
    native_field_fill_supported: bool = False
    overlay_fill_supported: bool = False
    ready_fill_modes: list[TransactionPaperworkTemplateFillMode] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)


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


OpenClawNeedsInputKind = Literal[
    "pending_approval",
    "failed_run",
    "strategy_human_review",
    "daily_market_scan_attention",
]


class OpenClawGuardrails(BaseModel):
    read_only: bool = True
    approvals_truth_in_skc: bool = True
    audit_truth_in_skc: bool = True
    no_send: bool = True
    no_crm_mutation: bool = True


class OpenClawNeedsInputItem(BaseModel):
    kind: OpenClawNeedsInputKind
    agent_type: AgentType
    run_id: Optional[int] = None
    approval_id: Optional[int] = None
    title: str
    summary: str
    created_at: datetime


class OpenClawModuleCard(BaseModel):
    agent_type: AgentType
    label: str
    latest_run_id: Optional[int] = None
    latest_run_status: Optional[RunStatus] = None
    latest_run_created_at: Optional[datetime] = None
    latest_run_finished_at: Optional[datetime] = None
    latest_run_error: Optional[str] = None
    pending_approvals: int = 0
    has_pending_approvals: bool = False
    summary: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    operator_notes: list[str] = Field(default_factory=list)


class OpenClawControlRoomResponse(BaseModel):
    as_of: datetime
    guardrails: OpenClawGuardrails = Field(default_factory=OpenClawGuardrails)
    needs_input_today: list[OpenClawNeedsInputItem] = Field(default_factory=list)
    pending_approvals: list[AgentOpsApprovalItem] = Field(default_factory=list)
    recent_failures: list[AgentOpsRunItem] = Field(default_factory=list)
    recent_runs: list[AgentOpsRunItem] = Field(default_factory=list)
    latest_strategy_coordination: StrategyCoordinationLatestResponse = Field(
        default_factory=StrategyCoordinationLatestResponse
    )
    latest_daily_market_scan: DailyMarketScanLatestResponse = Field(
        default_factory=DailyMarketScanLatestResponse
    )
    module_cards: list[OpenClawModuleCard] = Field(default_factory=list)
