import axios from 'axios';
import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import type {
    AgentAuditLog,
    AgentRun,
    StrategyCoordinationLatestResponse,
    StrategyCoordinationResultResponse,
    StrategyCoordinationRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: StrategyCoordinationLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
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

const formatAuditDetails = (value?: string) => {
    const parsed = parseJsonText(value);
    if (parsed) {
        return JSON.stringify(parsed, null, 2);
    }
    return value ?? '';
};

const parseCsvIds = (value: string) => {
    const seen = new Set<number>();
    return value
        .split(',')
        .map((item) => Number(item.trim()))
        .filter((item) => Number.isInteger(item) && item > 0)
        .filter((item) => {
            if (seen.has(item)) {
                return false;
            }
            seen.add(item);
            return true;
        });
};

const parseListingLines = (value: string) => {
    const seen = new Set<string>();
    return value
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const [listingRefRaw, propertyIdRaw, labelRaw] = line.split('|').map((item) => item?.trim());
            const listingRef = listingRefRaw || undefined;
            const propertyId = propertyIdRaw ? Number(propertyIdRaw) : undefined;
            const label = labelRaw || undefined;
            if (!listingRef && !propertyId) {
                return null;
            }
            const normalizedListingRef =
                listingRef || (Number.isInteger(propertyId) && propertyId! > 0 ? `manual:property:${propertyId}` : undefined);
            if (!normalizedListingRef || seen.has(normalizedListingRef)) {
                return null;
            }
            seen.add(normalizedListingRef);
            return {
                listing_ref: normalizedListingRef,
                property_id: Number.isInteger(propertyId) && propertyId! > 0 ? propertyId : undefined,
                label,
            };
        })
        .filter(Boolean) as StrategyCoordinationRunRequest['linked_entities']['listings'];
};

const formatPerspectiveName = (value: string) => {
    return value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const renderReportCard = (
    report: StrategyCoordinationResultResponse,
    heading: string,
    subtitle?: string | null,
) => {
    const perspectiveEntries = [
        ['follow_up', report.perspective_blocks.follow_up],
        ['conversation_retention', report.perspective_blocks.conversation_retention],
        ['listing_seller', report.perspective_blocks.listing_seller],
        ['operations_compliance', report.perspective_blocks.operations_compliance],
    ] as const;

    return (
        <div className="border rounded p-3 space-y-4 bg-white/5 text-sm">
            <div className="space-y-1">
                <div className="font-medium">{heading}</div>
                {subtitle && <div className="text-xs text-gray-400">{subtitle}</div>}
                <div className="text-xs text-gray-400">
                    Event: {report.event_summary.event_type} · Source: {report.event_summary.source_type} · Urgency:{' '}
                    {report.event_summary.urgency}
                </div>
                <div className="text-sm text-gray-200">{report.event_summary.summary}</div>
                {report.event_summary.details && (
                    <div className="text-xs text-gray-400 whitespace-pre-wrap">{report.event_summary.details}</div>
                )}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Importance
                    </div>
                    <div className="font-medium">{report.importance_assessment.classification}</div>
                    <div className="text-xs text-gray-400">
                        Confidence: {report.importance_assessment.confidence.toFixed(2)}
                    </div>
                    <div className="text-xs text-gray-300">{report.importance_assessment.reason}</div>
                </div>
                <div className="rounded border border-amber-500/20 bg-amber-500/5 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">
                        Execution Policy
                    </div>
                    <div>Mode: {report.execution_policy.mode}</div>
                    <div>Executable: {report.execution_policy.can_execute_actions ? 'yes' : 'no'}</div>
                    <div>Trigger agents: {report.execution_policy.can_trigger_agents ? 'yes' : 'no'}</div>
                    <div>Client outputs: {report.execution_policy.can_create_client_outputs ? 'yes' : 'no'}</div>
                </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Affected Entities
                    </div>
                    <div>Contacts: {report.affected_entities.contacts.length || 'none'}</div>
                    <div>Properties: {report.affected_entities.properties.length || 'none'}</div>
                    <div>Listings: {report.affected_entities.listings.length || 'none'}</div>
                    <div>Runs: {report.affected_entities.runs.length || 'none'}</div>
                    <div>Approvals: {report.affected_entities.approvals.length || 'none'}</div>
                </div>
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Risk Flags
                    </div>
                    {report.risk_flags.length === 0 ? (
                        <div className="text-gray-500">No risk flags.</div>
                    ) : (
                        report.risk_flags.map((flag) => (
                            <div key={flag} className="text-gray-300">{flag}</div>
                        ))
                    )}
                </div>
            </div>

            <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    Perspective Blocks
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                    {perspectiveEntries.map(([key, block]) => (
                        <div key={key} className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                            <div className="font-medium">{formatPerspectiveName(key)}</div>
                            <div className="text-xs text-gray-400">Relevance: {block.relevance}</div>
                            <div>{block.summary}</div>
                            {block.supporting_signals.length > 0 && (
                                <div className="text-xs text-gray-300">
                                    Signals: {block.supporting_signals.join(' | ')}
                                </div>
                            )}
                            {block.risk_flags.length > 0 && (
                                <div className="text-xs text-amber-200">
                                    Risks: {block.risk_flags.join(', ')}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className="space-y-1">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    Strategy Synthesis
                </div>
                <div>{report.strategy_synthesis.summary}</div>
                {report.strategy_synthesis.key_takeaways.length > 0 && (
                    <div className="text-xs text-gray-300">
                        {report.strategy_synthesis.key_takeaways.join(' | ')}
                    </div>
                )}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Internal Actions
                    </div>
                    {report.recommended_next_actions.internal_actions.length === 0 ? (
                        <div className="text-gray-500">No internal actions.</div>
                    ) : (
                        report.recommended_next_actions.internal_actions.map((item, index) => (
                            <div key={`${item}-${index}`}>{item}</div>
                        ))
                    )}
                </div>
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Human Review Actions
                    </div>
                    {report.recommended_next_actions.human_review_actions.length === 0 ? (
                        <div className="text-gray-500">No human review actions.</div>
                    ) : (
                        report.recommended_next_actions.human_review_actions.map((item, index) => (
                            <div key={`${item}-${index}`}>{item}</div>
                        ))
                    )}
                </div>
            </div>

            {report.operator_notes.length > 0 && (
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Operator Notes
                    </div>
                    {report.operator_notes.map((note, index) => (
                        <div key={`${note}-${index}`} className="text-xs text-gray-300">
                            {note}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

const StrategyCoordinationPanel = () => {
    const [eventType, setEventType] = useState('');
    const [sourceType, setSourceType] = useState<'external' | 'internal'>('internal');
    const [summary, setSummary] = useState('');
    const [details, setDetails] = useState('');
    const [urgency, setUrgency] = useState<'low' | 'medium' | 'high'>('medium');
    const [operatorGoal, setOperatorGoal] = useState('');
    const [contactIds, setContactIds] = useState('');
    const [propertyIds, setPropertyIds] = useState('');
    const [listingRefs, setListingRefs] = useState('');
    const [runIds, setRunIds] = useState('');
    const [approvalIds, setApprovalIds] = useState('');

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<StrategyCoordinationLatestResponse>(EMPTY_LATEST);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedReport, setSelectedReport] = useState<StrategyCoordinationResultResponse | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [triggering, setTriggering] = useState(false);
    const [reportLoading, setReportLoading] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [reportError, setReportError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);

    const isBusy = loading || refreshing;

    const loadSelectedRunData = async (runId: number) => {
        setReportLoading(true);
        setAuditLoading(true);
        setReportError(null);
        setAuditError(null);

        try {
            const [reportResult, auditResult] = await Promise.allSettled([
                agentsService.getStrategyCoordinationRunReport(runId),
                agentsService.getStrategyCoordinationRunAuditLogs(runId),
            ]);

            if (reportResult.status === 'fulfilled') {
                setSelectedReport(reportResult.value);
            } else {
                setSelectedReport(null);
                setReportError(
                    getErrorMessage(
                        reportResult.reason,
                        'Structured report is unavailable for this run.',
                    ),
                );
            }

            if (auditResult.status === 'fulfilled') {
                setAuditLogs(auditResult.value);
            } else {
                setAuditLogs([]);
                setAuditError(
                    getErrorMessage(
                        auditResult.reason,
                        'Audit history is unavailable for this run.',
                    ),
                );
            }
        } finally {
            setReportLoading(false);
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
            const [runsData, latestData] = await Promise.all([
                agentsService.getStrategyCoordinationRuns(),
                agentsService.getLatestStrategyCoordinationResult(),
            ]);
            setRuns(runsData);
            setLatest(latestData);

            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? latestData.run_id ?? null);
            setSelectedRunId(preferredRunId);

            if (preferredRunId !== null) {
                await loadSelectedRunData(preferredRunId);
            } else {
                setSelectedReport(null);
                setAuditLogs([]);
                setReportError(null);
                setAuditError(null);
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load Strategy Coordination data.'));
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

    const handleTrigger = async () => {
        if (!eventType.trim() || !summary.trim()) {
            setError('Provide at least an event type and summary before running Strategy Coordination.');
            return;
        }

        const payload: StrategyCoordinationRunRequest = {
            event_type: eventType.trim(),
            source_type: sourceType,
            summary: summary.trim(),
            details: details.trim() || undefined,
            urgency,
            operator_goal: operatorGoal.trim() || undefined,
            linked_entities: {
                contacts: parseCsvIds(contactIds),
                properties: parseCsvIds(propertyIds),
                listings: parseListingLines(listingRefs),
                runs: parseCsvIds(runIds),
                approvals: parseCsvIds(approvalIds),
            },
        };

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerStrategyCoordinationRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData();
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Strategy Coordination.'));
        } finally {
            setTriggering(false);
        }
    };

    const inspectRun = async (runId: number) => {
        setSelectedRunId(runId);
        await loadSelectedRunData(runId);
    };

    const latestRun = runs[0] ?? null;
    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const pageStatus = loading
        ? 'Loading Strategy Coordination data...'
        : refreshing
            ? 'Refreshing Strategy Coordination data...'
            : null;

    return (
        <section className="space-y-6 border-t border-white/10 pt-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-xl font-semibold">Strategy Coordination</h2>
                    <p className="text-sm text-gray-400">
                        Internal-only strategy reporting layer for manual event intake. Non-executable, no approvals, no hidden automation.
                    </p>
                </div>
                <button
                    onClick={() => void loadData()}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || triggering || reportLoading || auditLoading}
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
                <h3 className="text-lg font-medium">Execution Status</h3>
                <div className="border rounded p-3 bg-white/5 text-sm space-y-1">
                    <div>Mode: internal-only, non-executable strategy reporting</div>
                    <div>Execution: no action buttons, no client delivery, no module triggering</div>
                    <div>Approvals: not used by this layer in v1</div>
                    {latestRun ? (
                        <div className="text-gray-300">
                            Latest run #{latestRun.id} is <span className="font-medium">{latestRun.status}</span>
                            {latestRun.finished_at && <> as of {new Date(latestRun.finished_at).toLocaleString()}</>}
                        </div>
                    ) : (
                        <div className="text-gray-400">No strategy runs have been created yet.</div>
                    )}
                    {latestRun?.error && (
                        <div className="text-rose-300">Latest run error: {latestRun.error}</div>
                    )}
                </div>
            </section>

            <section className="space-y-3">
                <h3 className="text-lg font-medium">Manual Event Intake</h3>
                <div className="border rounded p-3 bg-white/5 space-y-3">
                    <div className="grid gap-3 md:grid-cols-3">
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Event Type</span>
                            <input
                                value={eventType}
                                onChange={(event) => setEventType(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="bank_of_canada_decision"
                            />
                        </label>
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Source Type</span>
                            <select
                                value={sourceType}
                                onChange={(event) => setSourceType(event.target.value as 'external' | 'internal')}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                            >
                                <option value="internal">internal</option>
                                <option value="external">external</option>
                            </select>
                        </label>
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Urgency</span>
                            <select
                                value={urgency}
                                onChange={(event) => setUrgency(event.target.value as 'low' | 'medium' | 'high')}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                            >
                                <option value="low">low</option>
                                <option value="medium">medium</option>
                                <option value="high">high</option>
                            </select>
                        </label>
                    </div>

                    <label className="text-sm space-y-1 block">
                        <span className="text-gray-300">Summary</span>
                        <textarea
                            value={summary}
                            onChange={(event) => setSummary(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white min-h-[72px]"
                            placeholder="Briefly describe the event and why it matters."
                        />
                    </label>

                    <div className="grid gap-3 md:grid-cols-2">
                        <label className="text-sm space-y-1 block">
                            <span className="text-gray-300">Details</span>
                            <textarea
                                value={details}
                                onChange={(event) => setDetails(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white min-h-[96px]"
                                placeholder="Optional operator-entered event detail."
                            />
                        </label>
                        <label className="text-sm space-y-1 block">
                            <span className="text-gray-300">Operator Goal</span>
                            <textarea
                                value={operatorGoal}
                                onChange={(event) => setOperatorGoal(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white min-h-[96px]"
                                placeholder="Optional goal, e.g. assess_pipeline_impact"
                            />
                        </label>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Linked Contact IDs</span>
                            <input
                                value={contactIds}
                                onChange={(event) => setContactIds(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="42, 51"
                            />
                        </label>
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Linked Property IDs</span>
                            <input
                                value={propertyIds}
                                onChange={(event) => setPropertyIds(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="17, 21"
                            />
                        </label>
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Linked Run IDs</span>
                            <input
                                value={runIds}
                                onChange={(event) => setRunIds(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="103, 104"
                            />
                        </label>
                        <label className="text-sm space-y-1">
                            <span className="text-gray-300">Linked Approval IDs</span>
                            <input
                                value={approvalIds}
                                onChange={(event) => setApprovalIds(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="88, 89"
                            />
                        </label>
                    </div>

                    <label className="text-sm space-y-1 block">
                        <span className="text-gray-300">Linked Listings</span>
                        <textarea
                            value={listingRefs}
                            onChange={(event) => setListingRefs(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white min-h-[96px]"
                            placeholder={'One per line: listing_ref|property_id|label\nmanual:downtown-condo-listing|17|20 Stewart St #706'}
                        />
                    </label>

                    <div className="flex justify-end">
                        <button
                            onClick={() => void handleTrigger()}
                            className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
                            disabled={isBusy || triggering || reportLoading || auditLoading}
                        >
                            {triggering ? 'Running...' : 'Run Strategy Coordination'}
                        </button>
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Latest Report</h3>
                {!latest.result ? (
                    <div className="text-sm text-gray-500">
                        {latest.run_id
                            ? 'The latest strategy run does not have a structured report available.'
                            : 'No strategy reports yet.'}
                    </div>
                ) : (
                    renderReportCard(
                        latest.result,
                        `Latest report · Run #${latest.run_id ?? 'n/a'}`,
                        latest.status ? `Status: ${latest.status}` : null,
                    )
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Recent Runs</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No strategy runs yet.</div>
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
                                    <div className="font-medium">Run #{run.id} – {run.status}</div>
                                    <div className="text-xs text-gray-400">
                                        Created: {new Date(run.created_at).toLocaleString()}
                                        {run.finished_at && <> · Finished: {new Date(run.finished_at).toLocaleString()}</>}
                                    </div>
                                    {run.summary && <div className="text-xs text-gray-300 mt-0.5">{run.summary}</div>}
                                    {run.error && <div className="text-xs text-rose-300 mt-0.5">Error: {run.error}</div>}
                                </div>
                                <button
                                    onClick={() => void inspectRun(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering || reportLoading || auditLoading}
                                >
                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Selected Run Report</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a strategy run to inspect its report.</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {reportError && <div className="text-sm text-amber-300">{reportError}</div>}
                {reportLoading ? (
                    <div className="text-sm text-gray-400">Loading structured report...</div>
                ) : selectedRunId === null ? null : selectedReport ? (
                    renderReportCard(
                        selectedReport,
                        `Selected report · Run #${selectedRunId}`,
                        selectedRun?.status ? `Status: ${selectedRun.status}` : null,
                    )
                ) : (
                    <div className="text-sm text-gray-500">No structured report found for this run.</div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Selected Run Audit History</h3>
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? (
                    <div className="text-sm text-gray-500">Select a strategy run to inspect its audit history.</div>
                ) : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => (
                            <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{log.action}</div>
                                    <div className="text-xs text-gray-400">
                                        {new Date(log.created_at).toLocaleString()}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400 mt-0.5">Actor: {log.actor_type}</div>
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
        </section>
    );
};

export default StrategyCoordinationPanel;
