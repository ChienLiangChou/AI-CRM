import axios from 'axios';
import { agentsService } from './agents';
import type {
    AgentAuditLog,
    AgentOpsApprovalItem,
    AgentOpsRunItem,
    BuyerMatchLatestResponse,
    ConversationCloserLatestResponse,
    DailyMarketScanLatestResponse,
    DailyMarketScanResultResponse,
    FollowUpRecommendationsResponse,
    ListingCmaLatestResponse,
    StrategyCoordinationLatestResponse,
    StrategyCoordinationResultResponse,
} from './agents';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
    baseURL: API_BASE_URL,
});

export type OpenClawAgentType =
    | 'follow_up'
    | 'conversation_closer'
    | 'listing_cma'
    | 'buyer_match'
    | 'strategy_coordination'
    | 'daily_market_scan';

export type OpenClawNeedsInputKind =
    | 'pending_approval'
    | 'failed_run'
    | 'strategy_human_review'
    | 'daily_market_scan_attention';

export type OpenClawDetailDepth = 'deep' | 'shallow';
export type OpenClawDetailLoadStatus = 'loaded' | 'partial' | 'unavailable';
export type OpenClawRouteKind = 'control_room' | 'latest' | 'report' | 'audit_logs';

export interface OpenClawGuardrails {
    read_only: boolean;
    approvals_truth_in_skc: boolean;
    audit_truth_in_skc: boolean;
    no_send: boolean;
    no_crm_mutation: boolean;
}

export interface OpenClawNeedsInputItem {
    kind: OpenClawNeedsInputKind;
    agent_type: OpenClawAgentType;
    run_id?: number | null;
    approval_id?: number | null;
    title: string;
    summary: string;
    created_at: string;
}

export interface OpenClawModuleCard {
    agent_type: OpenClawAgentType;
    label: string;
    latest_run_id?: number | null;
    latest_run_status?: string | null;
    latest_run_created_at?: string | null;
    latest_run_finished_at?: string | null;
    latest_run_error?: string | null;
    pending_approvals: number;
    has_pending_approvals: boolean;
    summary?: string | null;
    highlights: string[];
    risk_flags: string[];
    operator_notes: string[];
}

export interface OpenClawControlRoomResponse {
    as_of: string;
    guardrails: OpenClawGuardrails;
    needs_input_today: OpenClawNeedsInputItem[];
    pending_approvals: AgentOpsApprovalItem[];
    recent_failures: AgentOpsRunItem[];
    recent_runs: AgentOpsRunItem[];
    latest_strategy_coordination: StrategyCoordinationLatestResponse;
    latest_daily_market_scan: DailyMarketScanLatestResponse;
    module_cards: OpenClawModuleCard[];
}

export interface OpenClawReadonlyRoute {
    kind: OpenClawRouteKind;
    path: string;
    method: 'GET';
}

export interface OpenClawModuleDetailSupport {
    agent_type: OpenClawAgentType;
    label: string;
    depth: OpenClawDetailDepth;
    latest?: OpenClawReadonlyRoute;
    report?: OpenClawReadonlyRoute;
    audit_logs?: OpenClawReadonlyRoute;
    notes: string[];
}

export interface OpenClawModuleHomeItem {
    card: OpenClawModuleCard;
    detail_support: OpenClawModuleDetailSupport;
}

export interface OpenClawControlRoomHomeView {
    control_room_route: OpenClawReadonlyRoute;
    snapshot: OpenClawControlRoomResponse;
    modules: OpenClawModuleHomeItem[];
}

export type OpenClawLatestPayload =
    | FollowUpRecommendationsResponse
    | ConversationCloserLatestResponse
    | ListingCmaLatestResponse
    | BuyerMatchLatestResponse
    | StrategyCoordinationLatestResponse
    | DailyMarketScanLatestResponse;

export type OpenClawReportPayload =
    | StrategyCoordinationResultResponse
    | DailyMarketScanResultResponse;

export interface OpenClawModuleDetailResult {
    agent_type: OpenClawAgentType;
    label: string;
    depth: OpenClawDetailDepth;
    status: OpenClawDetailLoadStatus;
    latest?: OpenClawLatestPayload | null;
    report?: OpenClawReportPayload | null;
    audit_logs: AgentAuditLog[];
    errors: string[];
    routes_used: OpenClawReadonlyRoute[];
}

type DetailConfig = {
    label: string;
    depth: OpenClawDetailDepth;
    latestPath: string;
    auditPathTemplate?: string;
    reportPathTemplate?: string;
    notes?: string[];
    loadLatest: () => Promise<OpenClawLatestPayload>;
    loadReport?: (runId: number) => Promise<OpenClawReportPayload>;
    loadAuditLogs?: (runId: number) => Promise<AgentAuditLog[]>;
};

const CONTROL_ROOM_PATH = '/agents/openclaw/control-room';

const DETAIL_CONFIG: Record<OpenClawAgentType, DetailConfig> = {
    follow_up: {
        label: 'Follow-up',
        depth: 'shallow',
        latestPath: '/agents/follow-up/recommendations',
        auditPathTemplate: '/agents/runs/{run_id}/audit-logs',
        notes: [
            'Follow-up stays shallow in Phase 1.',
            'No per-run report route is required for this shell step.',
        ],
        loadLatest: async () => agentsService.getFollowUpRecommendations(),
        loadAuditLogs: async (runId: number) => agentsService.getRunAuditLogs(runId),
    },
    conversation_closer: {
        label: 'Client Conversation Closer',
        depth: 'shallow',
        latestPath: '/agents/conversation-closer/latest',
        auditPathTemplate: '/agents/conversation-closer/runs/{run_id}/audit-logs',
        loadLatest: async () => agentsService.getLatestConversationCloserResult(),
        loadAuditLogs: async (runId: number) => agentsService.getConversationCloserRunAuditLogs(runId),
    },
    listing_cma: {
        label: 'Listing / CMA',
        depth: 'shallow',
        latestPath: '/agents/listing-cma/latest',
        auditPathTemplate: '/agents/listing-cma/runs/{run_id}/audit-logs',
        loadLatest: async () => agentsService.getLatestListingCmaResult(),
        loadAuditLogs: async (runId: number) => agentsService.getListingCmaRunAuditLogs(runId),
    },
    buyer_match: {
        label: 'Buyer Match',
        depth: 'shallow',
        latestPath: '/agents/buyer-match/latest',
        auditPathTemplate: '/agents/buyer-match/runs/{run_id}/audit-logs',
        loadLatest: async () => agentsService.getLatestBuyerMatchResult(),
        loadAuditLogs: async (runId: number) => agentsService.getBuyerMatchRunAuditLogs(runId),
    },
    strategy_coordination: {
        label: 'Strategy Coordination',
        depth: 'deep',
        latestPath: '/agents/strategy-coordination/latest',
        reportPathTemplate: '/agents/strategy-coordination/runs/{run_id}/report',
        auditPathTemplate: '/agents/strategy-coordination/runs/{run_id}/audit-logs',
        loadLatest: async () => agentsService.getLatestStrategyCoordinationResult(),
        loadReport: async (runId: number) => agentsService.getStrategyCoordinationRunReport(runId),
        loadAuditLogs: async (runId: number) => agentsService.getStrategyCoordinationRunAuditLogs(runId),
    },
    daily_market_scan: {
        label: 'Daily Market Scan',
        depth: 'deep',
        latestPath: '/agents/daily-market-scan/latest',
        reportPathTemplate: '/agents/daily-market-scan/runs/{run_id}/report',
        auditPathTemplate: '/agents/daily-market-scan/runs/{run_id}/audit-logs',
        loadLatest: async () => agentsService.getLatestDailyMarketScanResult(),
        loadReport: async (runId: number) => agentsService.getDailyMarketScanRunReport(runId),
        loadAuditLogs: async (runId: number) => agentsService.getDailyMarketScanRunAuditLogs(runId),
    },
};

const ensureArray = <T>(value: unknown): T[] => {
    return Array.isArray(value) ? (value as T[]) : [];
};

const defaultGuardrails = (): OpenClawGuardrails => ({
    read_only: true,
    approvals_truth_in_skc: true,
    audit_truth_in_skc: true,
    no_send: true,
    no_crm_mutation: true,
});

const defaultStrategyLatest = (): StrategyCoordinationLatestResponse => ({
    run_id: null,
    status: null,
    error: null,
    result: null,
});

const defaultDailyLatest = (): DailyMarketScanLatestResponse => ({
    run_id: null,
    status: null,
    error: null,
    result: null,
});

const normalizeGuardrails = (value: unknown): OpenClawGuardrails => {
    if (!value || typeof value !== 'object') {
        return defaultGuardrails();
    }

    const source = value as Partial<OpenClawGuardrails>;
    return {
        read_only: source.read_only !== false,
        approvals_truth_in_skc: source.approvals_truth_in_skc !== false,
        audit_truth_in_skc: source.audit_truth_in_skc !== false,
        no_send: source.no_send !== false,
        no_crm_mutation: source.no_crm_mutation !== false,
    };
};

const normalizeModuleCard = (value: unknown): OpenClawModuleCard | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    const source = value as Partial<OpenClawModuleCard>;
    if (typeof source.agent_type !== 'string' || typeof source.label !== 'string') {
        return null;
    }

    return {
        agent_type: source.agent_type as OpenClawAgentType,
        label: source.label,
        latest_run_id: typeof source.latest_run_id === 'number' ? source.latest_run_id : null,
        latest_run_status: typeof source.latest_run_status === 'string' ? source.latest_run_status : null,
        latest_run_created_at:
            typeof source.latest_run_created_at === 'string' ? source.latest_run_created_at : null,
        latest_run_finished_at:
            typeof source.latest_run_finished_at === 'string' ? source.latest_run_finished_at : null,
        latest_run_error: typeof source.latest_run_error === 'string' ? source.latest_run_error : null,
        pending_approvals: typeof source.pending_approvals === 'number' ? source.pending_approvals : 0,
        has_pending_approvals: source.has_pending_approvals === true,
        summary: typeof source.summary === 'string' ? source.summary : null,
        highlights: ensureArray<string>(source.highlights),
        risk_flags: ensureArray<string>(source.risk_flags),
        operator_notes: ensureArray<string>(source.operator_notes),
    };
};

const normalizeNeedsInputItem = (value: unknown): OpenClawNeedsInputItem | null => {
    if (!value || typeof value !== 'object') {
        return null;
    }

    const source = value as Partial<OpenClawNeedsInputItem>;
    if (
        typeof source.kind !== 'string' ||
        typeof source.agent_type !== 'string' ||
        typeof source.title !== 'string' ||
        typeof source.summary !== 'string' ||
        typeof source.created_at !== 'string'
    ) {
        return null;
    }

    return {
        kind: source.kind as OpenClawNeedsInputKind,
        agent_type: source.agent_type as OpenClawAgentType,
        run_id: typeof source.run_id === 'number' ? source.run_id : null,
        approval_id: typeof source.approval_id === 'number' ? source.approval_id : null,
        title: source.title,
        summary: source.summary,
        created_at: source.created_at,
    };
};

const normalizeControlRoomResponse = (value: unknown): OpenClawControlRoomResponse => {
    const source = value && typeof value === 'object'
        ? (value as Partial<OpenClawControlRoomResponse>)
        : {};

    return {
        as_of: typeof source.as_of === 'string' ? source.as_of : new Date().toISOString(),
        guardrails: normalizeGuardrails(source.guardrails),
        needs_input_today: ensureArray(source.needs_input_today)
            .map(normalizeNeedsInputItem)
            .filter((item): item is OpenClawNeedsInputItem => item !== null),
        pending_approvals: ensureArray<AgentOpsApprovalItem>(source.pending_approvals),
        recent_failures: ensureArray<AgentOpsRunItem>(source.recent_failures),
        recent_runs: ensureArray<AgentOpsRunItem>(source.recent_runs),
        latest_strategy_coordination:
            source.latest_strategy_coordination ?? defaultStrategyLatest(),
        latest_daily_market_scan:
            source.latest_daily_market_scan ?? defaultDailyLatest(),
        module_cards: ensureArray(source.module_cards)
            .map(normalizeModuleCard)
            .filter((item): item is OpenClawModuleCard => item !== null),
    };
};

const resolvePath = (
    template: string | undefined,
    runId: number | null | undefined,
): string | undefined => {
    if (!template) {
        return undefined;
    }
    if (!template.includes('{run_id}')) {
        return template;
    }
    if (typeof runId !== 'number') {
        return undefined;
    }
    return template.replace('{run_id}', String(runId));
};

const buildRoute = (
    kind: OpenClawRouteKind,
    path: string | undefined,
): OpenClawReadonlyRoute | undefined => {
    if (!path) {
        return undefined;
    }
    return {
        kind,
        path,
        method: 'GET',
    };
};

const errorMessage = (kind: OpenClawRouteKind, path: string, error: unknown) => {
    const detail =
        error instanceof Error && error.message
            ? error.message
            : 'request_failed';
    return `${kind}:${path}:${detail}`;
};

const deriveStatus = (
    attemptedCount: number,
    loadedCount: number,
    errors: string[],
): OpenClawDetailLoadStatus => {
    if (loadedCount === 0 || attemptedCount === 0) {
        return 'unavailable';
    }
    if (errors.length > 0 || loadedCount < attemptedCount) {
        return 'partial';
    }
    return 'loaded';
};

export const getModuleDetailSupport = (
    agentType: OpenClawAgentType,
    runId?: number | null,
): OpenClawModuleDetailSupport => {
    const config = DETAIL_CONFIG[agentType];
    return {
        agent_type: agentType,
        label: config.label,
        depth: config.depth,
        latest: buildRoute('latest', config.latestPath),
        report: buildRoute('report', resolvePath(config.reportPathTemplate, runId)),
        audit_logs: buildRoute('audit_logs', resolvePath(config.auditPathTemplate, runId)),
        notes: config.notes ?? [],
    };
};

export const loadControlRoomSnapshot = async (): Promise<OpenClawControlRoomResponse> => {
    const response = await api.get(CONTROL_ROOM_PATH);
    return normalizeControlRoomResponse(response.data);
};

export const buildControlRoomHomeView = async (): Promise<OpenClawControlRoomHomeView> => {
    const snapshot = await loadControlRoomSnapshot();
    return {
        control_room_route: {
            kind: 'control_room',
            path: CONTROL_ROOM_PATH,
            method: 'GET',
        },
        snapshot,
        modules: snapshot.module_cards.map((card) => ({
            card,
            detail_support: getModuleDetailSupport(card.agent_type, card.latest_run_id),
        })),
    };
};

export const loadModuleDetail = async (
    agentType: OpenClawAgentType,
    runId?: number | null,
): Promise<OpenClawModuleDetailResult> => {
    const config = DETAIL_CONFIG[agentType];
    const support = getModuleDetailSupport(agentType, runId);
    let latest: OpenClawLatestPayload | null = null;
    let report: OpenClawReportPayload | null = null;
    let auditLogs: AgentAuditLog[] = [];
    const errors: string[] = [];
    const routesUsed: OpenClawReadonlyRoute[] = [];
    let attemptedCount = 0;
    let loadedCount = 0;

    if (support.latest) {
        attemptedCount += 1;
        routesUsed.push(support.latest);
        try {
            latest = await config.loadLatest();
            loadedCount += 1;
        } catch (error) {
            errors.push(errorMessage('latest', support.latest.path, error));
        }
    }

    if (support.report && config.loadReport && typeof runId === 'number') {
        attemptedCount += 1;
        routesUsed.push(support.report);
        try {
            report = await config.loadReport(runId);
            loadedCount += 1;
        } catch (error) {
            errors.push(errorMessage('report', support.report.path, error));
        }
    }

    if (support.audit_logs && config.loadAuditLogs && typeof runId === 'number') {
        attemptedCount += 1;
        routesUsed.push(support.audit_logs);
        try {
            auditLogs = await config.loadAuditLogs(runId);
            loadedCount += 1;
        } catch (error) {
            errors.push(errorMessage('audit_logs', support.audit_logs.path, error));
        }
    }

    return {
        agent_type: agentType,
        label: support.label,
        depth: support.depth,
        status: deriveStatus(attemptedCount, loadedCount, errors),
        latest,
        report,
        audit_logs: auditLogs,
        errors,
        routes_used: routesUsed,
    };
};
