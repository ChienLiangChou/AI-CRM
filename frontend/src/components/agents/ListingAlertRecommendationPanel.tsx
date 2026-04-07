import { useEffect, useRef, useState } from 'react';
import { agentsService } from '../../services/agents';
import { getApiErrorMessage } from '../../services/httpErrors';
import type {
    AgentApproval,
    AgentAuditLog,
    AgentRun,
    ListingAlertAutomaticBatchResult,
    ListingAlertAutomaticMessageOutcomeSummary,
    ListingAlertAutomaticReviewedResultResponse,
    ListingAlertClientAssociationResponse,
    ListingAlertGmailCandidateMessage,
    ListingAlertGmailFetchCandidatesResponse,
    ListingAlertGmailImportOutcome,
    ListingAlertGmailOAuthStatusResponse,
    ListingAlertManualPacketResultResponse,
    ListingAlertManualReviewPacket,
    ListingAlertManualReviewSubmissionRequest,
    ListingAlertRecommendationLatestResponse,
    ListingAlertRecommendationRunReportResponse,
    ListingAlertReviewedSubmissionResultResponse,
    ListingAlertRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: ListingAlertRecommendationLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

const AUTOMATIC_MAX_MESSAGES = 3;

type PacketFormState = {
    expectedContactId: string;
    messageId: string;
    threadId: string;
    receivedAt: string;
    subject: string;
    fromAddress: string;
    toAddresses: string;
    snippet: string;
    plainTextBody: string;
    htmlBody: string;
    labelIds: string;
    operatorNotes: string;
};

type GmailFetchFormState = {
    accessToken: string;
    gmailUserId: string;
    allowedSender: string;
    labelIds: string;
    subjectKeywords: string;
    maxResults: string;
    expectedContactId: string;
    operatorNotes: string;
};

type AutomaticRunFormState = {
    gmailUserId: string;
    allowedSender: string;
    labelIds: string;
    subjectKeywords: string;
    maxMessages: string;
    operatorNotes: string;
};

type GmailIntakeExecutionMode = 'stored_oauth' | 'manual_fallback';

type ShortlistSelectionState = {
    selected: boolean;
    rank: string;
    whySelected: string;
};

type ReviewFormState = {
    recommendationReasoning: string;
    tradeoffNotes: string;
    draftSubject: string;
    draftBody: string;
    operatorNotes: string;
};

type ApprovalPayloadPreview = {
    subject?: string;
    body?: string;
    contact_id?: number;
    shortlist_refs?: string[];
    shortlist_addresses?: string[];
    review_mode?: string;
    recommendation_reasoning?: string;
    tradeoff_notes?: string[];
    source_run_id?: number;
};

const EMPTY_PACKET_FORM: PacketFormState = {
    expectedContactId: '',
    messageId: '',
    threadId: '',
    receivedAt: '',
    subject: '',
    fromAddress: '',
    toAddresses: '',
    snippet: '',
    plainTextBody: '',
    htmlBody: '',
    labelIds: '',
    operatorNotes: '',
};

const EMPTY_GMAIL_FETCH_FORM: GmailFetchFormState = {
    accessToken: '',
    gmailUserId: 'me',
    allowedSender: '',
    labelIds: '',
    subjectKeywords: '',
    maxResults: '5',
    expectedContactId: '',
    operatorNotes: '',
};

const EMPTY_AUTOMATIC_FORM: AutomaticRunFormState = {
    gmailUserId: 'me',
    allowedSender: '',
    labelIds: '',
    subjectKeywords: '',
    maxMessages: '3',
    operatorNotes: '',
};

const EMPTY_REVIEW_FORM: ReviewFormState = {
    recommendationReasoning: '',
    tradeoffNotes: '',
    draftSubject: '',
    draftBody: '',
    operatorNotes: '',
};

const parseJsonText = (value?: string) => {
    if (!value) {
        return null;
    }

    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
};

const parseApprovalPayload = (payload?: string): ApprovalPayloadPreview => {
    const parsed = parseJsonText(payload);
    if (!parsed || typeof parsed !== 'object') {
        return {};
    }

    return parsed as ApprovalPayloadPreview;
};

const formatAuditDetails = (value?: string) => {
    const parsed = parseJsonText(value);
    if (parsed) {
        return JSON.stringify(parsed, null, 2);
    }
    return value ?? '';
};

const getErrorMessage = getApiErrorMessage;

const splitList = (value: string) =>
    value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean);

const clampAutomaticMaxMessages = (value: string) => {
    const parsed = Number(value.trim() || `${AUTOMATIC_MAX_MESSAGES}`);
    if (!Number.isFinite(parsed)) {
        return `${AUTOMATIC_MAX_MESSAGES}`;
    }
    return String(Math.max(1, Math.min(Math.trunc(parsed), AUTOMATIC_MAX_MESSAGES)));
};

const formatTimestamp = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }
    return date.toLocaleString();
};

const formatCurrency = (value?: number | null) => {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        return 'n/a';
    }

    return new Intl.NumberFormat('en-CA', {
        style: 'currency',
        currency: 'CAD',
        maximumFractionDigits: 0,
    }).format(value);
};

const humanizeEnum = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }

    return value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const renderInlineList = (values: string[]) => {
    if (values.length === 0) {
        return 'n/a';
    }
    return values.join(' | ');
};

const isPacketResult = (
    result: ListingAlertRecommendationRunReportResponse['result'] | ListingAlertRecommendationLatestResponse['result'],
): result is ListingAlertManualPacketResultResponse => {
    return Boolean(result && 'execution_status' in result);
};

const isReviewedSubmissionResult = (
    result: ListingAlertRecommendationRunReportResponse['result'] | ListingAlertRecommendationLatestResponse['result'],
): result is
    | ListingAlertReviewedSubmissionResultResponse
    | ListingAlertAutomaticReviewedResultResponse => {
    return Boolean(result && 'review_outcome' in result);
};

const isAutomaticReviewedResult = (
    result: ListingAlertRecommendationRunReportResponse['result'] | ListingAlertRecommendationLatestResponse['result'],
): result is ListingAlertAutomaticReviewedResultResponse => {
    return Boolean(result && 'workflow_mode' in result && result.workflow_mode === 'automatic');
};

const getRunKindLabel = (result: ListingAlertRecommendationRunReportResponse['result']) => {
    if (isPacketResult(result)) {
        return 'Packet prep';
    }
    if (isReviewedSubmissionResult(result)) {
        return isAutomaticReviewedResult(result)
            ? 'Automatic review'
            : 'Reviewed submission';
    }
    return 'Unknown';
};

const getAssociationTone = (association: ListingAlertClientAssociationResponse) => {
    if (association.status === 'matched') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
    }

    return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
};

const getExecutionTone = (executionStatus: ListingAlertManualPacketResultResponse['execution_status']) => {
    if (executionStatus === 'packet_ready') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
    }

    return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
};

const getApprovalDecisionMeta = (approval: AgentApproval) => {
    if (approval.status === 'approved' && approval.approved_at) {
        return `Approved ${new Date(approval.approved_at).toLocaleString()}`;
    }
    if (approval.status === 'rejected' && approval.rejected_at) {
        return `Rejected ${new Date(approval.rejected_at).toLocaleString()}`;
    }
    return `Created ${new Date(approval.created_at).toLocaleString()}`;
};

const getRunApproval = (
    runId: number,
    approvals: AgentApproval[],
    approvalHistory: AgentApproval[],
) => {
    const pendingApproval = approvals.find((approval) => approval.run_id === runId);
    if (pendingApproval) {
        return pendingApproval;
    }

    return approvalHistory.find((approval) => approval.run_id === runId) ?? null;
};

const getRunApprovalLabel = (approval: AgentApproval | null) => {
    if (!approval) {
        return null;
    }

    if (approval.status === 'pending') {
        return 'Pending';
    }

    return humanizeEnum(approval.status);
};

const getGmailImportOutcomeTone = (status?: ListingAlertGmailImportOutcome['status'] | null) => {
    if (status === 'imported') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
    }
    if (status === 'duplicate_skipped') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
    }
    return 'border-rose-500/30 bg-rose-500/10 text-rose-100';
};

const getAutomaticOutcomeTone = (
    status?: ListingAlertAutomaticMessageOutcomeSummary['status'] | null,
) => {
    if (status === 'waiting_approval') {
        return 'border-sky-500/30 bg-sky-500/10 text-sky-100';
    }
    if (status === 'completed_no_draft') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
    }
    if (status === 'duplicate_skipped' || status === 'blocked') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
    }
    return 'border-white/10 bg-black/10 text-gray-100';
};

const getGmailImportOutcomeFollowupText = (outcome: ListingAlertGmailImportOutcome) => {
    if (outcome.status === 'imported' && outcome.imported_run_id) {
        return `Run #${outcome.imported_run_id} is loaded below. Continue in Packet / Review Result and the existing Manual Review sections.`;
    }
    if (outcome.status === 'duplicate_skipped' && outcome.existing_run_id) {
        return `Existing run #${outcome.existing_run_id} is loaded below. Continue in Packet / Review Result, Audit Log View, and Approval Visibility.`;
    }
    if (outcome.status === 'policy_skipped') {
        return 'No run was created. The existing packet-prep and review state below was left unchanged.';
    }
    return null;
};

const getGmailOAuthStatusTone = (
    status?: ListingAlertGmailOAuthStatusResponse['status'] | null,
) => {
    if (status === 'connected') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
    }
    if (status === 'reconnect_required') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
    }
    return 'border-white/10 bg-black/10 text-gray-200';
};

const getGmailOAuthStatusDescription = (
    status?: ListingAlertGmailOAuthStatusResponse | null,
) => {
    if (!status) {
        return 'Loading Gmail connection status...';
    }
    if (!status.oauth_configured) {
        return 'Backend Gmail OAuth is not configured yet.';
    }
    if (status.status === 'connected') {
        return 'Stored Gmail OAuth connection is healthy and ready for read-only fetch/import.';
    }
    if (status.status === 'reconnect_required') {
        return 'Stored Gmail OAuth connection needs reauthorization before fetch/import can continue.';
    }
    return 'No stored Gmail OAuth connection is active yet.';
};

const findPacketReadyResult = (
    report: ListingAlertRecommendationRunReportResponse | null,
) => {
    if (!report?.result || !isPacketResult(report.result)) {
        return null;
    }

    if (report.result.execution_status !== 'packet_ready') {
        return null;
    }

    return report.result;
};

const renderContextValue = (value: unknown) => {
    if (Array.isArray(value)) {
        return value.length > 0 ? value.join(' | ') : 'none';
    }

    if (typeof value === 'boolean') {
        return value ? 'Yes' : 'No';
    }

    if (value === null || value === undefined || value === '') {
        return 'n/a';
    }

    if (typeof value === 'object') {
        return JSON.stringify(value);
    }

    return String(value);
};

const ListingAlertRecommendationPanel = () => {
    const gmailOauthPopupRef = useRef<Window | null>(null);
    const gmailOauthPollTimerRef = useRef<number | null>(null);

    const [gmailFetchForm, setGmailFetchForm] = useState<GmailFetchFormState>(
        EMPTY_GMAIL_FETCH_FORM,
    );
    const [automaticForm, setAutomaticForm] =
        useState<AutomaticRunFormState>(EMPTY_AUTOMATIC_FORM);
    const [packetForm, setPacketForm] = useState<PacketFormState>(EMPTY_PACKET_FORM);
    const [reviewForm, setReviewForm] = useState<ReviewFormState>(EMPTY_REVIEW_FORM);
    const [shortlistSelections, setShortlistSelections] = useState<
        Record<string, ShortlistSelectionState>
    >({});

    const [gmailCandidatesResult, setGmailCandidatesResult] =
        useState<ListingAlertGmailFetchCandidatesResponse | null>(null);
    const [selectedCandidateMessageId, setSelectedCandidateMessageId] = useState<string | null>(
        null,
    );
    const [gmailImportOutcome, setGmailImportOutcome] =
        useState<ListingAlertGmailImportOutcome | null>(null);
    const [gmailOAuthStatus, setGmailOAuthStatus] =
        useState<ListingAlertGmailOAuthStatusResponse | null>(null);
    const [automaticBatchResult, setAutomaticBatchResult] =
        useState<ListingAlertAutomaticBatchResult | null>(null);

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [runReports, setRunReports] = useState<Record<number, ListingAlertRecommendationRunReportResponse>>(
        {},
    );
    const [latest, setLatest] = useState<ListingAlertRecommendationLatestResponse>(EMPTY_LATEST);
    const [approvals, setApprovals] = useState<AgentApproval[]>([]);
    const [approvalHistory, setApprovalHistory] = useState<AgentApproval[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
    const [automaticRuns, setAutomaticRuns] = useState<AgentRun[]>([]);
    const [automaticRunReports, setAutomaticRunReports] = useState<
        Record<number, ListingAlertRecommendationRunReportResponse>
    >({});
    const [automaticLatest, setAutomaticLatest] =
        useState<ListingAlertRecommendationLatestResponse>(EMPTY_LATEST);
    const [automaticApprovals, setAutomaticApprovals] = useState<AgentApproval[]>([]);
    const [automaticApprovalHistory, setAutomaticApprovalHistory] = useState<AgentApproval[]>(
        [],
    );
    const [selectedAutomaticRunId, setSelectedAutomaticRunId] = useState<number | null>(null);
    const [automaticAuditLogs, setAutomaticAuditLogs] = useState<AgentAuditLog[]>([]);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [automaticLoading, setAutomaticLoading] = useState(true);
    const [automaticRefreshing, setAutomaticRefreshing] = useState(false);
    const [gmailFetching, setGmailFetching] = useState(false);
    const [gmailImporting, setGmailImporting] = useState(false);
    const [automaticRunning, setAutomaticRunning] = useState(false);
    const [gmailStatusLoading, setGmailStatusLoading] = useState(true);
    const [gmailConnectionActionLoading, setGmailConnectionActionLoading] = useState(false);
    const [prepareSubmitting, setPrepareSubmitting] = useState(false);
    const [reviewSubmitting, setReviewSubmitting] = useState(false);
    const [reportLoading, setReportLoading] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [automaticReportLoading, setAutomaticReportLoading] = useState(false);
    const [automaticAuditLoading, setAutomaticAuditLoading] = useState(false);
    const [activeApprovalId, setActiveApprovalId] = useState<number | null>(null);

    const [error, setError] = useState<string | null>(null);
    const [gmailError, setGmailError] = useState<string | null>(null);
    const [automaticError, setAutomaticError] = useState<string | null>(null);
    const [reportError, setReportError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);
    const [approvalError, setApprovalError] = useState<string | null>(null);
    const [automaticReportError, setAutomaticReportError] = useState<string | null>(null);
    const [automaticAuditError, setAutomaticAuditError] = useState<string | null>(null);
    const [automaticApprovalError, setAutomaticApprovalError] = useState<string | null>(null);
    const [reviewFormError, setReviewFormError] = useState<string | null>(null);
    const [gmailStatusNotice, setGmailStatusNotice] = useState<string | null>(null);
    const [showManualTokenFallback, setShowManualTokenFallback] = useState(false);
    const [manualTokenFallbackEnabled, setManualTokenFallbackEnabled] = useState(false);
    const [gmailLastImportMode, setGmailLastImportMode] =
        useState<GmailIntakeExecutionMode | null>(null);

    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const selectedReport = selectedRunId !== null ? runReports[selectedRunId] ?? null : null;
    const selectedPacketResult = findPacketReadyResult(selectedReport);
    const selectedPacket = selectedPacketResult?.manual_review_packet ?? null;
    const selectedAutomaticRun =
        automaticRuns.find((run) => run.id === selectedAutomaticRunId) ?? null;
    const selectedAutomaticReport =
        selectedAutomaticRunId !== null
            ? automaticRunReports[selectedAutomaticRunId] ?? null
            : null;
    const selectedCandidate =
        gmailCandidatesResult?.candidates.find(
            (candidate) => candidate.message_id === selectedCandidateMessageId,
        ) ?? null;
    const storedGmailConnectionReady =
        gmailOAuthStatus?.status === 'connected' && gmailOAuthStatus.has_refresh_token;
    const manualTokenValue = gmailFetchForm.accessToken.trim();
    const usingManualTokenFallback =
        showManualTokenFallback &&
        manualTokenFallbackEnabled &&
        manualTokenValue.length > 0;
    const gmailIntakeReady = storedGmailConnectionReady || usingManualTokenFallback;
    const selectedShortlistCount = Object.values(shortlistSelections).filter(
        (item) => item.selected,
    ).length;
    const automaticRunIds = new Set(automaticRuns.map((run) => run.id));
    const isBusy = loading || refreshing || automaticLoading || automaticRefreshing;

    const loadReportsForRuns = async (runList: AgentRun[]) => {
        const settled = await Promise.allSettled(
            runList.map(async (run) => agentsService.getListingAlertRecommendationRunReport(run.id)),
        );

        const nextReports: Record<number, ListingAlertRecommendationRunReportResponse> = {};
        for (const item of settled) {
            if (item.status === 'fulfilled') {
                nextReports[item.value.run_id] = item.value;
            }
        }

        setRunReports(nextReports);
        return nextReports;
    };

    const loadAutomaticReportsForRuns = async (runList: AgentRun[]) => {
        const settled = await Promise.allSettled(
            runList.map(async (run) =>
                agentsService.getListingAlertRecommendationAutomaticRunReport(run.id),
            ),
        );

        const nextReports: Record<number, ListingAlertRecommendationRunReportResponse> = {};
        for (const item of settled) {
            if (item.status === 'fulfilled') {
                nextReports[item.value.run_id] = item.value;
            }
        }

        setAutomaticRunReports(nextReports);
        return nextReports;
    };

    const loadAuditLogs = async (runId: number) => {
        setAuditLoading(true);
        setAuditError(null);
        try {
            const logs = await agentsService.getListingAlertRecommendationRunAuditLogs(runId);
            setAuditLogs(logs);
        } catch (loadError) {
            setAuditLogs([]);
            setAuditError(getErrorMessage(loadError, 'Audit history is unavailable for this run.'));
        } finally {
            setAuditLoading(false);
        }
    };

    const loadAutomaticAuditLogs = async (runId: number) => {
        setAutomaticAuditLoading(true);
        setAutomaticAuditError(null);
        try {
            const logs = await agentsService.getListingAlertRecommendationAutomaticRunAuditLogs(
                runId,
            );
            setAutomaticAuditLogs(logs);
        } catch (loadError) {
            setAutomaticAuditLogs([]);
            setAutomaticAuditError(
                getErrorMessage(
                    loadError,
                    'Automatic audit history is unavailable for this run.',
                ),
            );
        } finally {
            setAutomaticAuditLoading(false);
        }
    };

    const loadReport = async (runId: number) => {
        setReportLoading(true);
        setReportError(null);
        try {
            const report = await agentsService.getListingAlertRecommendationRunReport(runId);
            setRunReports((current) => ({
                ...current,
                [report.run_id]: report,
            }));
        } catch (loadError) {
            setReportError(getErrorMessage(loadError, 'Run report is unavailable.'));
        } finally {
            setReportLoading(false);
        }
    };

    const loadAutomaticReport = async (runId: number) => {
        setAutomaticReportLoading(true);
        setAutomaticReportError(null);
        try {
            const report = await agentsService.getListingAlertRecommendationAutomaticRunReport(
                runId,
            );
            setAutomaticRunReports((current) => ({
                ...current,
                [report.run_id]: report,
            }));
        } catch (loadError) {
            setAutomaticReportError(
                getErrorMessage(loadError, 'Automatic run report is unavailable.'),
            );
        } finally {
            setAutomaticReportLoading(false);
        }
    };

    const clearGmailOauthPoll = () => {
        if (gmailOauthPollTimerRef.current !== null) {
            window.clearInterval(gmailOauthPollTimerRef.current);
            gmailOauthPollTimerRef.current = null;
        }
    };

    const loadGmailOAuthStatus = async (
        options: { silent?: boolean } = {},
    ): Promise<ListingAlertGmailOAuthStatusResponse | null> => {
        if (!options.silent) {
            setGmailStatusLoading(true);
        }

        try {
            const status = await agentsService.getListingAlertGmailOAuthStatus();
            setGmailOAuthStatus(status);
            return status;
        } catch (loadError) {
            setGmailError(
                getErrorMessage(loadError, 'Failed to load Gmail OAuth connection status.'),
            );
            return null;
        } finally {
            if (!options.silent) {
                setGmailStatusLoading(false);
            }
        }
    };

    const startPollingGmailOAuthStatus = () => {
        clearGmailOauthPoll();
        gmailOauthPollTimerRef.current = window.setInterval(() => {
            void (async () => {
                const status = await loadGmailOAuthStatus({ silent: true });
                const popupClosed = gmailOauthPopupRef.current?.closed ?? true;
                if (status?.status === 'connected') {
                    setGmailStatusNotice(
                        'Gmail OAuth connection is active. Fetch/import now uses the stored mailbox connection by default.',
                    );
                    setGmailConnectionActionLoading(false);
                    clearGmailOauthPoll();
                    return;
                }
                if (status?.status === 'reconnect_required') {
                    setGmailStatusNotice(
                        'Gmail OAuth still needs reauthorization. Reconnect before fetch/import.',
                    );
                    setGmailConnectionActionLoading(false);
                    clearGmailOauthPoll();
                    return;
                }
                if (popupClosed) {
                    setGmailConnectionActionLoading(false);
                    clearGmailOauthPoll();
                }
            })();
        }, 1500);
    };

    const loadData = async (
        mode: 'initial' | 'refresh' = 'refresh',
        preferredRunId?: number | null,
    ) => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }
        setError(null);
        setApprovalError(null);

        try {
            const [runsData, latestData, approvalsData, approvalHistoryData] = await Promise.all([
                agentsService.getListingAlertRecommendationRuns(),
                agentsService.getLatestListingAlertRecommendationResult(),
                agentsService.getListingAlertRecommendationPendingApprovals(),
                agentsService.getListingAlertRecommendationApprovalHistory(),
            ]);

            setRuns(runsData);
            setLatest(latestData);
            setApprovals(approvalsData);
            setApprovalHistory(approvalHistoryData);

            const nextSelectedRunId =
                preferredRunId && runsData.some((run) => run.id === preferredRunId)
                    ? preferredRunId
                    : selectedRunId && runsData.some((run) => run.id === selectedRunId)
                        ? selectedRunId
                        : (runsData[0]?.id ?? null);

            setSelectedRunId(nextSelectedRunId);
            await loadReportsForRuns(runsData);
        } catch (loadError) {
            setError(
                getErrorMessage(loadError, 'Failed to load Listing Alert Recommendation data.'),
            );
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    const loadAutomaticData = async (
        mode: 'initial' | 'refresh' = 'refresh',
        preferredRunId?: number | null,
    ) => {
        if (mode === 'initial') {
            setAutomaticLoading(true);
        } else {
            setAutomaticRefreshing(true);
        }
        setAutomaticError(null);
        setAutomaticApprovalError(null);

        try {
            const [runsData, latestData, approvalsData, approvalHistoryData] =
                await Promise.all([
                    agentsService.getListingAlertRecommendationAutomaticRuns(),
                    agentsService.getLatestListingAlertRecommendationAutomaticResult(),
                    agentsService.getListingAlertRecommendationAutomaticPendingApprovals(),
                    agentsService.getListingAlertRecommendationAutomaticApprovalHistory(),
                ]);

            setAutomaticRuns(runsData);
            setAutomaticLatest(latestData);
            setAutomaticApprovals(approvalsData);
            setAutomaticApprovalHistory(approvalHistoryData);

            const nextSelectedRunId =
                preferredRunId && runsData.some((run) => run.id === preferredRunId)
                    ? preferredRunId
                    : selectedAutomaticRunId &&
                        runsData.some((run) => run.id === selectedAutomaticRunId)
                        ? selectedAutomaticRunId
                        : (runsData[0]?.id ?? null);

            setSelectedAutomaticRunId(nextSelectedRunId);
            await loadAutomaticReportsForRuns(runsData);
        } catch (loadError) {
            setAutomaticError(
                getErrorMessage(
                    loadError,
                    'Failed to load Automatic Mode Listing Alert data.',
                ),
            );
        } finally {
            if (mode === 'initial') {
                setAutomaticLoading(false);
            } else {
                setAutomaticRefreshing(false);
            }
        }
    };

    const refreshAllData = async (
        preferredManualRunId?: number | null,
        preferredAutomaticRunId?: number | null,
    ) => {
        await Promise.all([
            loadData('refresh', preferredManualRunId),
            loadAutomaticData('refresh', preferredAutomaticRunId),
        ]);
    };

    useEffect(() => {
        void loadData('initial');
        void loadAutomaticData('initial');
        void loadGmailOAuthStatus();

        return () => {
            clearGmailOauthPoll();
        };
    }, []);

    useEffect(() => {
        if (selectedRunId === null) {
            setAuditLogs([]);
            setAuditError(null);
            setReportError(null);
            return;
        }

        if (!runReports[selectedRunId]) {
            void loadReport(selectedRunId);
        }
        void loadAuditLogs(selectedRunId);
    }, [selectedRunId]);

    useEffect(() => {
        if (selectedAutomaticRunId === null) {
            setAutomaticAuditLogs([]);
            setAutomaticAuditError(null);
            setAutomaticReportError(null);
            return;
        }

        if (!automaticRunReports[selectedAutomaticRunId]) {
            void loadAutomaticReport(selectedAutomaticRunId);
        }
        void loadAutomaticAuditLogs(selectedAutomaticRunId);
    }, [selectedAutomaticRunId]);

    useEffect(() => {
        if (!selectedPacket) {
            setShortlistSelections({});
            setReviewForm(EMPTY_REVIEW_FORM);
            setReviewFormError(null);
            return;
        }

        const nextSelections: Record<string, ShortlistSelectionState> = {};
        for (const listing of selectedPacket.extracted_listings) {
            nextSelections[listing.listing_ref] = {
                selected: false,
                rank: '',
                whySelected: '',
            };
        }

        setShortlistSelections(nextSelections);
        setReviewForm(EMPTY_REVIEW_FORM);
        setReviewFormError(null);
    }, [selectedRunId, selectedPacket?.packet_version]);

    const updatePacketField = (key: keyof PacketFormState, value: string) => {
        setPacketForm((current) => ({
            ...current,
            [key]: value,
        }));
    };

    const updateGmailFetchField = (key: keyof GmailFetchFormState, value: string) => {
        setGmailFetchForm((current) => ({
            ...current,
            [key]: value,
        }));
    };

    const updateAutomaticField = (key: keyof AutomaticRunFormState, value: string) => {
        setAutomaticForm((current) => ({
            ...current,
            [key]: key === 'maxMessages' ? clampAutomaticMaxMessages(value) : value,
        }));
    };

    const updateReviewField = (key: keyof ReviewFormState, value: string) => {
        setReviewForm((current) => ({
            ...current,
            [key]: value,
        }));
    };

    const applyExpectedContactOverride = (contactId: number) => {
        const value = String(contactId);
        setGmailFetchForm((current) => ({
            ...current,
            expectedContactId: value,
        }));
        setPacketForm((current) => ({
            ...current,
            expectedContactId: value,
        }));
        setGmailStatusNotice(
            `Expected contact ID override set to #${contactId}. Import or packet prep will use it only when you rerun manually.`,
        );
    };

    const handleRefreshGmailOAuthStatus = async () => {
        setGmailStatusNotice(null);
        await loadGmailOAuthStatus();
    };

    const handleRefreshPanel = async () => {
        await Promise.all([
            refreshAllData(selectedRunId, selectedAutomaticRunId),
            loadGmailOAuthStatus({ silent: true }),
        ]);
    };

    const handleStartGmailOAuth = async () => {
        if (gmailOAuthStatus && !gmailOAuthStatus.oauth_configured) {
            setGmailError('Backend Gmail OAuth is not configured yet.');
            return;
        }

        setGmailError(null);
        setGmailStatusNotice(null);
        setGmailConnectionActionLoading(true);

        const popup = window.open(
            'about:blank',
            'listing-alert-gmail-oauth',
            'popup=yes,width=640,height=760',
        );
        if (!popup) {
            setGmailConnectionActionLoading(false);
            setGmailError('Popup was blocked. Allow popups and try Connect Gmail again.');
            return;
        }

        popup.document.title = 'Connect Gmail';
        popup.document.body.innerHTML =
            '<div style="font-family: sans-serif; padding: 24px;">Opening Gmail OAuth…</div>';

        try {
            const start = await agentsService.startListingAlertGmailOAuth();
            gmailOauthPopupRef.current = popup;
            popup.location.href = start.authorization_url;
            setGmailStatusNotice(
                'Gmail OAuth window opened. Complete Google authorization, then this panel will refresh connection status automatically.',
            );
            startPollingGmailOAuthStatus();
        } catch (startError) {
            popup.close();
            gmailOauthPopupRef.current = null;
            setGmailConnectionActionLoading(false);
            setGmailError(
                getErrorMessage(startError, 'Failed to start Gmail OAuth connection flow.'),
            );
        }
    };

    const handleDisconnectGmailOAuth = async () => {
        setGmailConnectionActionLoading(true);
        setGmailError(null);
        setGmailStatusNotice(null);
        clearGmailOauthPoll();

        try {
            const status = await agentsService.disconnectListingAlertGmailOAuth();
            setGmailOAuthStatus(status);
            setGmailStatusNotice(
                'Stored Gmail OAuth connection was disconnected. Fetch/import now requires reconnect or the debug fallback token.',
            );
        } catch (disconnectError) {
            setGmailError(
                getErrorMessage(disconnectError, 'Failed to disconnect stored Gmail OAuth connection.'),
            );
        } finally {
            setGmailConnectionActionLoading(false);
        }
    };

    const syncPacketFormFromImportedMessage = (
        outcome: ListingAlertGmailImportOutcome,
        candidate?: ListingAlertGmailCandidateMessage | null,
    ) => {
        const message = outcome.normalized_message;
        if (!message) {
            return;
        }

        setPacketForm({
            expectedContactId: gmailFetchForm.expectedContactId.trim(),
            messageId: message.message_id,
            threadId: message.thread_id,
            receivedAt: message.received_at
                ? new Date(message.received_at).toISOString().slice(0, 16)
                : '',
            subject: message.subject,
            fromAddress: message.from_address || '',
            toAddresses: message.to_addresses.join('\n'),
            snippet: message.snippet || '',
            plainTextBody: message.plain_text_body || '',
            htmlBody: message.html_body || '',
            labelIds: message.label_ids.join('\n'),
            operatorNotes:
                gmailFetchForm.operatorNotes.trim() ||
                packetForm.operatorNotes ||
                (candidate?.existing_run_id
                    ? `Duplicate Gmail import reference for run #${candidate.existing_run_id}.`
                    : 'Imported from Gmail read-only intake.'),
        });
    };

    const toggleListingSelection = (listingRef: string, selected: boolean) => {
        setShortlistSelections((current) => {
            const currentEntry = current[listingRef] ?? {
                selected: false,
                rank: '',
                whySelected: '',
            };

            if (selected && !currentEntry.selected) {
                const selectedCount = Object.values(current).filter((item) => item.selected).length;
                if (selectedCount >= 3) {
                    return current;
                }
            }

            return {
                ...current,
                [listingRef]: {
                    ...currentEntry,
                    selected,
                    rank: selected
                        ? currentEntry.rank || String(
                              Object.values(current).filter((item) => item.selected).length + 1,
                          )
                        : '',
                },
            };
        });
    };

    const updateListingSelection = (
        listingRef: string,
        field: 'rank' | 'whySelected',
        value: string,
    ) => {
        setShortlistSelections((current) => ({
            ...current,
            [listingRef]: {
                ...(current[listingRef] ?? {
                    selected: false,
                    rank: '',
                    whySelected: '',
                }),
                [field]: value,
            },
        }));
    };

    const handleFetchGmailCandidates = async () => {
        if (!gmailFetchForm.allowedSender.trim()) {
            setGmailError('Allowed sender is required for constrained Gmail fetch.');
            return;
        }

        if (!usingManualTokenFallback && !storedGmailConnectionReady) {
            setGmailError(
                gmailOAuthStatus?.status === 'reconnect_required'
                    ? 'Stored Gmail OAuth needs reconnect before fetch/import can continue.'
                    : 'Connect Gmail first, or explicitly enable the internal debug token fallback.',
            );
            return;
        }

        if (manualTokenFallbackEnabled && showManualTokenFallback && !manualTokenValue) {
            setGmailError('Debug fallback is enabled, but no temporary Gmail token was provided.');
            return;
        }

        const maxResults = Number(gmailFetchForm.maxResults.trim() || '5');
        if (!Number.isFinite(maxResults) || maxResults <= 0) {
            setGmailError('Max results must be a positive number.');
            return;
        }

        setGmailFetching(true);
        setGmailError(null);
        setGmailImportOutcome(null);

        try {
            const result = await agentsService.fetchListingAlertGmailCandidates({
                access_token: usingManualTokenFallback ? manualTokenValue : '',
                gmail_user_id: gmailFetchForm.gmailUserId.trim() || 'me',
                query_policy: {
                    allowed_sender: gmailFetchForm.allowedSender.trim(),
                    label_ids: splitList(gmailFetchForm.labelIds),
                    subject_keywords: splitList(gmailFetchForm.subjectKeywords),
                    max_results: maxResults,
                },
            });

            setGmailCandidatesResult(result);
            setSelectedCandidateMessageId(result.candidates[0]?.message_id ?? null);
        } catch (fetchError) {
            setGmailError(
                getErrorMessage(fetchError, 'Failed to fetch constrained Gmail candidates.'),
            );
        } finally {
            setGmailFetching(false);
        }
    };

    const handleImportGmailMessage = async () => {
        if (!selectedCandidateMessageId) {
            setGmailError('Select one Gmail candidate message before importing.');
            return;
        }

        if (!usingManualTokenFallback && !storedGmailConnectionReady) {
            setGmailError(
                gmailOAuthStatus?.status === 'reconnect_required'
                    ? 'Stored Gmail OAuth needs reconnect before import can continue.'
                    : 'Connect Gmail first, or explicitly enable the internal debug token fallback.',
            );
            return;
        }

        if (manualTokenFallbackEnabled && showManualTokenFallback && !manualTokenValue) {
            setGmailError('Debug fallback is enabled, but no temporary Gmail token was provided.');
            return;
        }

        const expectedContactId = gmailFetchForm.expectedContactId.trim();
        if (expectedContactId && !Number.isFinite(Number(expectedContactId))) {
            setGmailError('Expected contact ID must be a valid number when provided.');
            return;
        }

        const maxResults = Number(gmailFetchForm.maxResults.trim() || '5');
        if (!Number.isFinite(maxResults) || maxResults <= 0) {
            setGmailError('Max results must be a positive number.');
            return;
        }

        const selectedCandidate =
            gmailCandidatesResult?.candidates.find(
                (candidate) => candidate.message_id === selectedCandidateMessageId,
            ) ?? null;

        setGmailImporting(true);
        setGmailError(null);
        setGmailLastImportMode(usingManualTokenFallback ? 'manual_fallback' : 'stored_oauth');

        try {
            const outcome = await agentsService.importListingAlertGmailMessage({
                access_token: usingManualTokenFallback ? manualTokenValue : '',
                gmail_user_id: gmailFetchForm.gmailUserId.trim() || 'me',
                query_policy: {
                    allowed_sender: gmailFetchForm.allowedSender.trim(),
                    label_ids: splitList(gmailFetchForm.labelIds),
                    subject_keywords: splitList(gmailFetchForm.subjectKeywords),
                    max_results: maxResults,
                },
                message_id: selectedCandidateMessageId,
                expected_contact_id: expectedContactId ? Number(expectedContactId) : null,
                operator_notes: gmailFetchForm.operatorNotes.trim() || null,
            });

            setGmailImportOutcome(outcome);
            syncPacketFormFromImportedMessage(outcome, selectedCandidate);
            setGmailFetchForm((current) => ({
                ...current,
                accessToken: '',
            }));

            if (outcome.status === 'imported' && outcome.imported_run_id) {
                await loadData('refresh', outcome.imported_run_id);
                return;
            }

            if (outcome.status === 'duplicate_skipped' && outcome.existing_run_id) {
                await loadData('refresh', outcome.existing_run_id);
            }
        } catch (importError) {
            setGmailImportOutcome(null);
            setGmailError(getErrorMessage(importError, 'Failed to import Gmail message.'));
        } finally {
            setGmailImporting(false);
        }
    };

    const handleRunAutomaticMode = async () => {
        if (!automaticForm.allowedSender.trim()) {
            setAutomaticError('Allowed sender is required for Automatic Mode.');
            return;
        }

        if (!storedGmailConnectionReady) {
            setAutomaticError(
                gmailOAuthStatus?.status === 'reconnect_required'
                    ? 'Stored Gmail OAuth needs reconnect before Automatic Mode can run.'
                    : 'Connect Gmail first. Automatic Mode uses the stored Gmail OAuth production path only.',
            );
            return;
        }

        const maxMessages = Number(
            clampAutomaticMaxMessages(automaticForm.maxMessages.trim() || '3'),
        );
        if (!Number.isFinite(maxMessages) || maxMessages <= 0) {
            setAutomaticError('Max messages must be between 1 and 3.');
            return;
        }

        setAutomaticRunning(true);
        setAutomaticError(null);

        try {
            const result = await agentsService.runListingAlertAutomaticModeOnce({
                gmail_read_config: {
                    gmail_user_id: automaticForm.gmailUserId.trim() || 'me',
                    query_policy: {
                        allowed_sender: automaticForm.allowedSender.trim(),
                        label_ids: splitList(automaticForm.labelIds),
                        subject_keywords: splitList(automaticForm.subjectKeywords),
                        max_results: maxMessages,
                    },
                },
                operator_notes: automaticForm.operatorNotes.trim() || null,
                max_messages: maxMessages,
            });

            setAutomaticBatchResult(result);
            const preferredAutomaticRunId =
                result.outcomes.find(
                    (outcome) =>
                        outcome.status !== 'duplicate_skipped' &&
                        (outcome.review_run_id !== null || outcome.run_id !== null),
                )?.review_run_id ??
                result.outcomes.find(
                    (outcome) =>
                        outcome.status !== 'duplicate_skipped' && outcome.run_id !== null,
                )?.run_id ??
                null;

            await loadAutomaticData('refresh', preferredAutomaticRunId);
        } catch (runError) {
            setAutomaticBatchResult(null);
            setAutomaticError(
                getErrorMessage(
                    runError,
                    'Automatic Mode run failed before a batch summary could be returned.',
                ),
            );
        } finally {
            setAutomaticRunning(false);
        }
    };

    const handlePreparePacket = async () => {
        if (!packetForm.messageId.trim()) {
            setError('Message ID is required before preparing a manual review packet.');
            return;
        }

        if (!packetForm.subject.trim()) {
            setError('Subject is required before preparing a manual review packet.');
            return;
        }

        if (!packetForm.snippet.trim() && !packetForm.plainTextBody.trim() && !packetForm.htmlBody.trim()) {
            setError('Provide at least snippet, plain text body, or HTML body.');
            return;
        }

        const expectedContactId = packetForm.expectedContactId.trim();
        if (expectedContactId && !Number.isFinite(Number(expectedContactId))) {
            setError('Expected contact ID must be a valid number when provided.');
            return;
        }

        setPrepareSubmitting(true);
        setError(null);

        const payload: ListingAlertRunRequest = {
            execution_mode: 'manual',
            expected_contact_id: expectedContactId ? Number(expectedContactId) : null,
            operator_notes: packetForm.operatorNotes.trim() || null,
            manual_reasoning_surface: 'chatgpt_pro_gpt_5_4',
            gmail_alert: {
                message_id: packetForm.messageId.trim(),
                thread_id: packetForm.threadId.trim() || packetForm.messageId.trim(),
                received_at: packetForm.receivedAt.trim() || null,
                subject: packetForm.subject.trim(),
                from_address: packetForm.fromAddress.trim() || null,
                to_addresses: splitList(packetForm.toAddresses),
                cc_addresses: [],
                label_ids: splitList(packetForm.labelIds),
                snippet: packetForm.snippet.trim() || null,
                plain_text_body: packetForm.plainTextBody.trim() || null,
                html_body: packetForm.htmlBody.trim() || null,
                attachment_names: [],
            },
        };

        try {
            const run = await agentsService.prepareListingAlertManualPacket(payload);
            await loadData('refresh', run.id);
        } catch (submitError) {
            setError(getErrorMessage(submitError, 'Failed to prepare manual review packet.'));
        } finally {
            setPrepareSubmitting(false);
        }
    };

    const handleSubmitManualReview = async () => {
        if (!selectedPacket || selectedRunId === null) {
            setReviewFormError('Select a packet-ready run before submitting manual review output.');
            return;
        }

        const shortlistedListings = Object.entries(shortlistSelections)
            .filter(([, value]) => value.selected)
            .map(([listingRef, value]) => ({
                listing_ref: listingRef,
                rank: Number(value.rank),
                why_selected: splitList(value.whySelected),
            }));

        if (shortlistedListings.length > 3) {
            setReviewFormError('Shortlist cannot exceed 3 listings.');
            return;
        }

        if (
            shortlistedListings.some(
                (item) =>
                    !Number.isFinite(item.rank) ||
                    item.rank <= 0 ||
                    item.rank > selectedPacket.shortlist_cap ||
                    item.why_selected.length === 0,
            )
        ) {
            setReviewFormError(
                `Each shortlisted listing needs a unique rank between 1 and ${selectedPacket.shortlist_cap} and at least one why-selected note.`,
            );
            return;
        }

        const uniqueRanks = new Set(shortlistedListings.map((item) => item.rank));
        if (uniqueRanks.size !== shortlistedListings.length) {
            setReviewFormError('Shortlisted listing ranks must be unique.');
            return;
        }

        if (!reviewForm.recommendationReasoning.trim()) {
            setReviewFormError('Recommendation reasoning is required.');
            return;
        }

        const hasDraftSubject = reviewForm.draftSubject.trim().length > 0;
        const hasDraftBody = reviewForm.draftBody.trim().length > 0;
        if (hasDraftSubject !== hasDraftBody) {
            setReviewFormError('Draft subject and body must both be provided or both left blank.');
            return;
        }

        const payload: ListingAlertManualReviewSubmissionRequest = {
            source_run_id: selectedRunId,
            shortlisted_listings: shortlistedListings,
            tradeoff_notes: splitList(reviewForm.tradeoffNotes),
            recommendation_reasoning: reviewForm.recommendationReasoning.trim(),
            client_facing_drafts:
                hasDraftSubject && hasDraftBody
                    ? [
                          {
                              variant: 'shortlist_summary',
                              subject: reviewForm.draftSubject.trim(),
                              body: reviewForm.draftBody.trim(),
                          },
                      ]
                    : [],
            operator_notes: splitList(reviewForm.operatorNotes),
        };

        setReviewSubmitting(true);
        setReviewFormError(null);
        setError(null);

        try {
            const run = await agentsService.submitListingAlertManualReview(payload);
            await loadData('refresh', run.id);
        } catch (submitError) {
            setReviewFormError(
                getErrorMessage(submitError, 'Failed to submit manual review result.'),
            );
        } finally {
            setReviewSubmitting(false);
        }
    };

    const handleApprove = async (approvalId: number, scope: 'manual' | 'automatic') => {
        setActiveApprovalId(approvalId);
        if (scope === 'automatic') {
            setAutomaticApprovalError(null);
        } else {
            setApprovalError(null);
        }
        try {
            await agentsService.approve(approvalId);
            await refreshAllData(selectedRunId, selectedAutomaticRunId);
        } catch (decisionError) {
            const message = getErrorMessage(
                decisionError,
                'Failed to approve review item.',
            );
            if (scope === 'automatic') {
                setAutomaticApprovalError(message);
            } else {
                setApprovalError(message);
            }
        } finally {
            setActiveApprovalId(null);
        }
    };

    const handleReject = async (approvalId: number, scope: 'manual' | 'automatic') => {
        const reason = window.prompt('Rejection reason (optional):');
        if (reason === null) {
            return;
        }

        setActiveApprovalId(approvalId);
        if (scope === 'automatic') {
            setAutomaticApprovalError(null);
        } else {
            setApprovalError(null);
        }
        try {
            await agentsService.reject(approvalId, reason);
            await refreshAllData(selectedRunId, selectedAutomaticRunId);
        } catch (decisionError) {
            const message = getErrorMessage(
                decisionError,
                'Failed to reject review item.',
            );
            if (scope === 'automatic') {
                setAutomaticApprovalError(message);
            } else {
                setApprovalError(message);
            }
        } finally {
            setActiveApprovalId(null);
        }
    };

    const renderPacketDetails = (packet: ListingAlertManualReviewPacket) => {
        return (
            <div className="space-y-4">
                <div className="rounded border border-white/10 bg-black/10 p-3 text-sm space-y-2">
                    <div className="font-medium">Packet Summary</div>
                    <div className="text-xs text-gray-400">
                        Packet version: {packet.packet_version} · Manual reasoning surface:{' '}
                        {packet.manual_reasoning_surface}
                    </div>
                    <div className="text-xs text-gray-400">
                        Shortlist cap: {packet.shortlist_cap} · Draft cap: {packet.draft_output_cap}
                    </div>
                    <div className="text-xs text-gray-400">
                        Message: {packet.source_message.message_id} · Thread:{' '}
                        {packet.source_message.thread_id || 'n/a'}
                    </div>
                </div>

                {renderAssociationSummary(packet.association)}
                {renderAssociationDiagnostics(packet.association)}

                <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                        <div className="font-medium text-sm">Contact Context</div>
                        {Object.keys(packet.contact_context).length === 0 ? (
                            <div className="text-sm text-gray-500">No contact context recorded.</div>
                        ) : (
                            <div className="space-y-2 text-sm">
                                {Object.entries(packet.contact_context).map(([key, value]) => (
                                    <div key={key}>
                                        <div className="text-xs font-semibold text-gray-300">
                                            {humanizeEnum(key)}
                                        </div>
                                        <div className="text-xs text-gray-200">
                                            {renderContextValue(value)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                        <div className="font-medium text-sm">Prompt / Draft Constraints</div>
                        <div className="text-xs text-gray-400">
                            Gmail-driven MLS alert intake only. Gmail access here is read-only and
                            still feeds the same Manual Mode packet workflow.
                        </div>
                        <div>
                            <div className="text-xs font-semibold text-gray-300">Draft constraints</div>
                            {packet.draft_constraints.length === 0 ? (
                                <div className="text-xs text-gray-500">No draft constraints recorded.</div>
                            ) : (
                                <ul className="mt-1 list-disc pl-5 text-xs text-gray-200 space-y-1">
                                    {packet.draft_constraints.map((item) => (
                                        <li key={item}>{item}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                        <div>
                            <div className="text-xs font-semibold text-gray-300">Recommended prompt context</div>
                            {packet.recommended_prompt_context.length === 0 ? (
                                <div className="text-xs text-gray-500">No prompt context recorded.</div>
                            ) : (
                                <ul className="mt-1 list-disc pl-5 text-xs text-gray-200 space-y-1">
                                    {packet.recommended_prompt_context.map((item) => (
                                        <li key={item}>{item}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>

                <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="font-medium text-sm">Extracted Listings</div>
                        <div className="text-xs text-gray-400">
                            {packet.extracted_listing_count} extracted · cap 10
                        </div>
                    </div>
                    {packet.extracted_listings.length === 0 ? (
                        <div className="text-sm text-gray-500">No candidate listings were extracted.</div>
                    ) : (
                        <div className="space-y-3">
                            {packet.extracted_listings.map((listing) => (
                                <div
                                    key={listing.listing_ref}
                                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <div className="font-medium">{listing.address}</div>
                                            <div className="text-xs text-gray-400">
                                                Ref: {listing.listing_ref} · Market:{' '}
                                                {humanizeEnum(listing.market_type)} · Price:{' '}
                                                {formatCurrency(listing.price)}
                                            </div>
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            {listing.property_type || 'Unknown type'}
                                        </div>
                                    </div>
                                    <div className="mt-2 text-xs text-gray-300">
                                        Beds: {listing.bedrooms ?? 'n/a'} · Baths:{' '}
                                        {listing.bathrooms ?? 'n/a'} · Area:{' '}
                                        {listing.neighborhood || 'n/a'}
                                    </div>
                                    {listing.match_notes.length > 0 && (
                                        <div className="mt-2 text-xs text-gray-300">
                                            Notes: {listing.match_notes.join(' | ')}
                                        </div>
                                    )}
                                    <div className="mt-2 text-xs text-gray-400 whitespace-pre-wrap">
                                        Source excerpt: {listing.source_excerpt}
                                    </div>
                                    {listing.listing_url && (
                                        <div className="mt-2 text-xs text-sky-200 break-all">
                                            {listing.listing_url}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const renderReviewedSubmissionDetails = (
        runId: number,
        result:
            | ListingAlertReviewedSubmissionResultResponse
            | ListingAlertAutomaticReviewedResultResponse,
        activeApprovals: AgentApproval[],
        resolvedApprovals: AgentApproval[],
    ) => {
        const hasDraft = result.client_facing_drafts.length > 0;
        const approval = getRunApproval(runId, activeApprovals, resolvedApprovals);
        const approvalLabel = getRunApprovalLabel(approval);
        const isAutomatic = isAutomaticReviewedResult(result);

        return (
            <div className="space-y-4">
                <div
                    className={`rounded border px-3 py-2 text-sm ${
                        result.review_outcome === 'waiting_approval'
                            ? 'border-sky-500/30 bg-sky-500/10 text-sky-100'
                            : 'border-white/10 bg-black/10 text-gray-100'
                    }`}
                >
                    Review outcome: {humanizeEnum(result.review_outcome)}
                    {!hasDraft && (
                        <div className="mt-1 text-xs text-gray-300">
                            {isAutomatic
                                ? 'Automatic review completed safely without a client-facing draft.'
                                : 'Internal-only completion. No client-facing draft was submitted.'}
                        </div>
                    )}
                    {hasDraft && (
                        <div className="mt-1 text-xs text-sky-50">
                            {isAutomatic
                                ? 'Automatic review generated a client-facing draft and created a review-only approval. No send occurred.'
                                : 'Client-facing draft was submitted and approval was created.'}
                        </div>
                    )}
                    {approvalLabel && (
                        <div className="mt-1 text-xs text-gray-100">
                            Approval status: {approvalLabel}
                            {approval?.status === 'rejected' && approval.rejection_reason
                                ? ` · Reason: ${approval.rejection_reason}`
                                : ''}
                        </div>
                    )}
                </div>

                {renderAssociationSummary(result.association)}
                {renderAssociationDiagnostics(result.association)}

                <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                    <div className="font-medium text-sm">Shortlist</div>
                    {result.shortlisted_listings.length === 0 ? (
                        <div className="text-sm text-gray-500">No shortlisted listings were submitted.</div>
                    ) : (
                        <div className="space-y-3">
                            {result.shortlisted_listings
                                .slice()
                                .sort((a, b) => a.rank - b.rank)
                                .map((item) => (
                                    <div
                                        key={`${item.listing_ref}-${item.rank}`}
                                        className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                    >
                                        <div className="font-medium">
                                            #{item.rank} · {item.address}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Ref: {item.listing_ref}
                                        </div>
                                        <div className="mt-2 text-xs text-gray-200">
                                            {item.why_selected.join(' | ')}
                                        </div>
                                    </div>
                                ))}
                        </div>
                    )}
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                        <div className="font-medium text-sm">Tradeoff Notes</div>
                        {result.tradeoff_notes.length === 0 ? (
                            <div className="text-sm text-gray-500">No tradeoff notes submitted.</div>
                        ) : (
                            <ul className="list-disc pl-5 text-sm text-gray-200 space-y-1">
                                {result.tradeoff_notes.map((item) => (
                                    <li key={item}>{item}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                        <div className="font-medium text-sm">Recommendation Reasoning</div>
                        <div className="text-sm whitespace-pre-wrap text-gray-200">
                            {result.recommendation_reasoning}
                        </div>
                    </div>
                </div>

                <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                    <div className="font-medium text-sm">Client-Facing Draft</div>
                    {result.client_facing_drafts.length === 0 ? (
                        <div className="text-sm text-gray-500">
                            No client-facing draft stored for this reviewed submission.
                        </div>
                    ) : (
                        result.client_facing_drafts.map((draft, index) => (
                            <div
                                key={`${draft.variant}-${index}`}
                                className="rounded border border-white/10 bg-black/10 p-3 space-y-2"
                            >
                                <div className="text-xs text-gray-400">
                                    Variant: {humanizeEnum(draft.variant)}
                                    {draft.approval_id && <> · Approval #{draft.approval_id}</>}
                                </div>
                                <div>
                                    <div className="text-xs font-semibold text-gray-300">Subject</div>
                                    <div className="text-sm text-gray-100">{draft.subject}</div>
                                </div>
                                <div>
                                    <div className="text-xs font-semibold text-gray-300">Body</div>
                                    <pre className="text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                        {draft.body}
                                    </pre>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>
        );
    };

    const renderAssociationSummary = (association: ListingAlertClientAssociationResponse) => (
        <div className={`rounded border px-3 py-2 text-sm ${getAssociationTone(association)}`}>
            Association status: {humanizeEnum(association.status)}
            {association.blocked_reason && (
                <div className="mt-1 text-xs text-amber-50">
                    Blocked reason: {association.blocked_reason}
                </div>
            )}
            {association.contact_name && (
                <div className="mt-1 text-xs text-current">
                    Matched contact: {association.contact_name} (#{association.contact_id})
                </div>
            )}
            {association.representation_intent && (
                <div className="mt-1 text-xs text-current">
                    Representation intent: {humanizeEnum(association.representation_intent)}
                </div>
            )}
            {association.status !== 'matched' && (
                <div className="mt-2 grid gap-1 text-xs text-current md:grid-cols-3">
                    <div>
                        Match stage: {humanizeEnum(association.diagnostics?.match_stage ?? null)}
                    </div>
                    <div>
                        Market type: {humanizeEnum(association.diagnostics?.market_type ?? null)}
                    </div>
                    <div>
                        Operator override:{' '}
                        {association.diagnostics?.operator_override ? 'Yes' : 'No'}
                    </div>
                </div>
            )}
        </div>
    );

    const renderAssociationDiagnostics = (
        association: ListingAlertClientAssociationResponse,
    ) => {
        const candidateContacts = association.candidate_contacts ?? [];
        const missingCriteria = association.missing_criteria ?? [];
        const failedChecks = association.failed_checks ?? [];
        const hasBlockedDiagnostics =
            association.status !== 'matched' ||
            candidateContacts.length > 0 ||
            missingCriteria.length > 0 ||
            failedChecks.length > 0;

        if (!hasBlockedDiagnostics) {
            return null;
        }

        return (
            <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                <div>
                    <div className="font-medium text-sm">Association Diagnostics</div>
                    <div className="text-xs text-gray-400">
                        Use these signals to understand why association blocked and whether an Expected contact ID override is appropriate.
                    </div>
                </div>

                <div className="grid gap-2 text-xs text-gray-200 md:grid-cols-3">
                    <div>
                        <div className="font-semibold text-gray-300">Match stage</div>
                        <div>{humanizeEnum(association.diagnostics?.match_stage ?? null)}</div>
                    </div>
                    <div>
                        <div className="font-semibold text-gray-300">Market type</div>
                        <div>{humanizeEnum(association.diagnostics?.market_type ?? null)}</div>
                    </div>
                    <div>
                        <div className="font-semibold text-gray-300">Operator override</div>
                        <div>{association.diagnostics?.operator_override ? 'Yes' : 'No'}</div>
                    </div>
                </div>

                {(missingCriteria.length > 0 || failedChecks.length > 0) && (
                    <div className="grid gap-3 md:grid-cols-2">
                        <div className="rounded border border-white/10 bg-black/10 p-3 text-xs">
                            <div className="font-semibold text-gray-300">Missing criteria</div>
                            <div className="mt-1 text-gray-200">
                                {renderInlineList(missingCriteria)}
                            </div>
                        </div>
                        <div className="rounded border border-white/10 bg-black/10 p-3 text-xs">
                            <div className="font-semibold text-gray-300">Failed checks</div>
                            <div className="mt-1 text-gray-200">
                                {renderInlineList(failedChecks)}
                            </div>
                        </div>
                    </div>
                )}

                {candidateContacts.length > 0 && (
                    <div className="space-y-2">
                        <div className="font-semibold text-sm">Candidate Contacts</div>
                        <div className="space-y-2">
                            {candidateContacts.map((candidate) => (
                                <div
                                    key={`${candidate.stage}-${candidate.contact_id}`}
                                    className="rounded border border-white/10 bg-black/10 p-3 text-xs text-gray-200 space-y-2"
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <div className="font-medium text-sm text-white">
                                                {candidate.contact_name || 'Unnamed contact'} (#{candidate.contact_id})
                                            </div>
                                            <div className="text-gray-400">
                                                Stage: {humanizeEnum(candidate.stage)} · Score:{' '}
                                                {typeof candidate.score === 'number'
                                                    ? candidate.score.toFixed(2)
                                                    : 'n/a'}
                                                {' '}· Intent:{' '}
                                                {humanizeEnum(candidate.representation_intent ?? null)}
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => applyExpectedContactOverride(candidate.contact_id)}
                                            className="px-2 py-1 rounded border border-sky-500/30 bg-sky-500/10 text-sky-100 hover:bg-sky-500/20"
                                        >
                                            Use #{candidate.contact_id}
                                        </button>
                                    </div>

                                    <div>
                                        <div className="font-semibold text-gray-300">Matched on</div>
                                        <div>{renderInlineList(candidate.matched_on)}</div>
                                    </div>

                                    {(candidate.missing_criteria.length > 0 ||
                                        candidate.failed_checks.length > 0) && (
                                        <div className="grid gap-2 md:grid-cols-2">
                                            <div>
                                                <div className="font-semibold text-gray-300">
                                                    Missing criteria
                                                </div>
                                                <div>{renderInlineList(candidate.missing_criteria)}</div>
                                            </div>
                                            <div>
                                                <div className="font-semibold text-gray-300">
                                                    Failed checks
                                                </div>
                                                <div>{renderInlineList(candidate.failed_checks)}</div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    const pageStatus = loading || automaticLoading
        ? 'Loading Listing Alert Recommendation data...'
        : refreshing || automaticRefreshing
            ? 'Refreshing Listing Alert Recommendation data...'
            : null;
    const latestApproval =
        latest.run_id !== null ? getRunApproval(latest.run_id, approvals, approvalHistory) : null;
    const automaticLatestApproval =
        automaticLatest.run_id !== null
            ? getRunApproval(
                  automaticLatest.run_id,
                  automaticApprovals,
                  automaticApprovalHistory,
              )
            : null;

    return (
        <section className="space-y-4 border rounded p-4 bg-white/5">
            <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                    <h2 className="text-lg font-medium">Listing Alert Recommendation</h2>
                    <p className="text-sm text-gray-400">
                        Gmail-driven MLS alert intake with distinct Manual Mode and Automatic Mode v1
                        sections. Stored read-only Gmail OAuth is the production path; temporary token
                        input remains internal/debug only. Automatic Mode is manual-triggered, bounded,
                        review-first, and never sends automatically.
                    </p>
                </div>
                <button
                    onClick={() => void handleRefreshPanel()}
                    className="px-3 py-2 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={
                        isBusy ||
                        prepareSubmitting ||
                        reviewSubmitting ||
                        automaticRunning ||
                        activeApprovalId !== null
                    }
                >
                    {refreshing || automaticRefreshing ? 'Refreshing...' : 'Refresh'}
                </button>
            </div>

            {pageStatus && <div className="text-sm text-gray-400">{pageStatus}</div>}
            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            <div className="grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
                <div className="space-y-4">
                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">1. Gmail Intake</h3>
                            <p className="text-sm text-gray-400">
                                Gmail READ only. Stored OAuth is the default production path. Fetch
                                constrained MLS alert candidates, then import one message into the
                                existing Manual Mode packet-prep workflow. Temporary token fallback is
                                kept only for internal/debug use.
                            </p>
                        </div>

                        <div
                            className={`rounded border px-3 py-3 text-sm space-y-3 ${getGmailOAuthStatusTone(
                                gmailOAuthStatus?.status,
                            )}`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <div className="font-medium">
                                        Stored Gmail connection ·{' '}
                                        {gmailStatusLoading
                                            ? 'Loading...'
                                            : humanizeEnum(gmailOAuthStatus?.status || 'disconnected')}
                                    </div>
                                    <div className="mt-1 text-xs text-current/80">
                                        {getGmailOAuthStatusDescription(gmailOAuthStatus)}
                                    </div>
                                </div>
                                <div className="text-xs text-current/80">
                                    Logical connection: {gmailOAuthStatus?.connection_key || 'listing_alert_primary'}
                                </div>
                            </div>

                            <div className="grid gap-3 md:grid-cols-2 text-xs">
                                <div>
                                    <div className="font-semibold text-current/90">Mailbox</div>
                                    <div className="mt-1 text-current/80">
                                        {gmailOAuthStatus?.account_email || 'Not connected'}
                                    </div>
                                </div>
                                <div>
                                    <div className="font-semibold text-current/90">Gmail user ID</div>
                                    <div className="mt-1 text-current/80">
                                        {gmailOAuthStatus?.gmail_user_id || 'me'} (fixed for v1)
                                    </div>
                                </div>
                                <div className="md:col-span-2">
                                    <div className="font-semibold text-current/90">Granted scopes</div>
                                    <div className="mt-1 text-current/80 break-all">
                                        {gmailOAuthStatus?.granted_scopes?.length
                                            ? gmailOAuthStatus.granted_scopes.join(' | ')
                                            : 'No scopes recorded yet'}
                                    </div>
                                </div>
                                {(gmailOAuthStatus?.connected_at || gmailOAuthStatus?.last_refreshed_at) && (
                                    <>
                                        <div>
                                            <div className="font-semibold text-current/90">Connected</div>
                                            <div className="mt-1 text-current/80">
                                                {formatTimestamp(gmailOAuthStatus?.connected_at)}
                                            </div>
                                        </div>
                                        <div>
                                            <div className="font-semibold text-current/90">Last refreshed</div>
                                            <div className="mt-1 text-current/80">
                                                {formatTimestamp(gmailOAuthStatus?.last_refreshed_at)}
                                            </div>
                                        </div>
                                    </>
                                )}
                                {gmailOAuthStatus?.last_error && (
                                    <div className="md:col-span-2">
                                        <div className="font-semibold text-current/90">Connection health</div>
                                        <div className="mt-1 text-current/80">
                                            Last error: {gmailOAuthStatus.last_error}
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                                <button
                                    onClick={() => void handleStartGmailOAuth()}
                                    className="px-4 py-2 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
                                    disabled={
                                        gmailConnectionActionLoading ||
                                        !gmailOAuthStatus?.oauth_configured
                                    }
                                >
                                    {gmailConnectionActionLoading
                                        ? 'Opening Gmail OAuth...'
                                        : gmailOAuthStatus?.status === 'connected'
                                            ? 'Reconnect Gmail'
                                            : 'Connect Gmail'}
                                </button>
                                <button
                                    onClick={() => void handleRefreshGmailOAuthStatus()}
                                    className="px-3 py-2 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-50"
                                    disabled={gmailStatusLoading || gmailConnectionActionLoading}
                                >
                                    {gmailStatusLoading ? 'Refreshing Gmail Status...' : 'Refresh Gmail Status'}
                                </button>
                                <button
                                    onClick={() => void handleDisconnectGmailOAuth()}
                                    className="px-3 py-2 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-50"
                                    disabled={
                                        gmailConnectionActionLoading ||
                                        !gmailOAuthStatus?.has_refresh_token
                                    }
                                >
                                    Disconnect Gmail
                                </button>
                            </div>
                        </div>

                        {gmailStatusNotice && (
                            <div className="rounded border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100">
                                {gmailStatusNotice}
                            </div>
                        )}

                        <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Allowed sender</div>
                                <input
                                    value={gmailFetchForm.allowedSender}
                                    onChange={(event) => updateGmailFetchField('allowedSender', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="alerts@mls.example"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Label IDs</div>
                                <textarea
                                    value={gmailFetchForm.labelIds}
                                    onChange={(event) => updateGmailFetchField('labelIds', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Subject keywords</div>
                                <textarea
                                    value={gmailFetchForm.subjectKeywords}
                                    onChange={(event) => updateGmailFetchField('subjectKeywords', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Max results</div>
                                <input
                                    value={gmailFetchForm.maxResults}
                                    onChange={(event) => updateGmailFetchField('maxResults', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="5"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Expected contact ID</div>
                                <input
                                    value={gmailFetchForm.expectedContactId}
                                    onChange={(event) => updateGmailFetchField('expectedContactId', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Recovery override for a known CRM contact"
                                />
                                <div className="text-xs text-gray-500">
                                    Use this when association blocks and you already know the correct CRM buyer or renter contact. It is only applied when you import the selected message.
                                </div>
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Operator notes</div>
                                <textarea
                                    value={gmailFetchForm.operatorNotes}
                                    onChange={(event) => updateGmailFetchField('operatorNotes', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Applied at import only"
                                />
                            </label>
                        </div>

                        <div className="rounded border border-white/10 bg-black/10 p-3 text-xs text-gray-300 space-y-1">
                            <div>Manual fetch only. No polling, no background refresh, no hidden retries.</div>
                            <div>
                                Stored Gmail OAuth is the default production path for this panel. OAuth credentials are handled server-side and are not written into runs, tasks, or audit logs.
                            </div>
                            <div>
                                Temporary token fallback remains internal/debug only. If used, the token stays in component memory only long enough to support fetch, candidate selection, and import.
                            </div>
                        </div>

                        <div className="rounded border border-white/10 bg-black/10 p-3 space-y-3">
                            <div className="flex items-center justify-between gap-3">
                                <div>
                                    <div className="font-medium text-sm">
                                        Manual token fallback (internal/debug)
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Keep disabled in normal production use. Stored OAuth remains the primary path.
                                    </div>
                                </div>
                                <button
                                    onClick={() => {
                                        setShowManualTokenFallback((current) => {
                                            const next = !current;
                                            if (!next) {
                                                setManualTokenFallbackEnabled(false);
                                            }
                                            return next;
                                        });
                                    }}
                                    className="px-3 py-2 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                >
                                    {showManualTokenFallback ? 'Hide Debug Fallback' : 'Show Debug Fallback'}
                                </button>
                            </div>

                            {showManualTokenFallback && (
                                <div className="space-y-3">
                                    <label className="flex items-start gap-2 text-sm text-gray-300">
                                        <input
                                            type="checkbox"
                                            checked={manualTokenFallbackEnabled}
                                            onChange={(event) =>
                                                setManualTokenFallbackEnabled(event.target.checked)
                                            }
                                            className="mt-1"
                                        />
                                        <span>
                                            Use a temporary Gmail access token for fetch/import instead of the stored
                                            OAuth connection.
                                        </span>
                                    </label>

                                    <label className="space-y-1 text-sm">
                                        <div className="text-gray-300">Temporary access token</div>
                                        <input
                                            type="password"
                                            value={gmailFetchForm.accessToken}
                                            onChange={(event) => updateGmailFetchField('accessToken', event.target.value)}
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                            placeholder="Request-scoped only"
                                            autoComplete="off"
                                        />
                                    </label>

                                    <div className="text-xs text-gray-500">
                                        This fallback is not the primary production path. If used, the token is never
                                        stored in localStorage, sessionStorage, URL params, runs, tasks, or audit logs.
                                    </div>
                                </div>
                            )}
                        </div>

                        {gmailError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {gmailError}
                            </div>
                        )}

                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => void handleFetchGmailCandidates()}
                                className="px-4 py-2 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
                                disabled={
                                    gmailFetching ||
                                    gmailImporting ||
                                    prepareSubmitting ||
                                    reviewSubmitting ||
                                    isBusy ||
                                    gmailConnectionActionLoading ||
                                    !gmailIntakeReady
                                }
                            >
                                {gmailFetching ? 'Fetching...' : 'Fetch Gmail Candidates'}
                            </button>
                            {gmailCandidatesResult && (
                                <div className="text-xs text-gray-400">
                                    Query matched {gmailCandidatesResult.matched_message_count} message(s) · kept{' '}
                                    {gmailCandidatesResult.candidate_count} candidate(s)
                                </div>
                            )}
                        </div>

                        {!gmailIntakeReady && (
                            <div className="text-xs text-amber-100">
                                Stored Gmail OAuth is not ready yet. Connect Gmail first, or explicitly enable the
                                internal debug token fallback.
                            </div>
                        )}

                        <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                            <div>
                                <div className="font-medium text-sm">Candidate Message List</div>
                                <div className="text-xs text-gray-400">
                                    Fetch first, then select one candidate to import into the existing packet-prep workflow.
                                </div>
                                {gmailCandidatesResult?.query && (
                                    <div className="mt-2 text-xs text-gray-500 break-all">
                                        Constrained query: {gmailCandidatesResult.query}
                                    </div>
                                )}
                            </div>

                            {!gmailCandidatesResult ? (
                                <div className="text-sm text-gray-500">
                                    No Gmail candidates fetched yet.
                                </div>
                            ) : gmailCandidatesResult.candidates.length === 0 ? (
                                <div className="text-sm text-gray-500">
                                    No candidate messages passed the constrained Gmail policy.
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {gmailCandidatesResult.candidates.map((candidate) => {
                                        const isSelected =
                                            selectedCandidateMessageId === candidate.message_id;
                                        const isExisting = candidate.existing_run_id !== null;

                                        return (
                                            <label
                                                key={candidate.message_id}
                                                className={`block rounded border p-3 text-sm cursor-pointer ${
                                                    isSelected
                                                        ? 'border-sky-500/40 bg-sky-500/10'
                                                        : 'border-white/10 bg-black/10'
                                                }`}
                                            >
                                                <div className="flex items-start justify-between gap-3">
                                                    <div className="flex items-start gap-3">
                                                        <input
                                                            type="radio"
                                                            name="gmail-candidate"
                                                            checked={isSelected}
                                                            onChange={() =>
                                                                setSelectedCandidateMessageId(
                                                                    candidate.message_id,
                                                                )
                                                            }
                                                            className="mt-1"
                                                        />
                                                        <div className="space-y-1">
                                                            <div className="font-medium">
                                                                {candidate.subject || 'Untitled message'}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Message: {candidate.message_id}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Thread: {candidate.thread_id}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Received: {formatTimestamp(candidate.received_at)}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                From: {candidate.from_address || 'n/a'}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Labels:{' '}
                                                                {candidate.label_ids.length > 0
                                                                    ? candidate.label_ids.join(' | ')
                                                                    : 'none'}
                                                            </div>
                                                        </div>
                                                    </div>

                                                    <div className="text-right text-xs">
                                                        <div
                                                            className={`rounded px-2 py-1 ${
                                                                isExisting
                                                                    ? 'bg-amber-500/10 text-amber-100 border border-amber-500/30'
                                                                    : 'bg-emerald-500/10 text-emerald-100 border border-emerald-500/30'
                                                            }`}
                                                        >
                                                            {isExisting ? 'Already imported' : 'New candidate'}
                                                        </div>
                                                        {candidate.existing_task_id && (
                                                            <div className="mt-2 text-gray-400">
                                                                Task #{candidate.existing_task_id}
                                                            </div>
                                                        )}
                                                        {candidate.existing_run_id && (
                                                            <div className="text-gray-400">
                                                                Run #{candidate.existing_run_id}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            </label>
                                        );
                                    })}

                                    <div className="flex flex-wrap items-center gap-2">
                                        <button
                                            onClick={() => void handleImportGmailMessage()}
                                            className="px-4 py-2 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                                            disabled={
                                                !selectedCandidateMessageId ||
                                                gmailImporting ||
                                                gmailFetching ||
                                                prepareSubmitting ||
                                                reviewSubmitting ||
                                                isBusy
                                            }
                                        >
                                            {gmailImporting ? 'Importing...' : 'Import Selected Message'}
                                        </button>
                                        {selectedCandidate?.existing_run_id && (
                                            <button
                                                onClick={() => setSelectedRunId(selectedCandidate.existing_run_id ?? null)}
                                                className="px-3 py-2 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                                disabled={gmailImporting || gmailFetching}
                                            >
                                                Inspect Existing Run #{selectedCandidate.existing_run_id}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>

                        {gmailImportOutcome && (
                            <div
                                className={`rounded border px-3 py-2 text-sm ${getGmailImportOutcomeTone(
                                    gmailImportOutcome.status,
                                )}`}
                            >
                                Import outcome: {humanizeEnum(gmailImportOutcome.status)}
                                <div className="mt-1 text-xs">
                                    Message {gmailImportOutcome.message_id}
                                    {gmailImportOutcome.subject ? ` · ${gmailImportOutcome.subject}` : ''}
                                </div>
                                {gmailImportOutcome.reason && (
                                    <div className="mt-1 text-xs">
                                        Reason: {gmailImportOutcome.reason}
                                    </div>
                                )}
                                {gmailImportOutcome.imported_task_id && (
                                    <div className="mt-1 text-xs">
                                        Imported task #{gmailImportOutcome.imported_task_id} · run #
                                        {gmailImportOutcome.imported_run_id}
                                    </div>
                                )}
                                {gmailImportOutcome.existing_task_id && (
                                    <div className="mt-1 text-xs">
                                        Existing task #{gmailImportOutcome.existing_task_id} · run #
                                        {gmailImportOutcome.existing_run_id}
                                    </div>
                                )}
                                <div className="mt-1 text-xs">
                                    {gmailLastImportMode === 'manual_fallback'
                                        ? 'Temporary access token cleared after this import response.'
                                        : 'Stored Gmail OAuth connection remained in use. No temporary token was required.'}
                                </div>
                                {getGmailImportOutcomeFollowupText(gmailImportOutcome) && (
                                    <div className="mt-1 text-xs">
                                        {getGmailImportOutcomeFollowupText(gmailImportOutcome)}
                                    </div>
                                )}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">
                                Automatic Mode v1
                            </h3>
                            <p className="text-sm text-gray-400">
                                Manual trigger only. Bounded batch. Review-first. Uses the stored
                                Gmail OAuth production path and stops at blocked, completed without
                                draft, or waiting approval. No send, no Gmail draft creation, no
                                background processing.
                            </p>
                        </div>

                        <div className="rounded border border-white/10 bg-black/10 p-3 text-xs text-gray-300 space-y-1">
                            <div>
                                Production path: stored Gmail OAuth
                                {gmailOAuthStatus?.account_email
                                    ? ` (${gmailOAuthStatus.account_email})`
                                    : ''}
                            </div>
                            <div>
                                Trigger model: manual run-once only, max {AUTOMATIC_MAX_MESSAGES}{' '}
                                messages per batch in v1.
                            </div>
                            <div>
                                Stop points: blocked, completed_no_draft, waiting_approval.
                            </div>
                        </div>

                        <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Gmail user ID</div>
                                <input
                                    value={automaticForm.gmailUserId}
                                    onChange={(event) =>
                                        updateAutomaticField(
                                            'gmailUserId',
                                            event.target.value,
                                        )
                                    }
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="me"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Max messages</div>
                                <input
                                    type="number"
                                    min={1}
                                    max={AUTOMATIC_MAX_MESSAGES}
                                    value={automaticForm.maxMessages}
                                    onChange={(event) =>
                                        updateAutomaticField(
                                            'maxMessages',
                                            event.target.value,
                                        )
                                    }
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                />
                                <div className="text-xs text-gray-500">
                                    UI and backend both clamp this to {AUTOMATIC_MAX_MESSAGES}.
                                </div>
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Allowed sender</div>
                                <input
                                    value={automaticForm.allowedSender}
                                    onChange={(event) =>
                                        updateAutomaticField(
                                            'allowedSender',
                                            event.target.value,
                                        )
                                    }
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="alerts@mls.example"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Label IDs</div>
                                <textarea
                                    value={automaticForm.labelIds}
                                    onChange={(event) =>
                                        updateAutomaticField('labelIds', event.target.value)
                                    }
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Subject keywords</div>
                                <textarea
                                    value={automaticForm.subjectKeywords}
                                    onChange={(event) =>
                                        updateAutomaticField(
                                            'subjectKeywords',
                                            event.target.value,
                                        )
                                    }
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Operator notes</div>
                                <textarea
                                    value={automaticForm.operatorNotes}
                                    onChange={(event) =>
                                        updateAutomaticField(
                                            'operatorNotes',
                                            event.target.value,
                                        )
                                    }
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Optional notes stored with the automatic batch trigger"
                                />
                            </label>
                        </div>

                        {automaticError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {automaticError}
                            </div>
                        )}

                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => void handleRunAutomaticMode()}
                                className="px-4 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                                disabled={
                                    automaticRunning ||
                                    gmailFetching ||
                                    gmailImporting ||
                                    prepareSubmitting ||
                                    reviewSubmitting ||
                                    isBusy ||
                                    !storedGmailConnectionReady
                                }
                            >
                                {automaticRunning
                                    ? 'Running Automatic Mode...'
                                    : 'Run Automatic Mode Once'}
                            </button>
                            <div className="text-xs text-gray-400">
                                Stored OAuth only. No Expected contact ID auto-override. Uncertain
                                matches stay blocked.
                            </div>
                        </div>

                        {!storedGmailConnectionReady && (
                            <div className="text-xs text-amber-100">
                                Stored Gmail OAuth must be connected before Automatic Mode can run.
                            </div>
                        )}

                        <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <div className="font-medium text-sm">
                                        Automatic Batch Result
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Immediate batch summary only. Full per-message detail stays
                                        in the underlying automatic runs below.
                                    </div>
                                </div>
                                {automaticBatchResult?.query && (
                                    <div className="max-w-xs text-right text-xs text-gray-500 break-all">
                                        {automaticBatchResult.query}
                                    </div>
                                )}
                            </div>

                            {!automaticBatchResult ? (
                                <div className="text-sm text-gray-500">
                                    No Automatic Mode batch has been triggered yet.
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">Matched</div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.matched_message_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">Candidates</div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.candidate_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">Processed</div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.processed_message_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">Message cap</div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.message_cap}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">
                                                Duplicate skipped
                                            </div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.duplicate_skipped_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">Blocked</div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.blocked_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">
                                                Completed no draft
                                            </div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.completed_no_draft_count}
                                            </div>
                                        </div>
                                        <div className="rounded border border-white/10 bg-black/10 p-3 text-sm">
                                            <div className="text-xs text-gray-400">
                                                Waiting approval
                                            </div>
                                            <div className="mt-1 font-medium">
                                                {automaticBatchResult.waiting_approval_count}
                                            </div>
                                        </div>
                                    </div>

                                    {automaticBatchResult.outcomes.length === 0 ? (
                                        <div className="text-sm text-gray-500">
                                            This batch returned no per-message outcomes.
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {automaticBatchResult.outcomes.map((outcome) => {
                                                const inspectRunId =
                                                    outcome.review_run_id ?? outcome.run_id ?? null;
                                                const inspectable =
                                                    inspectRunId !== null &&
                                                    automaticRunIds.has(inspectRunId);

                                                return (
                                                    <div
                                                        key={`${outcome.message_id}-${outcome.status}`}
                                                        className={`rounded border px-3 py-3 text-sm space-y-2 ${getAutomaticOutcomeTone(
                                                            outcome.status,
                                                        )}`}
                                                    >
                                                        <div className="flex items-start justify-between gap-3">
                                                            <div>
                                                                <div className="font-medium">
                                                                    {humanizeEnum(outcome.status)}
                                                                </div>
                                                                <div className="mt-1 text-xs text-current/80">
                                                                    {outcome.subject ||
                                                                        'Untitled message'}{' '}
                                                                    · Message {outcome.message_id}
                                                                </div>
                                                                <div className="text-xs text-current/80">
                                                                    Thread:{' '}
                                                                    {outcome.thread_id || 'n/a'} ·
                                                                    Received:{' '}
                                                                    {formatTimestamp(
                                                                        outcome.received_at,
                                                                    )}
                                                                </div>
                                                            </div>
                                                            {inspectable && inspectRunId !== null && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() =>
                                                                        setSelectedAutomaticRunId(
                                                                            inspectRunId,
                                                                        )
                                                                    }
                                                                    className="px-3 py-2 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                                                >
                                                                    Inspect Run #{inspectRunId}
                                                                </button>
                                                            )}
                                                        </div>

                                                        <div className="grid gap-2 text-xs md:grid-cols-2 xl:grid-cols-4">
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Task:
                                                                </span>{' '}
                                                                {outcome.task_id ?? 'n/a'}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Packet run:
                                                                </span>{' '}
                                                                {outcome.run_id ?? 'n/a'}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Review run:
                                                                </span>{' '}
                                                                {outcome.review_run_id ?? 'n/a'}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Approval:
                                                                </span>{' '}
                                                                {outcome.approval_id ?? 'n/a'}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Execution:
                                                                </span>{' '}
                                                                {humanizeEnum(
                                                                    outcome.execution_status ??
                                                                        null,
                                                                )}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Association:
                                                                </span>{' '}
                                                                {humanizeEnum(
                                                                    outcome.association_status ??
                                                                        null,
                                                                )}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Review outcome:
                                                                </span>{' '}
                                                                {humanizeEnum(
                                                                    outcome.review_outcome ??
                                                                        null,
                                                                )}
                                                            </div>
                                                            <div>
                                                                <span className="font-semibold text-current/90">
                                                                    Packet ready:
                                                                </span>{' '}
                                                                {outcome.packet_ready
                                                                    ? 'Yes'
                                                                    : 'No'}
                                                            </div>
                                                        </div>

                                                        {outcome.reason && (
                                                            <div className="text-xs text-current/80">
                                                                Reason: {outcome.reason}
                                                            </div>
                                                        )}

                                                        {!inspectable &&
                                                            inspectRunId !== null && (
                                                                <div className="text-xs text-current/80">
                                                                    Underlying run #{inspectRunId}{' '}
                                                                    is not an automatic run and is
                                                                    therefore not shown in the
                                                                    automatic run views below.
                                                                </div>
                                                            )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">2. Manual Packet Preparation</h3>
                            <p className="text-sm text-gray-400">
                                Manual-input fallback. Use normalized Gmail fields directly when you do not
                                want to fetch/import through Gmail API read access.
                            </p>
                        </div>

                        <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Expected contact ID</div>
                                <input
                                    value={packetForm.expectedContactId}
                                    onChange={(event) => updatePacketField('expectedContactId', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Recovery override for a known CRM contact"
                                />
                                <div className="text-xs text-gray-500">
                                    If association blocked earlier, set the correct CRM contact ID here and rerun packet prep manually.
                                </div>
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Message ID</div>
                                <input
                                    value={packetForm.messageId}
                                    onChange={(event) => updatePacketField('messageId', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Required"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Thread ID</div>
                                <input
                                    value={packetForm.threadId}
                                    onChange={(event) => updatePacketField('threadId', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Optional"
                                />
                            </label>
                            <div className="text-xs text-gray-500 md:col-span-2 -mt-1">
                                If blank, the frontend reuses Message ID for the normalized contract.
                            </div>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Received at</div>
                                <input
                                    type="datetime-local"
                                    value={packetForm.receivedAt}
                                    onChange={(event) => updatePacketField('receivedAt', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Subject</div>
                                <input
                                    value={packetForm.subject}
                                    onChange={(event) => updatePacketField('subject', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Required"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">From address</div>
                                <input
                                    value={packetForm.fromAddress}
                                    onChange={(event) => updatePacketField('fromAddress', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="alerts@example.com"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">To addresses</div>
                                <textarea
                                    value={packetForm.toAddresses}
                                    onChange={(event) => updatePacketField('toAddresses', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Snippet</div>
                                <textarea
                                    value={packetForm.snippet}
                                    onChange={(event) => updatePacketField('snippet', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Plain text body</div>
                                <textarea
                                    value={packetForm.plainTextBody}
                                    onChange={(event) => updatePacketField('plainTextBody', event.target.value)}
                                    className="min-h-40 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">HTML body</div>
                                <textarea
                                    value={packetForm.htmlBody}
                                    onChange={(event) => updatePacketField('htmlBody', event.target.value)}
                                    className="min-h-28 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Optional"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Label IDs</div>
                                <textarea
                                    value={packetForm.labelIds}
                                    onChange={(event) => updatePacketField('labelIds', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Comma or newline separated"
                                />
                            </label>
                            <label className="space-y-1 text-sm md:col-span-2">
                                <div className="text-gray-300">Operator notes</div>
                                <textarea
                                    value={packetForm.operatorNotes}
                                    onChange={(event) => updatePacketField('operatorNotes', event.target.value)}
                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                    placeholder="Optional"
                                />
                            </label>
                        </div>

                        <button
                            onClick={() => void handlePreparePacket()}
                            className="px-4 py-2 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
                            disabled={prepareSubmitting || reviewSubmitting || gmailFetching || gmailImporting || isBusy}
                        >
                            {prepareSubmitting ? 'Preparing...' : 'Prepare Manual Review Packet'}
                        </button>
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">3. Packet / Review Result</h3>
                            <p className="text-sm text-gray-400">
                                Shows the stored packet or reviewed submission for the selected run.
                            </p>
                        </div>

                        {reportError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {reportError}
                            </div>
                        )}

                        {selectedRunId === null ? (
                            <div className="text-sm text-gray-500">
                                No runs yet. Prepare a manual packet to start this workflow.
                            </div>
                        ) : reportLoading && !selectedReport ? (
                            <div className="text-sm text-gray-400">Loading run report...</div>
                        ) : !selectedReport ? (
                            <div className="text-sm text-gray-500">
                                Run report is not available for the selected run.
                            </div>
                        ) : (
                            <div className="space-y-3">
                                <div className="rounded border border-white/10 bg-white/5 p-3 text-sm">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            Run #{selectedReport.run_id} · {getRunKindLabel(selectedReport.result)}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Status: {selectedReport.status}
                                        </div>
                                    </div>
                                    {selectedReport.summary && (
                                        <div className="mt-1 text-xs text-gray-300">
                                            {selectedReport.summary}
                                        </div>
                                    )}
                                    {selectedReport.error && (
                                        <div className="mt-2 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                                            Error: {selectedReport.error}
                                        </div>
                                    )}
                                </div>

                                {selectedReport.result && isPacketResult(selectedReport.result) && (
                                    <div className="space-y-3">
                                        <div
                                            className={`rounded border px-3 py-2 text-sm ${getExecutionTone(selectedReport.result.execution_status)}`}
                                        >
                                            Packet execution status:{' '}
                                            {humanizeEnum(selectedReport.result.execution_status)}
                                            {selectedReport.result.association.blocked_reason && (
                                                <div className="mt-1 text-xs">
                                                    Blocked reason:{' '}
                                                    {selectedReport.result.association.blocked_reason}
                                                </div>
                                            )}
                                        </div>
                                        {selectedReport.result.manual_review_packet ? (
                                            renderPacketDetails(selectedReport.result.manual_review_packet)
                                        ) : (
                                            <div className="space-y-3">
                                                {renderAssociationSummary(selectedReport.result.association)}
                                                {renderAssociationDiagnostics(selectedReport.result.association)}
                                                <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                                                    This packet-prep run was stored without a manual review packet.
                                                    Blocked or ambiguous states are still preserved above.
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {selectedReport.result &&
                                    isReviewedSubmissionResult(selectedReport.result) &&
                                    renderReviewedSubmissionDetails(
                                        selectedReport.run_id,
                                        selectedReport.result,
                                        approvals,
                                        approvalHistory,
                                    )}

                                {!selectedReport.result && selectedReport.status === 'failed' && (
                                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                                        This reviewed submission failed validation or could not be persisted.
                                        Inspect the audit log below for the validation-failed event trail.
                                    </div>
                                )}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">4. Manual Review Submission</h3>
                            <p className="text-sm text-gray-400">
                                Submit reviewed output from ChatGPT Pro / GPT-5.4 Pro back into SKC.
                                This remains review-only and does not create Gmail drafts or send email.
                            </p>
                        </div>

                        {reviewFormError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {reviewFormError}
                            </div>
                        )}

                        {!selectedReport ? (
                            <div className="text-sm text-gray-500">
                                Select a run before submitting reviewed output.
                            </div>
                        ) : !selectedPacket ? (
                            <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                                Manual review submission is available only for packet-ready runs.
                                Blocked packet runs and reviewed-submission runs are shown above but cannot
                                be resubmitted from this form.
                            </div>
                        ) : (
                            <div className="space-y-4 rounded border border-white/10 bg-white/5 p-4">
                                <div className="text-xs text-gray-400">
                                    Source packet run: #{selectedRunId} · Shortlist cap:{' '}
                                    {selectedPacket.shortlist_cap} · Draft cap:{' '}
                                    {selectedPacket.draft_output_cap}
                                </div>

                                <div className="space-y-3">
                                    <div className="font-medium text-sm">Shortlisted Listings</div>
                                    {selectedPacket.extracted_listings.length === 0 ? (
                                        <div className="text-sm text-gray-500">
                                            No extracted listings are available for shortlist selection.
                                        </div>
                                    ) : (
                                        selectedPacket.extracted_listings.map((listing) => {
                                            const selection = shortlistSelections[listing.listing_ref] ?? {
                                                selected: false,
                                                rank: '',
                                                whySelected: '',
                                            };
                                            const disableUnchecked =
                                                !selection.selected && selectedShortlistCount >= 3;

                                            return (
                                                <div
                                                    key={listing.listing_ref}
                                                    className="rounded border border-white/10 bg-black/10 p-3 space-y-3"
                                                >
                                                    <div className="flex items-start justify-between gap-3">
                                                        <label className="flex items-start gap-3 text-sm">
                                                            <input
                                                                type="checkbox"
                                                                checked={selection.selected}
                                                                onChange={(event) =>
                                                                    toggleListingSelection(
                                                                        listing.listing_ref,
                                                                        event.target.checked,
                                                                    )
                                                                }
                                                                disabled={disableUnchecked}
                                                                className="mt-1"
                                                            />
                                                            <span>
                                                                <div className="font-medium">
                                                                    {listing.address}
                                                                </div>
                                                                <div className="text-xs text-gray-400">
                                                                    Ref: {listing.listing_ref} · Price:{' '}
                                                                    {formatCurrency(listing.price)} · Market:{' '}
                                                                    {humanizeEnum(listing.market_type)}
                                                                </div>
                                                            </span>
                                                        </label>
                                                        <div className="text-xs text-gray-400">
                                                            {listing.property_type || 'Unknown type'}
                                                        </div>
                                                    </div>

                                                    {selection.selected && (
                                                        <div className="grid gap-3 md:grid-cols-[120px,1fr]">
                                                            <label className="space-y-1 text-sm">
                                                                <div className="text-gray-300">Rank</div>
                                                                <input
                                                                    value={selection.rank}
                                                                    onChange={(event) =>
                                                                        updateListingSelection(
                                                                            listing.listing_ref,
                                                                            'rank',
                                                                            event.target.value,
                                                                        )
                                                                    }
                                                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                                                    placeholder="1"
                                                                />
                                                            </label>
                                                            <label className="space-y-1 text-sm">
                                                                <div className="text-gray-300">Why selected</div>
                                                                <textarea
                                                                    value={selection.whySelected}
                                                                    onChange={(event) =>
                                                                        updateListingSelection(
                                                                            listing.listing_ref,
                                                                            'whySelected',
                                                                            event.target.value,
                                                                        )
                                                                    }
                                                                    className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                                                    placeholder="Comma or newline separated"
                                                                />
                                                            </label>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })
                                    )}
                                </div>

                                <div className="grid gap-3">
                                    <label className="space-y-1 text-sm">
                                        <div className="text-gray-300">Tradeoff notes</div>
                                        <textarea
                                            value={reviewForm.tradeoffNotes}
                                            onChange={(event) => updateReviewField('tradeoffNotes', event.target.value)}
                                            className="min-h-24 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                            placeholder="Comma or newline separated"
                                        />
                                    </label>

                                    <label className="space-y-1 text-sm">
                                        <div className="text-gray-300">Recommendation reasoning</div>
                                        <textarea
                                            value={reviewForm.recommendationReasoning}
                                            onChange={(event) =>
                                                updateReviewField('recommendationReasoning', event.target.value)
                                            }
                                            className="min-h-28 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                            placeholder="Required"
                                        />
                                    </label>
                                </div>

                                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-3">
                                    <div className="font-medium text-sm">
                                        Optional client-facing draft (max 1)
                                    </div>
                                    <label className="space-y-1 text-sm">
                                        <div className="text-gray-300">Subject</div>
                                        <input
                                            value={reviewForm.draftSubject}
                                            onChange={(event) => updateReviewField('draftSubject', event.target.value)}
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                        />
                                    </label>
                                    <label className="space-y-1 text-sm">
                                        <div className="text-gray-300">Body</div>
                                        <textarea
                                            value={reviewForm.draftBody}
                                            onChange={(event) => updateReviewField('draftBody', event.target.value)}
                                            className="min-h-28 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                        />
                                    </label>
                                </div>

                                <label className="space-y-1 text-sm">
                                    <div className="text-gray-300">Operator notes</div>
                                    <textarea
                                        value={reviewForm.operatorNotes}
                                        onChange={(event) => updateReviewField('operatorNotes', event.target.value)}
                                        className="min-h-20 w-full rounded border border-white/10 bg-black/20 px-3 py-2"
                                        placeholder="Comma or newline separated"
                                    />
                                </label>

                                <button
                                    onClick={() => void handleSubmitManualReview()}
                                    className="px-4 py-2 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                                    disabled={reviewSubmitting || prepareSubmitting || isBusy}
                                >
                                    {reviewSubmitting ? 'Submitting...' : 'Submit Manual Review'}
                                </button>
                            </div>
                        )}
                    </section>
                </div>

                <div className="space-y-4">
                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">
                                Automatic Mode Latest / Recent Runs
                            </h3>
                            <p className="text-sm text-gray-400">
                                Automatic per-message runs only. Manual Mode runs remain in their
                                own sections below.
                            </p>
                        </div>

                        {automaticError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {automaticError}
                            </div>
                        )}

                        <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2 text-sm">
                            <div className="font-medium">Latest Automatic Run</div>
                            {automaticLatest.run_id === null ? (
                                <div className="text-sm text-gray-500">
                                    No automatic runs yet.
                                </div>
                            ) : (
                                <div className="space-y-1">
                                    <div>
                                        Run #{automaticLatest.run_id} ·{' '}
                                        {automaticLatest.status || 'unknown status'}
                                    </div>
                                    {automaticLatest.result && (
                                        <div className="text-xs text-gray-400">
                                            {getRunKindLabel(automaticLatest.result)}
                                            {isPacketResult(automaticLatest.result) && (
                                                <>
                                                    {' '}
                                                    ·{' '}
                                                    {humanizeEnum(
                                                        automaticLatest.result.execution_status,
                                                    )}
                                                </>
                                            )}
                                            {isReviewedSubmissionResult(
                                                automaticLatest.result,
                                            ) && (
                                                <>
                                                    {' '}
                                                    ·{' '}
                                                    {(automaticLatestApproval
                                                        ? `Approval ${getRunApprovalLabel(automaticLatestApproval)}`
                                                        : null) ??
                                                        humanizeEnum(
                                                            automaticLatest.result.review_outcome,
                                                        )}
                                                </>
                                            )}
                                        </div>
                                    )}
                                    {automaticLatest.error && (
                                        <div className="text-xs text-rose-300">
                                            Error: {automaticLatest.error}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {automaticRuns.length === 0 ? (
                            <div className="text-sm text-gray-500">
                                No automatic recent runs yet.
                            </div>
                        ) : (
                            <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                                {automaticRuns.map((run) => {
                                    const report = automaticRunReports[run.id];
                                    const runKind = report
                                        ? getRunKindLabel(report.result)
                                        : 'Loading kind...';
                                    const runApproval = getRunApproval(
                                        run.id,
                                        automaticApprovals,
                                        automaticApprovalHistory,
                                    );

                                    return (
                                        <div
                                            key={run.id}
                                            className={`rounded border border-white/10 p-3 text-sm ${
                                                selectedAutomaticRunId === run.id
                                                    ? 'bg-white/10'
                                                    : 'bg-black/10'
                                            }`}
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <div className="font-medium">
                                                        Run #{run.id} · {run.status}
                                                    </div>
                                                    <div className="text-xs text-gray-400">
                                                        {runKind} · Created{' '}
                                                        {formatTimestamp(run.created_at)}
                                                    </div>
                                                    {report && isPacketResult(report.result) && (
                                                        <div className="text-xs text-gray-400 mt-1">
                                                            Packet state:{' '}
                                                            {humanizeEnum(
                                                                report.result.execution_status,
                                                            )}
                                                        </div>
                                                    )}
                                                    {report &&
                                                        isReviewedSubmissionResult(
                                                            report.result,
                                                        ) && (
                                                            <div className="text-xs text-gray-400 mt-1">
                                                                {getRunApprovalLabel(runApproval)
                                                                    ? `Approval status: ${getRunApprovalLabel(runApproval)}`
                                                                    : `Review outcome: ${humanizeEnum(report.result.review_outcome)}`}
                                                            </div>
                                                        )}
                                                    {run.error && (
                                                        <div className="text-xs text-rose-300 mt-1">
                                                            Error: {run.error}
                                                        </div>
                                                    )}
                                                </div>
                                                <button
                                                    onClick={() =>
                                                        setSelectedAutomaticRunId(run.id)
                                                    }
                                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                                    disabled={
                                                        prepareSubmitting ||
                                                        reviewSubmitting ||
                                                        automaticRunning ||
                                                        activeApprovalId !== null
                                                    }
                                                >
                                                    {selectedAutomaticRunId === run.id
                                                        ? 'Inspecting'
                                                        : 'Inspect'}
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">
                                Automatic Selected Run Report
                            </h3>
                            <p className="text-sm text-gray-400">
                                Shows the stored automatic packet-prep or automatic reviewed result
                                for the selected automatic run.
                            </p>
                        </div>

                        {automaticReportError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {automaticReportError}
                            </div>
                        )}

                        {selectedAutomaticRunId === null ? (
                            <div className="text-sm text-gray-500">
                                No automatic runs yet. Trigger Automatic Mode once to create one.
                            </div>
                        ) : automaticReportLoading && !selectedAutomaticReport ? (
                            <div className="text-sm text-gray-400">
                                Loading automatic run report...
                            </div>
                        ) : !selectedAutomaticReport ? (
                            <div className="text-sm text-gray-500">
                                Automatic run report is not available for the selected run.
                            </div>
                        ) : (
                            <div className="space-y-3">
                                <div className="rounded border border-white/10 bg-white/5 p-3 text-sm">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            Run #{selectedAutomaticReport.run_id} ·{' '}
                                            {getRunKindLabel(selectedAutomaticReport.result)}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Status: {selectedAutomaticReport.status}
                                        </div>
                                    </div>
                                    {selectedAutomaticReport.summary && (
                                        <div className="mt-1 text-xs text-gray-300">
                                            {selectedAutomaticReport.summary}
                                        </div>
                                    )}
                                    {selectedAutomaticReport.error && (
                                        <div className="mt-2 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                                            Error: {selectedAutomaticReport.error}
                                        </div>
                                    )}
                                </div>

                                {selectedAutomaticReport.result &&
                                    isPacketResult(selectedAutomaticReport.result) && (
                                        <div className="space-y-3">
                                            <div
                                                className={`rounded border px-3 py-2 text-sm ${getExecutionTone(selectedAutomaticReport.result.execution_status)}`}
                                            >
                                                Packet execution status:{' '}
                                                {humanizeEnum(
                                                    selectedAutomaticReport.result
                                                        .execution_status,
                                                )}
                                                {selectedAutomaticReport.result.association
                                                    .blocked_reason && (
                                                    <div className="mt-1 text-xs">
                                                        Blocked reason:{' '}
                                                        {
                                                            selectedAutomaticReport.result
                                                                .association.blocked_reason
                                                        }
                                                    </div>
                                                )}
                                            </div>
                                            {selectedAutomaticReport.result
                                                .manual_review_packet ? (
                                                renderPacketDetails(
                                                    selectedAutomaticReport.result
                                                        .manual_review_packet,
                                                )
                                            ) : (
                                                <div className="space-y-3">
                                                    {renderAssociationSummary(
                                                        selectedAutomaticReport.result
                                                            .association,
                                                    )}
                                                    {renderAssociationDiagnostics(
                                                        selectedAutomaticReport.result
                                                            .association,
                                                    )}
                                                    <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                                                        This automatic packet-prep run was stored
                                                        without a manual review packet. Blocked or
                                                        ambiguous states are still preserved above.
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                {selectedAutomaticReport.result &&
                                    isReviewedSubmissionResult(
                                        selectedAutomaticReport.result,
                                    ) &&
                                    renderReviewedSubmissionDetails(
                                        selectedAutomaticReport.run_id,
                                        selectedAutomaticReport.result,
                                        automaticApprovals,
                                        automaticApprovalHistory,
                                    )}

                                {!selectedAutomaticReport.result &&
                                    selectedAutomaticReport.status === 'failed' && (
                                        <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                                            This automatic run failed validation or could not be
                                            persisted. Inspect the automatic audit log below for the
                                            failure trail.
                                        </div>
                                    )}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">
                                Automatic Audit Log View
                            </h3>
                            <p className="text-sm text-gray-400">
                                Automatic per-message audit trail only. This shows real underlying
                                automatic run logs, not a synthetic batch object.
                            </p>
                        </div>

                        {selectedAutomaticRun ? (
                            <div className="text-sm text-gray-400">
                                Inspecting automatic run #{selectedAutomaticRun.id} (
                                {selectedAutomaticRun.status})
                            </div>
                        ) : (
                            <div className="text-sm text-gray-500">
                                Select an automatic run to inspect its audit log.
                            </div>
                        )}

                        {automaticAuditError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {automaticAuditError}
                            </div>
                        )}

                        {automaticAuditLoading ? (
                            <div className="text-sm text-gray-400">
                                Loading automatic audit history...
                            </div>
                        ) : selectedAutomaticRunId === null ? null : automaticAuditLogs.length ===
                          0 ? (
                            <div className="text-sm text-gray-500">
                                No automatic audit history found for this run.
                            </div>
                        ) : (
                            <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                {automaticAuditLogs.map((log) => (
                                    <div
                                        key={log.id}
                                        className="border-b border-gray-700/40 pb-3 last:border-b-0"
                                    >
                                        <div className="flex items-center justify-between gap-3">
                                            <div className="text-sm font-medium">
                                                {humanizeEnum(log.action)}
                                            </div>
                                            <div className="text-xs text-gray-400">
                                                {formatTimestamp(log.created_at)}
                                            </div>
                                        </div>
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Actor: {humanizeEnum(log.actor_type)}
                                        </div>
                                        {log.details && (
                                            <pre className="mt-2 text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                {formatAuditDetails(log.details)}
                                            </pre>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">
                                Automatic Approval Visibility
                            </h3>
                            <p className="text-sm text-gray-400">
                                Pending and resolved approvals created by automatic review only. No
                                client delivery occurs from this panel.
                            </p>
                        </div>

                        {automaticApprovalError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {automaticApprovalError}
                            </div>
                        )}

                        <div className="space-y-3">
                            <div>
                                <div className="font-medium text-sm mb-2">
                                    Pending Automatic Approvals
                                </div>
                                {automaticApprovals.length === 0 ? (
                                    <div className="text-sm text-gray-500">
                                        No pending automatic approvals.
                                    </div>
                                ) : (
                                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                        {automaticApprovals.map((approval) => {
                                            const payload = parseApprovalPayload(
                                                approval.payload,
                                            );
                                            const isSubmitting =
                                                activeApprovalId === approval.id;

                                            return (
                                                <div
                                                    key={approval.id}
                                                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                                >
                                                    <div className="flex items-start justify-between gap-3">
                                                        <div>
                                                            <div className="font-medium">
                                                                Approval #{approval.id} ·{' '}
                                                                {approval.action_type}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Run #{approval.run_id} · Risk{' '}
                                                                {approval.risk_level}
                                                            </div>
                                                            {payload.contact_id && (
                                                                <div className="text-xs text-gray-400 mt-1">
                                                                    Contact #{payload.contact_id}
                                                                </div>
                                                            )}
                                                            {payload.review_mode && (
                                                                <div className="text-xs text-gray-400 mt-1">
                                                                    Review mode:{' '}
                                                                    {payload.review_mode}
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                onClick={() =>
                                                                    void handleApprove(
                                                                        approval.id,
                                                                        'automatic',
                                                                    )
                                                                }
                                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                                                                disabled={
                                                                    isBusy ||
                                                                    prepareSubmitting ||
                                                                    reviewSubmitting ||
                                                                    automaticRunning ||
                                                                    activeApprovalId !== null
                                                                }
                                                            >
                                                                {isSubmitting
                                                                    ? 'Working...'
                                                                    : 'Approve'}
                                                            </button>
                                                            <button
                                                                onClick={() =>
                                                                    void handleReject(
                                                                        approval.id,
                                                                        'automatic',
                                                                    )
                                                                }
                                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
                                                                disabled={
                                                                    isBusy ||
                                                                    prepareSubmitting ||
                                                                    reviewSubmitting ||
                                                                    automaticRunning ||
                                                                    activeApprovalId !== null
                                                                }
                                                            >
                                                                Reject
                                                            </button>
                                                        </div>
                                                    </div>
                                                    {payload.subject && (
                                                        <div className="mt-3">
                                                            <div className="text-xs font-semibold text-gray-300">
                                                                Subject
                                                            </div>
                                                            <div className="text-sm text-gray-100">
                                                                {payload.subject}
                                                            </div>
                                                        </div>
                                                    )}
                                                    {payload.body && (
                                                        <div className="mt-3">
                                                            <div className="text-xs font-semibold text-gray-300">
                                                                Body
                                                            </div>
                                                            <pre className="text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                                {payload.body}
                                                            </pre>
                                                        </div>
                                                    )}
                                                    {payload.shortlist_addresses &&
                                                        payload.shortlist_addresses.length > 0 && (
                                                            <div className="mt-2 text-xs text-gray-300">
                                                                Shortlist:{' '}
                                                                {payload.shortlist_addresses.join(
                                                                    ' | ',
                                                                )}
                                                            </div>
                                                        )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>

                            <div>
                                <div className="font-medium text-sm mb-2">
                                    Automatic Approval History
                                </div>
                                {automaticApprovalHistory.length === 0 ? (
                                    <div className="text-sm text-gray-500">
                                        No automatic approval decisions yet.
                                    </div>
                                ) : (
                                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                        {automaticApprovalHistory.map((approval) => {
                                            const payload = parseApprovalPayload(
                                                approval.payload,
                                            );
                                            return (
                                                <div
                                                    key={approval.id}
                                                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                                >
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div className="font-medium">
                                                            Approval #{approval.id} ·{' '}
                                                            {approval.status}
                                                        </div>
                                                        <div className="text-xs text-gray-400">
                                                            {getApprovalDecisionMeta(approval)}
                                                        </div>
                                                    </div>
                                                    <div className="text-xs text-gray-400 mt-1">
                                                        Run #{approval.run_id} ·{' '}
                                                        {approval.action_type}
                                                    </div>
                                                    {approval.rejection_reason && (
                                                        <div className="mt-2 text-xs text-rose-300">
                                                            Rejection reason:{' '}
                                                            {approval.rejection_reason}
                                                        </div>
                                                    )}
                                                    {payload.subject && (
                                                        <div className="mt-2 text-xs text-gray-300">
                                                            Subject: {payload.subject}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">5. Latest / Recent Runs</h3>
                            <p className="text-sm text-gray-400">
                                Manual refresh only. Packet-prep runs and reviewed-submission runs are
                                labeled separately.
                            </p>
                        </div>

                        <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2 text-sm">
                            <div className="font-medium">Latest Run</div>
                            {latest.run_id === null ? (
                                <div className="text-sm text-gray-500">No runs yet.</div>
                            ) : (
                                <div className="space-y-1">
                                    <div>
                                        Run #{latest.run_id} · {latest.status || 'unknown status'}
                                    </div>
                                    {latest.result && (
                                        <div className="text-xs text-gray-400">
                                            {getRunKindLabel(latest.result)}
                                            {isPacketResult(latest.result) && (
                                                <> · {humanizeEnum(latest.result.execution_status)}</>
                                            )}
                                            {isReviewedSubmissionResult(latest.result) && (
                                                <>
                                                    {' '}
                                                    ·{' '}
                                                    {(latestApproval
                                                        ? `Approval ${getRunApprovalLabel(latestApproval)}`
                                                        : null) ??
                                                        humanizeEnum(latest.result.review_outcome)}
                                                </>
                                            )}
                                        </div>
                                    )}
                                    {latest.error && (
                                        <div className="text-xs text-rose-300">Error: {latest.error}</div>
                                    )}
                                </div>
                            )}
                        </div>

                        {runs.length === 0 ? (
                            <div className="text-sm text-gray-500">No recent runs yet.</div>
                        ) : (
                            <div className="rounded border border-white/10 bg-white/5 p-3 space-y-2">
                                {runs.map((run) => {
                                    const report = runReports[run.id];
                                    const runKind = report ? getRunKindLabel(report.result) : 'Loading kind...';
                                    const runApproval = getRunApproval(run.id, approvals, approvalHistory);

                                    return (
                                        <div
                                            key={run.id}
                                            className={`rounded border border-white/10 p-3 text-sm ${
                                                selectedRunId === run.id ? 'bg-white/10' : 'bg-black/10'
                                            }`}
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <div className="font-medium">
                                                        Run #{run.id} · {run.status}
                                                    </div>
                                                    <div className="text-xs text-gray-400">
                                                        {runKind} · Created {formatTimestamp(run.created_at)}
                                                    </div>
                                                    {report && isPacketResult(report.result) && (
                                                        <div className="text-xs text-gray-400 mt-1">
                                                            Packet state:{' '}
                                                            {humanizeEnum(report.result.execution_status)}
                                                        </div>
                                                    )}
                                                    {report && isReviewedSubmissionResult(report.result) && (
                                                        <div className="text-xs text-gray-400 mt-1">
                                                            {getRunApprovalLabel(runApproval)
                                                                ? `Approval status: ${getRunApprovalLabel(runApproval)}`
                                                                : `Review outcome: ${humanizeEnum(report.result.review_outcome)}`}
                                                        </div>
                                                    )}
                                                    {run.error && (
                                                        <div className="text-xs text-rose-300 mt-1">
                                                            Error: {run.error}
                                                        </div>
                                                    )}
                                                </div>
                                                <button
                                                    onClick={() => setSelectedRunId(run.id)}
                                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                                    disabled={prepareSubmitting || reviewSubmitting || activeApprovalId !== null}
                                                >
                                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">6. Audit Log View</h3>
                            <p className="text-sm text-gray-400">
                                Shows packet prepared, submission received, validation failed, approval
                                created, and completed-without-draft style events for the selected run.
                            </p>
                        </div>

                        {selectedRun ? (
                            <div className="text-sm text-gray-400">
                                Inspecting run #{selectedRun.id} ({selectedRun.status})
                            </div>
                        ) : (
                            <div className="text-sm text-gray-500">
                                Select a run to inspect its audit log.
                            </div>
                        )}

                        {auditError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {auditError}
                            </div>
                        )}

                        {auditLoading ? (
                            <div className="text-sm text-gray-400">Loading audit history...</div>
                        ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                            <div className="text-sm text-gray-500">No audit history found for this run.</div>
                        ) : (
                            <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                {auditLogs.map((log) => (
                                    <div
                                        key={log.id}
                                        className="border-b border-gray-700/40 pb-3 last:border-b-0"
                                    >
                                        <div className="flex items-center justify-between gap-3">
                                            <div className="text-sm font-medium">
                                                {humanizeEnum(log.action)}
                                            </div>
                                            <div className="text-xs text-gray-400">
                                                {formatTimestamp(log.created_at)}
                                            </div>
                                        </div>
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Actor: {humanizeEnum(log.actor_type)}
                                        </div>
                                        {log.details && (
                                            <pre className="mt-2 text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                {formatAuditDetails(log.details)}
                                            </pre>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <div>
                            <h3 className="text-base font-medium">7. Approval Visibility</h3>
                            <p className="text-sm text-gray-400">
                                Review-only approvals for this workflow. Generic approve/reject endpoints
                                are reused as-is.
                            </p>
                        </div>

                        {approvalError && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                {approvalError}
                            </div>
                        )}

                        <div className="space-y-3">
                            <div>
                                <div className="font-medium text-sm mb-2">Pending Approvals</div>
                                {approvals.length === 0 ? (
                                    <div className="text-sm text-gray-500">No pending approvals.</div>
                                ) : (
                                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                        {approvals.map((approval) => {
                                            const payload = parseApprovalPayload(approval.payload);
                                            const isSubmitting = activeApprovalId === approval.id;

                                            return (
                                                <div
                                                    key={approval.id}
                                                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                                >
                                                    <div className="flex items-start justify-between gap-3">
                                                        <div>
                                                            <div className="font-medium">
                                                                Approval #{approval.id} · {approval.action_type}
                                                            </div>
                                                            <div className="text-xs text-gray-400">
                                                                Run #{approval.run_id} · Risk {approval.risk_level}
                                                            </div>
                                                            {payload.contact_id && (
                                                                <div className="text-xs text-gray-400 mt-1">
                                                                    Contact #{payload.contact_id}
                                                                </div>
                                                            )}
                                                            {payload.review_mode && (
                                                                <div className="text-xs text-gray-400 mt-1">
                                                                    Review mode: {payload.review_mode}
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                onClick={() =>
                                                                    void handleApprove(
                                                                        approval.id,
                                                                        'manual',
                                                                    )
                                                                }
                                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                                                                disabled={isBusy || prepareSubmitting || reviewSubmitting || activeApprovalId !== null}
                                                            >
                                                                {isSubmitting ? 'Working...' : 'Approve'}
                                                            </button>
                                                            <button
                                                                onClick={() =>
                                                                    void handleReject(
                                                                        approval.id,
                                                                        'manual',
                                                                    )
                                                                }
                                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
                                                                disabled={isBusy || prepareSubmitting || reviewSubmitting || activeApprovalId !== null}
                                                            >
                                                                Reject
                                                            </button>
                                                        </div>
                                                    </div>
                                                    {payload.subject && (
                                                        <div className="mt-3">
                                                            <div className="text-xs font-semibold text-gray-300">
                                                                Subject
                                                            </div>
                                                            <div className="text-sm text-gray-100">
                                                                {payload.subject}
                                                            </div>
                                                        </div>
                                                    )}
                                                    {payload.body && (
                                                        <div className="mt-3">
                                                            <div className="text-xs font-semibold text-gray-300">
                                                                Body
                                                            </div>
                                                            <pre className="text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                                {payload.body}
                                                            </pre>
                                                        </div>
                                                    )}
                                                    {payload.shortlist_addresses && payload.shortlist_addresses.length > 0 && (
                                                        <div className="mt-2 text-xs text-gray-300">
                                                            Shortlist: {payload.shortlist_addresses.join(' | ')}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>

                            <div>
                                <div className="font-medium text-sm mb-2">Approval History</div>
                                {approvalHistory.length === 0 ? (
                                    <div className="text-sm text-gray-500">No approval decisions yet.</div>
                                ) : (
                                    <div className="rounded border border-white/10 bg-white/5 p-3 space-y-3">
                                        {approvalHistory.map((approval) => {
                                            const payload = parseApprovalPayload(approval.payload);
                                            return (
                                                <div
                                                    key={approval.id}
                                                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                                                >
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div className="font-medium">
                                                            Approval #{approval.id} · {approval.status}
                                                        </div>
                                                        <div className="text-xs text-gray-400">
                                                            {getApprovalDecisionMeta(approval)}
                                                        </div>
                                                    </div>
                                                    <div className="text-xs text-gray-400 mt-1">
                                                        Run #{approval.run_id} · {approval.action_type}
                                                    </div>
                                                    {approval.rejection_reason && (
                                                        <div className="mt-2 text-xs text-rose-300">
                                                            Rejection reason: {approval.rejection_reason}
                                                        </div>
                                                    )}
                                                    {payload.subject && (
                                                        <div className="mt-2 text-xs text-gray-300">
                                                            Subject: {payload.subject}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        </section>
    );
};

export default ListingAlertRecommendationPanel;
