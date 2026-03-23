import axios from 'axios';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    AlertTriangle,
    ChevronRight,
    Clock3,
    Eye,
    FileSearch,
    RefreshCw,
    ShieldCheck,
} from 'lucide-react';
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
} from '../services/agents';
import {
    buildControlRoomHomeView,
    getModuleDetailSupport,
    loadModuleDetail,
} from '../services/openclaw';
import type {
    OpenClawAgentType,
    OpenClawControlRoomHomeView,
    OpenClawModuleCard,
    OpenClawModuleDetailResult,
    OpenClawNeedsInputItem,
} from '../services/openclaw';
import './OpenClawShell.css';

type DetailSelection = {
    agentType: OpenClawAgentType;
    runId?: number | null;
    title: string;
    sourceLabel: string;
};

const formatDateTime = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }

    return parsed.toLocaleString();
};

const getErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
    }
    if (error instanceof Error && error.message.trim()) {
        return error.message;
    }
    return fallback;
};

const statusToneClass = (status?: string | null) => {
    switch (status) {
        case 'completed':
            return 'is-completed';
        case 'failed':
            return 'is-failed';
        case 'waiting_approval':
            return 'is-waiting';
        case 'running':
            return 'is-running';
        default:
            return 'is-neutral';
    }
};

const detailStatusToneClass = (status: OpenClawModuleDetailResult['status']) => {
    switch (status) {
        case 'loaded':
            return 'is-completed';
        case 'partial':
            return 'is-waiting';
        default:
            return 'is-neutral';
    }
};

const renderAuditLogs = (auditLogs: AgentAuditLog[]) => {
    if (auditLogs.length === 0) {
        return <p className="openclaw-empty-text">No audit history loaded for this selection.</p>;
    }

    return (
        <div className="openclaw-audit-list">
            {auditLogs.map((log) => (
                (() => {
                    const extendedLog = log as AgentAuditLog & {
                        details_text?: string | null;
                        details_json?: unknown;
                    };
                    const renderedDetails =
                        extendedLog.details_text ??
                        (extendedLog.details_json !== undefined
                            ? JSON.stringify(extendedLog.details_json, null, 2)
                            : log.details);

                    return (
                        <article key={`${log.id}-${log.created_at}`} className="openclaw-audit-item">
                            <div className="openclaw-audit-meta">
                                <strong>{log.action}</strong>
                                <span>{formatDateTime(log.created_at)}</span>
                            </div>
                            <div className="openclaw-audit-actor">Actor: {log.actor_type}</div>
                            {renderedDetails && (
                                <pre className="openclaw-code-block">{renderedDetails}</pre>
                            )}
                        </article>
                    );
                })()
            ))}
        </div>
    );
};

const renderStringList = (
    title: string,
    items: string[],
) => {
    if (items.length === 0) {
        return null;
    }

    return (
        <section className="openclaw-detail-section">
            <h4>{title}</h4>
            <ul className="openclaw-detail-list">
                {items.map((item, index) => (
                    <li key={`${title}-${index}`}>{item}</li>
                ))}
            </ul>
        </section>
    );
};

const renderFollowUpDetail = (latest?: FollowUpRecommendationsResponse | null) => {
    const recommendations = latest?.recommendations ?? [];
    const drafts = latest?.drafts ?? [];

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Follow-up snapshot</h4>
                <div className="openclaw-stat-grid">
                    <div className="openclaw-mini-stat">
                        <span>Recommendations</span>
                        <strong>{recommendations.length}</strong>
                    </div>
                    <div className="openclaw-mini-stat">
                        <span>Drafts</span>
                        <strong>{drafts.length}</strong>
                    </div>
                    <div className="openclaw-mini-stat">
                        <span>Latest run</span>
                        <strong>{latest?.run_id ?? 'n/a'}</strong>
                    </div>
                </div>
            </section>

            {recommendations.length > 0 && (
                <section className="openclaw-detail-section">
                    <h4>Recommendations</h4>
                    <ul className="openclaw-detail-list">
                        {recommendations.slice(0, 4).map((item, index) => (
                            <li key={`${item.contact_id}-${index}`}>
                                <strong>{item.contact_name || `Contact #${item.contact_id}`}</strong>
                                <span>{item.suggested_action || item.message || 'Manual follow-up review.'}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {drafts.length > 0 && (
                <section className="openclaw-detail-section">
                    <h4>Draft previews</h4>
                    <ul className="openclaw-detail-list">
                        {drafts.slice(0, 3).map((draft) => (
                            <li key={draft.approval_id}>
                                <strong>{draft.subject}</strong>
                                <span>{draft.body}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </>
    );
};

const renderConversationCloserDetail = (
    latest?: ConversationCloserLatestResponse | null,
) => {
    const result = latest?.result;

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Latest conversation review</h4>
                <p>{result?.summary || 'No structured conversation result is available yet.'}</p>
            </section>
            {renderStringList('Talking points', result?.talking_points ?? [])}
            {renderStringList('Risk flags', result?.risk_flags ?? [])}
            {renderStringList('Operator notes', result?.operator_notes ?? [])}
        </>
    );
};

const renderListingDetail = (latest?: ListingCmaLatestResponse | null) => {
    const result = latest?.result;

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Latest listing / CMA summary</h4>
                <p>{result?.listing_brief.summary || 'No structured listing summary is available yet.'}</p>
            </section>
            {renderStringList('Property highlights', result?.listing_brief.property_highlights ?? [])}
            {renderStringList('Comparable narrative', result?.cma_support.comparable_narrative ?? [])}
            {renderStringList('Risk flags', result?.risk_flags ?? [])}
            {renderStringList('Operator notes', result?.operator_notes ?? [])}
        </>
    );
};

const renderBuyerMatchDetail = (latest?: BuyerMatchLatestResponse | null) => {
    const result = latest?.result;

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Latest buyer match framing</h4>
                <p>{result?.shortlist_framing || 'No structured buyer match result is available yet.'}</p>
            </section>
            {result?.recommended_next_manual_action && (
                <section className="openclaw-detail-section">
                    <h4>Recommended next manual action</h4>
                    <p>{result.recommended_next_manual_action}</p>
                </section>
            )}
            {result && result.shortlist.length > 0 && (
                <section className="openclaw-detail-section">
                    <h4>Shortlist</h4>
                    <ul className="openclaw-detail-list">
                        {result.shortlist.slice(0, 4).map((item) => (
                            <li key={`${item.rank}-${item.title}`}>
                                <strong>{item.title}</strong>
                                <span>{item.match_strength}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            {renderStringList('Risk flags', result?.risk_flags ?? [])}
            {renderStringList('Operator notes', result?.operator_notes ?? [])}
        </>
    );
};

const renderStrategyDetail = (
    latest?: StrategyCoordinationLatestResponse | null,
    report?: StrategyCoordinationResultResponse | null,
) => {
    const result = report ?? latest?.result ?? null;

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Latest strategy synthesis</h4>
                <p>{result?.strategy_synthesis.summary || 'No structured strategy report is available yet.'}</p>
            </section>
            {renderStringList('Key takeaways', result?.strategy_synthesis.key_takeaways ?? [])}
            {renderStringList('Human review actions', result?.recommended_next_actions.human_review_actions ?? [])}
            {renderStringList('Internal actions', result?.recommended_next_actions.internal_actions ?? [])}
            {renderStringList('Risk flags', result?.risk_flags ?? [])}
            {renderStringList('Operator notes', result?.operator_notes ?? [])}
        </>
    );
};

const renderDailyMarketScanDetail = (
    latest?: DailyMarketScanLatestResponse | null,
    report?: DailyMarketScanResultResponse | null,
) => {
    const result = report ?? latest?.result ?? null;
    const providerOrder = result?.scan_summary.provider_order.join(' -> ') ?? '';

    return (
        <>
            <section className="openclaw-detail-section">
                <h4>Latest market scan summary</h4>
                <div className="openclaw-stat-grid">
                    <div className="openclaw-mini-stat">
                        <span>Mode</span>
                        <strong>{result?.scan_summary.scan_mode || 'n/a'}</strong>
                    </div>
                    <div className="openclaw-mini-stat">
                        <span>Client scans</span>
                        <strong>{result?.client_match_scans.length ?? 0}</strong>
                    </div>
                    <div className="openclaw-mini-stat">
                        <span>Competitor scans</span>
                        <strong>{result?.competitor_watch_scans.length ?? 0}</strong>
                    </div>
                </div>
                {providerOrder && <p className="openclaw-detail-meta">Provider order: {providerOrder}</p>}
            </section>
            {result && result.client_match_scans.length > 0 && (
                <section className="openclaw-detail-section">
                    <h4>Client match workflows</h4>
                    <ul className="openclaw-detail-list">
                        {result.client_match_scans.slice(0, 4).map((scan) => (
                            <li key={`client-${scan.contact_id}`}>
                                <strong>Contact #{scan.contact_id}</strong>
                                <span>{scan.status}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            {result && result.competitor_watch_scans.length > 0 && (
                <section className="openclaw-detail-section">
                    <h4>Competitor watch workflows</h4>
                    <ul className="openclaw-detail-list">
                        {result.competitor_watch_scans.slice(0, 4).map((scan, index) => (
                            <li key={`competitor-${index}`}>
                                <strong>{scan.subject.listing_ref || `Workflow ${index + 1}`}</strong>
                                <span>{scan.status}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            {renderStringList('Risk flags', result?.risk_flags ?? [])}
            {renderStringList('Operator notes', result?.operator_notes ?? [])}
        </>
    );
};

const renderDetailContent = (detail: OpenClawModuleDetailResult | null) => {
    if (!detail) {
        return (
            <div className="openclaw-detail-empty">
                <Eye size={18} />
                <p>Select a queue item or module card to inspect its read-only detail.</p>
            </div>
        );
    }

    switch (detail.agent_type) {
        case 'follow_up':
            return renderFollowUpDetail(detail.latest as FollowUpRecommendationsResponse | null | undefined);
        case 'conversation_closer':
            return renderConversationCloserDetail(
                detail.latest as ConversationCloserLatestResponse | null | undefined,
            );
        case 'listing_cma':
            return renderListingDetail(detail.latest as ListingCmaLatestResponse | null | undefined);
        case 'buyer_match':
            return renderBuyerMatchDetail(detail.latest as BuyerMatchLatestResponse | null | undefined);
        case 'strategy_coordination':
            return renderStrategyDetail(
                detail.latest as StrategyCoordinationLatestResponse | null | undefined,
                detail.report as StrategyCoordinationResultResponse | null | undefined,
            );
        case 'daily_market_scan':
            return renderDailyMarketScanDetail(
                detail.latest as DailyMarketScanLatestResponse | null | undefined,
                detail.report as DailyMarketScanResultResponse | null | undefined,
            );
        default:
            return (
                <section className="openclaw-detail-section">
                    <h4>Read-only detail</h4>
                    <pre className="openclaw-code-block">{JSON.stringify(detail, null, 2)}</pre>
                </section>
            );
    }
};

const renderNeedsInputItem = (
    item: OpenClawNeedsInputItem,
    onInspect: (selection: DetailSelection) => void,
) => {
    const inspectable = item.run_id !== null && item.run_id !== undefined;

    return (
        <article key={`${item.kind}-${item.created_at}-${item.title}`} className="openclaw-feed-item">
            <div className="openclaw-feed-copy">
                <div className="openclaw-feed-title-row">
                    <strong>{item.title}</strong>
                    <span className={`openclaw-status-pill ${statusToneClass(item.kind === 'failed_run' ? 'failed' : 'waiting_approval')}`}>
                        {item.kind}
                    </span>
                </div>
                <p>{item.summary}</p>
                <span className="openclaw-feed-meta">{formatDateTime(item.created_at)}</span>
            </div>
            <button
                type="button"
                className="openclaw-inline-button"
                onClick={() => onInspect({
                    agentType: item.agent_type,
                    runId: item.run_id,
                    title: item.title,
                    sourceLabel: 'Needs input',
                })}
                disabled={!inspectable}
            >
                Inspect <ChevronRight size={14} />
            </button>
        </article>
    );
};

const renderApprovalItem = (
    approval: AgentOpsApprovalItem,
    onInspect: (selection: DetailSelection) => void,
) => {
    return (
        <article key={approval.approval_id} className="openclaw-feed-item">
            <div className="openclaw-feed-copy">
                <div className="openclaw-feed-title-row">
                    <strong>{approval.preview.title || approval.action_type}</strong>
                    <span className={`openclaw-status-pill ${statusToneClass(approval.run_status)}`}>
                        {approval.run_status}
                    </span>
                </div>
                <p>{approval.preview.subject || approval.preview.body_excerpt || approval.run_summary || 'Pending manual review.'}</p>
                <span className="openclaw-feed-meta">
                    Approval #{approval.approval_id} · {formatDateTime(approval.created_at)}
                </span>
            </div>
            <button
                type="button"
                className="openclaw-inline-button"
                onClick={() => onInspect({
                    agentType: approval.agent_type as OpenClawAgentType,
                    runId: approval.run_id,
                    title: `Approval #${approval.approval_id}`,
                    sourceLabel: 'Pending approvals',
                })}
            >
                Inspect <ChevronRight size={14} />
            </button>
        </article>
    );
};

const renderRunItem = (
    run: AgentOpsRunItem,
    label: string,
    onInspect: (selection: DetailSelection) => void,
) => {
    return (
        <article key={`${label}-${run.run_id}`} className="openclaw-feed-item">
            <div className="openclaw-feed-copy">
                <div className="openclaw-feed-title-row">
                    <strong>{run.summary || `${run.agent_type} run #${run.run_id}`}</strong>
                    <span className={`openclaw-status-pill ${statusToneClass(run.status)}`}>
                        {run.status}
                    </span>
                </div>
                <p>{run.error || run.summary || 'No additional summary.'}</p>
                <span className="openclaw-feed-meta">
                    Run #{run.run_id} · {formatDateTime(run.created_at)}
                </span>
            </div>
            <button
                type="button"
                className="openclaw-inline-button"
                onClick={() => onInspect({
                    agentType: run.agent_type as OpenClawAgentType,
                    runId: run.run_id,
                    title: `${run.agent_type} run #${run.run_id}`,
                    sourceLabel: label,
                })}
            >
                Inspect <ChevronRight size={14} />
            </button>
        </article>
    );
};

const OpenClawShell = () => {
    const [homeView, setHomeView] = useState<OpenClawControlRoomHomeView | null>(null);
    const [selection, setSelection] = useState<DetailSelection | null>(null);
    const [detail, setDetail] = useState<OpenClawModuleDetailResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [detailLoading, setDetailLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);

    const loadDetailForSelection = async (nextSelection: DetailSelection) => {
        setSelection(nextSelection);
        setDetailLoading(true);
        setDetailError(null);

        try {
            const nextDetail = await loadModuleDetail(nextSelection.agentType, nextSelection.runId);
            setDetail(nextDetail);
        } catch (detailLoadError) {
            setDetail(null);
            setDetailError(getErrorMessage(detailLoadError, 'Read-only detail is unavailable.'));
        } finally {
            setDetailLoading(false);
        }
    };

    const loadShell = async (mode: 'initial' | 'manual' = 'manual') => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }

        setError(null);

        try {
            const nextHomeView = await buildControlRoomHomeView();
            setHomeView(nextHomeView);
            setLastRefreshedAt(new Date().toISOString());

            if (selection) {
                void loadDetailForSelection(selection);
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load the OpenClaw control-room snapshot.'));
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    useEffect(() => {
        void loadShell('initial');
        // Manual refresh only for Phase 1.
    }, []);

    const handleInspectCard = (card: OpenClawModuleCard) => {
        void loadDetailForSelection({
            agentType: card.agent_type,
            runId: card.latest_run_id,
            title: card.label,
            sourceLabel: 'Module cards',
        });
    };

    const handleInspectSelection = (nextSelection: DetailSelection) => {
        void loadDetailForSelection(nextSelection);
    };

    const isBusy = loading || refreshing;
    const snapshot = homeView?.snapshot ?? null;

    return (
        <div className="openclaw-shell">
            <header className="openclaw-hero">
                <div>
                    <div className="openclaw-kicker">OpenClaw Phase 1</div>
                    <h1>Read-only operator shell</h1>
                    <p>
                        Company inbox for SKC Agent OS. This prototype consumes the approved control-room
                        snapshot and read-only drill-down routes only.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Link to="/agents/workbench" className="btn btn-ghost">
                        Open workbench
                    </Link>
                    <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => void loadShell()}
                        disabled={isBusy}
                    >
                        <RefreshCw size={16} className={refreshing ? 'openclaw-spin' : ''} />
                        {refreshing ? 'Refreshing' : 'Manual refresh'}
                    </button>
                </div>
            </header>

            {error && (
                <div className="openclaw-banner openclaw-banner-error">
                    <AlertTriangle size={16} />
                    <span>{error}</span>
                </div>
            )}

            {loading ? (
                <div className="glass-panel openclaw-loading-panel">
                    <RefreshCw size={18} className="openclaw-spin" />
                    <span>Loading the OpenClaw control room...</span>
                </div>
            ) : snapshot ? (
                <>
                    <section className="glass-panel openclaw-guardrail-strip">
                        <div className="openclaw-guardrail-header">
                            <div>
                                <h2>Guardrails</h2>
                                <p>Read-only only. SKC remains truth for approvals, audit, and business logic.</p>
                            </div>
                            <div className="openclaw-staleness">
                                <div><Clock3 size={14} /> Snapshot as of {formatDateTime(snapshot.as_of)}</div>
                                <div><RefreshCw size={14} /> Last refreshed {formatDateTime(lastRefreshedAt)}</div>
                            </div>
                        </div>
                        <div className="openclaw-chip-row">
                            <span className="openclaw-guardrail-chip"><ShieldCheck size={14} /> Read-only</span>
                            {snapshot.guardrails.no_send && <span className="openclaw-guardrail-chip">No send</span>}
                            {snapshot.guardrails.no_crm_mutation && <span className="openclaw-guardrail-chip">No CRM mutation</span>}
                            {snapshot.guardrails.approvals_truth_in_skc && <span className="openclaw-guardrail-chip">Approvals truth in SKC</span>}
                            {snapshot.guardrails.audit_truth_in_skc && <span className="openclaw-guardrail-chip">Audit truth in SKC</span>}
                        </div>
                    </section>

                    <div className="openclaw-layout">
                        <div className="openclaw-primary-column">
                            <section className="glass-panel openclaw-panel">
                                <div className="openclaw-section-header">
                                    <div>
                                        <h3>Needs input today</h3>
                                        <p>Conservative unresolved-state queue from SKC.</p>
                                    </div>
                                    <span className="openclaw-count-pill">{snapshot.needs_input_today.length}</span>
                                </div>
                                {snapshot.needs_input_today.length === 0 ? (
                                    <p className="openclaw-empty-text">No explicit unresolved items are waiting right now.</p>
                                ) : (
                                    <div className="openclaw-feed-list">
                                        {snapshot.needs_input_today.map((item) => renderNeedsInputItem(item, handleInspectSelection))}
                                    </div>
                                )}
                            </section>

                            <div className="openclaw-two-up">
                                <section className="glass-panel openclaw-panel">
                                    <div className="openclaw-section-header">
                                        <div>
                                            <h3>Pending approvals</h3>
                                            <p>Preview-only. No approve or reject controls exist here.</p>
                                        </div>
                                        <span className="openclaw-count-pill">{snapshot.pending_approvals.length}</span>
                                    </div>
                                    {snapshot.pending_approvals.length === 0 ? (
                                        <p className="openclaw-empty-text">No pending approvals.</p>
                                    ) : (
                                        <div className="openclaw-feed-list">
                                            {snapshot.pending_approvals.map((approval) => renderApprovalItem(approval, handleInspectSelection))}
                                        </div>
                                    )}
                                </section>

                                <section className="glass-panel openclaw-panel">
                                    <div className="openclaw-section-header">
                                        <div>
                                            <h3>Recent failures</h3>
                                            <p>Read-only visibility into failed runs and their audit trails.</p>
                                        </div>
                                        <span className="openclaw-count-pill">{snapshot.recent_failures.length}</span>
                                    </div>
                                    {snapshot.recent_failures.length === 0 ? (
                                        <p className="openclaw-empty-text">No recent failures.</p>
                                    ) : (
                                        <div className="openclaw-feed-list">
                                            {snapshot.recent_failures.map((run) => renderRunItem(run, 'Recent failures', handleInspectSelection))}
                                        </div>
                                    )}
                                </section>
                            </div>

                            <section className="glass-panel openclaw-panel">
                                <div className="openclaw-section-header">
                                    <div>
                                        <h3>Recent runs</h3>
                                        <p>Latest company activity across the approved Phase 1 modules.</p>
                                    </div>
                                    <span className="openclaw-count-pill">{snapshot.recent_runs.length}</span>
                                </div>
                                {snapshot.recent_runs.length === 0 ? (
                                    <p className="openclaw-empty-text">No recent runs yet.</p>
                                ) : (
                                    <div className="openclaw-feed-list">
                                        {snapshot.recent_runs.map((run) => renderRunItem(run, 'Recent runs', handleInspectSelection))}
                                    </div>
                                )}
                            </section>

                            <section className="glass-panel openclaw-panel">
                                <div className="openclaw-section-header">
                                    <div>
                                        <h3>Modules</h3>
                                        <p>Read-only cards for the current state of each approved OpenClaw Phase 1 module.</p>
                                    </div>
                                    <span className="openclaw-count-pill">{homeView?.modules.length ?? 0}</span>
                                </div>
                                <div className="openclaw-module-grid">
                                    {homeView?.modules.map(({ card, detail_support }) => (
                                        <button
                                            type="button"
                                            key={card.agent_type}
                                            className="openclaw-module-card"
                                            onClick={() => handleInspectCard(card)}
                                        >
                                            <div className="openclaw-module-card-header">
                                                <div>
                                                    <span className="openclaw-module-label">{card.label}</span>
                                                    <div className={`openclaw-status-pill ${statusToneClass(card.latest_run_status)}`}>
                                                        {card.latest_run_status || 'no run'}
                                                    </div>
                                                </div>
                                                <span className={`openclaw-depth-pill ${detail_support.depth}`}>
                                                    {detail_support.depth}
                                                </span>
                                            </div>
                                            <p className="openclaw-module-summary">
                                                {card.summary || 'No structured summary is available yet.'}
                                            </p>
                                            <div className="openclaw-module-meta">
                                                <span>Run {card.latest_run_id ?? 'n/a'}</span>
                                                <span>{card.pending_approvals} approval(s)</span>
                                            </div>
                                            {card.highlights.length > 0 && (
                                                <ul className="openclaw-card-list">
                                                    {card.highlights.slice(0, 3).map((item, index) => (
                                                        <li key={`${card.agent_type}-highlight-${index}`}>{item}</li>
                                                    ))}
                                                </ul>
                                            )}
                                            {card.risk_flags.length > 0 && (
                                                <div className="openclaw-tag-row">
                                                    {card.risk_flags.slice(0, 3).map((flag) => (
                                                        <span key={flag} className="openclaw-tag risk">{flag}</span>
                                                    ))}
                                                </div>
                                            )}
                                        </button>
                                    ))}
                                </div>
                            </section>
                        </div>

                        <aside className="glass-panel openclaw-detail-pane">
                            <div className="openclaw-detail-header">
                                <div>
                                    <div className="openclaw-kicker">Detail drawer</div>
                                    <h3>{selection?.title || 'Read-only detail'}</h3>
                                    <p>{selection ? `${selection.sourceLabel} · ${getModuleDetailSupport(selection.agentType, selection.runId).label}` : 'Select any queue item or module card to inspect it.'}</p>
                                </div>
                                {detail && (
                                    <div className={`openclaw-status-pill ${detailStatusToneClass(detail.status)}`}>
                                        {detail.status}
                                    </div>
                                )}
                            </div>

                            {detailError && (
                                <div className="openclaw-banner openclaw-banner-warning">
                                    <AlertTriangle size={16} />
                                    <span>{detailError}</span>
                                </div>
                            )}

                            {detailLoading ? (
                                <div className="openclaw-detail-empty">
                                    <FileSearch size={18} />
                                    <p>Loading read-only detail...</p>
                                </div>
                            ) : (
                                <>
                                    {detail && (
                                        <>
                                            <div className="openclaw-detail-summary-bar">
                                                <span className={`openclaw-depth-pill ${detail.depth}`}>{detail.depth}</span>
                                                <span>{detail.routes_used.length} GET route(s)</span>
                                                <span>{detail.audit_logs.length} audit log(s)</span>
                                            </div>

                                            {getModuleDetailSupport(detail.agent_type, selection?.runId).notes.length > 0 && (
                                                <div className="openclaw-note-stack">
                                                    {getModuleDetailSupport(detail.agent_type, selection?.runId).notes.map((note) => (
                                                        <div key={note} className="openclaw-note">
                                                            {note}
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </>
                                    )}

                                    {renderDetailContent(detail)}

                                    {detail && detail.errors.length > 0 && (
                                        <section className="openclaw-detail-section">
                                            <h4>Fail-soft detail notes</h4>
                                            <ul className="openclaw-detail-list">
                                                {detail.errors.map((item) => (
                                                    <li key={item}>{item}</li>
                                                ))}
                                            </ul>
                                        </section>
                                    )}

                                    <section className="openclaw-detail-section">
                                        <h4>Audit logs</h4>
                                        {detail ? renderAuditLogs(detail.audit_logs) : <p className="openclaw-empty-text">Select a module or queue item to load audit history.</p>}
                                    </section>
                                </>
                            )}
                        </aside>
                    </div>
                </>
            ) : (
                <div className="glass-panel openclaw-loading-panel">
                    <AlertTriangle size={18} />
                    <span>The OpenClaw shell did not receive a control-room snapshot.</span>
                </div>
            )}
        </div>
    );
};

export default OpenClawShell;
