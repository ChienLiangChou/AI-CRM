import axios from 'axios';
import { useEffect, useState } from 'react';
import { agentsService } from '../services/agents';
import ConversationCloserPanel from '../components/agents/ConversationCloserPanel';
import ListingCmaPanel from '../components/agents/ListingCmaPanel';
import OperationsCompliancePanel from '../components/agents/OperationsCompliancePanel';
import BuyerMatchPanel from '../components/agents/BuyerMatchPanel';
import StrategyCoordinationPanel from '../components/agents/StrategyCoordinationPanel';
import MlsAuthPanel from '../components/agents/MlsAuthPanel';
import type {
    AgentRun,
    AgentApproval,
    AgentAuditLog,
    FollowUpRecommendationsResponse,
    FollowUpDraftItem,
} from '../services/agents';

const EMPTY_FOLLOW_UP: FollowUpRecommendationsResponse = {
    recommendations: [],
    drafts: [],
    run_id: null,
};

type ApprovalPayload = {
    subject?: string;
    body?: string;
    contact_id?: number;
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

const parseApprovalPayload = (payload?: string): ApprovalPayload => {
    const parsed = parseJsonText(payload);
    if (!parsed || typeof parsed !== 'object') {
        return {};
    }

    return parsed as ApprovalPayload;
};

const getErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
    }
    return fallback;
};

const AgentDashboard = () => {
    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [approvals, setApprovals] = useState<AgentApproval[]>([]);
    const [recentDecisions, setRecentDecisions] = useState<AgentApproval[]>([]);
    const [followUp, setFollowUp] = useState<FollowUpRecommendationsResponse>(EMPTY_FOLLOW_UP);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [triggering, setTriggering] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [activeApprovalId, setActiveApprovalId] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);
    const [decisionError, setDecisionError] = useState<string | null>(null);

    const loadAuditLogs = async (runId: number) => {
        setAuditLoading(true);
        setAuditError(null);
        try {
            const logs = await agentsService.getRunAuditLogs(runId);
            setAuditLogs(logs);
        } catch (e) {
            setAuditLogs([]);
            setAuditError(getErrorMessage(e, 'Audit history is unavailable for this run.'));
        } finally {
            setAuditLoading(false);
        }
    };

    const loadData = async (mode: 'initial' | 'refresh' = 'refresh') => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }
        setError(null);
        try {
            const [runsData, approvalsData, followUpData] = await Promise.all([
                agentsService.getRuns(),
                agentsService.getPendingApprovals(),
                agentsService.getFollowUpRecommendations(),
            ]);
            setRuns(runsData);
            setApprovals(approvalsData);
            setFollowUp(followUpData);
            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? null);
            setSelectedRunId(preferredRunId);

            try {
                const decisions = await agentsService.getRecentApprovalDecisions();
                setRecentDecisions(decisions);
                setDecisionError(null);
            } catch (decisionLoadError) {
                setRecentDecisions([]);
                setDecisionError(
                    getErrorMessage(decisionLoadError, 'Recent approval history is unavailable.'),
                );
            }
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to load follow-up agent data.'));
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    useEffect(() => {
        // Single-load on mount; no auto-polling.
        void loadData('initial');
    }, []);

    useEffect(() => {
        if (selectedRunId === null) {
            setAuditLogs([]);
            setAuditError(null);
            return;
        }

        void loadAuditLogs(selectedRunId);
    }, [selectedRunId]);

    const handleTriggerFollowUp = async () => {
        setTriggering(true);
        setError(null);
        try {
            await agentsService.triggerFollowUpRunOnce();
            await loadData();
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to trigger follow-up run.'));
        } finally {
            setTriggering(false);
        }
    };

    const handleApprove = async (id: number) => {
        setActiveApprovalId(id);
        setError(null);
        try {
            await agentsService.approve(id);
            await loadData();
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to approve action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const handleReject = async (id: number) => {
        const promptValue = window.prompt('Rejection reason (optional):');
        if (promptValue === null) {
            return;
        }

        const reason = promptValue;
        setActiveApprovalId(id);
        setError(null);
        try {
            await agentsService.reject(id, reason);
            await loadData();
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to reject action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const draftsByApprovalId = new Map<number, FollowUpDraftItem>();
    for (const draft of followUp.drafts) {
        draftsByApprovalId.set(draft.approval_id, draft);
    }

    const latestRun = runs[0] ?? null;
    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const hasRecommendations = followUp.recommendations.length > 0;
    const hasApprovals = approvals.length > 0;
    const hasRecentDecisions = recentDecisions.length > 0;
    const isBusy = loading || refreshing;
    const pageStatus = loading
        ? 'Loading follow-up agent data...'
        : refreshing
            ? 'Refreshing follow-up agent data...'
            : null;

    const renderDecisionMeta = (approval: AgentApproval) => {
        if (approval.status === 'approved' && approval.approved_at) {
            return `Approved ${new Date(approval.approved_at).toLocaleString()}`;
        }
        if (approval.status === 'rejected' && approval.rejected_at) {
            return `Rejected ${new Date(approval.rejected_at).toLocaleString()}`;
        }
        return `Created ${new Date(approval.created_at).toLocaleString()}`;
    };

    return (
        <div className="p-4 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-xl font-semibold">Agent Dashboard</h1>
                    <p className="text-sm text-gray-400">
                        Manual review surfaces for the current MVP agents. No sending or hidden automation.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => void loadData()}
                        className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        Refresh
                    </button>
                    <button
                        onClick={handleTriggerFollowUp}
                        className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        {triggering ? 'Running...' : 'Run Follow-up Agent'}
                    </button>
                </div>
            </div>

            {error && <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}

            {pageStatus && <div className="text-sm text-gray-400">{pageStatus}</div>}

            <section className="space-y-2">
                <h2 className="text-lg font-medium">MVP Status</h2>
                <div className="border rounded p-3 bg-white/5 text-sm space-y-1">
                    <div>Scope: Follow-up Agent v1 baseline + Client Conversation Closer v1 baseline + Listing / CMA v1 panel</div>
                    <div>Review model: approval-only, no email sending, no push sending</div>
                    {latestRun ? (
                        <div className="text-gray-300">
                            Latest run #{latestRun.id} is <span className="font-medium">{latestRun.status}</span>
                            {latestRun.finished_at && <> as of {new Date(latestRun.finished_at).toLocaleString()}</>}
                        </div>
                    ) : (
                        <div className="text-gray-400">No follow-up runs have been created yet.</div>
                    )}
                    {latestRun?.error && (
                        <div className="text-rose-300">
                            Latest run error: {latestRun.error}
                        </div>
                    )}
                </div>
            </section>

            <section className="space-y-2">
                <h2 className="text-lg font-medium">Follow-up Recommendations</h2>
                {!hasRecommendations ? (
                    <div className="text-sm text-gray-500">
                        {followUp.run_id
                            ? 'The latest follow-up run produced no actionable recommendations.'
                            : 'No follow-up recommendations yet.'}
                    </div>
                ) : (
                    <div className="border rounded p-3 space-y-2 bg-white/5">
                        {followUp.recommendations.map((item, idx) => (
                            <div key={`${item.contact_id}-${idx}`} className="text-sm border-b border-gray-700/40 pb-2 last:border-b-0">
                                <div className="font-medium">
                                    {item.contact_name || 'Unknown contact'}{' '}
                                    {item.company && <span className="text-gray-400">({item.company})</span>}
                                </div>
                                <div className="text-xs text-gray-400">
                                    Urgency: {item.urgency || 'n/a'} | Action: {item.suggested_action || 'n/a'}
                                </div>
                                <div className="text-sm mt-1">{item.message}</div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-lg font-medium">Pending Approvals</h2>
                <p className="text-sm text-gray-400">
                    Approving or rejecting here only resolves review status. It does not send anything.
                </p>
                {!hasApprovals ? (
                    <div className="text-sm text-gray-500">No pending approvals.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {approvals.map((approval) => {
                            const parsedPayload = parseApprovalPayload(approval.payload);
                            const matchingDraft = draftsByApprovalId.get(approval.id);
                            const subject = parsedPayload.subject || matchingDraft?.subject;
                            const body = parsedPayload.body || matchingDraft?.body;
                            const contactId = parsedPayload.contact_id || matchingDraft?.contact_id;
                            const isSubmitting = activeApprovalId === approval.id;
                            return (
                                <div key={approval.id} className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between">
                                        <div className="font-medium">
                                            #{approval.id} – {approval.action_type}
                                        </div>
                                        <div className="space-x-2">
                                            <button
                                                onClick={() => handleApprove(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700"
                                                disabled={isBusy || triggering || activeApprovalId !== null}
                                            >
                                                {isSubmitting ? 'Working...' : 'Approve'}
                                            </button>
                                            <button
                                                onClick={() => handleReject(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700"
                                                disabled={isBusy || triggering || activeApprovalId !== null}
                                            >
                                                Reject
                                            </button>
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Risk: {approval.risk_level} · Status: {approval.status}
                                    </div>
                                    {contactId && (
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Contact ID: {contactId}
                                        </div>
                                    )}
                                    {subject && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Subject</div>
                                            <div className="text-sm">{subject}</div>
                                        </div>
                                    )}
                                    {body && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Body</div>
                                            <pre className="text-xs whitespace-pre-wrap bg-black/20 rounded p-2 max-h-48 overflow-auto">
                                                {body}
                                            </pre>
                                        </div>
                                    )}
                                    {!subject && approval.payload && (
                                        <div className="mt-1 text-xs text-gray-400 break-all">
                                            Raw payload: {approval.payload}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-lg font-medium">Recent Approval Decisions</h2>
                <p className="text-sm text-gray-400">
                    Recent manual review outcomes for the Follow-up Agent.
                </p>
                {decisionError && (
                    <div className="text-sm text-amber-300">{decisionError}</div>
                )}
                {!hasRecentDecisions ? (
                    <div className="text-sm text-gray-500">No approval decisions yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentDecisions.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            return (
                                <div key={approval.id} className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {approval.action_type}
                                        </div>
                                        <div className={`text-xs font-medium ${approval.status === 'approved' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                            {approval.status}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Run #{approval.run_id} · {renderDecisionMeta(approval)}
                                    </div>
                                    {approval.approved_by && (
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Reviewed by: {approval.approved_by}
                                        </div>
                                    )}
                                    {approval.rejection_reason && (
                                        <div className="text-xs text-rose-200 mt-1">
                                            Rejection reason: {approval.rejection_reason}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="text-xs text-gray-300 mt-1">
                                            Subject: {payload.subject}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-lg font-medium">Recent Runs</h2>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-1 bg-white/5 text-sm">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between border-b border-gray-700/40 pb-2 last:border-b-0 ${selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''}`}
                            >
                                <div>
                                    <div className="font-medium">
                                        Run #{run.id} – {run.status}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Created: {new Date(run.created_at).toLocaleString()}
                                        {run.finished_at && <> · Finished: {new Date(run.finished_at).toLocaleString()}</>}
                                    </div>
                                    {run.error && (
                                        <div className="text-xs text-rose-300 mt-0.5">
                                            Error: {run.error}
                                        </div>
                                    )}
                                </div>
                                <div className="flex items-center gap-3">
                                    {run.summary && <div className="text-xs text-gray-300">{run.summary}</div>}
                                    <button
                                        onClick={() => setSelectedRunId(run.id)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || triggering || activeApprovalId !== null}
                                    >
                                        {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-lg font-medium">Run Audit History</h2>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a run to inspect its audit history.</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {auditError && (
                    <div className="text-sm text-amber-300">{auditError}</div>
                )}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => {
                            const parsedDetails = parseJsonText(log.details);
                            const renderedDetails = parsedDetails
                                ? JSON.stringify(parsedDetails, null, 2)
                                : log.details;

                            return (
                                <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-sm font-medium">{log.action}</div>
                                        <div className="text-xs text-gray-400">
                                            {new Date(log.created_at).toLocaleString()}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Actor: {log.actor_type}
                                    </div>
                                    {renderedDetails && (
                                        <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                            {renderedDetails}
                                        </pre>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <ConversationCloserPanel />
            <ListingCmaPanel />
            <BuyerMatchPanel />
            <OperationsCompliancePanel />
            <StrategyCoordinationPanel />
            <MlsAuthPanel />
        </div>
    );
};

export default AgentDashboard;
