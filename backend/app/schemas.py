from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict, Any

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

class ContactUpdate(BaseModel):
    name: Optional[str] = None
    name_zh: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    preferred_language: Optional[str] = None
    client_type: Optional[str] = None
    status: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    expected_roi: Optional[float] = None
    investment_focus: Optional[str] = None
    preferred_areas: Optional[str] = None
    property_preferences: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    stage_id: Optional[int] = None

class Contact(ContactBase):
    id: int
    tags: Optional[str] = ""
    lead_score: float
    qualification_status: Optional[str] = "unqualified"
    qualification_route: Optional[str] = None
    qualification_json: Optional[str] = "{}"
    qualification_updated_at: Optional[datetime] = None
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


class LeadQualification(BaseModel):
    schema_version: str = "lead_qualification_v2"
    score: int
    intent: str
    client_type_guess: str
    urgency: str
    confidence: float
    recommended_route: str
    status: str
    summary: str
    routing_reason: str
    evidence: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    safe_defaults_applied: List[str] = Field(default_factory=list)


class LeadQualificationResponse(BaseModel):
    contact: Contact
    qualification: LeadQualification


class LegacyVoiceMemoReviewItem(BaseModel):
    contact_id: int
    contact_name: str
    interaction_id: Optional[int] = None
    interaction_date: Optional[datetime] = None
    suggested_name: Optional[str] = None
    suggested_existing_contact_id: Optional[int] = None
    suggested_existing_contact_name: Optional[str] = None
    reason: str
    evidence_snippet: str
    action_required: str
    safety_note: str


class LegacyVoiceMemoReviewResponse(BaseModel):
    count: int
    items: List[LegacyVoiceMemoReviewItem] = Field(default_factory=list)
    message: str

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
    listed_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    leased_at: Optional[datetime] = None
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


class PropertyImportResult(BaseModel):
    success: bool
    message: str
    dry_run: bool = False
    created: int
    updated: int
    unchanged: int = 0
    skipped: int
    total_rows: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    preview_rows: List[Dict[str, Any]] = Field(default_factory=list)
    watchlist_match_preview: List[Dict[str, Any]] = Field(default_factory=list)
    watchlist_readiness_preview: List[Dict[str, Any]] = Field(default_factory=list)


class CsvDropFolderImportFile(BaseModel):
    file: str
    sha256: Optional[str] = None
    status: str
    result: Optional[PropertyImportResult] = None
    error: Optional[str] = None


class CsvDropFolderImportResult(BaseModel):
    success: bool
    message: str
    dry_run: bool = False
    drop_dir: str
    state_path: str
    imported: List[CsvDropFolderImportFile] = Field(default_factory=list)
    skipped: List[CsvDropFolderImportFile] = Field(default_factory=list)
    failed: List[CsvDropFolderImportFile] = Field(default_factory=list)
    processed_count: int = 0
    pending_before: int = 0
    pending_after: int = 0


class PropertyFeedImportRequest(BaseModel):
    text: str
    dry_run: bool = True


class PropertyResoJsonImportRequest(BaseModel):
    data: Any
    dry_run: bool = True


class GmailPropertyFeedImportRequest(BaseModel):
    query: Optional[str] = "newer_than:14d (MLS OR listing OR sold OR leased OR REALM OR TRREB)"
    max_results: int = 10
    dry_run: bool = True
    gmail_read_confirmation: Optional[str] = None


class ResoConnectorStatus(BaseModel):
    enabled: bool = False
    url_configured: bool = False
    auth_configured: bool = False
    ready: bool = False
    status: str = "disabled"
    endpoint: Optional[str] = None
    message: str


class PropertySourceStatus(BaseModel):
    properties_count: int
    status_counts: Dict[str, int]
    latest_property_update: Optional[datetime] = None
    internal_properties_ready: bool
    csv_import_ready: bool
    csv_drop_folder: Optional[str] = None
    csv_drop_folder_exists: bool = False
    csv_drop_folder_file_count: int = 0
    csv_drop_folder_importable_count: int = 0
    csv_drop_folder_pending_count: int = 0
    csv_drop_folder_processed_count: int = 0
    csv_drop_folder_total_file_count: int = 0
    csv_drop_folder_non_importable_count: int = 0
    csv_drop_folder_disabled_template_count: int = 0
    csv_drop_folder_instruction_file_count: int = 0
    csv_drop_folder_state_path: Optional[str] = None
    external_mls_connector_ready: bool
    reso_connector: ResoConnectorStatus
    watch_type_coverage: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality_issues: List[str] = Field(default_factory=list)
    recommended_next_import: Optional[str] = None
    message: str


class PropertyFeedConfigUpdate(BaseModel):
    gmail_feed_enabled: Optional[bool] = None
    gmail_feed_confirmation: Optional[str] = None
    gmail_query: Optional[str] = None
    gmail_max_results: Optional[int] = None


class PropertyFeedConfig(BaseModel):
    id: int
    gmail_feed_enabled: bool
    gmail_query: str
    gmail_max_results: int
    last_import_at: Optional[datetime] = None
    last_import_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# Watchlist / Listing Alert Schemas
class ClientWatchlistCreate(BaseModel):
    contact_id: int
    name: Optional[str] = None
    watch_type: str
    status: Optional[str] = "active"
    criteria: Dict[str, Any] = Field(default_factory=dict)
    schedule: Dict[str, Any] = Field(default_factory=lambda: {"times": ["09:00"], "timezone": "America/Toronto"})
    notification_channel: Optional[str] = "codex_app"
    review_mode: Optional[str] = "auto_gmail_draft"
    data_source: Optional[str] = "internal_properties"
    source_query: Optional[str] = None
    auto_send_confirmation: Optional[str] = None


class ClientWatchlistUpdate(BaseModel):
    name: Optional[str] = None
    watch_type: Optional[str] = None
    status: Optional[str] = None
    criteria: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    notification_channel: Optional[str] = None
    review_mode: Optional[str] = None
    data_source: Optional[str] = None
    source_query: Optional[str] = None
    auto_send_confirmation: Optional[str] = None


class ContactWatchlistReviewModeUpdate(BaseModel):
    review_mode: str
    auto_send_confirmation: Optional[str] = None


class ContactWatchlistScheduleUpdate(BaseModel):
    schedule: Dict[str, Any]


class ContactWatchlistNotificationChannelUpdate(BaseModel):
    notification_channel: str


class ClientWatchlist(BaseModel):
    id: int
    contact_id: int
    contact_name: Optional[str] = None
    name: str
    watch_type: str
    status: str
    criteria: Dict[str, Any]
    schedule: Dict[str, Any]
    notification_channel: str
    review_mode: str
    data_source: str
    source_query: Optional[str] = None
    readiness: Dict[str, Any] = Field(default_factory=dict)
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class WatchlistSourceSetup(BaseModel):
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    watch_type: str
    readiness: str
    current_matching_rows: int
    required_statuses: List[str] = Field(default_factory=list)
    matching_status_counts: Dict[str, int] = Field(default_factory=dict)
    missing_required_statuses: List[str] = Field(default_factory=list)
    required_fields: List[str] = Field(default_factory=list)
    csv_columns: List[str] = Field(default_factory=list)
    gmail_query: str
    saved_search_name: str
    realm_criteria: List[str] = Field(default_factory=list)
    realm_steps: List[str] = Field(default_factory=list)
    export_statuses: List[str] = Field(default_factory=list)
    recommended_method: str
    next_actions: List[str] = Field(default_factory=list)


class WatchlistDataIntakeItem(BaseModel):
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    watch_type: str
    readiness: str
    source_ready: bool
    delivery_ready: bool
    contact_email_present: bool = False
    current_matching_rows: int = 0
    required_statuses: List[str] = Field(default_factory=list)
    missing_required_statuses: List[str] = Field(default_factory=list)
    matching_status_counts: Dict[str, int] = Field(default_factory=dict)
    required_fields: List[str] = Field(default_factory=list)
    gmail_query: str
    saved_search_name: str
    realm_criteria: List[str] = Field(default_factory=list)
    realm_steps: List[str] = Field(default_factory=list)
    export_statuses: List[str] = Field(default_factory=list)
    recommended_method: str
    primary_next_step: str
    blockers: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class WatchlistDataIntakeChecklist(BaseModel):
    overall_status: str
    active_count: int
    ready_count: int
    blocked_count: int
    warning_count: int
    source_rows: int
    pending_csv_count: int
    recommended_next_action: Optional[str] = None
    message: str
    items: List[WatchlistDataIntakeItem] = Field(default_factory=list)


class WatchlistSourceTask(BaseModel):
    task_id: str
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    watch_type: str
    priority: str
    source_ready: bool
    delivery_ready: bool
    client_email_needed: bool = False
    source_goal: str
    required_statuses: List[str] = Field(default_factory=list)
    missing_required_statuses: List[str] = Field(default_factory=list)
    required_fields: List[str] = Field(default_factory=list)
    csv_columns: List[str] = Field(default_factory=list)
    gmail_query: str
    saved_search_name: str
    realm_criteria: List[str] = Field(default_factory=list)
    realm_steps: List[str] = Field(default_factory=list)
    export_statuses: List[str] = Field(default_factory=list)
    drop_folder: Optional[str] = None
    recommended_method: str
    steps: List[str] = Field(default_factory=list)


class WatchlistSourceTaskList(BaseModel):
    overall_status: str
    task_count: int
    ready_count: int
    source_rows: int
    pending_csv_count: int
    message: str
    tasks: List[WatchlistSourceTask] = Field(default_factory=list)


class WatchlistLaunchActionItem(BaseModel):
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    watch_type: str
    priority: str
    source_ready: bool
    delivery_ready: bool
    client_email_needed: bool = False
    required_statuses: List[str] = Field(default_factory=list)
    missing_required_statuses: List[str] = Field(default_factory=list)
    saved_search_name: str
    gmail_query: str
    drop_folder: Optional[str] = None
    source_goal: str
    actions: List[str] = Field(default_factory=list)
    copy_text: str


class WatchlistLaunchPreflightCheck(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    next_step: Optional[str] = None


class WatchlistLaunchActionPack(BaseModel):
    overall_status: str
    generated_at: datetime
    summary: str
    source_rows: int
    pending_csv_count: int
    ready_count: int
    active_count: int
    missing_email_count: int
    source_task_count: int
    gmail_feed_enabled: bool
    auto_send_server_enabled: bool
    gmail_connected: bool
    reso_connector: ResoConnectorStatus
    recommended_method: str
    next_actions: List[str] = Field(default_factory=list)
    preflight_checks: List[WatchlistLaunchPreflightCheck] = Field(default_factory=list)
    copy_text: str
    items: List[WatchlistLaunchActionItem] = Field(default_factory=list)


class WatchlistOperatorHelperFile(BaseModel):
    key: str
    label: str
    filename: str
    path: str
    exists: bool
    size_bytes: int = 0
    updated_at: Optional[datetime] = None
    importable_csv: bool = False
    description: str


class WatchlistSourceKitFile(BaseModel):
    key: str
    label: str
    filename: str
    included: bool = True
    importable: bool = False
    description: str


class WatchlistOperatorHandoffStatus(BaseModel):
    automation_id: str
    automation_status: str
    automation_config_path: str
    schedule_summary: str
    drop_folder: str
    drop_folder_exists: bool
    helper_files_ready: bool
    importable_csv_count: int = 0
    pending_csv_count: int = 0
    processed_csv_count: int = 0
    non_importable_file_count: int = 0
    disabled_template_count: int = 0
    instruction_file_count: int = 0
    files: List[WatchlistOperatorHelperFile] = Field(default_factory=list)
    source_kit_files: List[WatchlistSourceKitFile] = Field(default_factory=list)
    message: str
    next_step: str


class WatchlistAutomationLatestSummary(BaseModel):
    available: bool
    artifact_path: str
    updated_at: Optional[datetime] = None
    checked_at: Optional[datetime] = None
    overall_status: Optional[str] = None
    created_alerts: int = 0
    checked_count: int = 0
    source_rows: int = 0
    pending_csv_count: int = 0
    missing_email_count: int = 0
    gmail_feed_enabled: bool = False
    auto_send_server_enabled: bool = False
    summary: Optional[str] = None
    message: str
    next_actions: List[str] = Field(default_factory=list)


class WatchlistAlertUpdate(BaseModel):
    status: str


class WatchlistAlert(BaseModel):
    id: int
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    property_id: Optional[int] = None
    interaction_id: Optional[int] = None
    draft_status: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    gmail_message_id: Optional[str] = None
    alert_type: str
    title: str
    summary: str
    analysis: str
    source: str
    source_url: Optional[str] = None
    payload: Dict[str, Any]
    notification_statuses: Dict[str, str] = Field(default_factory=dict)
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class WatchlistNotification(BaseModel):
    id: int
    alert_id: int
    watchlist_id: int
    contact_id: int
    channel: str
    status: str
    title: str
    body: str
    error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime


class WatchlistNotificationMarkReportedRequest(BaseModel):
    ids: List[int] = Field(default_factory=list)


class WatchlistNotificationMarkReportedResponse(BaseModel):
    updated: int
    notifications: List[WatchlistNotification] = Field(default_factory=list)


class WatchlistAutoSendArmedItem(BaseModel):
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    contact_email_present: bool
    can_auto_send: bool
    action_required: Optional[str] = None


class WatchlistSafetyStatus(BaseModel):
    auto_send_server_enabled: bool
    gmail_connected: bool
    gmail_account_email: Optional[str] = None
    auto_send_armed_count: int = 0
    auto_send_armed_watchlists: List[WatchlistAutoSendArmedItem] = Field(default_factory=list)
    can_auto_send: bool
    draft_only: bool
    required_server_flag: str = "WATCHLIST_AUTO_SEND_ENABLED"
    message: str


class WatchlistDeliveryGate(BaseModel):
    watchlist_id: int
    contact_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    review_mode: str
    notification_channel: str
    delivery_state: str
    contact_email_present: bool
    gmail_connected: bool
    auto_send_server_enabled: bool
    can_create_gmail_draft: bool
    can_auto_send: bool
    notification_ready: bool
    action_required: Optional[str] = None
    safety_note: str


class WatchlistDeliveryGateList(BaseModel):
    overall_status: str
    active_count: int
    ready_count: int
    blocked_count: int
    warning_count: int
    message: str
    items: List[WatchlistDeliveryGate] = Field(default_factory=list)


class WatchlistReadinessReportItem(BaseModel):
    watchlist_id: int
    contact_name: Optional[str] = None
    watchlist_name: str
    ready: bool
    severity: str
    matching_source_rows: int = 0
    required_statuses: List[str] = Field(default_factory=list)
    matching_status_counts: Dict[str, int] = Field(default_factory=dict)
    missing_required_statuses: List[str] = Field(default_factory=list)
    notification_channel: str
    review_mode: str
    contact_email_present: bool = False
    delivery_ready: bool = False
    delivery_issues: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)


class WatchlistReadinessReport(BaseModel):
    overall_status: str
    active_count: int
    ready_count: int
    blocked_count: int
    warning_count: int
    property_rows: int
    pending_csv_count: int
    safety: WatchlistSafetyStatus
    blockers: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    items: List[WatchlistReadinessReportItem] = Field(default_factory=list)
    message: str


class WatchlistCheckResponse(BaseModel):
    watchlist: ClientWatchlist
    alerts: List[WatchlistAlert]
    created_count: int
    matched_properties: int
    data_source_status: str
    message: str


class WatchlistRunLogCreate(BaseModel):
    run_type: Optional[str] = "manual"
    status: Optional[str] = "success"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    checked_count: Optional[int] = 0
    created_alerts: Optional[int] = 0
    matched_properties: Optional[int] = 0
    active_count: Optional[int] = 0
    due_count: Optional[int] = 0
    not_due_count: Optional[int] = 0
    pending_alert_count: Optional[int] = 0
    draft_alert_count: Optional[int] = 0
    sent_alert_count: Optional[int] = 0
    source_status: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class WatchlistRunLog(BaseModel):
    id: int
    run_type: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    checked_count: int
    created_alerts: int
    matched_properties: int
    active_count: int
    due_count: int
    not_due_count: int
    pending_alert_count: int
    draft_alert_count: int
    sent_alert_count: int
    source_status: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WatchlistDraftResponse(BaseModel):
    success: bool
    message: str
    alert: WatchlistAlert
    interaction_id: Optional[int] = None


class WatchlistDigestDraftResponse(BaseModel):
    success: bool
    message: str
    watchlist: ClientWatchlist
    interaction_id: Optional[int] = None
    alert_ids: List[int] = Field(default_factory=list)
    alert_count: int = 0
    subject: Optional[str] = None
    body: Optional[str] = None

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


class GmailOAuthStatusResponse(BaseModel):
    connection_key: str
    gmail_user_id: str
    status: str
    account_email: Optional[str] = None
    granted_scopes: List[str] = []
    oauth_configured: bool
    has_refresh_token: bool
    reconnect_required: bool = False
    expected_account_email: Optional[str] = None


class GmailOAuthStartResponse(BaseModel):
    connection_key: str
    authorization_url: str
    state_expires_at: datetime
    requested_scopes: List[str]


class PendingEmailDraft(BaseModel):
    interaction_id: int
    contact_id: int
    contact_name: str
    to_email: Optional[str] = None
    subject: str
    body: str
    status: Optional[str] = None
    created_at: datetime
    gmail_draft_id: Optional[str] = None
    gmail_message_id: Optional[str] = None


class PendingEmailDraftsResponse(BaseModel):
    drafts: List[PendingEmailDraft]


class GmailDraftActionRequest(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    confirm_send: Optional[bool] = False
    review_confirmation: Optional[str] = None


class GmailDraftActionResponse(BaseModel):
    success: bool
    message: str
    interaction_id: int
    status: str
    account_email: Optional[str] = None
    to_email: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    gmail_message_id: Optional[str] = None

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
    interaction_id: Optional[int] = None
    extracted_data: Optional[Dict[str, Any]] = None
    email_draft: Optional[EmailDraftResponse] = None

class VoiceMemoTranscriptionResponse(BaseModel):
    success: bool
    text: str
    message: str
    language: Optional[str] = None
    duration: Optional[float] = None

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
