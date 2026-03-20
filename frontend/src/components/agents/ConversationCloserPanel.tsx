import axios from 'axios';
import { useEffect, useState } from 'react';
import { crmService } from '../../services/api';
import type { Contact } from '../../services/api';
import { agentsService } from '../../services/agents';
import type {
    AgentApproval,
    AgentAuditLog,
    AgentRun,
    ConversationCloserLatestResponse,
    ConversationCloserRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: ConversationCloserLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

type ConversationApprovalPayload = {
    subject?: string;
    body?: string;
    contact_id?: number;
    variant?: string;
    primary_objection?: string;
    risk_flags?: string[];
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

const parseApprovalPayload = (payload?: string): ConversationApprovalPayload => {
    const parsed = parseJsonText(payload);
    if (!parsed || typeof parsed !== 'object') {
        return {};
    }

    return parsed as ConversationApprovalPayload;
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

const formatAuditDetails = (value?: string) => {
    const parsed = parseJsonText(value);
    if (parsed) {
        return JSON.stringify(parsed, null, 2);
    }
    return value ?? '';
};

const getDecisionMeta = (approval: AgentApproval) => {
    if (approval.status === 'approved' && approval.approved_at) {
        return `Approved ${new Date(approval.approved_at).toLocaleString()}`;
    }
    if (approval.status === 'rejected' && approval.rejected_at) {
        return `Rejected ${new Date(approval.rejected_at).toLocaleString()}`;
    }
    return `Created ${new Date(approval.created_at).toLocaleString()}`;
};

const ConversationCloserPanel = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [contactId, setContactId] = useState<number | ''>('');
    const [message, setMessage] = useState('');
    const [channel, setChannel] = useState('email');
    const [operatorGoal, setOperatorGoal] = useState('');
    const [desiredOutcome, setDesiredOutcome] = useState('');
    const [contextNotes, setContextNotes] = useState('');

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<ConversationCloserLatestResponse>(EMPTY_LATEST);
    const [approvals, setApprovals] = useState<AgentApproval[]>([]);
    const [recentDecisions, setRecentDecisions] = useState<AgentApproval[]>([]);
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

    const isBusy = loading || refreshing;

    const loadAuditLogs = async (runId: number) => {
        setAuditLoading(true);
        setAuditError(null);
        try {
            const logs = await agentsService.getConversationCloserRunAuditLogs(runId);
            setAuditLogs(logs);
        } catch (loadError) {
            setAuditLogs([]);
            setAuditError(getErrorMessage(loadError, 'Audit history is unavailable for this run.'));
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
            const [contactsData, runsData, latestData, approvalsData] = await Promise.all([
                crmService.getContacts(),
                agentsService.getConversationCloserRuns(),
                agentsService.getLatestConversationCloserResult(),
                agentsService.getConversationCloserPendingApprovals(),
            ]);
            setContacts([...contactsData].sort((a, b) => a.name.localeCompare(b.name)));
            setRuns(runsData);
            setLatest(latestData);
            setApprovals(approvalsData);

            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? null);
            setSelectedRunId(preferredRunId);

            try {
                const history = await agentsService.getConversationCloserApprovalHistory();
                setRecentDecisions(history);
                setDecisionError(null);
            } catch (historyError) {
                setRecentDecisions([]);
                setDecisionError(
                    getErrorMessage(historyError, 'Recent approval history is unavailable.'),
                );
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load Client Conversation Closer data.'));
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    useEffect(() => {
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

    const handleTrigger = async () => {
        if (!contactId || !message.trim()) {
            setError('Select a contact and enter the client message before running the agent.');
            return;
        }

        const payload: ConversationCloserRunRequest = {
            contact_id: contactId,
            message: message.trim(),
            channel,
            operator_goal: operatorGoal.trim() || undefined,
            desired_outcome: desiredOutcome.trim() || undefined,
            context_notes: contextNotes.trim() || undefined,
        };

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerConversationCloserRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData();
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Client Conversation Closer.'));
        } finally {
            setTriggering(false);
        }
    };

    const handleApprove = async (approvalId: number) => {
        setActiveApprovalId(approvalId);
        setError(null);
        try {
            await agentsService.approve(approvalId);
            await loadData();
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
            await loadData();
        } catch (rejectError) {
            setError(getErrorMessage(rejectError, 'Failed to reject action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const latestRun = runs[0] ?? null;
    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const pageStatus = loading
        ? 'Loading Client Conversation Closer data...'
        : refreshing
            ? 'Refreshing Client Conversation Closer data...'
            : null;

    return (
        <section className="space-y-6 border-t border-white/10 pt-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-xl font-semibold">Client Conversation Closer</h2>
                    <p className="text-sm text-gray-400">
                        Manual objection-handling support with review-only reply drafts. No sending or hidden automation.
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
                        onClick={handleTrigger}
                        className="px-3 py-1.5 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-60"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        {triggering ? 'Running...' : 'Run Conversation Closer'}
                    </button>
                </div>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            {pageStatus && <div className="text-sm text-gray-400">{pageStatus}</div>}

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Manual Trigger</h3>
                <div className="border rounded p-3 bg-white/5 space-y-3">
                    <div>
                        <label htmlFor="cc-contact" className="block text-sm font-medium mb-1">
                            Contact
                        </label>
                        <select
                            id="cc-contact"
                            value={contactId}
                            onChange={(event) =>
                                setContactId(event.target.value ? Number(event.target.value) : '')
                            }
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        >
                            <option value="">Select a contact</option>
                            {contacts.map((contact) => (
                                <option key={contact.id} value={contact.id}>
                                    {contact.name}
                                    {contact.company ? ` (${contact.company})` : ''}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label htmlFor="cc-message" className="block text-sm font-medium mb-1">
                            Client Message
                        </label>
                        <textarea
                            id="cc-message"
                            value={message}
                            onChange={(event) => setMessage(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-28"
                            placeholder="Paste the client's objection, hesitation, or message here."
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        />
                    </div>

                    <div className="grid gap-3 md:grid-cols-3">
                        <div>
                            <label htmlFor="cc-channel" className="block text-sm font-medium mb-1">
                                Channel
                            </label>
                            <select
                                id="cc-channel"
                                value={channel}
                                onChange={(event) => setChannel(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="email">Email</option>
                                <option value="sms">SMS</option>
                                <option value="phone">Phone</option>
                            </select>
                        </div>

                        <div>
                            <label htmlFor="cc-operator-goal" className="block text-sm font-medium mb-1">
                                Operator Goal
                            </label>
                            <input
                                id="cc-operator-goal"
                                value={operatorGoal}
                                onChange={(event) => setOperatorGoal(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="retain_seller"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="cc-desired-outcome" className="block text-sm font-medium mb-1">
                                Desired Outcome
                            </label>
                            <input
                                id="cc-desired-outcome"
                                value={desiredOutcome}
                                onChange={(event) => setDesiredOutcome(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="keep_conversation_open"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>
                    </div>

                    <div>
                        <label htmlFor="cc-context-notes" className="block text-sm font-medium mb-1">
                            Context Notes
                        </label>
                        <textarea
                            id="cc-context-notes"
                            value={contextNotes}
                            onChange={(event) => setContextNotes(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-20"
                            placeholder="Optional notes for tone, relationship context, or what matters in the reply."
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        />
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Latest Result</h3>
                {!latest.run_id ? (
                    <div className="text-sm text-gray-500">No conversation closer runs yet.</div>
                ) : (
                    <div className="border rounded p-3 bg-white/5 space-y-3 text-sm">
                        <div className="text-gray-300">
                            Latest run #{latest.run_id} is{' '}
                            <span className="font-medium">{latest.status ?? 'unknown'}</span>
                        </div>
                        {latest.error && (
                            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                                Run error: {latest.error}
                            </div>
                        )}
                        {!latest.result ? (
                            <div className="text-sm text-gray-400">
                                No parsed result is available for the latest run yet.
                            </div>
                        ) : (
                            <>
                                <div>
                                    <div className="text-xs font-semibold text-gray-300">Summary</div>
                                    <div>{latest.result.summary}</div>
                                </div>

                                <div className="grid gap-3 md:grid-cols-2">
                                    <div className="rounded border border-white/10 bg-black/20 p-3">
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Objection Analysis
                                        </div>
                                        <div>Primary: {latest.result.objection_analysis.primary_type}</div>
                                        <div>Sentiment: {latest.result.objection_analysis.sentiment}</div>
                                        <div>Urgency: {latest.result.objection_analysis.urgency}</div>
                                        <div>
                                            Confidence:{' '}
                                            {Math.round(latest.result.objection_analysis.confidence * 100)}%
                                        </div>
                                        <div>
                                            Escalation required:{' '}
                                            {latest.result.objection_analysis.requires_manual_escalation
                                                ? 'yes'
                                                : 'no'}
                                        </div>
                                        {latest.result.objection_analysis.secondary_types.length > 0 && (
                                            <div className="mt-1">
                                                Secondary:{' '}
                                                {latest.result.objection_analysis.secondary_types.join(', ')}
                                            </div>
                                        )}
                                    </div>

                                    <div className="rounded border border-white/10 bg-black/20 p-3">
                                        <div className="text-xs font-semibold text-gray-300 mb-1">Strategy</div>
                                        <div>Action: {latest.result.strategy.recommended_action}</div>
                                        <div>Goal: {latest.result.strategy.goal}</div>
                                        <div>Tone: {latest.result.strategy.tone}</div>
                                        <div className="mt-1 text-gray-300">
                                            {latest.result.strategy.rationale}
                                        </div>
                                    </div>
                                </div>

                                <div className="grid gap-3 md:grid-cols-2">
                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Talking Points
                                        </div>
                                        {latest.result.talking_points.length === 0 ? (
                                            <div className="text-gray-500">No talking points.</div>
                                        ) : (
                                            <ul className="list-disc pl-5 space-y-1">
                                                {latest.result.talking_points.map((item, index) => (
                                                    <li key={`${item}-${index}`}>{item}</li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Risk Flags / Notes
                                        </div>
                                        {latest.result.risk_flags.length > 0 ? (
                                            <div className="mb-2 text-amber-200">
                                                {latest.result.risk_flags.join(', ')}
                                            </div>
                                        ) : (
                                            <div className="mb-2 text-gray-500">No risk flags.</div>
                                        )}
                                        {latest.result.operator_notes.length === 0 ? (
                                            <div className="text-gray-500">No operator notes.</div>
                                        ) : (
                                            <ul className="list-disc pl-5 space-y-1">
                                                {latest.result.operator_notes.map((item, index) => (
                                                    <li key={`${item}-${index}`}>{item}</li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                </div>

                                <div>
                                    <div className="text-xs font-semibold text-gray-300 mb-1">Draft Variants</div>
                                    {latest.result.drafts.length === 0 ? (
                                        <div className="text-gray-500">
                                            No reply drafts were generated for the latest run.
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {latest.result.drafts.map((draft, index) => (
                                                <div
                                                    key={`${draft.variant}-${index}`}
                                                    className="rounded border border-white/10 bg-black/20 p-3"
                                                >
                                                    <div className="font-medium">
                                                        {draft.variant} · {draft.channel}
                                                    </div>
                                                    {draft.subject && (
                                                        <div className="mt-1 text-sm text-gray-300">
                                                            Subject: {draft.subject}
                                                        </div>
                                                    )}
                                                    <pre className="mt-2 text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                        {draft.body}
                                                    </pre>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Pending Approvals</h3>
                <p className="text-sm text-gray-400">
                    Approve or reject only resolves review status. It does not send anything.
                </p>
                {approvals.length === 0 ? (
                    <div className="text-sm text-gray-500">No pending approvals.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {approvals.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            const isSubmitting = activeApprovalId === approval.id;
                            return (
                                <div
                                    key={approval.id}
                                    className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0"
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {payload.variant || approval.action_type}
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
                                    {payload.contact_id && (
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Contact ID: {payload.contact_id}
                                            {payload.primary_objection
                                                ? ` · Objection: ${payload.primary_objection}`
                                                : ''}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Subject</div>
                                            <div>{payload.subject}</div>
                                        </div>
                                    )}
                                    {payload.body && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Body</div>
                                            <pre className="text-xs whitespace-pre-wrap bg-black/20 rounded p-2 max-h-48 overflow-auto">
                                                {payload.body}
                                            </pre>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Recent Approval Decisions</h3>
                <p className="text-sm text-gray-400">
                    Recent manual review outcomes for the Client Conversation Closer.
                </p>
                {decisionError && <div className="text-sm text-amber-300">{decisionError}</div>}
                {recentDecisions.length === 0 ? (
                    <div className="text-sm text-gray-500">No approval decisions yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentDecisions.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            return (
                                <div
                                    key={approval.id}
                                    className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0"
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {payload.variant || approval.action_type}
                                        </div>
                                        <div
                                            className={`text-xs font-medium ${
                                                approval.status === 'approved'
                                                    ? 'text-emerald-300'
                                                    : 'text-rose-300'
                                            }`}
                                        >
                                            {approval.status}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Run #{approval.run_id} · {getDecisionMeta(approval)}
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
                <h3 className="text-lg font-medium">Recent Runs</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-1 bg-white/5 text-sm">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between border-b border-gray-700/40 pb-2 last:border-b-0 ${
                                    selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''
                                }`}
                            >
                                <div>
                                    <div className="font-medium">
                                        Run #{run.id} – {run.status}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Created: {new Date(run.created_at).toLocaleString()}
                                        {run.finished_at && (
                                            <> · Finished: {new Date(run.finished_at).toLocaleString()}</>
                                        )}
                                    </div>
                                    {run.error && (
                                        <div className="text-xs text-rose-300 mt-0.5">
                                            Error: {run.error}
                                        </div>
                                    )}
                                </div>
                                <button
                                    onClick={() => setSelectedRunId(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering || activeApprovalId !== null}
                                >
                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Run Audit History</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">
                        Select a run to inspect its audit history.
                    </div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => (
                            <div
                                key={log.id}
                                className="border-b border-gray-700/40 pb-3 last:border-b-0"
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{log.action}</div>
                                    <div className="text-xs text-gray-400">
                                        {new Date(log.created_at).toLocaleString()}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400 mt-0.5">
                                    Actor: {log.actor_type}
                                </div>
                                {log.details && (
                                    <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                        {formatAuditDetails(log.details)}
                                    </pre>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {latestRun && latestRun.id !== latest.run_id && (
                <div className="text-xs text-amber-300">
                    Latest result payload is from run #{latest.run_id}, while the newest run in the list is #{latestRun.id}.
                </div>
            )}
        </section>
    );
};

export default ConversationCloserPanel;
