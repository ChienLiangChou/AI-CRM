import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import { getApiErrorMessage } from '../../services/httpErrors';
import type {
    AgentAuditLog,
    AgentRun,
    EventStrategyReviewClusteredSource,
    EventStrategyReviewExecutionResult,
    EventStrategyReviewLatestResponse,
    EventStrategyReviewOutputMode,
    EventStrategyReviewPackageArtifact,
    EventStrategyReviewPackageLatestResponse,
    EventStrategyReviewPackageRequest,
    EventStrategyReviewPerspectiveBlock,
    EventStrategyReviewRetrievalMetadata,
    EventStrategyReviewReportResponse,
    EventStrategyReviewRunRequest,
    EventStrategyReviewSourceMode,
    EventStrategyReviewUrlSourceInput,
} from '../../services/agents';

const EMPTY_LATEST: EventStrategyReviewLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

const EMPTY_PACKAGE_LATEST = (sourceRunId: number): EventStrategyReviewPackageLatestResponse => ({
    source_run_id: sourceRunId,
    package_run_id: null,
    status: null,
    error: null,
    result: null,
});

const OUTPUT_MODE_LABELS: Record<EventStrategyReviewOutputMode, string> = {
    internal_report_only: 'Internal report only',
    html_report_package: 'HTML report package',
    social_post_draft_pack: 'Social post draft pack',
    email_newsletter_draft_pack: 'Email/newsletter draft pack',
    client_summary_draft_pack: 'Client summary draft pack',
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

const parseTextList = (value: string) => {
    const seen = new Set<string>();
    return value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean)
        .filter((item) => {
            const key = item.toLowerCase();
            if (seen.has(key)) {
                return false;
            }
            seen.add(key);
            return true;
        });
};

const parseUrlBundleLines = (value: string): EventStrategyReviewUrlSourceInput[] => {
    return value
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const [urlRaw, titleRaw, publisherRaw, publishedAtRaw] = line
                .split('|')
                .map((item) => item?.trim());
            const url = urlRaw || '';
            if (!url) {
                return null;
            }

            return {
                url,
                title: titleRaw || undefined,
                publisher: publisherRaw || undefined,
                published_at: publishedAtRaw || undefined,
            };
        })
        .filter(Boolean) as EventStrategyReviewUrlSourceInput[];
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

const formatBytes = (value?: number | null) => {
    if (typeof value !== 'number' || value <= 0) {
        return 'n/a';
    }
    if (value < 1024) {
        return `${value} B`;
    }
    if (value < 1024 * 1024) {
        return `${(value / 1024).toFixed(1)} KB`;
    }
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

const humanizeEnum = (value: string) =>
    value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');

const joinList = (items: string[], fallback = 'none') => (items.length > 0 ? items.join(' | ') : fallback);

const getRetrievalStateLabel = (metadata: EventStrategyReviewRetrievalMetadata) =>
    humanizeEnum(metadata.retrieval_state);

const getExecutionStateMessage = (executionResult: EventStrategyReviewExecutionResult) => {
    switch (executionResult.execution_status) {
        case 'retrieval_unavailable':
            return 'No structured report was generated because controlled curated retrieval was unavailable for this run.';
        case 'rate_limited':
            return 'No structured report was generated because the constrained retrieval provider was rate limited for this run.';
        case 'no_credible_sources':
            return 'No structured report was generated because the curated retrieval results did not yield enough credible sources after trust filtering.';
        case 'not_active_yet':
            return executionResult.source_mode === 'curated_search_query'
                ? 'Curated search query was accepted, but this run remained non-active and did not generate a structured report.'
                : 'No structured report was generated for this run.';
        default:
            return 'No structured report was generated for this run.';
    }
};

const summarizeTrustCoverage = (sources: EventStrategyReviewClusteredSource[]) => {
    const counts = sources.reduce<Record<string, number>>((accumulator, source) => {
        if (!source.trust_tier) {
            return accumulator;
        }
        accumulator[source.trust_tier] = (accumulator[source.trust_tier] ?? 0) + 1;
        return accumulator;
    }, {});

    const orderedTiers = [
        'tier_1_primary',
        'tier_2_reputable',
        'tier_3_trade',
        'untrusted',
    ] as const;

    const summary = orderedTiers
        .filter((tier) => counts[tier] > 0)
        .map((tier) => `${humanizeEnum(tier)}: ${counts[tier]}`);

    return summary.length > 0 ? summary.join(' | ') : 'No trust-tier summary available.';
};

const renderSourceList = (sources: EventStrategyReviewClusteredSource[]) => {
    if (sources.length === 0) {
        return <div className="text-sm text-gray-500">No source citations recorded.</div>;
    }

    return (
        <div className="space-y-3">
            {sources.map((source, index) => (
                <div
                    key={`${source.url ?? source.title ?? source.source_label ?? 'source'}-${index}`}
                    className="rounded border border-white/10 bg-black/10 p-3 space-y-1 text-sm"
                >
                    <div className="flex items-start justify-between gap-3">
                        <div className="font-medium">{source.title || source.source_label || 'Source'}</div>
                        {source.trust_tier && (
                            <div className="rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-gray-200">
                                {humanizeEnum(source.trust_tier)}
                            </div>
                        )}
                    </div>
                    <div className="text-xs text-gray-400">
                        Domain: {source.source_domain || 'n/a'} · Publisher: {source.publisher || 'n/a'}
                    </div>
                    <div className="text-xs text-gray-400">
                        Published: {formatTimestamp(source.published_at)} · Observed:{' '}
                        {formatTimestamp(source.observed_at)}
                    </div>
                    {source.url && (
                        <div className="text-xs text-sky-200 break-all">
                            {source.url}
                        </div>
                    )}
                    {source.notes.length > 0 && (
                        <div className="text-xs text-gray-300">{source.notes.join(' | ')}</div>
                    )}
                </div>
            ))}
        </div>
    );
};

const perspectiveEntries = (
    report: EventStrategyReviewReportResponse,
): Array<[string, EventStrategyReviewPerspectiveBlock]> => [
    ['follow_up', report.perspective_blocks.follow_up],
    ['conversation_retention', report.perspective_blocks.conversation_retention],
    ['listing_seller', report.perspective_blocks.listing_seller],
    ['cma_market', report.perspective_blocks.cma_market],
    ['ops_compliance', report.perspective_blocks.ops_compliance],
    ['buyer_renter', report.perspective_blocks.buyer_renter],
];

const renderArtifactList = (artifacts: EventStrategyReviewPackageArtifact[]) => {
    if (artifacts.length === 0) {
        return <div className="text-sm text-gray-500">No package artifacts recorded.</div>;
    }

    return (
        <div className="space-y-3">
            {artifacts.map((artifact, index) => (
                <div
                    key={`${artifact.file_name ?? artifact.label ?? artifact.path ?? 'artifact'}-${index}`}
                    className="rounded border border-white/10 bg-black/10 p-3 space-y-1 text-sm"
                >
                    <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">
                            {artifact.label || artifact.file_name || 'Artifact'}
                        </div>
                        {artifact.is_entrypoint && (
                            <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-100">
                                entrypoint
                            </div>
                        )}
                    </div>
                    <div className="text-xs text-gray-400">
                        Type: {humanizeEnum(artifact.artifact_type)} · Content:{' '}
                        {artifact.content_type || 'n/a'} · Size: {formatBytes(artifact.file_size_bytes)}
                    </div>
                    {artifact.file_name && (
                        <div className="text-xs text-gray-300">File: {artifact.file_name}</div>
                    )}
                    {artifact.path && (
                        <div className="text-xs text-gray-400 break-all">Path: {artifact.path}</div>
                    )}
                    {artifact.checksum_sha256 && (
                        <div className="text-xs text-gray-400 break-all">
                            SHA-256: {artifact.checksum_sha256}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
};

const renderReport = (executionResult: EventStrategyReviewExecutionResult | null) => {
    if (!executionResult) {
        return <div className="text-sm text-gray-500">No structured report available for this run.</div>;
    }

    const retrievalMetadata = executionResult.execution_plan.retrieval_metadata;
    const report = executionResult.report;

    if (executionResult.execution_status !== 'report_generated' || !report) {
        return (
            <div className="border rounded p-3 bg-white/5 space-y-2 text-sm">
                <div className="font-medium">Execution state: {humanizeEnum(executionResult.execution_status)}</div>
                <div className="text-xs text-gray-400">
                    Retrieval state: {getRetrievalStateLabel(retrievalMetadata)} · Execution path:{' '}
                    {humanizeEnum(executionResult.execution_plan.execution_path)}
                </div>
                <div className="text-gray-300">{getExecutionStateMessage(executionResult)}</div>
                {executionResult.inactive_reason && (
                    <div className="text-gray-300">{executionResult.inactive_reason}</div>
                )}
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Retrieval Summary
                        </div>
                        <div>Raw candidates: {retrievalMetadata.raw_candidate_count} / {retrievalMetadata.raw_candidate_cap}</div>
                        <div>Fetched sources: {retrievalMetadata.fetched_source_count} / {retrievalMetadata.fetched_source_cap}</div>
                        <div>Independent sources: {retrievalMetadata.independent_source_count}</div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Trust Policy
                        </div>
                        <div>Adapter: {retrievalMetadata.adapter_key || 'none'}</div>
                        <div>
                            Tier 1 / 2 support:{' '}
                            {retrievalMetadata.has_tier_one_or_two_support ? 'present' : 'not present'}
                        </div>
                        <div>
                            Allowed domains:{' '}
                            {joinList(retrievalMetadata.allowed_domains_applied, retrievalMetadata.default_trusted_domain_policy_applied
                                ? 'default trusted-domain policy'
                                : 'none')}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Source Mode
                        </div>
                        <div>{humanizeEnum(executionResult.source_mode)}</div>
                        <div>Deduped sources: {executionResult.execution_plan.deduped_source_count}</div>
                        <div>Duplicates collapsed: {executionResult.execution_plan.duplicate_source_count}</div>
                    </div>
                </div>
                {retrievalMetadata.notes.length > 0 && (
                    <div className="space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Retrieval Notes
                        </div>
                        {retrievalMetadata.notes.map((note, index) => (
                            <div key={`${note}-${index}`} className="text-xs text-gray-300">
                                {note}
                            </div>
                        ))}
                    </div>
                )}
                {executionResult.operator_notes.length > 0 && (
                    <div className="space-y-1">
                        {executionResult.operator_notes.map((note, index) => (
                            <div key={`${note}-${index}`} className="text-xs text-gray-300">
                                {note}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    const scores = report.score_breakdown;

    return (
        <div className="border rounded p-3 bg-white/5 space-y-4 text-sm">
            <div className="space-y-1">
                <div className="font-medium">{report.report_title}</div>
                <div className="text-xs text-gray-400">
                    Source mode: {humanizeEnum(report.retrieval_contract.source_mode)} · Execution path:{' '}
                    {humanizeEnum(executionResult.execution_plan.execution_path)}
                </div>
                <div className="text-xs text-gray-400">
                    Execution status: {humanizeEnum(executionResult.execution_status)} · Retrieval state:{' '}
                    {getRetrievalStateLabel(retrievalMetadata)}
                </div>
                <div className="text-xs text-gray-400">
                    Event cluster: {report.event_cluster.canonical_event_title}
                </div>
                <div className="text-gray-200">{report.event_cluster.canonical_summary}</div>
            </div>

            {retrievalMetadata.retrieval_state === 'low_confidence_watchlist' && (
                <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                    This report was generated from a low-confidence curated retrieval result and should be treated as watchlist-grade internal intelligence, not a strong confirmed event package.
                </div>
            )}

            {retrievalMetadata.retrieval_state === 'successful_retrieval' && (
                <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
                    Controlled curated retrieval completed successfully and produced a structured report from the stored source cluster.
                </div>
            )}

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Importance
                    </div>
                    <div className="font-medium">
                        {humanizeEnum(report.importance_assessment.classification)}
                    </div>
                    <div className="text-xs text-gray-400">
                        Confidence: {report.importance_assessment.confidence.toFixed(2)}
                    </div>
                    <div className="text-xs text-gray-300">{report.importance_assessment.reason}</div>
                </div>
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Score Breakdown
                    </div>
                    <div>Total: {scores.total_score.toFixed(1)}</div>
                    <div className="text-xs text-gray-400">
                        Relevance {scores.relevance_score.toFixed(1)} · Geography {scores.geography_score.toFixed(1)}
                    </div>
                    <div className="text-xs text-gray-400">
                        Recency {scores.recency_score.toFixed(1)} · Credibility {scores.source_credibility_score.toFixed(1)}
                    </div>
                    <div className="text-xs text-gray-400">
                        Cluster {scores.cluster_strength_score.toFixed(1)} · Usefulness {scores.operator_usefulness_score.toFixed(1)}
                    </div>
                </div>
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Source Cluster
                    </div>
                    <div>Sources: {report.event_cluster.source_count}</div>
                    <div>Duplicates collapsed: {report.event_cluster.duplicate_count}</div>
                    <div>Cluster strength: {report.event_cluster.cluster_strength}</div>
                    <div>Independent sources: {retrievalMetadata.independent_source_count}</div>
                </div>
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Affected Entities
                    </div>
                    <div>Geographies: {report.affected_entities.geographies.join(' | ') || 'none'}</div>
                    <div>Market segments: {report.affected_entities.market_segments.join(' | ') || 'none'}</div>
                    <div>Business functions: {report.affected_entities.business_functions.join(' | ') || 'none'}</div>
                </div>
            </div>

            {(executionResult.source_mode === 'curated_search_query' ||
                retrievalMetadata.retrieval_state !== 'not_requested') && (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Retrieval Summary
                        </div>
                        <div>Adapter: {retrievalMetadata.adapter_key || 'none'}</div>
                        <div>
                            Raw candidates: {retrievalMetadata.raw_candidate_count} / {retrievalMetadata.raw_candidate_cap}
                        </div>
                        <div>
                            Fetched sources: {retrievalMetadata.fetched_source_count} / {retrievalMetadata.fetched_source_cap}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Trust Coverage
                        </div>
                        <div>
                            Tier 1 / 2 support:{' '}
                            {retrievalMetadata.has_tier_one_or_two_support ? 'present' : 'not present'}
                        </div>
                        <div className="text-xs text-gray-400">
                            {summarizeTrustCoverage(report.event_cluster.sources)}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Domain Policy
                        </div>
                        <div>
                            {joinList(
                                retrievalMetadata.allowed_domains_applied,
                                retrievalMetadata.default_trusted_domain_policy_applied
                                    ? 'Default trusted-domain policy'
                                    : 'No explicit domains recorded',
                            )}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Deduping
                        </div>
                        <div>Deduped sources: {executionResult.execution_plan.deduped_source_count}</div>
                        <div>Duplicates collapsed: {executionResult.execution_plan.duplicate_source_count}</div>
                    </div>
                </div>
            )}

            {(report.event_cluster.taxonomy_tags.length > 0 || report.event_cluster.geography_tags.length > 0) && (
                <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Taxonomy Tags
                        </div>
                        <div className="text-gray-300">
                            {report.event_cluster.taxonomy_tags.length > 0
                                ? report.event_cluster.taxonomy_tags.join(' | ')
                                : 'No taxonomy tags.'}
                        </div>
                    </div>
                    <div className="space-y-1">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Geo Focus
                        </div>
                        <div className="text-gray-300">
                            {report.event_cluster.geography_tags.length > 0
                                ? report.event_cluster.geography_tags.join(' | ')
                                : 'No geography tags.'}
                        </div>
                    </div>
                </div>
            )}

            {report.affected_entities.notes.length > 0 && (
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Affected Entity Notes
                    </div>
                    {report.affected_entities.notes.map((note, index) => (
                        <div key={`${note}-${index}`} className="text-xs text-gray-300">
                            {note}
                        </div>
                    ))}
                </div>
            )}

            {(report.event_cluster.retrieval_notes.length > 0 || retrievalMetadata.notes.length > 0) && (
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        Retrieval Notes
                    </div>
                    {[...report.event_cluster.retrieval_notes, ...retrievalMetadata.notes].map((note, index) => (
                        <div key={`${note}-${index}`} className="text-xs text-gray-300">
                            {note}
                        </div>
                    ))}
                </div>
            )}

            <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    Citations / Source List
                </div>
                {renderSourceList(report.event_cluster.sources)}
            </div>

            <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    Perspective Blocks
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {perspectiveEntries(report).map(([key, block]) => (
                        <div key={key} className="rounded border border-white/10 bg-black/10 p-3 space-y-2">
                            <div className="flex items-center justify-between gap-3">
                                <div className="font-medium">{humanizeEnum(key)}</div>
                                <div className="text-xs text-gray-400">
                                    {humanizeEnum(block.status)}
                                </div>
                            </div>
                            <div>{block.summary}</div>
                            <div className="space-y-1">
                                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Why It Matters
                                </div>
                                {block.why_it_matters.length === 0 ? (
                                    <div className="text-xs text-gray-500">No entries.</div>
                                ) : (
                                    block.why_it_matters.map((item, index) => (
                                        <div key={`${key}-matter-${index}`} className="text-xs text-gray-300">
                                            {item}
                                        </div>
                                    ))
                                )}
                            </div>
                            <div className="space-y-1">
                                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Business Implications
                                </div>
                                {block.business_implications.length === 0 ? (
                                    <div className="text-xs text-gray-500">No entries.</div>
                                ) : (
                                    block.business_implications.map((item, index) => (
                                        <div key={`${key}-implication-${index}`} className="text-xs text-gray-300">
                                            {item}
                                        </div>
                                    ))
                                )}
                            </div>
                            <div className="space-y-1">
                                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Internal Actions
                                </div>
                                {block.recommended_internal_actions.length === 0 ? (
                                    <div className="text-xs text-gray-500">No entries.</div>
                                ) : (
                                    block.recommended_internal_actions.map((item, index) => (
                                        <div key={`${key}-action-${index}`} className="text-xs text-gray-300">
                                            {item}
                                        </div>
                                    ))
                                )}
                            </div>
                            <div className="space-y-1">
                                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Cautions
                                </div>
                                {block.cautions.length === 0 ? (
                                    <div className="text-xs text-gray-500">No entries.</div>
                                ) : (
                                    block.cautions.map((item, index) => (
                                        <div key={`${key}-caution-${index}`} className="text-xs text-gray-300">
                                            {item}
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="space-y-2">
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
                            <div key={`internal-${index}`} className="text-gray-300">
                                {item}
                            </div>
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
                            <div key={`human-${index}`} className="text-gray-300">
                                {item}
                            </div>
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

const EventStrategyReviewPanel = () => {
    const [sourceMode, setSourceMode] = useState<EventStrategyReviewSourceMode>('manual_summary');
    const [headline, setHeadline] = useState('');
    const [summary, setSummary] = useState('');
    const [sourceLabel, setSourceLabel] = useState('');
    const [eventDate, setEventDate] = useState('');
    const [urlBundleText, setUrlBundleText] = useState('');
    const [curatedQuery, setCuratedQuery] = useState('');
    const [topicHintsText, setTopicHintsText] = useState('');
    const [geoFocusText, setGeoFocusText] = useState('');
    const [operatorNotes, setOperatorNotes] = useState('');
    const [selectedOutputMode, setSelectedOutputMode] =
        useState<EventStrategyReviewOutputMode>('html_report_package');

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<EventStrategyReviewLatestResponse>(EMPTY_LATEST);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedReport, setSelectedReport] = useState<EventStrategyReviewExecutionResult | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
    const [packageLatest, setPackageLatest] = useState<EventStrategyReviewPackageLatestResponse | null>(null);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [triggering, setTriggering] = useState(false);
    const [reportLoading, setReportLoading] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [packageLoading, setPackageLoading] = useState(false);
    const [packaging, setPackaging] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [reportError, setReportError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);
    const [packageError, setPackageError] = useState<string | null>(null);

    const isBusy = loading || refreshing;

    const loadSelectedRunData = async (runId: number) => {
        setReportLoading(true);
        setAuditLoading(true);
        setPackageLoading(true);
        setReportError(null);
        setAuditError(null);
        setPackageError(null);

        try {
            const [reportResult, auditResult, packageResult] = await Promise.allSettled([
                agentsService.getEventStrategyReviewRunReport(runId),
                agentsService.getEventStrategyReviewRunAuditLogs(runId),
                agentsService.getEventStrategyReviewPackage(runId),
            ]);

            if (reportResult.status === 'fulfilled') {
                setSelectedReport(reportResult.value);
            } else {
                setSelectedReport(null);
                setReportError(
                    getApiErrorMessage(
                        reportResult.reason,
                        'Structured event strategy report is unavailable for this run.',
                    ),
                );
            }

            if (auditResult.status === 'fulfilled') {
                setAuditLogs(auditResult.value);
            } else {
                setAuditLogs([]);
                setAuditError(
                    getApiErrorMessage(
                        auditResult.reason,
                        'Audit history is unavailable for this run.',
                    ),
                );
            }

            if (packageResult.status === 'fulfilled') {
                setPackageLatest(packageResult.value);
            } else {
                setPackageLatest(EMPTY_PACKAGE_LATEST(runId));
                setPackageError(
                    getApiErrorMessage(
                        packageResult.reason,
                        'Package status is unavailable for this run.',
                    ),
                );
            }
        } finally {
            setReportLoading(false);
            setAuditLoading(false);
            setPackageLoading(false);
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
            const [runsResult, latestResult] = await Promise.all([
                agentsService.getEventStrategyReviewRuns(),
                agentsService.getLatestEventStrategyReviewResult(),
            ]);

            setRuns(runsResult);
            setLatest(latestResult);

            const preferredRunId = runsResult.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (latestResult.run_id ?? runsResult[0]?.id ?? null);
            setSelectedRunId(preferredRunId);
        } catch (loadError) {
            setError(
                getApiErrorMessage(
                    loadError,
                    'Failed to load Event Strategy Review data.',
                ),
            );
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
            setPackageLatest(null);
            setReportError(null);
            setAuditError(null);
            setPackageError(null);
            return;
        }

        void loadSelectedRunData(selectedRunId);
    }, [selectedRunId]);

    const resetModeFields = (nextMode: EventStrategyReviewSourceMode) => {
        setSourceMode(nextMode);
        setError(null);
    };

    const buildRunRequest = (): EventStrategyReviewRunRequest => {
        const geoFocus = parseTextList(geoFocusText);
        const baseRequest: EventStrategyReviewRunRequest = {
            retrieval_contract: {
                source_mode: sourceMode,
                live_retrieval_enabled: sourceMode === 'curated_search_query',
            },
            operator_notes: operatorNotes.trim() || null,
            topic_hints: parseTextList(topicHintsText),
            geo_focus: geoFocus,
        };

        if (sourceMode === 'manual_summary') {
            if (!headline.trim() || !summary.trim()) {
                throw new Error('Manual summary requires both a headline and summary.');
            }

            baseRequest.retrieval_contract.manual_summary_input = {
                headline: headline.trim(),
                summary: summary.trim(),
                source_label: sourceLabel.trim() || undefined,
                event_date: eventDate.trim() || undefined,
            };
            return baseRequest;
        }

        if (sourceMode === 'manual_url_bundle') {
            const items = parseUrlBundleLines(urlBundleText);
            if (items.length === 0) {
                throw new Error('Manual URL bundle requires at least one valid URL line.');
            }

            baseRequest.retrieval_contract.manual_url_bundle_input = {
                items,
                submitted_item_count: urlBundleText
                    .split('\n')
                    .map((line) => line.trim())
                    .filter(Boolean).length,
            };
            return baseRequest;
        }

        if (!curatedQuery.trim()) {
            throw new Error('Curated search query requires a query value.');
        }

        baseRequest.retrieval_contract.curated_search_query_input = {
            query: curatedQuery.trim(),
            geography_hint: geoFocus[0] || undefined,
            topic_hints: parseTextList(topicHintsText),
            allowed_domains: [],
            max_results: 8,
        };
        return baseRequest;
    };

    const handleRunOnce = async () => {
        setTriggering(true);
        setError(null);

        try {
            const payload = buildRunRequest();
            await agentsService.triggerEventStrategyReviewRunOnce(payload);
            await loadData();
        } catch (runError) {
            setError(getApiErrorMessage(runError, 'Failed to run Event Strategy Review.'));
        } finally {
            setTriggering(false);
        }
    };

    const handlePackage = async () => {
        if (selectedRunId === null) {
            return;
        }

        setPackaging(true);
        setPackageError(null);
        try {
            const payload: EventStrategyReviewPackageRequest = {
                source_run_id: selectedRunId,
                selected_output_mode: selectedOutputMode,
            };
            await agentsService.createEventStrategyReviewPackage(selectedRunId, payload);
            const nextPackage = await agentsService.getEventStrategyReviewPackage(selectedRunId);
            setPackageLatest(nextPackage);
        } catch (packageTriggerError) {
            setPackageError(
                getApiErrorMessage(
                    packageTriggerError,
                    'Failed to create Event Strategy Review package.',
                ),
            );
        } finally {
            setPackaging(false);
        }
    };

    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const selectedOutputModeOptions =
        selectedReport?.report?.output_mode_options.length
            ? selectedReport.report.output_mode_options
            : [
                {
                    mode: 'html_report_package' as const,
                    status: 'first_class_v1' as const,
                    reason: 'HTML packaging remains the only active packaging mode in this phase.',
                },
                {
                    mode: 'internal_report_only' as const,
                    status: 'planned_later' as const,
                    reason: 'Analysis already provides the internal report directly.',
                },
                {
                    mode: 'social_post_draft_pack' as const,
                    status: 'planned_later' as const,
                    reason: 'Planned later.',
                },
                {
                    mode: 'email_newsletter_draft_pack' as const,
                    status: 'planned_later' as const,
                    reason: 'Planned later.',
                },
                {
                    mode: 'client_summary_draft_pack' as const,
                    status: 'planned_later' as const,
                    reason: 'Planned later.',
                },
            ];

    const canPackageSelectedRun =
        selectedRunId !== null &&
        selectedOutputMode === 'html_report_package' &&
        selectedReport?.execution_status === 'report_generated' &&
        selectedReport.report !== null;

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h2 className="text-lg font-medium">Event Strategy Review</h2>
                    <p className="text-sm text-gray-400">
                        Internal event-driven strategy review only. Manual trigger, manual refresh, controlled curated-query retrieval only, no auto-send, no publishing.
                    </p>
                </div>
                <button
                    onClick={() => void loadData()}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || triggering || packaging}
                >
                    {refreshing ? 'Refreshing...' : 'Refresh'}
                </button>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                <div className="border rounded p-4 bg-white/5 space-y-4">
                    <div className="space-y-2">
                        <div className="text-sm font-medium">Manual Event Intake</div>
                        <div className="text-xs text-gray-400">
                            Use manual summary or manual URL bundle for direct internal analysis. Curated search query uses the controlled retrieval path when available and fails soft when retrieval is unavailable or low-confidence.
                        </div>
                    </div>

                    <div className="space-y-2">
                        <label className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Source Mode
                        </label>
                        <select
                            value={sourceMode}
                            onChange={(event) => resetModeFields(event.target.value as EventStrategyReviewSourceMode)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                        >
                            <option value="manual_summary">Manual summary</option>
                            <option value="manual_url_bundle">Manual URL bundle</option>
                            <option value="curated_search_query">Curated search query</option>
                        </select>
                    </div>

                    {sourceMode === 'manual_summary' && (
                        <div className="space-y-3">
                            <div className="grid gap-3 md:grid-cols-2">
                                <label className="space-y-1">
                                    <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Headline
                                    </span>
                                    <input
                                        value={headline}
                                        onChange={(event) => setHeadline(event.target.value)}
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                        placeholder="Bank of Canada rate decision affects GTA housing"
                                    />
                                </label>
                                <label className="space-y-1">
                                    <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Source Label
                                    </span>
                                    <input
                                        value={sourceLabel}
                                        onChange={(event) => setSourceLabel(event.target.value)}
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                        placeholder="operator_note"
                                    />
                                </label>
                            </div>
                            <label className="space-y-1">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Summary
                                </span>
                                <textarea
                                    value={summary}
                                    onChange={(event) => setSummary(event.target.value)}
                                    className="min-h-[120px] w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                    placeholder="Summarize the high-signal event and why it matters for Toronto / GTA real estate operations."
                                />
                            </label>
                            <label className="space-y-1">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Event Date
                                </span>
                                <input
                                    value={eventDate}
                                    onChange={(event) => setEventDate(event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                    placeholder="2026-03-23"
                                />
                            </label>
                        </div>
                    )}

                    {sourceMode === 'manual_url_bundle' && (
                        <div className="space-y-2">
                            <label className="space-y-1">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Manual URL Bundle
                                </span>
                                <textarea
                                    value={urlBundleText}
                                    onChange={(event) => setUrlBundleText(event.target.value)}
                                    className="min-h-[140px] w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                    placeholder={[
                                        'One source per line.',
                                        'Format: url | optional title | optional publisher | optional published_at',
                                        'Example: https://example.com/story | Toronto inventory update | Example News | 2026-03-23',
                                    ].join('\n')}
                                />
                            </label>
                            <div className="text-xs text-gray-400">
                                Duplicate or tracked URLs are deduplicated by the backend before clustering.
                            </div>
                        </div>
                    )}

                    <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                            Topic Hints
                        </span>
                        <input
                            value={topicHintsText}
                            onChange={(event) => setTopicHintsText(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                            placeholder="mortgage, policy, condo, rental"
                        />
                        <span className="block text-xs text-gray-400">
                            Topic hints are optional for all source modes and help the v1 scorer/tagger stay focused.
                        </span>
                    </label>

                    {sourceMode === 'curated_search_query' && (
                        <div className="space-y-3">
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                                Curated search query uses the controlled retrieval path in this phase. If provider access is unavailable, rate limited, or no credible sources survive filtering, the run fails soft with a clear stored state instead of faking a report.
                            </div>
                            <label className="space-y-1">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Curated Search Query
                                </span>
                                <input
                                    value={curatedQuery}
                                    onChange={(event) => setCuratedQuery(event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                    placeholder="Bank of Canada Toronto housing mortgage rates"
                                />
                            </label>
                        </div>
                    )}

                    <div className="grid gap-3 md:grid-cols-2">
                        <label className="space-y-1">
                            <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                Geo Focus
                            </span>
                            <input
                                value={geoFocusText}
                                onChange={(event) => setGeoFocusText(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="Toronto, GTA, Ontario"
                            />
                        </label>
                        <label className="space-y-1">
                            <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                Operator Notes
                            </span>
                            <input
                                value={operatorNotes}
                                onChange={(event) => setOperatorNotes(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                placeholder="Focus on high-signal events with direct operator usefulness."
                            />
                        </label>
                    </div>

                    <div className="flex items-center justify-between gap-3">
                        <div className="text-xs text-gray-400">
                            Manual trigger only. Curated query retrieval is controlled and capped. No auto-send, no hidden automation.
                        </div>
                        <button
                            onClick={handleRunOnce}
                            className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
                            disabled={isBusy || triggering || packaging}
                        >
                            {triggering ? 'Running...' : 'Run Event Strategy Review'}
                        </button>
                    </div>
                </div>

                <div className="border rounded p-4 bg-white/5 space-y-4">
                    <div>
                        <div className="text-sm font-medium">Latest Result</div>
                        <div className="text-xs text-gray-400">
                            Manual refresh only. The panel uses the stored Step 2-4 analysis and packaging contracts directly.
                        </div>
                    </div>

                    {!latest.run_id ? (
                        <div className="text-sm text-gray-500">No Event Strategy Review runs yet.</div>
                    ) : (
                        <div className="space-y-3">
                            <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1 text-sm">
                                <div className="font-medium">
                                    Latest run #{latest.run_id} · {latest.status || 'unknown'}
                                </div>
                                <div className="text-xs text-gray-400">
                                    Execution: {humanizeEnum(latest.result?.execution_status || 'not_active_yet')}
                                </div>
                                {latest.result && (
                                    <div className="text-xs text-gray-400">
                                        Retrieval:{' '}
                                        {getRetrievalStateLabel(
                                            latest.result.execution_plan.retrieval_metadata,
                                        )}
                                    </div>
                                )}
                                {latest.result?.report && (
                                    <>
                                        <div className="text-gray-200">
                                            {latest.result.report.event_cluster.canonical_event_title}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Importance:{' '}
                                            {humanizeEnum(
                                                latest.result.report.importance_assessment.classification,
                                            )}{' '}
                                            · Total score {latest.result.report.score_breakdown.total_score.toFixed(1)}
                                        </div>
                                    </>
                                )}
                                {latest.result?.inactive_reason && (
                                    <div className="text-xs text-amber-200">{latest.result.inactive_reason}</div>
                                )}
                                {latest.error && (
                                    <div className="text-xs text-rose-300">Error: {latest.error}</div>
                                )}
                            </div>

                            {latest.result ? (
                                <div className="space-y-2">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Latest Result Detail
                                    </div>
                                    {renderReport(latest.result)}
                                </div>
                            ) : (
                                <div className="text-sm text-gray-500">
                                    Latest run does not currently expose a structured report.
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
                <section className="space-y-2">
                    <h3 className="text-base font-medium">Recent Runs</h3>
                    {runs.length === 0 ? (
                        <div className="text-sm text-gray-500">No Event Strategy Review runs yet.</div>
                    ) : (
                        <div className="border rounded p-3 bg-white/5 space-y-2 text-sm">
                            {runs.map((run) => (
                                <div
                                    key={run.id}
                                    className={`flex items-center justify-between gap-3 border-b border-gray-700/40 pb-2 last:border-b-0 ${
                                        selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''
                                    }`}
                                >
                                    <div>
                                        <div className="font-medium">
                                            Run #{run.id} · {run.status}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Created: {formatTimestamp(run.created_at)} · Finished:{' '}
                                            {formatTimestamp(run.finished_at)}
                                        </div>
                                        {run.summary && (
                                            <div className="text-xs text-gray-300">{run.summary}</div>
                                        )}
                                        {run.error && (
                                            <div className="text-xs text-rose-300">Error: {run.error}</div>
                                        )}
                                    </div>
                                    <button
                                        onClick={() => setSelectedRunId(run.id)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || triggering || packaging}
                                    >
                                        {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                <section className="space-y-2">
                    <h3 className="text-base font-medium">Selected Run Report</h3>
                    {selectedRun ? (
                        <div className="text-sm text-gray-400">
                            Inspecting run #{selectedRun.id} ({selectedRun.status})
                        </div>
                    ) : (
                        <div className="text-sm text-gray-500">
                            Select a run to inspect its report, package status, and audit history.
                        </div>
                    )}
                    {reportError && <div className="text-sm text-amber-300">{reportError}</div>}
                    {reportLoading ? (
                        <div className="text-sm text-gray-400">Loading report...</div>
                    ) : (
                        renderReport(selectedReport)
                    )}
                </section>
            </div>

            <section className="space-y-2">
                <h3 className="text-base font-medium">Output Packaging</h3>
                <div className="text-sm text-gray-400">
                    Packaging is an explicit second step. In this phase, only HTML report packaging is active and artifacts are shown as informational metadata.
                </div>
                {selectedRunId === null ? (
                    <div className="text-sm text-gray-500">Select a run before requesting packaging.</div>
                ) : (
                    <div className="border rounded p-3 bg-white/5 space-y-4">
                        <div className="grid gap-3 md:grid-cols-[minmax(0,0.75fr)_auto]">
                            <label className="space-y-1">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                    Output Mode
                                </span>
                                <select
                                    value={selectedOutputMode}
                                    onChange={(event) => setSelectedOutputMode(event.target.value as EventStrategyReviewOutputMode)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
                                >
                                    {selectedOutputModeOptions.map((option) => (
                                        <option key={option.mode} value={option.mode}>
                                            {OUTPUT_MODE_LABELS[option.mode]}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <div className="flex items-end">
                                <button
                                    onClick={handlePackage}
                                    className="px-3 py-1.5 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
                                    disabled={!canPackageSelectedRun || packaging || isBusy}
                                >
                                    {packaging ? 'Packaging...' : 'Create HTML Package'}
                                </button>
                            </div>
                        </div>

                        <div className="space-y-1">
                            {selectedOutputModeOptions.map((option) => (
                                <div key={option.mode} className="text-xs text-gray-400">
                                    {OUTPUT_MODE_LABELS[option.mode]}: {humanizeEnum(option.status)}
                                    {option.reason && <> · {option.reason}</>}
                                </div>
                            ))}
                        </div>

                        {selectedOutputMode !== 'html_report_package' && (
                            <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                                Only HTML report packaging is active in this phase. Other output modes remain planned and are not triggered from the UI.
                            </div>
                        )}

                        {!canPackageSelectedRun && selectedRunId !== null && (
                            <div className="text-xs text-gray-400">
                                {selectedReport && !selectedReport.report
                                    ? `Packaging is blocked because this run does not have a stored structured report (${humanizeEnum(selectedReport.execution_status)}).`
                                    : 'Packaging stays disabled until the selected run has a stored structured report with `report_generated` status.'}
                            </div>
                        )}

                        {packageError && <div className="text-sm text-amber-300">{packageError}</div>}

                        {packageLoading ? (
                            <div className="text-sm text-gray-400">Loading package status...</div>
                        ) : !packageLatest ? (
                            <div className="text-sm text-gray-500">No package status available yet.</div>
                        ) : (
                            <div className="space-y-3">
                                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1 text-sm">
                                    <div className="font-medium">
                                        Package status:{' '}
                                        {packageLatest.result
                                            ? humanizeEnum(packageLatest.result.status)
                                            : 'Not generated'}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Source run #{packageLatest.source_run_id} · Package run:{' '}
                                        {packageLatest.package_run_id ?? 'n/a'} · Run status:{' '}
                                        {packageLatest.status || 'n/a'}
                                    </div>
                                    {packageLatest.error && (
                                        <div className="text-xs text-rose-300">Error: {packageLatest.error}</div>
                                    )}
                                    {packageLatest.result?.requires_explicit_operator_step && (
                                        <div className="text-xs text-gray-300">
                                            Packaging remains operator-triggered only.
                                        </div>
                                    )}
                                    {packageLatest.result?.package_directory_path && (
                                        <div className="text-xs text-gray-400 break-all">
                                            Package directory: {packageLatest.result.package_directory_path}
                                        </div>
                                    )}
                                </div>

                                {packageLatest.result?.operator_notes && packageLatest.result.operator_notes.length > 0 && (
                                    <div className="space-y-1">
                                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                            Packaging Notes
                                        </div>
                                        {packageLatest.result.operator_notes.map((note, index) => (
                                            <div key={`${note}-${index}`} className="text-xs text-gray-300">
                                                {note}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <div className="space-y-2">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        Artifact Manifest
                                    </div>
                                    {renderArtifactList(packageLatest.result?.artifacts ?? [])}
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-base font-medium">Run Audit History</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting audit history for run #{selectedRun.id}.
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a run to inspect audit history.</div>
                )}
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 bg-white/5 space-y-3">
                        {auditLogs.map((log) => (
                            <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{log.action}</div>
                                    <div className="text-xs text-gray-400">{formatTimestamp(log.created_at)}</div>
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
        </section>
    );
};

export default EventStrategyReviewPanel;
