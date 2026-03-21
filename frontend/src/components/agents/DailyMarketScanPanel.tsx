import axios from 'axios';
import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import type {
    AgentAuditLog,
    AgentRun,
    DailyMarketScanFailureMetadata,
    DailyMarketScanLatestResponse,
    DailyMarketScanResultResponse,
    DailyMarketScanRunRequest,
    DailyMarketScanSourceAttempt,
} from '../../services/agents';

const EMPTY_LATEST: DailyMarketScanLatestResponse = {
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
        .filter(Boolean) as DailyMarketScanRunRequest['listing_refs'];
};

const formatTimestamp = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'n/a';
    }
    return date.toLocaleString();
};

const humanizeValue = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }
    return value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const getWorkflowBadgeClass = (status?: string | null) => {
    switch (status) {
        case 'completed':
            return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
        case 'no_findings':
            return 'border-slate-500/30 bg-slate-500/10 text-slate-100';
        case 'no_providers':
            return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
        case 'partial':
            return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
        case 'failed':
            return 'border-rose-500/30 bg-rose-500/10 text-rose-100';
        default:
            return 'border-white/10 bg-white/5 text-gray-200';
    }
};

const renderFailureMetadata = (
    items: DailyMarketScanFailureMetadata[],
    emptyLabel = 'No failure metadata.',
) => {
    if (items.length === 0) {
        return <div className="text-gray-500">{emptyLabel}</div>;
    }

    return (
        <div className="space-y-2">
            {items.map((item, index) => (
                <div key={`${item.code}-${item.provider_key ?? 'none'}-${index}`} className="rounded border border-amber-500/20 bg-amber-500/5 p-2">
                    <div className="font-medium text-amber-100">{humanizeValue(item.code)}</div>
                    <div className="text-xs text-gray-300">
                        Provider: {item.provider_key || 'n/a'} · Retryable: {item.retryable ? 'yes' : 'no'} · Fallback attempted:{' '}
                        {item.fallback_attempted ? 'yes' : 'no'} · Fallback used: {item.fallback_used ? 'yes' : 'no'}
                    </div>
                    {item.message && <div className="text-xs text-gray-300 mt-1">{item.message}</div>}
                </div>
            ))}
        </div>
    );
};

const renderSourceAttempts = (attempts: DailyMarketScanSourceAttempt[]) => {
    if (attempts.length === 0) {
        return <div className="text-gray-500">No source attempts recorded.</div>;
    }

    return (
        <div className="space-y-2">
            {attempts.map((attempt, index) => (
                <div key={`${attempt.provider_key}-${attempt.source_used}-${index}`} className="rounded border border-white/10 bg-black/10 p-2 space-y-1">
                    <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">
                            {attempt.provider_key} via {attempt.source_used}
                        </div>
                        <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(attempt.status)}`}>
                            {humanizeValue(attempt.status)}
                        </div>
                    </div>
                    <div className="text-xs text-gray-400">
                        Auth state: {humanizeValue(attempt.auth_state)} · Fallback used: {attempt.fallback_used ? 'yes' : 'no'}
                    </div>
                    {attempt.notes.length > 0 && (
                        <div className="text-xs text-gray-300">{attempt.notes.join(' | ')}</div>
                    )}
                    {attempt.failure_metadata.length > 0 && renderFailureMetadata(attempt.failure_metadata)}
                </div>
            ))}
        </div>
    );
};

const summarizeAuditDetails = (action: string, details?: string) => {
    const parsed = parseJsonText(details);
    if (!parsed || typeof parsed !== 'object') {
        return details || 'No additional audit detail.';
    }

    const data = parsed as Record<string, unknown>;

    if (action === 'daily_market_scan_request_normalized') {
        return [
            `Scan mode: ${humanizeValue(typeof data.scan_mode === 'string' ? data.scan_mode : null)}`,
            `Run mode: ${humanizeValue(typeof data.run_mode === 'string' ? data.run_mode : null)}`,
            `Source preference: ${humanizeValue(typeof data.source_preference === 'string' ? data.source_preference : null)}`,
            `Max subjects: ${typeof data.max_subjects === 'number' ? data.max_subjects : 'n/a'}`,
        ].join(' | ');
    }

    if (action === 'daily_market_scan_subjects_resolved') {
        const scope = data.scope as Record<string, unknown> | undefined;
        const selected = data.selected_subjects as Record<string, unknown> | undefined;
        const counts = selected?.counts as Record<string, unknown> | undefined;
        return [
            `Scope: ${humanizeValue(typeof scope?.decision === 'string' ? scope.decision : null)}`,
            `Requested: ${typeof scope?.requested_subject_count === 'number' ? scope.requested_subject_count : 'n/a'}`,
            `Effective: ${typeof scope?.effective_subject_count === 'number' ? scope.effective_subject_count : 'n/a'}`,
            `Selected contacts/properties/listings: ${typeof counts?.contacts_selected === 'number' ? counts.contacts_selected : 0}/${typeof counts?.properties_selected === 'number' ? counts.properties_selected : 0}/${typeof counts?.listings_selected === 'number' ? counts.listings_selected : 0}`,
        ].join(' | ');
    }

    if (action === 'daily_market_scan_provider_plan_generated') {
        const providerOrder = Array.isArray(data.provider_order) ? data.provider_order.join(' -> ') : 'n/a';
        return `Provider order: ${providerOrder}`;
    }

    if (action === 'daily_market_scan_provider_execution_completed') {
        const clientMatchScans = Array.isArray(data.client_match_scans) ? data.client_match_scans.length : 0;
        const competitorWatchScans = Array.isArray(data.competitor_watch_scans) ? data.competitor_watch_scans.length : 0;
        const riskFlags = Array.isArray(data.risk_flags) ? data.risk_flags.join(', ') : 'none';
        return `Client match scans: ${clientMatchScans} | Competitor watch scans: ${competitorWatchScans} | Risk flags: ${riskFlags}`;
    }

    if (action === 'daily_market_scan_provider_failure_recorded') {
        const failures = Array.isArray(data.failure_metadata) ? data.failure_metadata : [];
        const summary = failures
            .map((item) => {
                if (!item || typeof item !== 'object') {
                    return null;
                }
                const failure = item as Record<string, unknown>;
                return `${typeof failure.provider_key === 'string' ? failure.provider_key : 'n/a'}:${typeof failure.code === 'string' ? failure.code : 'unknown_failure'}`;
            })
            .filter(Boolean)
            .join(' | ');
        return summary || 'Provider failure metadata recorded.';
    }

    if (action === 'daily_market_scan_run_completed') {
        const riskFlags = Array.isArray(data.risk_flags) ? data.risk_flags.join(', ') : 'none';
        return `Run completed. Risk flags: ${riskFlags}`;
    }

    if (action === 'daily_market_scan_run_failed') {
        return `Run failed: ${typeof data.error === 'string' ? data.error : 'unknown_error'}`;
    }

    return 'Internal audit detail recorded.';
};

const renderReport = (
    report: DailyMarketScanResultResponse,
    heading: string,
    subtitle?: string | null,
) => {
    return (
        <div className="border rounded p-3 space-y-4 bg-white/5 text-sm">
            <div className="space-y-1">
                <div className="font-medium">{heading}</div>
                {subtitle && <div className="text-xs text-gray-400">{subtitle}</div>}
                <div className="text-xs text-gray-400">
                    Scan mode: {humanizeValue(report.scan_summary.scan_mode)} · Run mode: {humanizeValue(report.scan_summary.run_mode)}
                </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Scope
                    </div>
                    <div>Decision: {humanizeValue(report.scan_summary.scope.decision)}</div>
                    <div>Requested subjects: {report.scan_summary.scope.requested_subject_count}</div>
                    <div>Effective subjects: {report.scan_summary.scope.effective_subject_count}</div>
                    <div>Max subjects: {report.scan_summary.scope.max_subjects}</div>
                    {report.scan_summary.scope.notes.length > 0 && (
                        <div className="text-xs text-gray-300">{report.scan_summary.scope.notes.join(' | ')}</div>
                    )}
                </div>
                <div className="rounded border border-sky-500/20 bg-sky-500/5 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                        Execution Policy
                    </div>
                    <div>Mode: {report.execution_policy.mode}</div>
                    <div>No auto-send: {report.execution_policy.can_auto_send ? 'no' : 'yes'}</div>
                    <div>No auto-contact: {report.execution_policy.can_auto_contact_clients ? 'no' : 'yes'}</div>
                    <div>No client outputs without approval: {report.execution_policy.can_create_client_outputs_without_approval ? 'no' : 'yes'}</div>
                </div>
            </div>

            <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    Providers
                </div>
                <div className="text-xs text-gray-400">
                    Provider order: {report.scan_summary.provider_order.length > 0 ? report.scan_summary.provider_order.join(' -> ') : 'none'}
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                    {report.provider_catalog.map((provider) => (
                        <div key={provider.provider_key} className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                            <div className="font-medium">{provider.display_name}</div>
                            <div className="text-xs text-gray-400">
                                Key: {provider.provider_key} · Availability: {humanizeValue(provider.availability)} · Auth:{' '}
                                {humanizeValue(provider.auth_state)}
                            </div>
                            <div className="text-xs text-gray-300">
                                Detail: {humanizeValue(provider.detail_level)} · Confidence: {humanizeValue(provider.confidence_level)} · Fallback capable:{' '}
                                {provider.fallback_capable ? 'yes' : 'no'}
                            </div>
                            {provider.notes.length > 0 && (
                                <div className="text-xs text-gray-300">{provider.notes.join(' | ')}</div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Client Match
                    </div>
                    {report.client_match_scans.length === 0 ? (
                        <div className="text-gray-500">No client-match scans in this run.</div>
                    ) : (
                        report.client_match_scans.map((scan, index) => (
                            <div key={`${scan.contact_id}-${index}`} className="rounded border border-white/10 bg-black/10 p-3 space-y-2">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="font-medium">Contact #{scan.contact_id}</div>
                                    <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(scan.status)}`}>
                                        {humanizeValue(scan.status)}
                                    </div>
                                </div>
                                {scan.criteria_summary && (
                                    <div className="text-xs text-gray-300">{scan.criteria_summary}</div>
                                )}
                                <div className="text-xs text-gray-400">
                                    Findings: {scan.findings.length} · Fallback used: {scan.fallback_used ? 'yes' : 'no'}
                                </div>
                                {scan.findings.length > 0 && (
                                    <div className="space-y-2">
                                        {scan.findings.map((finding, findingIndex) => (
                                            <div key={`${finding.address}-${findingIndex}`} className="rounded border border-white/10 bg-white/5 p-2">
                                                <div className="font-medium">{finding.address}</div>
                                                <div className="text-xs text-gray-400">
                                                    Source: {finding.source_used}
                                                    {finding.mls_number && <> · MLS: {finding.mls_number}</>}
                                                    {finding.listing_ref && <> · Listing ref: {finding.listing_ref}</>}
                                                </div>
                                                {finding.why_it_matches.length > 0 && (
                                                    <div className="text-xs text-gray-300 mt-1">
                                                        Match signals: {finding.why_it_matches.join(' | ')}
                                                    </div>
                                                )}
                                                {finding.tradeoffs.length > 0 && (
                                                    <div className="text-xs text-amber-100 mt-1">
                                                        Tradeoffs: {finding.tradeoffs.join(' | ')}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Source Attempts
                                    </div>
                                    {renderSourceAttempts(scan.source_attempts)}
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Failure Metadata
                                    </div>
                                    {renderFailureMetadata(scan.failure_metadata)}
                                </div>
                            </div>
                        ))
                    )}
                </div>

                <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Competitor Watch
                    </div>
                    {report.competitor_watch_scans.length === 0 ? (
                        <div className="text-gray-500">No competitor-watch scans in this run.</div>
                    ) : (
                        report.competitor_watch_scans.map((scan, index) => (
                            <div key={`${scan.subject.property_id ?? scan.subject.listing_ref ?? index}-${index}`} className="rounded border border-white/10 bg-black/10 p-3 space-y-2">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="font-medium">
                                        {scan.subject.listing_ref
                                            ? `Listing ${scan.subject.listing_ref}`
                                            : `Property #${scan.subject.property_id ?? 'n/a'}`}
                                    </div>
                                    <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(scan.status)}`}>
                                        {humanizeValue(scan.status)}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400">
                                    Competitor mode: {humanizeValue(scan.subject.competitor_mode)} · Findings: {scan.findings.length} · Fallback used:{' '}
                                    {scan.fallback_used ? 'yes' : 'no'}
                                </div>
                                {scan.findings.length > 0 && (
                                    <div className="space-y-2">
                                        {scan.findings.map((finding, findingIndex) => (
                                            <div key={`${finding.address}-${findingIndex}`} className="rounded border border-white/10 bg-white/5 p-2">
                                                <div className="font-medium">{finding.address}</div>
                                                <div className="text-xs text-gray-400">
                                                    Source: {finding.source_used}
                                                    {finding.mls_number && <> · MLS: {finding.mls_number}</>}
                                                    {finding.listing_ref && <> · Listing ref: {finding.listing_ref}</>}
                                                </div>
                                                {finding.why_relevant.length > 0 && (
                                                    <div className="text-xs text-gray-300 mt-1">
                                                        Relevance: {finding.why_relevant.join(' | ')}
                                                    </div>
                                                )}
                                                {finding.competitor_notes.length > 0 && (
                                                    <div className="text-xs text-amber-100 mt-1">
                                                        Notes: {finding.competitor_notes.join(' | ')}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Source Attempts
                                    </div>
                                    {renderSourceAttempts(scan.source_attempts)}
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Failure Metadata
                                    </div>
                                    {renderFailureMetadata(scan.failure_metadata)}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
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
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Top-Level Failure Metadata
                    </div>
                    {renderFailureMetadata(report.failure_metadata)}
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

const DailyMarketScanPanel = () => {
    const [scanMode, setScanMode] = useState<'client_match' | 'competitor_watch' | 'full_daily_scan'>('full_daily_scan');
    const [runMode, setRunMode] = useState<'manual_preview' | 'simulated_preview'>('manual_preview');
    const [sourcePreference, setSourcePreference] = useState<'auto' | 'authenticated_mls_browser_first' | 'public_only'>('auto');
    const [contactIds, setContactIds] = useState('');
    const [propertyIds, setPropertyIds] = useState('');
    const [listingRefs, setListingRefs] = useState('');
    const [maxSubjects, setMaxSubjects] = useState('25');

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<DailyMarketScanLatestResponse>(EMPTY_LATEST);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedReport, setSelectedReport] = useState<DailyMarketScanResultResponse | null>(null);
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
                agentsService.getDailyMarketScanRunReport(runId),
                agentsService.getDailyMarketScanRunAuditLogs(runId),
            ]);

            if (reportResult.status === 'fulfilled') {
                setSelectedReport(reportResult.value);
            } else {
                setSelectedReport(null);
                setReportError(
                    getErrorMessage(
                        reportResult.reason,
                        'Structured Daily Market Scan report is unavailable for this run.',
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
                        'Audit history is unavailable for this Daily Market Scan run.',
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
                agentsService.getDailyMarketScanRuns(),
                agentsService.getLatestDailyMarketScanResult(),
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
            setError(getErrorMessage(loadError, 'Failed to load Daily Market Scan data.'));
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
            setSelectedReport(null);
            setAuditLogs([]);
            setReportError(null);
            setAuditError(null);
            return;
        }

        void loadSelectedRunData(selectedRunId);
    }, [selectedRunId]);

    const handleTrigger = async () => {
        const payload: DailyMarketScanRunRequest = {
            scan_mode: scanMode,
            run_mode: runMode,
            source_preference: sourcePreference,
            contact_ids: parseCsvIds(contactIds),
            property_ids: parseCsvIds(propertyIds),
            listing_refs: parseListingLines(listingRefs),
            max_subjects: maxSubjects.trim() ? Number(maxSubjects) : undefined,
        };

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerDailyMarketScanRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData('refresh');
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Daily Market Scan.'));
        } finally {
            setTriggering(false);
        }
    };

    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;

    return (
        <section className="space-y-4 border border-cyan-500/20 rounded-lg p-4 bg-cyan-500/5">
            <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                    <h2 className="text-lg font-medium">Daily Market Scan</h2>
                    <div className="text-sm text-gray-300">
                        Internal-only market scan workspace. Manual or simulated only. No auto-send. No hidden automation.
                    </div>
                    <div className="text-xs text-gray-400">
                        This panel does not perform real provider retrieval, browser automation, CRM writeback, or TRREB integration yet.
                    </div>
                </div>
                <button
                    onClick={() => void loadData('refresh')}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || triggering}
                >
                    {refreshing ? 'Refreshing...' : 'Refresh'}
                </button>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            <div className="border rounded p-3 bg-white/5 space-y-3">
                <div className="text-sm font-medium">Manual / Simulated Run</div>
                <div className="grid gap-3 md:grid-cols-3">
                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Scan mode</div>
                        <select
                            value={scanMode}
                            onChange={(event) => setScanMode(event.target.value as typeof scanMode)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="full_daily_scan">full_daily_scan</option>
                            <option value="client_match">client_match</option>
                            <option value="competitor_watch">competitor_watch</option>
                        </select>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Run mode</div>
                        <select
                            value={runMode}
                            onChange={(event) => setRunMode(event.target.value as typeof runMode)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="manual_preview">manual_preview</option>
                            <option value="simulated_preview">simulated_preview</option>
                        </select>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Source preference</div>
                        <select
                            value={sourcePreference}
                            onChange={(event) => setSourcePreference(event.target.value as typeof sourcePreference)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="auto">auto</option>
                            <option value="authenticated_mls_browser_first">authenticated_mls_browser_first</option>
                            <option value="public_only">public_only</option>
                        </select>
                    </label>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Contact IDs</div>
                        <input
                            value={contactIds}
                            onChange={(event) => setContactIds(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder="12, 18, 51"
                        />
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Property IDs</div>
                        <input
                            value={propertyIds}
                            onChange={(event) => setPropertyIds(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder="101, 102"
                        />
                    </label>
                </div>

                <div className="grid gap-3 md:grid-cols-[1fr_180px]">
                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Listing refs</div>
                        <textarea
                            value={listingRefs}
                            onChange={(event) => setListingRefs(event.target.value)}
                            rows={4}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder={'manual:listing:20-stewart|17|20 Stewart St #706\nmanual:property:88|88|88 King St W'}
                        />
                        <div className="text-xs text-gray-400">
                            One per line. Format: listing_ref|property_id|label
                        </div>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">Max subjects</div>
                        <input
                            value={maxSubjects}
                            onChange={(event) => setMaxSubjects(event.target.value)}
                            inputMode="numeric"
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder="25"
                        />
                    </label>
                </div>

                <div className="flex items-center justify-between gap-3">
                    <div className="text-xs text-gray-400">
                        Review-only. Stable result shapes include zero findings, no providers, and partial failures without treating them as crashes.
                    </div>
                    <button
                        onClick={handleTrigger}
                        className="px-3 py-2 text-sm rounded bg-cyan-600 text-white hover:bg-cyan-700 disabled:opacity-60"
                        disabled={isBusy || triggering}
                    >
                        {triggering ? 'Running...' : 'Run Daily Market Scan'}
                    </button>
                </div>
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Latest Scan Result</h3>
                {latest.run_id === null ? (
                    <div className="text-sm text-gray-500">No Daily Market Scan runs yet.</div>
                ) : latest.result ? (
                    renderReport(
                        latest.result,
                        `Latest run #${latest.run_id}`,
                        latest.status ? `Status: ${latest.status}` : null,
                    )
                ) : (
                    <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                        Latest run #{latest.run_id} is {latest.status || 'unknown'}.
                        {latest.error && <span className="text-rose-200"> Error: {latest.error}</span>}
                        {!latest.error && <span> Structured result is unavailable for this run.</span>}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Recent Runs</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No Daily Market Scan runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-2 bg-white/5">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between gap-3 border-b border-gray-700/40 pb-2 last:border-b-0 ${selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''}`}
                            >
                                <div>
                                    <div className="font-medium">Run #{run.id} - {run.status}</div>
                                    <div className="text-xs text-gray-400">
                                        Created: {formatTimestamp(run.created_at)}
                                        {run.finished_at && <> · Finished: {formatTimestamp(run.finished_at)}</>}
                                    </div>
                                    {run.summary && <div className="text-xs text-gray-300">{run.summary}</div>}
                                    {run.error && <div className="text-xs text-rose-300">Error: {run.error}</div>}
                                </div>
                                <button
                                    onClick={() => setSelectedRunId(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering}
                                >
                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Selected Run Report</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a run to inspect its report and audit history.</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {reportError && <div className="text-sm text-amber-300">{reportError}</div>}
                {reportLoading ? (
                    <div className="text-sm text-gray-400">Loading Daily Market Scan report...</div>
                ) : selectedRunId === null ? null : selectedReport ? (
                    renderReport(selectedReport, `Selected run #${selectedRunId}`)
                ) : (
                    <div className="text-sm text-gray-500">Structured report is unavailable for this run.</div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Selected Run Audit History</h3>
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => (
                            <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{log.action}</div>
                                    <div className="text-xs text-gray-400">
                                        {formatTimestamp(log.created_at)}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400 mt-0.5">
                                    Actor: {log.actor_type}
                                </div>
                                <div className="mt-2 text-xs text-gray-300">
                                    {summarizeAuditDetails(log.action, log.details)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
};

export default DailyMarketScanPanel;
