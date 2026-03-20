import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
    baseURL: API_BASE_URL,
});

export interface AgentRun {
    id: number;
    task_id: number;
    status: string;
    summary?: string;
    plan?: string;
    result?: string;
    error?: string;
    created_at: string;
    started_at?: string;
    finished_at?: string;
}

export interface AgentApproval {
    id: number;
    run_id: number;
    action_type: string;
    risk_level: string;
    payload?: string;
    status: string;
    approved_by?: string;
    approved_at?: string;
    rejected_at?: string;
    rejection_reason?: string;
    created_at: string;
}

export interface AgentAuditLog {
    id: number;
    run_id?: number;
    task_id?: number;
    actor_type: string;
    action: string;
    details?: string;
    created_at: string;
}

export interface FollowUpRecommendationItem {
    contact_id: number;
    contact_name?: string;
    company?: string;
    urgency?: string;
    message?: string;
    suggested_action?: string;
}

export interface FollowUpDraftItem {
    contact_id: number;
    approval_id: number;
    subject: string;
    body: string;
}

export interface FollowUpRecommendationsResponse {
    recommendations: FollowUpRecommendationItem[];
    drafts: FollowUpDraftItem[];
    run_id: number | null;
}

export interface ConversationCloserRunRequest {
    contact_id: number;
    message: string;
    channel?: string;
    operator_goal?: string;
    desired_outcome?: string;
    context_notes?: string;
}

export interface ConversationCloserAnalysis {
    primary_type: string;
    secondary_types: string[];
    sentiment: string;
    confidence: number;
    urgency: string;
    requires_manual_escalation: boolean;
}

export interface ConversationCloserStrategy {
    recommended_action: string;
    goal: string;
    tone: string;
    rationale: string;
    do_not_say: string[];
}

export interface ConversationCloserDraftItem {
    variant: string;
    channel: string;
    subject?: string;
    body: string;
    approval_id?: number | null;
}

export interface ConversationCloserResultResponse {
    summary: string;
    objection_analysis: ConversationCloserAnalysis;
    strategy: ConversationCloserStrategy;
    talking_points: string[];
    drafts: ConversationCloserDraftItem[];
    risk_flags: string[];
    operator_notes: string[];
}

export interface ConversationCloserLatestResponse {
    run_id: number | null;
    status: string | null;
    error: string | null;
    result: ConversationCloserResultResponse | null;
}

export interface ListingCmaComparableInput {
    address: string;
    status: string;
    price?: number;
    close_date?: string;
    property_type?: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    notes?: string;
}

export interface ListingCmaRunRequest {
    contact_id: number;
    property_id?: number;
    meeting_goal?: string;
    subject_property_notes?: string;
    seller_context_notes?: string;
    comparables: ListingCmaComparableInput[];
}

export interface ListingCmaListingBrief {
    summary: string;
    property_highlights: string[];
    seller_context: string[];
}

export interface ListingCmaSupport {
    internal_price_discussion_range?: string | null;
    range_framing: string;
    comparable_narrative: string[];
    missing_data_flags: string[];
}

export interface ListingCmaDraftItem {
    variant: string;
    subject?: string;
    body: string;
    approval_id?: number | null;
}

export interface ListingCmaResultResponse {
    listing_brief: ListingCmaListingBrief;
    cma_support: ListingCmaSupport;
    talking_points: string[];
    seller_drafts: ListingCmaDraftItem[];
    risk_flags: string[];
    operator_notes: string[];
}

export interface ListingCmaLatestResponse {
    run_id: number | null;
    status: string | null;
    error: string | null;
    result: ListingCmaResultResponse | null;
}

export interface BuyerMatchCriteriaInput {
    budget_min?: number;
    budget_max?: number;
    areas: string[];
    property_type?: string;
    bedrooms_min?: number;
    bathrooms_min?: number;
    sqft_min?: number;
    parking_required?: boolean;
    timeline?: string;
    must_haves: string[];
    nice_to_haves: string[];
    deal_breakers: string[];
}

export interface BuyerMatchCandidateInput {
    property_id?: number;
    address?: string;
    list_price?: number;
    property_type?: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    area?: string;
    parking?: number;
    notes?: string;
}

export interface BuyerMatchRunRequest {
    contact_id: number;
    goal?: string;
    criteria: BuyerMatchCriteriaInput;
    buyer_context_notes?: string;
    candidates: BuyerMatchCandidateInput[];
}

export interface BuyerMatchNeedsSummary {
    summary: string;
    must_haves: string[];
    nice_to_haves: string[];
    deal_breakers: string[];
}

export interface BuyerMatchShortlistItem {
    rank: number;
    title: string;
    property_id?: number | null;
    match_strength: string;
    why_it_fits: string[];
    tradeoffs: string[];
}

export interface BuyerMatchDraftItem {
    variant: string;
    subject?: string;
    body: string;
    approval_id?: number | null;
}

export interface BuyerMatchResultResponse {
    buyer_needs_summary: BuyerMatchNeedsSummary;
    shortlist_framing: string;
    shortlist: BuyerMatchShortlistItem[];
    tradeoff_summary: string[];
    recommended_next_manual_action: string;
    buyer_drafts: BuyerMatchDraftItem[];
    risk_flags: string[];
    missing_data_flags: string[];
    operator_notes: string[];
}

export interface BuyerMatchLatestResponse {
    run_id: number | null;
    status: string | null;
    error: string | null;
    result: BuyerMatchResultResponse | null;
}

export interface StrategyCoordinationListingReference {
    listing_ref: string;
    property_id?: number | null;
    label?: string | null;
}

export interface StrategyCoordinationLinkedEntities {
    contacts: number[];
    properties: number[];
    listings: StrategyCoordinationListingReference[];
    runs: number[];
    approvals: number[];
}

export interface StrategyCoordinationRunRequest {
    event_type: string;
    source_type: 'external' | 'internal';
    summary: string;
    details?: string;
    urgency?: 'low' | 'medium' | 'high';
    operator_goal?: string;
    linked_entities: StrategyCoordinationLinkedEntities;
}

export interface StrategyCoordinationEventSummary {
    event_type: string;
    source_type: 'external' | 'internal';
    summary: string;
    details?: string | null;
    urgency: 'low' | 'medium' | 'high';
}

export interface StrategyCoordinationImportanceAssessment {
    classification: 'noise' | 'watchlist' | 'strategy_review_required';
    reason: string;
    confidence: number;
}

export interface StrategyCoordinationPerspectiveBlock {
    relevance: 'none' | 'low' | 'medium' | 'high';
    summary: string;
    supporting_signals: string[];
    risk_flags: string[];
}

export interface StrategyCoordinationPerspectiveBlocks {
    follow_up: StrategyCoordinationPerspectiveBlock;
    conversation_retention: StrategyCoordinationPerspectiveBlock;
    listing_seller: StrategyCoordinationPerspectiveBlock;
    operations_compliance: StrategyCoordinationPerspectiveBlock;
}

export interface StrategyCoordinationExecutionPolicy {
    mode: 'internal_only_non_executable';
    can_execute_actions: boolean;
    can_trigger_agents: boolean;
    can_create_client_outputs: boolean;
}

export interface StrategyCoordinationSynthesis {
    summary: string;
    key_takeaways: string[];
}

export interface StrategyCoordinationRecommendedActions {
    internal_actions: string[];
    human_review_actions: string[];
}

export interface StrategyCoordinationResultResponse {
    event_summary: StrategyCoordinationEventSummary;
    importance_assessment: StrategyCoordinationImportanceAssessment;
    affected_entities: StrategyCoordinationLinkedEntities;
    execution_policy: StrategyCoordinationExecutionPolicy;
    perspective_blocks: StrategyCoordinationPerspectiveBlocks;
    strategy_synthesis: StrategyCoordinationSynthesis;
    recommended_next_actions: StrategyCoordinationRecommendedActions;
    risk_flags: string[];
    operator_notes: string[];
}

export interface StrategyCoordinationLatestResponse {
    run_id: number | null;
    status: string | null;
    error: string | null;
    result: StrategyCoordinationResultResponse | null;
}

export interface AgentOpsReviewModel {
    manual_only: boolean;
    no_send: boolean;
    tracked_agent_types: string[];
}

export interface AgentOpsOverviewAgentItem {
    agent_type: string;
    latest_run_id: number | null;
    latest_run_status: string | null;
    latest_run_created_at: string | null;
    latest_run_error: string | null;
    pending_approvals: number;
    failed_runs: number;
    runs_tracked: number;
}

export interface AgentOpsOverviewTotals {
    pending_approvals: number;
    recent_decisions: number;
    failed_runs: number;
    runs_tracked: number;
}

export interface AgentOpsOverviewResponse {
    agents: AgentOpsOverviewAgentItem[];
    totals: AgentOpsOverviewTotals;
    review_model: AgentOpsReviewModel;
}

export interface AgentOpsApprovalPreview {
    title?: string | null;
    subject?: string | null;
    body_excerpt?: string | null;
    contact_id?: number | null;
    property_id?: number | null;
    review_mode?: string | null;
    payload_text?: string | null;
}

export interface AgentOpsApprovalItem {
    approval_id: number;
    agent_type: string;
    run_id: number;
    task_id: number;
    action_type: string;
    risk_level: string;
    status: string;
    created_at: string;
    approved_at?: string | null;
    rejected_at?: string | null;
    decisioned_at?: string | null;
    approved_by?: string | null;
    rejection_reason?: string | null;
    run_status: string;
    run_summary?: string | null;
    subject_type?: string | null;
    subject_id?: number | null;
    preview: AgentOpsApprovalPreview;
}

export interface AgentOpsRunItem {
    run_id: number;
    task_id: number;
    agent_type: string;
    status: string;
    summary?: string | null;
    error?: string | null;
    created_at: string;
    started_at?: string | null;
    finished_at?: string | null;
    subject_type?: string | null;
    subject_id?: number | null;
    approval_count: number;
    pending_approval_count: number;
    has_pending_approvals: boolean;
    is_internal_only: boolean;
}

export interface AgentOpsAuditItem {
    id: number;
    actor_type: string;
    action: string;
    details_json?: unknown;
    details_text?: string | null;
    created_at: string;
}

export interface AgentOpsRunAuditResponse {
    run: AgentOpsRunItem;
    audit_logs: AgentOpsAuditItem[];
}

const ensureArray = <T>(value: unknown): T[] => {
    return Array.isArray(value) ? (value as T[]) : [];
};

const normalizeFollowUpResponse = (
    value: Partial<FollowUpRecommendationsResponse> | null | undefined,
): FollowUpRecommendationsResponse => {
    return {
        recommendations: ensureArray<FollowUpRecommendationItem>(value?.recommendations),
        drafts: ensureArray<FollowUpDraftItem>(value?.drafts),
        run_id: typeof value?.run_id === 'number' ? value.run_id : null,
    };
};

const normalizeConversationCloserAnalysis = (
    value: Partial<ConversationCloserAnalysis> | null | undefined,
): ConversationCloserAnalysis => {
    return {
        primary_type: typeof value?.primary_type === 'string' ? value.primary_type : 'unknown',
        secondary_types: ensureArray<string>(value?.secondary_types),
        sentiment: typeof value?.sentiment === 'string' ? value.sentiment : 'unknown',
        confidence: typeof value?.confidence === 'number' ? value.confidence : 0,
        urgency: typeof value?.urgency === 'string' ? value.urgency : 'unknown',
        requires_manual_escalation: value?.requires_manual_escalation === true,
    };
};

const normalizeConversationCloserStrategy = (
    value: Partial<ConversationCloserStrategy> | null | undefined,
): ConversationCloserStrategy => {
    return {
        recommended_action:
            typeof value?.recommended_action === 'string' ? value.recommended_action : 'unknown',
        goal: typeof value?.goal === 'string' ? value.goal : 'unknown',
        tone: typeof value?.tone === 'string' ? value.tone : 'unknown',
        rationale: typeof value?.rationale === 'string' ? value.rationale : '',
        do_not_say: ensureArray<string>(value?.do_not_say),
    };
};

const normalizeConversationCloserDraft = (
    value: Partial<ConversationCloserDraftItem> | null | undefined,
): ConversationCloserDraftItem => {
    return {
        variant: typeof value?.variant === 'string' ? value.variant : 'unknown',
        channel: typeof value?.channel === 'string' ? value.channel : 'email',
        subject: typeof value?.subject === 'string' ? value.subject : undefined,
        body: typeof value?.body === 'string' ? value.body : '',
        approval_id: typeof value?.approval_id === 'number' ? value.approval_id : null,
    };
};

const normalizeConversationCloserResult = (
    value: Partial<ConversationCloserResultResponse> | null | undefined,
): ConversationCloserResultResponse | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    return {
        summary: typeof value.summary === 'string' ? value.summary : '',
        objection_analysis: normalizeConversationCloserAnalysis(value.objection_analysis),
        strategy: normalizeConversationCloserStrategy(value.strategy),
        talking_points: ensureArray<string>(value.talking_points),
        drafts: ensureArray<Partial<ConversationCloserDraftItem>>(value.drafts).map(
            normalizeConversationCloserDraft,
        ),
        risk_flags: ensureArray<string>(value.risk_flags),
        operator_notes: ensureArray<string>(value.operator_notes),
    };
};

const normalizeConversationCloserLatest = (
    value: Partial<ConversationCloserLatestResponse> | null | undefined,
): ConversationCloserLatestResponse => {
    return {
        run_id: typeof value?.run_id === 'number' ? value.run_id : null,
        status: typeof value?.status === 'string' ? value.status : null,
        error: typeof value?.error === 'string' ? value.error : null,
        result: normalizeConversationCloserResult(value?.result),
    };
};

const normalizeListingCmaListingBrief = (
    value: Partial<ListingCmaListingBrief> | null | undefined,
): ListingCmaListingBrief => {
    return {
        summary: typeof value?.summary === 'string' ? value.summary : '',
        property_highlights: ensureArray<string>(value?.property_highlights),
        seller_context: ensureArray<string>(value?.seller_context),
    };
};

const normalizeListingCmaSupport = (
    value: Partial<ListingCmaSupport> | null | undefined,
): ListingCmaSupport => {
    return {
        internal_price_discussion_range:
            typeof value?.internal_price_discussion_range === 'string'
                ? value.internal_price_discussion_range
                : null,
        range_framing:
            typeof value?.range_framing === 'string' ? value.range_framing : '',
        comparable_narrative: ensureArray<string>(value?.comparable_narrative),
        missing_data_flags: ensureArray<string>(value?.missing_data_flags),
    };
};

const normalizeListingCmaDraft = (
    value: Partial<ListingCmaDraftItem> | null | undefined,
): ListingCmaDraftItem => {
    return {
        variant: typeof value?.variant === 'string' ? value.variant : 'unknown',
        subject: typeof value?.subject === 'string' ? value.subject : undefined,
        body: typeof value?.body === 'string' ? value.body : '',
        approval_id: typeof value?.approval_id === 'number' ? value.approval_id : null,
    };
};

const normalizeListingCmaResult = (
    value: Partial<ListingCmaResultResponse> | null | undefined,
): ListingCmaResultResponse | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    return {
        listing_brief: normalizeListingCmaListingBrief(value.listing_brief),
        cma_support: normalizeListingCmaSupport(value.cma_support),
        talking_points: ensureArray<string>(value.talking_points),
        seller_drafts: ensureArray<Partial<ListingCmaDraftItem>>(value.seller_drafts).map(
            normalizeListingCmaDraft,
        ),
        risk_flags: ensureArray<string>(value.risk_flags),
        operator_notes: ensureArray<string>(value.operator_notes),
    };
};

const normalizeListingCmaLatest = (
    value: Partial<ListingCmaLatestResponse> | null | undefined,
): ListingCmaLatestResponse => {
    return {
        run_id: typeof value?.run_id === 'number' ? value.run_id : null,
        status: typeof value?.status === 'string' ? value.status : null,
        error: typeof value?.error === 'string' ? value.error : null,
        result: normalizeListingCmaResult(value?.result),
    };
};

const normalizeBuyerMatchNeedsSummary = (
    value: Partial<BuyerMatchNeedsSummary> | null | undefined,
): BuyerMatchNeedsSummary => {
    return {
        summary: typeof value?.summary === 'string' ? value.summary : '',
        must_haves: ensureArray<string>(value?.must_haves),
        nice_to_haves: ensureArray<string>(value?.nice_to_haves),
        deal_breakers: ensureArray<string>(value?.deal_breakers),
    };
};

const normalizeBuyerMatchShortlistItem = (
    value: Partial<BuyerMatchShortlistItem> | null | undefined,
): BuyerMatchShortlistItem => {
    return {
        rank: typeof value?.rank === 'number' ? value.rank : 0,
        title: typeof value?.title === 'string' ? value.title : 'Unknown candidate',
        property_id: typeof value?.property_id === 'number' ? value.property_id : null,
        match_strength: typeof value?.match_strength === 'string' ? value.match_strength : 'unknown',
        why_it_fits: ensureArray<string>(value?.why_it_fits),
        tradeoffs: ensureArray<string>(value?.tradeoffs),
    };
};

const normalizeBuyerMatchDraft = (
    value: Partial<BuyerMatchDraftItem> | null | undefined,
): BuyerMatchDraftItem => {
    return {
        variant: typeof value?.variant === 'string' ? value.variant : 'unknown',
        subject: typeof value?.subject === 'string' ? value.subject : undefined,
        body: typeof value?.body === 'string' ? value.body : '',
        approval_id: typeof value?.approval_id === 'number' ? value.approval_id : null,
    };
};

const normalizeBuyerMatchResult = (
    value: Partial<BuyerMatchResultResponse> | null | undefined,
): BuyerMatchResultResponse | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    return {
        buyer_needs_summary: normalizeBuyerMatchNeedsSummary(value.buyer_needs_summary),
        shortlist_framing:
            typeof value.shortlist_framing === 'string' ? value.shortlist_framing : '',
        shortlist: ensureArray<Partial<BuyerMatchShortlistItem>>(value.shortlist).map(
            normalizeBuyerMatchShortlistItem,
        ),
        tradeoff_summary: ensureArray<string>(value.tradeoff_summary),
        recommended_next_manual_action:
            typeof value.recommended_next_manual_action === 'string'
                ? value.recommended_next_manual_action
                : '',
        buyer_drafts: ensureArray<Partial<BuyerMatchDraftItem>>(value.buyer_drafts).map(
            normalizeBuyerMatchDraft,
        ),
        risk_flags: ensureArray<string>(value.risk_flags),
        missing_data_flags: ensureArray<string>(value.missing_data_flags),
        operator_notes: ensureArray<string>(value.operator_notes),
    };
};

const normalizeBuyerMatchLatest = (
    value: Partial<BuyerMatchLatestResponse> | null | undefined,
): BuyerMatchLatestResponse => {
    return {
        run_id: typeof value?.run_id === 'number' ? value.run_id : null,
        status: typeof value?.status === 'string' ? value.status : null,
        error: typeof value?.error === 'string' ? value.error : null,
        result: normalizeBuyerMatchResult(value?.result),
    };
};

const normalizeStrategyCoordinationListingReference = (
    value: Partial<StrategyCoordinationListingReference> | null | undefined,
): StrategyCoordinationListingReference => {
    return {
        listing_ref: typeof value?.listing_ref === 'string' ? value.listing_ref : 'unknown',
        property_id: typeof value?.property_id === 'number' ? value.property_id : null,
        label: typeof value?.label === 'string' ? value.label : null,
    };
};

const normalizeStrategyCoordinationLinkedEntities = (
    value: Partial<StrategyCoordinationLinkedEntities> | null | undefined,
): StrategyCoordinationLinkedEntities => {
    return {
        contacts: ensureArray<number>(value?.contacts).filter((item) => typeof item === 'number'),
        properties: ensureArray<number>(value?.properties).filter((item) => typeof item === 'number'),
        listings: ensureArray<Partial<StrategyCoordinationListingReference>>(value?.listings).map(
            normalizeStrategyCoordinationListingReference,
        ),
        runs: ensureArray<number>(value?.runs).filter((item) => typeof item === 'number'),
        approvals: ensureArray<number>(value?.approvals).filter((item) => typeof item === 'number'),
    };
};

const normalizeStrategyCoordinationEventSummary = (
    value: Partial<StrategyCoordinationEventSummary> | null | undefined,
): StrategyCoordinationEventSummary => {
    return {
        event_type: typeof value?.event_type === 'string' ? value.event_type : 'manual_event',
        source_type: value?.source_type === 'external' ? 'external' : 'internal',
        summary: typeof value?.summary === 'string' ? value.summary : '',
        details: typeof value?.details === 'string' ? value.details : null,
        urgency:
            value?.urgency === 'low' || value?.urgency === 'high' ? value.urgency : 'medium',
    };
};

const normalizeStrategyCoordinationImportanceAssessment = (
    value: Partial<StrategyCoordinationImportanceAssessment> | null | undefined,
): StrategyCoordinationImportanceAssessment => {
    return {
        classification:
            value?.classification === 'noise' ||
            value?.classification === 'watchlist' ||
            value?.classification === 'strategy_review_required'
                ? value.classification
                : 'watchlist',
        reason: typeof value?.reason === 'string' ? value.reason : '',
        confidence: typeof value?.confidence === 'number' ? value.confidence : 0,
    };
};

const normalizeStrategyCoordinationPerspectiveBlock = (
    value: Partial<StrategyCoordinationPerspectiveBlock> | null | undefined,
): StrategyCoordinationPerspectiveBlock => {
    return {
        relevance:
            value?.relevance === 'none' ||
            value?.relevance === 'low' ||
            value?.relevance === 'medium' ||
            value?.relevance === 'high'
                ? value.relevance
                : 'none',
        summary: typeof value?.summary === 'string' ? value.summary : '',
        supporting_signals: ensureArray<string>(value?.supporting_signals),
        risk_flags: ensureArray<string>(value?.risk_flags),
    };
};

const normalizeStrategyCoordinationPerspectiveBlocks = (
    value: Partial<StrategyCoordinationPerspectiveBlocks> | null | undefined,
): StrategyCoordinationPerspectiveBlocks => {
    return {
        follow_up: normalizeStrategyCoordinationPerspectiveBlock(value?.follow_up),
        conversation_retention: normalizeStrategyCoordinationPerspectiveBlock(
            value?.conversation_retention,
        ),
        listing_seller: normalizeStrategyCoordinationPerspectiveBlock(value?.listing_seller),
        operations_compliance: normalizeStrategyCoordinationPerspectiveBlock(
            value?.operations_compliance,
        ),
    };
};

const normalizeStrategyCoordinationExecutionPolicy = (
    value: Partial<StrategyCoordinationExecutionPolicy> | null | undefined,
): StrategyCoordinationExecutionPolicy => {
    return {
        mode: 'internal_only_non_executable',
        can_execute_actions: value?.can_execute_actions === true,
        can_trigger_agents: value?.can_trigger_agents === true,
        can_create_client_outputs: value?.can_create_client_outputs === true,
    };
};

const normalizeStrategyCoordinationSynthesis = (
    value: Partial<StrategyCoordinationSynthesis> | null | undefined,
): StrategyCoordinationSynthesis => {
    return {
        summary: typeof value?.summary === 'string' ? value.summary : '',
        key_takeaways: ensureArray<string>(value?.key_takeaways),
    };
};

const normalizeStrategyCoordinationRecommendedActions = (
    value: Partial<StrategyCoordinationRecommendedActions> | null | undefined,
): StrategyCoordinationRecommendedActions => {
    return {
        internal_actions: ensureArray<string>(value?.internal_actions),
        human_review_actions: ensureArray<string>(value?.human_review_actions),
    };
};

const normalizeStrategyCoordinationResult = (
    value: Partial<StrategyCoordinationResultResponse> | null | undefined,
): StrategyCoordinationResultResponse | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    return {
        event_summary: normalizeStrategyCoordinationEventSummary(value.event_summary),
        importance_assessment: normalizeStrategyCoordinationImportanceAssessment(
            value.importance_assessment,
        ),
        affected_entities: normalizeStrategyCoordinationLinkedEntities(value.affected_entities),
        execution_policy: normalizeStrategyCoordinationExecutionPolicy(value.execution_policy),
        perspective_blocks: normalizeStrategyCoordinationPerspectiveBlocks(
            value.perspective_blocks,
        ),
        strategy_synthesis: normalizeStrategyCoordinationSynthesis(value.strategy_synthesis),
        recommended_next_actions: normalizeStrategyCoordinationRecommendedActions(
            value.recommended_next_actions,
        ),
        risk_flags: ensureArray<string>(value.risk_flags),
        operator_notes: ensureArray<string>(value.operator_notes),
    };
};

const normalizeStrategyCoordinationLatest = (
    value: Partial<StrategyCoordinationLatestResponse> | null | undefined,
): StrategyCoordinationLatestResponse => {
    return {
        run_id: typeof value?.run_id === 'number' ? value.run_id : null,
        status: typeof value?.status === 'string' ? value.status : null,
        error: typeof value?.error === 'string' ? value.error : null,
        result: normalizeStrategyCoordinationResult(value?.result),
    };
};

const normalizeOpsOverviewAgentItem = (
    value: Partial<AgentOpsOverviewAgentItem> | null | undefined,
): AgentOpsOverviewAgentItem => {
    return {
        agent_type: typeof value?.agent_type === 'string' ? value.agent_type : 'unknown',
        latest_run_id: typeof value?.latest_run_id === 'number' ? value.latest_run_id : null,
        latest_run_status: typeof value?.latest_run_status === 'string' ? value.latest_run_status : null,
        latest_run_created_at:
            typeof value?.latest_run_created_at === 'string' ? value.latest_run_created_at : null,
        latest_run_error: typeof value?.latest_run_error === 'string' ? value.latest_run_error : null,
        pending_approvals: typeof value?.pending_approvals === 'number' ? value.pending_approvals : 0,
        failed_runs: typeof value?.failed_runs === 'number' ? value.failed_runs : 0,
        runs_tracked: typeof value?.runs_tracked === 'number' ? value.runs_tracked : 0,
    };
};

const normalizeOpsOverview = (
    value: Partial<AgentOpsOverviewResponse> | null | undefined,
): AgentOpsOverviewResponse => {
    return {
        agents: ensureArray<Partial<AgentOpsOverviewAgentItem>>(value?.agents).map(
            normalizeOpsOverviewAgentItem,
        ),
        totals: {
            pending_approvals:
                typeof value?.totals?.pending_approvals === 'number'
                    ? value.totals.pending_approvals
                    : 0,
            recent_decisions:
                typeof value?.totals?.recent_decisions === 'number'
                    ? value.totals.recent_decisions
                    : 0,
            failed_runs:
                typeof value?.totals?.failed_runs === 'number' ? value.totals.failed_runs : 0,
            runs_tracked:
                typeof value?.totals?.runs_tracked === 'number' ? value.totals.runs_tracked : 0,
        },
        review_model: {
            manual_only: value?.review_model?.manual_only === true,
            no_send: value?.review_model?.no_send === true,
            tracked_agent_types: ensureArray<string>(value?.review_model?.tracked_agent_types),
        },
    };
};

const normalizeOpsApprovalPreview = (
    value: Partial<AgentOpsApprovalPreview> | null | undefined,
): AgentOpsApprovalPreview => {
    return {
        title: typeof value?.title === 'string' ? value.title : null,
        subject: typeof value?.subject === 'string' ? value.subject : null,
        body_excerpt: typeof value?.body_excerpt === 'string' ? value.body_excerpt : null,
        contact_id: typeof value?.contact_id === 'number' ? value.contact_id : null,
        property_id: typeof value?.property_id === 'number' ? value.property_id : null,
        review_mode: typeof value?.review_mode === 'string' ? value.review_mode : null,
        payload_text: typeof value?.payload_text === 'string' ? value.payload_text : null,
    };
};

const normalizeOpsApprovalItem = (
    value: Partial<AgentOpsApprovalItem> | null | undefined,
): AgentOpsApprovalItem => {
    return {
        approval_id: typeof value?.approval_id === 'number' ? value.approval_id : 0,
        agent_type: typeof value?.agent_type === 'string' ? value.agent_type : 'unknown',
        run_id: typeof value?.run_id === 'number' ? value.run_id : 0,
        task_id: typeof value?.task_id === 'number' ? value.task_id : 0,
        action_type: typeof value?.action_type === 'string' ? value.action_type : 'unknown',
        risk_level: typeof value?.risk_level === 'string' ? value.risk_level : 'medium',
        status: typeof value?.status === 'string' ? value.status : 'unknown',
        created_at: typeof value?.created_at === 'string' ? value.created_at : '',
        approved_at: typeof value?.approved_at === 'string' ? value.approved_at : null,
        rejected_at: typeof value?.rejected_at === 'string' ? value.rejected_at : null,
        decisioned_at: typeof value?.decisioned_at === 'string' ? value.decisioned_at : null,
        approved_by: typeof value?.approved_by === 'string' ? value.approved_by : null,
        rejection_reason:
            typeof value?.rejection_reason === 'string' ? value.rejection_reason : null,
        run_status: typeof value?.run_status === 'string' ? value.run_status : 'unknown',
        run_summary: typeof value?.run_summary === 'string' ? value.run_summary : null,
        subject_type: typeof value?.subject_type === 'string' ? value.subject_type : null,
        subject_id: typeof value?.subject_id === 'number' ? value.subject_id : null,
        preview: normalizeOpsApprovalPreview(value?.preview),
    };
};

const normalizeOpsRunItem = (
    value: Partial<AgentOpsRunItem> | null | undefined,
): AgentOpsRunItem => {
    return {
        run_id: typeof value?.run_id === 'number' ? value.run_id : 0,
        task_id: typeof value?.task_id === 'number' ? value.task_id : 0,
        agent_type: typeof value?.agent_type === 'string' ? value.agent_type : 'unknown',
        status: typeof value?.status === 'string' ? value.status : 'unknown',
        summary: typeof value?.summary === 'string' ? value.summary : null,
        error: typeof value?.error === 'string' ? value.error : null,
        created_at: typeof value?.created_at === 'string' ? value.created_at : '',
        started_at: typeof value?.started_at === 'string' ? value.started_at : null,
        finished_at: typeof value?.finished_at === 'string' ? value.finished_at : null,
        subject_type: typeof value?.subject_type === 'string' ? value.subject_type : null,
        subject_id: typeof value?.subject_id === 'number' ? value.subject_id : null,
        approval_count: typeof value?.approval_count === 'number' ? value.approval_count : 0,
        pending_approval_count:
            typeof value?.pending_approval_count === 'number' ? value.pending_approval_count : 0,
        has_pending_approvals: value?.has_pending_approvals === true,
        is_internal_only: value?.is_internal_only === true,
    };
};

const normalizeOpsAuditItem = (
    value: Partial<AgentOpsAuditItem> | null | undefined,
): AgentOpsAuditItem => {
    return {
        id: typeof value?.id === 'number' ? value.id : 0,
        actor_type: typeof value?.actor_type === 'string' ? value.actor_type : 'unknown',
        action: typeof value?.action === 'string' ? value.action : 'unknown',
        details_json: value?.details_json,
        details_text: typeof value?.details_text === 'string' ? value.details_text : null,
        created_at: typeof value?.created_at === 'string' ? value.created_at : '',
    };
};

const normalizeOpsRunAudit = (
    value: Partial<AgentOpsRunAuditResponse> | null | undefined,
): AgentOpsRunAuditResponse => {
    return {
        run: normalizeOpsRunItem(value?.run),
        audit_logs: ensureArray<Partial<AgentOpsAuditItem>>(value?.audit_logs).map(
            normalizeOpsAuditItem,
        ),
    };
};

export const agentsService = {
    triggerFollowUpRunOnce: async (): Promise<AgentRun> => {
        const res = await api.post<AgentRun>('/agents/follow-up/run-once');
        return res.data;
    },

    getRuns: async (): Promise<AgentRun[]> => {
        const res = await api.get<AgentRun[]>('/agents/runs');
        return ensureArray<AgentRun>(res.data);
    },

    getPendingApprovals: async (): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/approvals');
        return ensureArray<AgentApproval>(res.data);
    },

    getRecentApprovalDecisions: async (limit = 10): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/approvals/history', {
            params: { limit },
        });
        return ensureArray<AgentApproval>(res.data);
    },

    approve: async (approvalId: number): Promise<AgentApproval> => {
        const res = await api.post<AgentApproval>(`/agents/approvals/${approvalId}/approve`);
        return res.data;
    },

    reject: async (approvalId: number, reason: string): Promise<AgentApproval> => {
        const res = await api.post<AgentApproval>(`/agents/approvals/${approvalId}/reject`, null, {
            params: { reason },
        });
        return res.data;
    },

    getFollowUpRecommendations: async (): Promise<FollowUpRecommendationsResponse> => {
        const res = await api.get<FollowUpRecommendationsResponse>('/agents/follow-up/recommendations');
        return normalizeFollowUpResponse(res.data);
    },

    getRunAuditLogs: async (runId: number, limit = 100): Promise<AgentAuditLog[]> => {
        const res = await api.get<AgentAuditLog[]>(`/agents/runs/${runId}/audit-logs`, {
            params: { limit },
        });
        return ensureArray<AgentAuditLog>(res.data);
    },

    triggerConversationCloserRunOnce: async (
        payload: ConversationCloserRunRequest,
    ): Promise<AgentRun> => {
        const res = await api.post<AgentRun>('/agents/conversation-closer/run-once', payload);
        return res.data;
    },

    getConversationCloserRuns: async (limit = 50): Promise<AgentRun[]> => {
        const res = await api.get<AgentRun[]>('/agents/conversation-closer/runs', {
            params: { limit },
        });
        return ensureArray<AgentRun>(res.data);
    },

    getLatestConversationCloserResult: async (): Promise<ConversationCloserLatestResponse> => {
        const res = await api.get<ConversationCloserLatestResponse>(
            '/agents/conversation-closer/latest',
        );
        return normalizeConversationCloserLatest(res.data);
    },

    getConversationCloserPendingApprovals: async (): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/conversation-closer/approvals');
        return ensureArray<AgentApproval>(res.data);
    },

    getConversationCloserApprovalHistory: async (limit = 10): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/conversation-closer/approvals/history', {
            params: { limit },
        });
        return ensureArray<AgentApproval>(res.data);
    },

    getConversationCloserRunAuditLogs: async (
        runId: number,
        limit = 100,
    ): Promise<AgentAuditLog[]> => {
        const res = await api.get<AgentAuditLog[]>(
            `/agents/conversation-closer/runs/${runId}/audit-logs`,
            {
                params: { limit },
            },
        );
        return ensureArray<AgentAuditLog>(res.data);
    },

    triggerListingCmaRunOnce: async (payload: ListingCmaRunRequest): Promise<AgentRun> => {
        const res = await api.post<AgentRun>('/agents/listing-cma/run-once', payload);
        return res.data;
    },

    getListingCmaRuns: async (limit = 50): Promise<AgentRun[]> => {
        const res = await api.get<AgentRun[]>('/agents/listing-cma/runs', {
            params: { limit },
        });
        return ensureArray<AgentRun>(res.data);
    },

    getLatestListingCmaResult: async (): Promise<ListingCmaLatestResponse> => {
        const res = await api.get<ListingCmaLatestResponse>('/agents/listing-cma/latest');
        return normalizeListingCmaLatest(res.data);
    },

    getListingCmaPendingApprovals: async (): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/listing-cma/approvals');
        return ensureArray<AgentApproval>(res.data);
    },

    getListingCmaApprovalHistory: async (limit = 10): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/listing-cma/approvals/history', {
            params: { limit },
        });
        return ensureArray<AgentApproval>(res.data);
    },

    getListingCmaRunAuditLogs: async (
        runId: number,
        limit = 100,
    ): Promise<AgentAuditLog[]> => {
        const res = await api.get<AgentAuditLog[]>(
            `/agents/listing-cma/runs/${runId}/audit-logs`,
            {
                params: { limit },
            },
        );
        return ensureArray<AgentAuditLog>(res.data);
    },

    triggerBuyerMatchRunOnce: async (payload: BuyerMatchRunRequest): Promise<AgentRun> => {
        const res = await api.post<AgentRun>('/agents/buyer-match/run-once', payload);
        return res.data;
    },

    getBuyerMatchRuns: async (limit = 50): Promise<AgentRun[]> => {
        const res = await api.get<AgentRun[]>('/agents/buyer-match/runs', {
            params: { limit },
        });
        return ensureArray<AgentRun>(res.data);
    },

    getLatestBuyerMatchResult: async (): Promise<BuyerMatchLatestResponse> => {
        const res = await api.get<BuyerMatchLatestResponse>('/agents/buyer-match/latest');
        return normalizeBuyerMatchLatest(res.data);
    },

    getBuyerMatchPendingApprovals: async (): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/buyer-match/approvals');
        return ensureArray<AgentApproval>(res.data);
    },

    getBuyerMatchApprovalHistory: async (limit = 10): Promise<AgentApproval[]> => {
        const res = await api.get<AgentApproval[]>('/agents/buyer-match/approvals/history', {
            params: { limit },
        });
        return ensureArray<AgentApproval>(res.data);
    },

    getBuyerMatchRunAuditLogs: async (
        runId: number,
        limit = 100,
    ): Promise<AgentAuditLog[]> => {
        const res = await api.get<AgentAuditLog[]>(
            `/agents/buyer-match/runs/${runId}/audit-logs`,
            {
                params: { limit },
            },
        );
        return ensureArray<AgentAuditLog>(res.data);
    },

    triggerStrategyCoordinationRunOnce: async (
        payload: StrategyCoordinationRunRequest,
    ): Promise<AgentRun> => {
        const res = await api.post<AgentRun>('/agents/strategy-coordination/run-once', payload);
        return res.data;
    },

    getStrategyCoordinationRuns: async (limit = 50): Promise<AgentRun[]> => {
        const res = await api.get<AgentRun[]>('/agents/strategy-coordination/runs', {
            params: { limit },
        });
        return ensureArray<AgentRun>(res.data);
    },

    getLatestStrategyCoordinationResult: async (): Promise<StrategyCoordinationLatestResponse> => {
        const res = await api.get<StrategyCoordinationLatestResponse>(
            '/agents/strategy-coordination/latest',
        );
        return normalizeStrategyCoordinationLatest(res.data);
    },

    getStrategyCoordinationRunReport: async (
        runId: number,
    ): Promise<StrategyCoordinationResultResponse> => {
        const res = await api.get<StrategyCoordinationResultResponse>(
            `/agents/strategy-coordination/runs/${runId}/report`,
        );
        return normalizeStrategyCoordinationResult(res.data) as StrategyCoordinationResultResponse;
    },

    getStrategyCoordinationRunAuditLogs: async (
        runId: number,
        limit = 100,
    ): Promise<AgentAuditLog[]> => {
        const res = await api.get<AgentAuditLog[]>(
            `/agents/strategy-coordination/runs/${runId}/audit-logs`,
            {
                params: { limit },
            },
        );
        return ensureArray<AgentAuditLog>(res.data);
    },

    getOpsOverview: async (): Promise<AgentOpsOverviewResponse> => {
        const res = await api.get<AgentOpsOverviewResponse>('/agents/ops/overview');
        return normalizeOpsOverview(res.data);
    },

    getOpsPendingApprovals: async (limit = 50): Promise<AgentOpsApprovalItem[]> => {
        const res = await api.get<AgentOpsApprovalItem[]>('/agents/ops/approvals/pending', {
            params: { limit },
        });
        return ensureArray<Partial<AgentOpsApprovalItem>>(res.data).map(normalizeOpsApprovalItem);
    },

    getOpsApprovalHistory: async (limit = 50): Promise<AgentOpsApprovalItem[]> => {
        const res = await api.get<AgentOpsApprovalItem[]>('/agents/ops/approvals/history', {
            params: { limit },
        });
        return ensureArray<Partial<AgentOpsApprovalItem>>(res.data).map(normalizeOpsApprovalItem);
    },

    getOpsRecentRuns: async (limit = 50): Promise<AgentOpsRunItem[]> => {
        const res = await api.get<AgentOpsRunItem[]>('/agents/ops/runs/recent', {
            params: { limit },
        });
        return ensureArray<Partial<AgentOpsRunItem>>(res.data).map(normalizeOpsRunItem);
    },

    getOpsFailedRuns: async (limit = 50): Promise<AgentOpsRunItem[]> => {
        const res = await api.get<AgentOpsRunItem[]>('/agents/ops/runs/failed', {
            params: { limit },
        });
        return ensureArray<Partial<AgentOpsRunItem>>(res.data).map(normalizeOpsRunItem);
    },

    getOpsRunAudit: async (
        runId: number,
        limit = 100,
    ): Promise<AgentOpsRunAuditResponse> => {
        const res = await api.get<AgentOpsRunAuditResponse>(`/agents/ops/runs/${runId}/audit-logs`, {
            params: { limit },
        });
        return normalizeOpsRunAudit(res.data);
    },
};
