import axios from 'axios';
import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import type {
    AgentOpsApprovalItem,
    AgentOpsOverviewAgentItem,
    AgentOpsOverviewResponse,
    AgentOpsRunAuditResponse,
    AgentOpsRunItem,
} from '../../services/agents';

const EMPTY_OVERVIEW: AgentOpsOverviewResponse = {
    agents: [],
    totals: {
        pending_approvals: 0,
        recent_decisions: 0,
        failed_runs: 0,
        runs_tracked: 0,
    },
    review_model: {
        manual_only: true,
        no_send: true,
        tracked_agent_types: [],
    },
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

const formatAgentType = (agentType: string) => {
    return agentType
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const formatTimestamp = (value?: string | null) => {
    if (!value) {
        return null;
    }
    return new Date(value).toLocaleString();
};

const renderAuditDetails = (audit: AgentOpsRunAuditResponse['audit_logs'][number]) => {
    if (audit.details_json !== undefined && audit.details_json !== null) {
        return JSON.stringify(audit.details_json, null, 2);
    }
    return audit.details_text ?? '';
};

const getDecisionMeta = (approval: AgentOpsApprovalItem) => {
    const timestamp = approval.decisioned_at ?? approval.created_at;
    const formatted = formatTimestamp(timestamp);
    if (approval.status === 'approved') {
        return formatted ? `Approved ${formatted}` : 'Approved';
    }
    if (approval.status === 'rejected') {
        return formatted ? `Rejected ${formatted}` : 'Rejected';
    }
    return formatted ? `Created ${formatted}` : 'Created';
};

const getRunMeta = (run: AgentOpsRunItem) => {
    if (run.finished_at) {
        return `Finished ${formatTimestamp(run.finished_at)}`;
    }
    if (run.started_at) {
        return `Started ${formatTimestamp(run.started_at)}`;
    }
    return `Created ${formatTimestamp(run.created_at)}`;
};

const agentAccentClass = (agentType: string) => {
    switch (agentType) {
        case 'follow_up':
            return 'text-indigo-300';
        case 'conversation_closer':
            return 'text-sky-300';
        case 'listing_cma':
            return 'text-amber-300';
        default:
            return 'text-gray-300';
    }
};

const OperationsCompliancePanel = () => {
    const [overview, setOverview] = useState<AgentOpsOverviewResponse>(EMPTY_OVERVIEW);
    const [pendingApprovals, setPendingApprovals] = useState<AgentOpsApprovalItem[]>([]);
    const [recentDecisions, setRecentDecisions] = useState<AgentOpsApprovalItem[]>([]);
    const [recentRuns, setRecentRuns] = useState<AgentOpsRunItem[]>([]);
    const [failedRuns, setFailedRuns] = useState<AgentOpsRunItem[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [auditPayload, setAuditPayload] = useState<AgentOpsRunAuditResponse | null>(null);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [activeApprovalId, setActiveApprovalId] = useState<number | null>(null);

    const [error, setError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);

    const isBusy = loading || refreshing;

    const loadAuditPayload = async (runId: number) => {
        setAuditLoading(true);
        setAuditError(null);
        try {
            const payload = await agentsService.getOpsRunAudit(runId);
            setAuditPayload(payload);
        } catch (loadError) {
            setAuditPayload(null);
            setAuditError(getErrorMessage(loadError, 'Audit inspection is unavailable for this run.'));
        } finally {
            setAuditLoading(false);
        }
    };

    const refreshAll = async (mode: 'initial' | 'refresh' = 'refresh') => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }
        setError(null);

        try {
            const [
                overviewData,
                pendingData,
                historyData,
                recentRunsData,
                failedRunsData,
            ] = await Promise.all([
                agentsService.getOpsOverview(),
                agentsService.getOpsPendingApprovals(),
                agentsService.getOpsApprovalHistory(),
                agentsService.getOpsRecentRuns(),
                agentsService.getOpsFailedRuns(),
            ]);

            setOverview(overviewData);
            setPendingApprovals(pendingData);
            setRecentDecisions(historyData);
            setRecentRuns(recentRunsData);
            setFailedRuns(failedRunsData);

            const nextRunId = recentRunsData.some((run) => run.run_id === selectedRunId)
                ? selectedRunId
                : (failedRunsData[0]?.run_id ?? recentRunsData[0]?.run_id ?? null);

            setSelectedRunId(nextRunId);
            if (nextRunId !== null) {
                await loadAuditPayload(nextRunId);
            } else {
                setAuditPayload(null);
                setAuditError(null);
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load operations visibility data.'));
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    useEffect(() => {
        void refreshAll('initial');
    }, []);

    const inspectRun = async (runId: number) => {
        setSelectedRunId(runId);
        await loadAuditPayload(runId);
    };

    const handleApprove = async (approvalId: number) => {
        setActiveApprovalId(approvalId);
        setError(null);
        try {
            await agentsService.approve(approvalId);
            await refreshAll();
        } catch (approveError) {
            setError(getErrorMessage(approveError, 'Failed to approve action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const handleReject = async (approvalId: number) => {
        const promptValue = window.prompt('Rejection reason (optional):');
        if (promptValue === null) {
            return;
        }

        setActiveApprovalId(approvalId);
        setError(null);
        try {
            await agentsService.reject(approvalId, promptValue);
            await refreshAll();
        } catch (rejectError) {
            setError(getErrorMessage(rejectError, 'Failed to reject action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const pageStatus = loading
        ? 'Loading operations visibility data...'
        : refreshing
            ? 'Refreshing operations visibility data...'
            : null;

    const selectedRun =
        auditPayload?.run ??
        recentRuns.find((run) => run.run_id === selectedRunId) ??
        failedRuns.find((run) => run.run_id === selectedRunId) ??
        null;

    return (
        <section className="space-y-6 border-t border-white/10 pt-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-xl font-semibold">Operations / Compliance Visibility</h2>
                    <p className="text-sm text-gray-400">
                        Cross-agent supervision for approvals, failures, and audit history. Manual review only.
                    </p>
                </div>
                <button
                    onClick={() => void refreshAll()}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || auditLoading || activeApprovalId !== null}
                >
                    Refresh
                </button>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            {pageStatus && <div className="text-sm text-gray-400">{pageStatus}</div>}

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Review Model</h3>
                <div className="border rounded p-3 bg-white/5 text-sm space-y-1">
                    <div>Mode: {overview.review_model.manual_only ? 'manual review only' : 'custom'}</div>
                    <div>Sending: {overview.review_model.no_send ? 'no email or push send path' : 'custom'}</div>
                    <div>
                        Tracked agents:{' '}
                        {overview.review_model.tracked_agent_types.length > 0
                            ? overview.review_model.tracked_agent_types.map(formatAgentType).join(', ')
                            : 'none'}
                    </div>
                    <div className="text-gray-300">
                        Totals: {overview.totals.pending_approvals} pending approvals,{' '}
                        {overview.totals.recent_decisions} recent decisions,{' '}
                        {overview.totals.failed_runs} failed runs,{' '}
                        {overview.totals.runs_tracked} tracked runs
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Cross-Agent Overview</h3>
                {overview.agents.length === 0 ? (
                    <div className="text-sm text-gray-500">No agent activity has been recorded yet.</div>
                ) : (
                    <div className="grid gap-3 md:grid-cols-3">
                        {overview.agents.map((agent: AgentOpsOverviewAgentItem) => (
                            <div key={agent.agent_type} className="border rounded p-3 bg-white/5 text-sm space-y-1">
                                <div className={`font-medium ${agentAccentClass(agent.agent_type)}`}>
                                    {formatAgentType(agent.agent_type)}
                                </div>
                                <div>Pending approvals: {agent.pending_approvals}</div>
                                <div>Failed runs: {agent.failed_runs}</div>
                                <div>Tracked runs: {agent.runs_tracked}</div>
                                <div className="text-gray-400">
                                    Latest:{' '}
                                    {agent.latest_run_id
                                        ? `#${agent.latest_run_id} ${agent.latest_run_status ?? 'unknown'}`
                                        : 'No runs yet'}
                                </div>
                                {agent.latest_run_created_at && (
                                    <div className="text-xs text-gray-500">
                                        {formatTimestamp(agent.latest_run_created_at)}
                                    </div>
                                )}
                                {agent.latest_run_error && (
                                    <div className="text-xs text-rose-300">
                                        Error: {agent.latest_run_error}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Unified Pending Approvals</h3>
                <p className="text-sm text-gray-400">
                    Actions here reuse the shared approval endpoints and resolve review state only.
                </p>
                {pendingApprovals.length === 0 ? (
                    <div className="text-sm text-gray-500">No pending approvals across the frozen agents.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {pendingApprovals.map((approval) => {
                            const isSubmitting = activeApprovalId === approval.approval_id;
                            return (
                                <div key={approval.approval_id} className="border-b border-gray-700/40 pb-3 last:border-b-0 text-sm">
                                    <div className="flex items-center justify-between gap-3">
                                        <div>
                                            <div className={`font-medium ${agentAccentClass(approval.agent_type)}`}>
                                                {formatAgentType(approval.agent_type)} · {approval.preview.title || approval.action_type}
                                            </div>
                                            <div className="text-xs text-gray-400">
                                                Approval #{approval.approval_id} · Run #{approval.run_id} · Risk {approval.risk_level}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button
                                                onClick={() => void handleApprove(approval.approval_id)}
                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700"
                                                disabled={isBusy || auditLoading || activeApprovalId !== null}
                                            >
                                                {isSubmitting ? 'Working...' : 'Approve'}
                                            </button>
                                            <button
                                                onClick={() => void handleReject(approval.approval_id)}
                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700"
                                                disabled={isBusy || auditLoading || activeApprovalId !== null}
                                            >
                                                Reject
                                            </button>
                                        </div>
                                    </div>
                                    <div className="mt-1 text-xs text-gray-400">
                                        {approval.run_summary || 'No run summary'} · {formatTimestamp(approval.created_at)}
                                    </div>
                                    {approval.preview.review_mode && (
                                        <div className="mt-1 text-xs text-gray-400">
                                            Review mode: {approval.preview.review_mode}
                                        </div>
                                    )}
                                    {(approval.preview.contact_id || approval.preview.property_id) && (
                                        <div className="mt-1 text-xs text-gray-400">
                                            {approval.preview.contact_id && <>Contact #{approval.preview.contact_id}</>}
                                            {approval.preview.contact_id && approval.preview.property_id && <> · </>}
                                            {approval.preview.property_id && <>Property #{approval.preview.property_id}</>}
                                        </div>
                                    )}
                                    {approval.preview.subject && (
                                        <div className="mt-2">
                                            <div className="text-xs font-semibold text-gray-300">Subject</div>
                                            <div>{approval.preview.subject}</div>
                                        </div>
                                    )}
                                    {approval.preview.body_excerpt && (
                                        <div className="mt-2">
                                            <div className="text-xs font-semibold text-gray-300">Preview</div>
                                            <div className="text-gray-200">{approval.preview.body_excerpt}</div>
                                        </div>
                                    )}
                                    {!approval.preview.subject &&
                                        !approval.preview.body_excerpt &&
                                        approval.preview.payload_text && (
                                            <div className="mt-2 text-xs text-gray-400 break-all">
                                                Payload: {approval.preview.payload_text}
                                            </div>
                                        )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Unified Recent Decisions</h3>
                {recentDecisions.length === 0 ? (
                    <div className="text-sm text-gray-500">No recent approval decisions across the frozen agents.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentDecisions.map((approval) => (
                            <div key={approval.approval_id} className="border-b border-gray-700/40 pb-3 last:border-b-0 text-sm">
                                <div className="flex items-center justify-between gap-3">
                                    <div className={`font-medium ${agentAccentClass(approval.agent_type)}`}>
                                        {formatAgentType(approval.agent_type)} · {approval.preview.title || approval.action_type}
                                    </div>
                                    <div className={approval.status === 'approved' ? 'text-xs font-medium text-emerald-300' : 'text-xs font-medium text-rose-300'}>
                                        {approval.status}
                                    </div>
                                </div>
                                <div className="mt-1 text-xs text-gray-400">
                                    Run #{approval.run_id} · {getDecisionMeta(approval)}
                                </div>
                                {approval.approved_by && (
                                    <div className="mt-1 text-xs text-gray-400">Reviewed by: {approval.approved_by}</div>
                                )}
                                {approval.rejection_reason && (
                                    <div className="mt-1 text-xs text-rose-200">
                                        Rejection reason: {approval.rejection_reason}
                                    </div>
                                )}
                                {approval.preview.subject && (
                                    <div className="mt-1 text-xs text-gray-300">
                                        Subject: {approval.preview.subject}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Unified Failed Runs</h3>
                {failedRuns.length === 0 ? (
                    <div className="text-sm text-gray-500">No failed runs across the frozen agents.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {failedRuns.map((run) => (
                            <div key={run.run_id} className="border-b border-gray-700/40 pb-3 last:border-b-0 text-sm">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <div className={`font-medium ${agentAccentClass(run.agent_type)}`}>
                                            {formatAgentType(run.agent_type)} · Run #{run.run_id}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            {run.summary || 'No summary'} · {getRunMeta(run)}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => void inspectRun(run.run_id)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || auditLoading || activeApprovalId !== null}
                                    >
                                        {selectedRunId === run.run_id ? 'Inspecting' : 'Inspect'}
                                    </button>
                                </div>
                                <div className="mt-1 text-xs text-rose-300">
                                    Error: {run.error || 'Unknown error'}
                                </div>
                                <div className="mt-1 text-xs text-gray-400">
                                    {run.is_internal_only ? 'Internal-only run' : `${run.approval_count} approval item(s)`}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Unified Recent Runs</h3>
                {recentRuns.length === 0 ? (
                    <div className="text-sm text-gray-500">No cross-agent runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentRuns.map((run) => (
                            <div
                                key={run.run_id}
                                className={`border-b border-gray-700/40 pb-3 last:border-b-0 text-sm ${selectedRunId === run.run_id ? 'rounded bg-white/5 px-2 py-2' : ''}`}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <div className={`font-medium ${agentAccentClass(run.agent_type)}`}>
                                            {formatAgentType(run.agent_type)} · Run #{run.run_id} · {run.status}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            {run.summary || 'No summary'} · {getRunMeta(run)}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => void inspectRun(run.run_id)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || auditLoading || activeApprovalId !== null}
                                    >
                                        {selectedRunId === run.run_id ? 'Inspecting' : 'Inspect'}
                                    </button>
                                </div>
                                <div className="mt-1 text-xs text-gray-400">
                                    {run.is_internal_only
                                        ? 'Internal-only run with no approvals'
                                        : `${run.approval_count} approval item(s), ${run.pending_approval_count} pending`}
                                </div>
                                {run.error && (
                                    <div className="mt-1 text-xs text-rose-300">Error: {run.error}</div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Audit Inspector</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting {formatAgentType(selectedRun.agent_type)} run #{selectedRun.run_id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a recent or failed run to inspect audit history.</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : !auditPayload || auditPayload.audit_logs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditPayload.audit_logs.map((audit) => {
                            const details = renderAuditDetails(audit);
                            return (
                                <div key={audit.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-sm font-medium">{audit.action}</div>
                                        <div className="text-xs text-gray-400">
                                            {formatTimestamp(audit.created_at)}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Actor: {audit.actor_type}
                                    </div>
                                    {details && (
                                        <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                            {details}
                                        </pre>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>
        </section>
    );
};

export default OperationsCompliancePanel;
