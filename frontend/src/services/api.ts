import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
    baseURL: API_BASE_URL,
});

export interface Contact {
    id: number;
    name: string;
    name_zh?: string;
    email?: string;
    phone?: string;
    company?: string;
    preferred_language?: string;
    client_type?: string;
    status?: string;
    budget_min?: number;
    budget_max?: number;
    expected_roi?: number;
    investment_focus?: string;
    preferred_areas?: string;
    property_preferences?: string;
    notes?: string;
    tags?: string;
    lead_score: number;
    qualification_status?: string;
    qualification_route?: string;
    qualification_json?: string;
    qualification_updated_at?: string;
    mood_score?: number;
    mood_notes?: string;
    ai_summary?: string;
    source?: string;
    last_contacted_at?: string;
    next_followup_at?: string;
    followup_priority?: string;
    stage_id?: number;
}

export interface LegacyVoiceMemoReviewItem {
    contact_id: number;
    contact_name: string;
    interaction_id?: number | null;
    interaction_date?: string | null;
    suggested_name?: string | null;
    suggested_existing_contact_id?: number | null;
    suggested_existing_contact_name?: string | null;
    reason: string;
    evidence_snippet: string;
    action_required: string;
    safety_note: string;
}

export interface LegacyVoiceMemoReviewResponse {
    count: number;
    items: LegacyVoiceMemoReviewItem[];
    message: string;
}

export interface Property {
    id: number;
    unit?: string;
    street: string;
    city: string;
    province?: string;
    postal_code?: string;
    neighborhood?: string;
    property_type: string;
    status?: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    parking?: number;
    year_built?: number;
    listing_price?: number;
    sold_price?: number;
    monthly_rent?: number;
    monthly_expenses?: number;
    cap_rate?: number;
    annual_roi?: number;
    listed_at?: string;
    sold_at?: string;
    leased_at?: string;
    mls_number?: string;
    listing_url?: string;
    photos?: string;
    maintenance_contacts?: string;
    notes?: string;
    owner_client_id?: number;
    tenant_client_id?: number;
    created_at: string;
    updated_at: string;
}

export interface PropertyImportResult {
    success: boolean;
    message: string;
    dry_run: boolean;
    created: number;
    updated: number;
    unchanged: number;
    skipped: number;
    total_rows: number;
    errors: string[];
    warnings: string[];
    preview_rows: Record<string, unknown>[];
    watchlist_match_preview: PropertyImportMatchPreview[];
    watchlist_readiness_preview: PropertyImportReadinessPreview[];
}

export interface CsvDropFolderImportFile {
    file: string;
    sha256?: string;
    status: string;
    result?: PropertyImportResult;
    error?: string;
}

export interface CsvDropFolderImportResult {
    success: boolean;
    message: string;
    dry_run: boolean;
    drop_dir: string;
    state_path: string;
    imported: CsvDropFolderImportFile[];
    skipped: CsvDropFolderImportFile[];
    failed: CsvDropFolderImportFile[];
    processed_count: number;
    pending_before: number;
    pending_after: number;
}

export interface PropertyImportMatchPreview {
    watchlist_id: number;
    watchlist_name: string;
    contact_id: number;
    contact_name?: string;
    watch_type: string;
    match_score: number;
    reasons: string[];
    analysis: string;
    property: Record<string, unknown>;
}

export interface PropertyImportReadinessPreview {
    watchlist_id: number;
    watchlist_name: string;
    contact_id: number;
    contact_name?: string;
    watch_type: string;
    required_statuses: string[];
    current_status_counts: Record<string, number>;
    preview_status_counts: Record<string, number>;
    projected_status_counts: Record<string, number>;
    missing_before: string[];
    missing_after: string[];
    current_matching_rows: number;
    preview_matching_rows: number;
    projected_matching_rows: number;
    source_ready_before: boolean;
    source_ready_after: boolean;
    readiness_delta: 'becomes_ready' | 'improves' | 'unchanged_ready' | 'still_missing' | string;
    primary_next_step: string;
    review_mode: string;
    notification_channel: string;
    contact_email_present: boolean;
    needs_gmail_recipient: boolean;
    auto_send_server_enabled: boolean;
    draft_recipient_ready_after: boolean;
    can_auto_send_after: boolean;
    delivery_state_after: string;
    delivery_blockers_after: string[];
    delivery_next_step: string;
}

export interface PropertySourceStatus {
    properties_count: number;
    status_counts: Record<string, number>;
    latest_property_update?: string;
    internal_properties_ready: boolean;
    csv_import_ready: boolean;
    csv_drop_folder?: string;
    csv_drop_folder_exists: boolean;
    csv_drop_folder_file_count: number;
    csv_drop_folder_importable_count: number;
    csv_drop_folder_pending_count: number;
    csv_drop_folder_processed_count: number;
    csv_drop_folder_total_file_count: number;
    csv_drop_folder_non_importable_count: number;
    csv_drop_folder_disabled_template_count: number;
    csv_drop_folder_instruction_file_count: number;
    csv_drop_folder_state_path?: string;
    external_mls_connector_ready: boolean;
    reso_connector: ResoConnectorStatus;
    watch_type_coverage: {
        watch_type: string;
        label: string;
        required_statuses: string[];
        matching_rows: number;
        usable_rows: number;
        readiness: string;
        missing_fields: string[];
        missing_field_counts: Record<string, number>;
        next_step: string;
    }[];
    data_quality_issues: string[];
    recommended_next_import?: string;
    message: string;
}

export interface ResoConnectorStatus {
    enabled: boolean;
    url_configured: boolean;
    auth_configured: boolean;
    ready: boolean;
    status: string;
    endpoint?: string | null;
    message: string;
}

export interface PropertyFeedConfig {
    id: number;
    gmail_feed_enabled: boolean;
    gmail_query: string;
    gmail_max_results: number;
    last_import_at?: string;
    last_import_message?: string;
    created_at: string;
    updated_at: string;
}

export interface WatchlistReadiness {
    ready: boolean;
    severity: 'ready' | 'warning' | 'blocked' | string;
    issues: string[];
    next_steps: string[];
    required_statuses: string[];
    matching_source_rows: number;
    matching_status_counts: Record<string, number>;
    missing_required_statuses: string[];
    push_subscriptions: number;
    notification_channel: string;
    data_source: string;
    contact_email_present?: boolean;
    delivery_ready?: boolean;
    delivery_issues?: string[];
}

export interface ClientWatchlist {
    id: number;
    contact_id: number;
    contact_name?: string;
    name: string;
    watch_type: string;
    status: string;
    criteria: Record<string, unknown>;
    schedule: Record<string, unknown>;
    notification_channel: string;
    review_mode: string;
    data_source: string;
    source_query?: string | null;
    readiness?: WatchlistReadiness;
    last_checked_at?: string;
    next_check_at?: string;
    created_at: string;
    updated_at: string;
}

export interface WatchlistSourceSetup {
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    watchlist_name: string;
    watch_type: string;
    readiness: string;
    current_matching_rows: number;
    required_statuses: string[];
    matching_status_counts: Record<string, number>;
    missing_required_statuses: string[];
    required_fields: string[];
    csv_columns: string[];
    gmail_query: string;
    saved_search_name: string;
    realm_criteria: string[];
    realm_steps: string[];
    export_statuses: string[];
    recommended_method: string;
    next_actions: string[];
}

export interface WatchlistAlert {
    id: number;
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    property_id?: number;
    interaction_id?: number;
    draft_status?: string | null;
    gmail_draft_id?: string | null;
    gmail_message_id?: string | null;
    alert_type: string;
    title: string;
    summary: string;
    analysis: string;
    source: string;
    source_url?: string;
    payload: Record<string, unknown>;
    notification_statuses: Record<string, string>;
    status: string;
    created_at: string;
    reviewed_at?: string;
}

export interface WatchlistNotification {
    id: number;
    alert_id: number;
    watchlist_id: number;
    contact_id: number;
    channel: string;
    status: string;
    title: string;
    body: string;
    error?: string;
    delivered_at?: string;
    created_at: string;
}

export interface WatchlistNotificationMarkReportedResponse {
    updated: number;
    notifications: WatchlistNotification[];
}

export interface WatchlistSafetyStatus {
    auto_send_server_enabled: boolean;
    gmail_connected: boolean;
    gmail_account_email?: string;
    auto_send_armed_count: number;
    auto_send_armed_watchlists: {
        watchlist_id: number;
        contact_id: number;
        contact_name?: string;
        watchlist_name: string;
        contact_email_present: boolean;
        can_auto_send: boolean;
        action_required?: string | null;
    }[];
    can_auto_send: boolean;
    draft_only: boolean;
    required_server_flag: string;
    message: string;
}

export interface WatchlistDeliveryGate {
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    watchlist_name: string;
    review_mode: string;
    notification_channel: string;
    delivery_state: string;
    contact_email_present: boolean;
    gmail_connected: boolean;
    auto_send_server_enabled: boolean;
    can_create_gmail_draft: boolean;
    can_auto_send: boolean;
    notification_ready: boolean;
    action_required?: string | null;
    safety_note: string;
}

export interface WatchlistDeliveryGateList {
    overall_status: string;
    active_count: number;
    ready_count: number;
    blocked_count: number;
    warning_count: number;
    message: string;
    items: WatchlistDeliveryGate[];
}

export interface WatchlistReadinessReportItem {
    watchlist_id: number;
    contact_name?: string;
    watchlist_name: string;
    ready: boolean;
    severity: string;
    matching_source_rows: number;
    required_statuses: string[];
    matching_status_counts: Record<string, number>;
    missing_required_statuses: string[];
    notification_channel: string;
    review_mode: string;
    contact_email_present: boolean;
    delivery_ready: boolean;
    delivery_issues: string[];
    next_steps: string[];
}

export interface WatchlistReadinessReport {
    overall_status: string;
    active_count: number;
    ready_count: number;
    blocked_count: number;
    warning_count: number;
    property_rows: number;
    pending_csv_count: number;
    safety: WatchlistSafetyStatus;
    blockers: string[];
    next_actions: string[];
    items: WatchlistReadinessReportItem[];
    message: string;
}

export interface WatchlistDataIntakeItem {
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    watchlist_name: string;
    watch_type: string;
    readiness: string;
    source_ready: boolean;
    delivery_ready: boolean;
    contact_email_present: boolean;
    current_matching_rows: number;
    required_statuses: string[];
    missing_required_statuses: string[];
    matching_status_counts: Record<string, number>;
    required_fields: string[];
    gmail_query: string;
    saved_search_name: string;
    realm_criteria: string[];
    realm_steps: string[];
    export_statuses: string[];
    recommended_method: string;
    primary_next_step: string;
    blockers: string[];
    next_actions: string[];
}

export interface WatchlistDataIntakeChecklist {
    overall_status: string;
    active_count: number;
    ready_count: number;
    blocked_count: number;
    warning_count: number;
    source_rows: number;
    pending_csv_count: number;
    recommended_next_action?: string;
    message: string;
    items: WatchlistDataIntakeItem[];
}

export interface WatchlistSourceTask {
    task_id: string;
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    watchlist_name: string;
    watch_type: string;
    priority: string;
    source_ready: boolean;
    delivery_ready: boolean;
    client_email_needed: boolean;
    source_goal: string;
    required_statuses: string[];
    missing_required_statuses: string[];
    required_fields: string[];
    csv_columns: string[];
    gmail_query: string;
    saved_search_name: string;
    realm_criteria: string[];
    realm_steps: string[];
    export_statuses: string[];
    drop_folder?: string;
    recommended_method: string;
    steps: string[];
}

export interface WatchlistSourceTaskList {
    overall_status: string;
    task_count: number;
    ready_count: number;
    source_rows: number;
    pending_csv_count: number;
    message: string;
    tasks: WatchlistSourceTask[];
}

export interface WatchlistLaunchActionItem {
    watchlist_id: number;
    contact_id: number;
    contact_name?: string;
    watchlist_name: string;
    watch_type: string;
    priority: string;
    source_ready: boolean;
    delivery_ready: boolean;
    client_email_needed: boolean;
    required_statuses: string[];
    missing_required_statuses: string[];
    saved_search_name: string;
    gmail_query: string;
    drop_folder?: string | null;
    source_goal: string;
    actions: string[];
    copy_text: string;
}

export interface WatchlistLaunchPreflightCheck {
    key: string;
    label: string;
    status: string;
    detail: string;
    next_step?: string | null;
}

export interface WatchlistLaunchActionPack {
    overall_status: string;
    generated_at: string;
    summary: string;
    source_rows: number;
    pending_csv_count: number;
    ready_count: number;
    active_count: number;
    missing_email_count: number;
    source_task_count: number;
    gmail_feed_enabled: boolean;
    auto_send_server_enabled: boolean;
    gmail_connected: boolean;
    reso_connector: ResoConnectorStatus;
    recommended_method: string;
    next_actions: string[];
    preflight_checks: WatchlistLaunchPreflightCheck[];
    copy_text: string;
    items: WatchlistLaunchActionItem[];
}

export interface WatchlistOperatorHelperFile {
    key: string;
    label: string;
    filename: string;
    path: string;
    exists: boolean;
    size_bytes: number;
    updated_at?: string | null;
    importable_csv: boolean;
    description: string;
}

export interface WatchlistSourceKitFile {
    key: string;
    label: string;
    filename: string;
    included: boolean;
    importable: boolean;
    description: string;
}

export interface WatchlistOperatorHandoffStatus {
    automation_id: string;
    automation_status: string;
    automation_config_path: string;
    schedule_summary: string;
    drop_folder: string;
    drop_folder_exists: boolean;
    helper_files_ready: boolean;
    importable_csv_count: number;
    pending_csv_count: number;
    processed_csv_count: number;
    non_importable_file_count: number;
    disabled_template_count: number;
    instruction_file_count: number;
    files: WatchlistOperatorHelperFile[];
    source_kit_files: WatchlistSourceKitFile[];
    message: string;
    next_step: string;
}

export interface WatchlistRunLog {
    id: number;
    run_type: string;
    status: string;
    started_at?: string;
    finished_at?: string;
    checked_count: number;
    created_alerts: number;
    matched_properties: number;
    active_count: number;
    due_count: number;
    not_due_count: number;
    pending_alert_count: number;
    draft_alert_count: number;
    sent_alert_count: number;
    source_status?: string;
    message?: string;
    error?: string;
    payload: Record<string, unknown>;
    created_at: string;
}

export interface WatchlistCheckResponse {
    watchlist: ClientWatchlist;
    alerts: WatchlistAlert[];
    created_count: number;
    matched_properties: number;
    data_source_status: string;
    message: string;
}

export interface WatchlistDraftResponse {
    success: boolean;
    message: string;
    alert: WatchlistAlert;
    interaction_id?: number;
}

export interface WatchlistDigestDraftResponse {
    success: boolean;
    message: string;
    watchlist: ClientWatchlist;
    interaction_id?: number;
    alert_ids: number[];
    alert_count: number;
    subject?: string;
    body?: string;
}

export interface WatchlistsBatchCheckResponse {
    checked: number;
    created_alerts: number;
    matched_properties: number;
    watchlists: {
        id: number;
        name: string;
        created_count: number;
        matched_properties: number;
        data_source_status: string;
        message: string;
    }[];
}

export interface Interaction {
    id: number;
    contact_id: number;
    interaction_type: string;
    notes: string;
    date: string;
    channel?: string;
    direction?: string;
    ai_parsed_intent?: string;
    ai_parsed_sentiment?: string;
    ai_auto_summary?: string;
    generated_response_type?: string;
    generated_response_content?: string;
    generated_response_status?: string;
}

export interface SmartSearchResult {
    query: string;
    interpreted_intent: string;
    results: Contact[];
}

export interface EmailDraftResponse {
    subject: string;
    body: string;
}

export interface LeadQualification {
    schema_version: string;
    score: number;
    intent: string;
    client_type_guess: string;
    urgency: string;
    confidence: number;
    recommended_route: string;
    status: string;
    summary: string;
    routing_reason: string;
    evidence: string[];
    missing_fields: string[];
    next_actions: string[];
    safe_defaults_applied: string[];
}

export interface LeadQualificationResponse {
    contact: Contact;
    qualification: LeadQualification;
}

export interface EnrichProfileResponse {
    summary: string;
    updated_notes: string;
}

export interface ScoutResponse {
    message: string;
    new_contacts: Contact[];
}

// AI Dashboard types
export interface Nudge {
    contact_id: number;
    contact_name: string;
    company?: string;
    urgency: string;
    message: string;
    action: string;
}

export interface NudgesResponse {
    nudges: Nudge[];
    generated_at: string;
}

export interface SegmentGroup {
    label: string;
    key: string;
    count: number;
    contacts: Contact[];
}

export interface SegmentsResponse {
    segments: SegmentGroup[];
}

export interface PipelineInsightsResponse {
    total_contacts: number;
    stage_breakdown: { name: string; count: number; percentage: number }[];
    avg_score: number;
    conversion_summary: string;
    bottleneck?: string;
    recommendations: string[];
}

// Workflow types
export interface VoiceMemoResponse {
    success: boolean;
    message: string;
    client_name?: string;
    client_id?: number;
    interaction_id?: number;
    extracted_data?: Record<string, unknown>;
    email_draft?: EmailDraftResponse;
}

export interface VoiceMemoTranscriptionResponse {
    success: boolean;
    text: string;
    message: string;
    language?: string;
    duration?: number;
}

export interface MarketTriggerResponse {
    success: boolean;
    message: string;
    investors_count: number;
    drafts_generated: number;
}

export interface MaintenanceReportResponse {
    success: boolean;
    message: string;
    tenant_reply_sent: boolean;
    vendor_notified: boolean;
    issue_type?: string;
    urgency?: string;
}

export interface GmailOAuthStatusResponse {
    connection_key: string;
    gmail_user_id: string;
    status: string;
    account_email?: string;
    granted_scopes: string[];
    oauth_configured: boolean;
    has_refresh_token: boolean;
    reconnect_required: boolean;
    expected_account_email?: string;
}

export interface GmailOAuthStartResponse {
    connection_key: string;
    authorization_url: string;
    state_expires_at: string;
    requested_scopes: string[];
}

export interface PendingEmailDraft {
    interaction_id: number;
    contact_id: number;
    contact_name: string;
    to_email?: string;
    subject: string;
    body: string;
    status?: string;
    created_at: string;
    gmail_draft_id?: string;
    gmail_message_id?: string;
}

export interface PendingEmailDraftsResponse {
    drafts: PendingEmailDraft[];
}

export interface GmailDraftActionResponse {
    success: boolean;
    message: string;
    interaction_id: number;
    status: string;
    account_email?: string;
    to_email?: string;
    gmail_draft_id?: string;
    gmail_message_id?: string;
}

export const crmService = {
    // --- Contacts ---
    getContacts: async () => {
        const response = await api.get<Contact[]>('/contacts');
        return response.data;
    },

    getLegacyVoiceMemoReview: async () => {
        const response = await api.get<LegacyVoiceMemoReviewResponse>('/voice-memo/legacy-review');
        return response.data;
    },

    createContact: async (data: Partial<Contact>) => {
        const response = await api.post<Contact>('/contacts', data);
        return response.data;
    },

    updateContact: async (id: number, data: Partial<Contact>) => {
        const response = await api.put<Contact>(`/contacts/${id}`, data);
        return response.data;
    },

    deleteContact: async (id: number) => {
        const response = await api.delete<Contact>(`/contacts/${id}`);
        return response.data;
    },

    updateContactStage: async (contactId: number, stageId: number) => {
        const response = await api.patch<Contact>(`/contacts/${contactId}/stage`, { stage_id: stageId });
        return response.data;
    },

    qualifyContact: async (contactId: number) => {
        const response = await api.post<LeadQualificationResponse>(`/contacts/${contactId}/qualify`);
        return response.data;
    },

    // --- Properties ---
    getProperties: async () => {
        const response = await api.get<Property[]>('/properties');
        return response.data;
    },

    createProperty: async (data: Partial<Property>) => {
        const response = await api.post<Property>('/properties', data);
        return response.data;
    },

    updateProperty: async (id: number, data: Partial<Property>) => {
        const response = await api.put<Property>(`/properties/${id}`, data);
        return response.data;
    },

    deleteProperty: async (id: number) => {
        const response = await api.delete<Property>(`/properties/${id}`);
        return response.data;
    },

    getPropertySourceStatus: async () => {
        const response = await api.get<PropertySourceStatus>('/property-source/status');
        return response.data;
    },

    getPropertyFeedConfig: async () => {
        const response = await api.get<PropertyFeedConfig>('/property-feed/config');
        return response.data;
    },

    updatePropertyFeedConfig: async (data: Partial<PropertyFeedConfig> & { gmail_feed_confirmation?: string }) => {
        const response = await api.patch<PropertyFeedConfig>('/property-feed/config', data);
        return response.data;
    },

    downloadPropertyCsvTemplate: async () => {
        const response = await api.get<Blob>('/properties/import-template.csv', {
            responseType: 'blob',
        });
        return response.data;
    },

    downloadWatchlistSourceTemplate: async (watchlistId: number) => {
        const response = await api.get<Blob>(`/watchlists/${watchlistId}/source-template.csv`, {
            responseType: 'blob',
        });
        return response.data;
    },

    downloadWatchlistSourceKit: async () => {
        const response = await api.get<Blob>('/watchlists/source-kit.zip', {
            responseType: 'blob',
        });
        return response.data;
    },

    downloadWatchlistClientEmailTasks: async () => {
        const response = await api.get<Blob>('/watchlists/client-email-tasks.csv', {
            responseType: 'blob',
        });
        return response.data;
    },

    importPropertiesCsv: async (file: File, dryRun = false) => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await api.post<PropertyImportResult>('/properties/import-csv', formData, {
            params: { dry_run: dryRun },
        });
        return response.data;
    },

    importPropertiesCsvFolder: async (dryRun = true, maxFiles = 10) => {
        const response = await api.post<CsvDropFolderImportResult>('/properties/import-csv-folder', null, {
            params: { dry_run: dryRun, max_files: maxFiles },
        });
        return response.data;
    },

    importPropertiesFeedText: async (text: string, dryRun = true) => {
        const response = await api.post<PropertyImportResult>('/properties/import-feed-text', {
            text,
            dry_run: dryRun,
        });
        return response.data;
    },

    importPropertiesResoJson: async (data: unknown, dryRun = true) => {
        const response = await api.post<PropertyImportResult>('/properties/import-reso-json', {
            data,
            dry_run: dryRun,
        });
        return response.data;
    },

    importPropertiesGmailFeed: async (query: string, maxResults = 10, dryRun = true, gmailReadConfirmation?: string) => {
        const response = await api.post<PropertyImportResult>('/properties/import-gmail-feed', {
            query,
            max_results: maxResults,
            dry_run: dryRun,
            gmail_read_confirmation: gmailReadConfirmation,
        });
        return response.data;
    },

    // --- Watchlists / Listing Alerts ---
    getWatchlists: async (contactId?: number) => {
        const response = await api.get<ClientWatchlist[]>('/watchlists', {
            params: contactId ? { contact_id: contactId } : {},
        });
        return response.data;
    },

    getWatchlistSourceSetups: async (contactId?: number) => {
        const response = await api.get<WatchlistSourceSetup[]>('/watchlists/source-setups', {
            params: contactId ? { contact_id: contactId } : {},
        });
        return response.data;
    },

    createDefaultWatchlist: async (contactId: number) => {
        const response = await api.post<ClientWatchlist>(`/contacts/${contactId}/watchlists/default`);
        return response.data;
    },

    getWatchlistSafetyStatus: async () => {
        const response = await api.get<WatchlistSafetyStatus>('/watchlists/safety-status');
        return response.data;
    },

    getWatchlistDeliveryGates: async () => {
        const response = await api.get<WatchlistDeliveryGateList>('/watchlists/delivery-gates');
        return response.data;
    },

    getWatchlistReadinessReport: async () => {
        const response = await api.get<WatchlistReadinessReport>('/watchlists/readiness-report');
        return response.data;
    },

    getWatchlistDataIntakeChecklist: async () => {
        const response = await api.get<WatchlistDataIntakeChecklist>('/watchlists/data-intake-checklist');
        return response.data;
    },

    getWatchlistSourceTasks: async () => {
        const response = await api.get<WatchlistSourceTaskList>('/watchlists/source-tasks');
        return response.data;
    },

    getWatchlistLaunchActionPack: async () => {
        const response = await api.get<WatchlistLaunchActionPack>('/watchlists/launch-action-pack');
        return response.data;
    },

    getWatchlistOperatorHandoff: async () => {
        const response = await api.get<WatchlistOperatorHandoffStatus>('/watchlists/operator-handoff');
        return response.data;
    },

    updateWatchlist: async (id: number, data: Partial<ClientWatchlist> & { auto_send_confirmation?: string }) => {
        const response = await api.patch<ClientWatchlist>(`/watchlists/${id}`, data);
        return response.data;
    },

    updateContactWatchlistReviewMode: async (
        contactId: number,
        data: { review_mode: string; auto_send_confirmation?: string },
    ) => {
        const response = await api.patch<ClientWatchlist[]>(`/contacts/${contactId}/watchlists/review-mode`, data);
        return response.data;
    },

    updateContactWatchlistSchedule: async (
        contactId: number,
        data: { schedule: Record<string, unknown> },
    ) => {
        const response = await api.patch<ClientWatchlist[]>(`/contacts/${contactId}/watchlists/schedule`, data);
        return response.data;
    },

    updateContactWatchlistNotificationChannel: async (
        contactId: number,
        data: { notification_channel: string },
    ) => {
        const response = await api.patch<ClientWatchlist[]>(`/contacts/${contactId}/watchlists/notification-channel`, data);
        return response.data;
    },

    checkWatchlist: async (id: number) => {
        const response = await api.post<WatchlistCheckResponse>(`/watchlists/${id}/check`);
        return response.data;
    },

    checkAllWatchlists: async () => {
        const response = await api.post<WatchlistsBatchCheckResponse>('/watchlists/check-all');
        return response.data;
    },

    createWatchlistDigestDraft: async (watchlistId: number) => {
        const response = await api.post<WatchlistDigestDraftResponse>(`/watchlists/${watchlistId}/digest-draft`);
        return response.data;
    },

    createWatchlistDigestGmailDraft: async (watchlistId: number) => {
        const response = await api.post<GmailDraftActionResponse>(`/watchlists/${watchlistId}/digest-gmail-draft`);
        return response.data;
    },

    getWatchlistAlerts: async (status?: string) => {
        const response = await api.get<WatchlistAlert[]>('/watchlist-alerts', {
            params: status ? { status } : {},
        });
        return response.data;
    },

    getWatchlistNotifications: async (params?: { alert_id?: number; channel?: string; status?: string; limit?: number }) => {
        const response = await api.get<WatchlistNotification[]>('/watchlist-notifications', {
            params: params || {},
        });
        return response.data;
    },

    markWatchlistNotificationsReported: async (ids?: number[]) => {
        const response = await api.post<WatchlistNotificationMarkReportedResponse>('/watchlist-notifications/mark-reported', {
            ids: ids || null,
        });
        return response.data;
    },

    getWatchlistRunLogs: async (limit = 10) => {
        const response = await api.get<WatchlistRunLog[]>('/watchlist-run-logs', {
            params: { limit },
        });
        return response.data;
    },

    updateWatchlistAlert: async (id: number, status: string) => {
        const response = await api.patch<WatchlistAlert>(`/watchlist-alerts/${id}`, { status });
        return response.data;
    },

    createWatchlistAlertDraft: async (alertId: number) => {
        const response = await api.post<WatchlistDraftResponse>(`/watchlist-alerts/${alertId}/draft`);
        return response.data;
    },

    createWatchlistAlertGmailDraft: async (alertId: number) => {
        const response = await api.post<GmailDraftActionResponse>(`/watchlist-alerts/${alertId}/gmail-draft`);
        return response.data;
    },

    sendWatchlistAlertGmail: async (alertId: number, data: { subject?: string; body?: string; confirm_send: boolean; review_confirmation?: string }) => {
        const response = await api.post<GmailDraftActionResponse>(`/watchlist-alerts/${alertId}/send`, data);
        return response.data;
    },

    // --- Interactions ---
    getInteractions: async (contactId: number) => {
        const response = await api.get<Interaction[]>(`/contacts/${contactId}/interactions`);
        return response.data;
    },

    createInteraction: async (contactId: number, data: { interaction_type: string; notes: string }) => {
        const response = await api.post<Interaction>(`/contacts/${contactId}/interactions`, data);
        return response.data;
    },

    // --- AI Features ---
    smartSearch: async (query: string) => {
        const response = await api.get<SmartSearchResult>('/smart-search', { params: { q: query } });
        return response.data;
    },

    draftEmail: async (contactId: number) => {
        const response = await api.post<EmailDraftResponse>(`/contacts/${contactId}/draft-email`);
        return response.data;
    },

    getGmailStatus: async () => {
        const response = await api.get<GmailOAuthStatusResponse>('/gmail/oauth/status');
        return response.data;
    },

    startGmailOAuth: async () => {
        const response = await api.post<GmailOAuthStartResponse>('/gmail/oauth/start');
        return response.data;
    },

    disconnectGmail: async () => {
        const response = await api.post<GmailOAuthStatusResponse>('/gmail/oauth/disconnect');
        return response.data;
    },

    getPendingEmailDrafts: async () => {
        const response = await api.get<PendingEmailDraftsResponse>('/email-drafts/pending');
        return response.data;
    },

    createGmailDraft: async (interactionId: number, data?: { subject?: string; body?: string }) => {
        const response = await api.post<GmailDraftActionResponse>(`/email-drafts/${interactionId}/gmail-draft`, data || {});
        return response.data;
    },

    sendGmailDraft: async (interactionId: number, data: { subject?: string; body?: string; confirm_send: boolean; review_confirmation?: string }) => {
        const response = await api.post<GmailDraftActionResponse>(`/email-drafts/${interactionId}/send`, data);
        return response.data;
    },

    enrichProfile: async (contactId: number) => {
        const response = await api.post<EnrichProfileResponse>(`/contacts/${contactId}/enrich`);
        return response.data;
    },

    scoutLeads: async (query: string) => {
        const response = await api.post<ScoutResponse>('/prospector/scout', { query });
        return response.data;
    },

    // --- AI Dashboard Intelligence ---
    getNudges: async () => {
        const response = await api.get<NudgesResponse>('/dashboard/nudges');
        return response.data;
    },

    getSegments: async () => {
        const response = await api.get<SegmentsResponse>('/dashboard/segments');
        return response.data;
    },

    getPipelineInsights: async () => {
        const response = await api.get<PipelineInsightsResponse>('/dashboard/insights');
        return response.data;
    },

    // --- Workflows ---
    voiceMemo: async (audioText: string) => {
        const response = await api.post<VoiceMemoResponse>('/workflow/voice-memo', { audio_text: audioText });
        return response.data;
    },

    transcribeVoiceMemoAudio: async (audioBlob: Blob, filename = 'voice-memo.webm') => {
        const formData = new FormData();
        formData.append('file', audioBlob, filename);
        const response = await api.post<VoiceMemoTranscriptionResponse>('/workflow/voice-memo/transcribe', formData);
        return response.data;
    },

    marketTrigger: async (trigger: string, source?: string) => {
        const response = await api.post<MarketTriggerResponse>('/workflow/market-trigger', { trigger, source });
        return response.data;
    },

    maintenanceReport: async (tenantEmail: string, message: string, photos: string[]) => {
        const response = await api.post<MaintenanceReportResponse>('/workflow/maintenance-report', {
            tenant_email: tenantEmail,
            message,
            photos,
        });
        return response.data;
    },
};
