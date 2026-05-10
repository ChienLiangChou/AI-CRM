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
    mood_score?: number;
    mood_notes?: string;
    ai_summary?: string;
    source?: string;
    last_contacted_at?: string;
    next_followup_at?: string;
    followup_priority?: string;
    stage_id?: number;
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
    extracted_data?: Record<string, unknown>;
    email_draft?: EmailDraftResponse;
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

export interface AgentBridgeCapability {
    key: string;
    label: string;
    status: string;
    product_surface: string;
    description: string;
    guardrails: string[];
    evidence: string[];
    next_action: string;
}

export interface AgentBridgeStatusResponse {
    product: string;
    mode: string;
    bridge_status: string;
    direct_external_actions: boolean;
    safety_boundary: string;
    capabilities: AgentBridgeCapability[];
}

export interface AgentBridgeSessionRequest {
    workflow: string;
    source_context: string;
    client_name?: string;
    property_address?: string;
    requested_outcome?: string;
    include_openclaw: boolean;
    include_codex_chrome: boolean;
}

export interface AgentBridgeHandoff {
    target: string;
    target_label: string;
    status: string;
    title: string;
    instructions: string[];
    prompt: string;
    approval_required: boolean;
}

export interface AgentBridgeSessionResponse {
    session_id: string;
    status: string;
    created_at: string;
    workflow: string;
    summary: string;
    approvals_required: string[];
    handoffs: AgentBridgeHandoff[];
    audit_notes: string[];
}

export type AgentBridgeTarget = 'openclaw' | 'codex_chrome_extension' | 'skc_agent_os';

export interface AgentBridgeExecutionCreateRequest {
    target: AgentBridgeTarget;
    workflow: string;
    execution_profile?: string;
    source_context: string;
    client_name?: string;
    property_address?: string;
    requested_outcome?: string;
    approved_by_kevin: boolean;
    operator_notes?: string;
}

export interface AgentBridgeExecutionApproveRequest {
    approved_by_kevin: boolean;
    operator_notes?: string;
}

export interface AgentBridgeExecutionResultRequest {
    status: 'completed' | 'blocked' | 'needs_review';
    result_summary: string;
    result_payload: Record<string, unknown>;
}

export interface AgentBridgeExecutionResponse {
    run_id: string;
    target: AgentBridgeTarget;
    target_label: string;
    execution_profile: string;
    status: string;
    workflow: string;
    summary: string;
    safety_boundary: string;
    approval_required: boolean;
    approved_by_kevin: boolean;
    created_at: string;
    updated_at: string;
    approved_at?: string;
    handoff_prompt: string;
    execution_package: Record<string, unknown>;
    command_text?: string;
    audit_notes: string[];
    result_summary?: string;
    result_payload: Record<string, unknown>;
}

export const crmService = {
    // --- Contacts ---
    getContacts: async () => {
        const response = await api.get<Contact[]>('/contacts');
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

    // --- Agent Bridge Integrations ---
    getAgentBridgeStatus: async () => {
        const response = await api.get<AgentBridgeStatusResponse>('/integrations/agent-bridge/status');
        return response.data;
    },

    createAgentBridgeSession: async (data: AgentBridgeSessionRequest) => {
        const response = await api.post<AgentBridgeSessionResponse>('/integrations/agent-bridge/sessions', data);
        return response.data;
    },

    listAgentBridgeExecutions: async () => {
        const response = await api.get<AgentBridgeExecutionResponse[]>('/integrations/agent-bridge/executions');
        return response.data;
    },

    createAgentBridgeExecution: async (data: AgentBridgeExecutionCreateRequest) => {
        const response = await api.post<AgentBridgeExecutionResponse>('/integrations/agent-bridge/executions', data);
        return response.data;
    },

    approveAgentBridgeExecution: async (runId: string, data: AgentBridgeExecutionApproveRequest) => {
        const response = await api.post<AgentBridgeExecutionResponse>(`/integrations/agent-bridge/executions/${runId}/approve`, data);
        return response.data;
    },

    recordAgentBridgeExecutionResult: async (runId: string, data: AgentBridgeExecutionResultRequest) => {
        const response = await api.post<AgentBridgeExecutionResponse>(`/integrations/agent-bridge/executions/${runId}/result`, data);
        return response.data;
    },
};
