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

type OutputLanguagePreference = 'english' | 'traditional_chinese' | 'both';

const LANGUAGE_PREFERENCE_STORAGE_KEY = 'daily-market-scan:output-language-preference';
const RUN_LANGUAGE_PREFERENCES_STORAGE_KEY = 'daily-market-scan:run-language-preferences';

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

const readSessionValue = <T,>(key: string, fallback: T) => {
    if (typeof window === 'undefined') {
        return fallback;
    }

    try {
        const raw = window.sessionStorage.getItem(key);
        if (!raw) {
            return fallback;
        }
        return JSON.parse(raw) as T;
    } catch {
        return fallback;
    }
};

const writeSessionValue = (key: string, value: unknown) => {
    if (typeof window === 'undefined') {
        return;
    }

    try {
        window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
        // Ignore session persistence failures and continue with in-memory state.
    }
};

const coerceLanguagePreference = (value: unknown): OutputLanguagePreference => {
    if (value === 'traditional_chinese' || value === 'both') {
        return value;
    }
    return 'english';
};

const readStoredRunLanguagePreferences = () => {
    const stored = readSessionValue<Record<string, unknown>>(
        RUN_LANGUAGE_PREFERENCES_STORAGE_KEY,
        {},
    );
    const preferences: Record<number, OutputLanguagePreference> = {};

    Object.entries(stored).forEach(([key, value]) => {
        const runId = Number(key);
        if (Number.isInteger(runId) && runId > 0) {
            preferences[runId] = coerceLanguagePreference(value);
        }
    });

    return preferences;
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

const localizeText = (
    preference: OutputLanguagePreference,
    english: string,
    traditionalChinese: string,
) => {
    switch (preference) {
        case 'traditional_chinese':
            return traditionalChinese;
        case 'both':
            return `${english} / ${traditionalChinese}`;
        default:
            return english;
    }
};

const formatAvailabilityValue = (
    preference: OutputLanguagePreference,
    value?: string | null,
) => {
    if (!value) {
        return localizeText(preference, 'n/a', '未提供');
    }

    const labels: Record<string, [string, string]> = {
        auto: ['Auto', '自動'],
        authenticated_mls_browser: ['Authenticated MLS Browser', '已驗證 MLS 瀏覽器'],
        authenticated_mls_browser_first: ['Authenticated MLS Browser First', '已驗證 MLS 瀏覽器優先'],
        auth_in_progress: ['Auth In Progress', '驗證進行中'],
        available: ['Available', '可用'],
        client_match: ['Client Match', '客戶配對'],
        completed: ['Completed', '已完成'],
        competitor_watch: ['Competitor Watch', '競品監測'],
        condo_same_building: ['Condo Same Building', '同棟公寓'],
        expired: ['Expired', '已過期'],
        failed: ['Failed', '失敗'],
        full_daily_scan: ['Full Daily Scan', '完整每日掃描'],
        high: ['High', '高'],
        limited: ['Limited', '受限'],
        low: ['Low', '低'],
        manual_preview: ['Manual Preview', '手動預覽'],
        medium: ['Medium', '中'],
        no_findings: ['No Findings', '無結果'],
        no_providers: ['No Providers', '無可用提供者'],
        partial: ['Partial', '部分完成'],
        public_listing: ['Public Listing', '公開房源'],
        public_only: ['Public Only', '僅公開來源'],
        queued: ['Queued', '已排隊'],
        running: ['Running', '執行中'],
        simulated_preview: ['Simulated Preview', '模擬預覽'],
        summary_only: ['Summary Only', '僅摘要'],
        unauthenticated: ['Unauthenticated', '未驗證'],
        unavailable: ['Unavailable', '不可用'],
        awaiting_otp: ['Awaiting OTP', '等待 OTP'],
        area_nearby_non_condo: ['Area Nearby Non-Condo', '周邊非公寓區域'],
    };

    const translated = labels[value];
    if (!translated) {
        return humanizeValue(value);
    }

    return localizeText(preference, translated[0], translated[1]);
};

const formatBooleanValue = (
    preference: OutputLanguagePreference,
    value: boolean,
) => localizeText(preference, value ? 'yes' : 'no', value ? '是' : '否');

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
    preference: OutputLanguagePreference,
    emptyLabel = 'No failure metadata.',
) => {
    if (items.length === 0) {
        return <div className="text-gray-500">{emptyLabel}</div>;
    }

    return (
        <div className="space-y-2">
            {items.map((item, index) => (
                <div key={`${item.code}-${item.provider_key ?? 'none'}-${index}`} className="rounded border border-amber-500/20 bg-amber-500/5 p-2">
                    <div className="font-medium text-amber-100">{formatAvailabilityValue(preference, item.code)}</div>
                    <div className="text-xs text-gray-300">
                        {localizeText(preference, 'Provider', '提供者')}: {item.provider_key || localizeText(preference, 'n/a', '未提供')} ·{' '}
                        {localizeText(preference, 'Retryable', '可重試')}: {formatBooleanValue(preference, item.retryable)} ·{' '}
                        {localizeText(preference, 'Fallback attempted', '已嘗試回退')}:{' '}
                        {formatBooleanValue(preference, item.fallback_attempted)} ·{' '}
                        {localizeText(preference, 'Fallback used', '已使用回退')}:{' '}
                        {formatBooleanValue(preference, item.fallback_used)}
                    </div>
                    {item.message && <div className="text-xs text-gray-300 mt-1">{item.message}</div>}
                </div>
            ))}
        </div>
    );
};

const renderSourceAttempts = (
    attempts: DailyMarketScanSourceAttempt[],
    preference: OutputLanguagePreference,
) => {
    if (attempts.length === 0) {
        return <div className="text-gray-500">{localizeText(preference, 'No source attempts recorded.', '沒有來源嘗試記錄。')}</div>;
    }

    return (
        <div className="space-y-2">
            {attempts.map((attempt, index) => (
                <div key={`${attempt.provider_key}-${attempt.source_used}-${index}`} className="rounded border border-white/10 bg-black/10 p-2 space-y-1">
                    <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">
                            {attempt.provider_key} {localizeText(preference, 'via', '經由')} {attempt.source_used}
                        </div>
                        <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(attempt.status)}`}>
                            {formatAvailabilityValue(preference, attempt.status)}
                        </div>
                    </div>
                    <div className="text-xs text-gray-400">
                        {localizeText(preference, 'Auth state', '驗證狀態')}: {formatAvailabilityValue(preference, attempt.auth_state)} ·{' '}
                        {localizeText(preference, 'Fallback used', '已使用回退')}: {formatBooleanValue(preference, attempt.fallback_used)}
                    </div>
                    {attempt.notes.length > 0 && (
                        <div className="text-xs text-gray-300">{attempt.notes.join(' | ')}</div>
                    )}
                    {attempt.failure_metadata.length > 0 && renderFailureMetadata(attempt.failure_metadata, preference)}
                </div>
            ))}
        </div>
    );
};

const summarizeAuditDetails = (
    action: string,
    details: string | undefined,
    preference: OutputLanguagePreference,
) => {
    const parsed = parseJsonText(details);
    if (!parsed || typeof parsed !== 'object') {
        return details || localizeText(preference, 'No additional audit detail.', '沒有額外稽核細節。');
    }

    const data = parsed as Record<string, unknown>;

    if (action === 'daily_market_scan_request_normalized') {
        return [
            `${localizeText(preference, 'Scan mode', '掃描模式')}: ${formatAvailabilityValue(preference, typeof data.scan_mode === 'string' ? data.scan_mode : null)}`,
            `${localizeText(preference, 'Run mode', '執行模式')}: ${formatAvailabilityValue(preference, typeof data.run_mode === 'string' ? data.run_mode : null)}`,
            `${localizeText(preference, 'Source preference', '來源偏好')}: ${formatAvailabilityValue(preference, typeof data.source_preference === 'string' ? data.source_preference : null)}`,
            `${localizeText(preference, 'Max subjects', '主體上限')}: ${typeof data.max_subjects === 'number' ? data.max_subjects : localizeText(preference, 'n/a', '未提供')}`,
        ].join(' | ');
    }

    if (action === 'daily_market_scan_subjects_resolved') {
        const scope = data.scope as Record<string, unknown> | undefined;
        const selected = data.selected_subjects as Record<string, unknown> | undefined;
        const counts = selected?.counts as Record<string, unknown> | undefined;
        return [
            `${localizeText(preference, 'Scope', '範圍')}: ${formatAvailabilityValue(preference, typeof scope?.decision === 'string' ? scope.decision : null)}`,
            `${localizeText(preference, 'Requested', '請求數量')}: ${typeof scope?.requested_subject_count === 'number' ? scope.requested_subject_count : localizeText(preference, 'n/a', '未提供')}`,
            `${localizeText(preference, 'Effective', '實際數量')}: ${typeof scope?.effective_subject_count === 'number' ? scope.effective_subject_count : localizeText(preference, 'n/a', '未提供')}`,
            `${localizeText(preference, 'Selected contacts/properties/listings', '已選聯絡人/物件/房源')}: ${typeof counts?.contacts_selected === 'number' ? counts.contacts_selected : 0}/${typeof counts?.properties_selected === 'number' ? counts.properties_selected : 0}/${typeof counts?.listings_selected === 'number' ? counts.listings_selected : 0}`,
        ].join(' | ');
    }

    if (action === 'daily_market_scan_provider_plan_generated') {
        const providerOrder = Array.isArray(data.provider_order) ? data.provider_order.join(' -> ') : 'n/a';
        return `${localizeText(preference, 'Provider order', '提供者順序')}: ${providerOrder}`;
    }

    if (action === 'daily_market_scan_provider_execution_completed') {
        const clientMatchScans = Array.isArray(data.client_match_scans) ? data.client_match_scans.length : 0;
        const competitorWatchScans = Array.isArray(data.competitor_watch_scans) ? data.competitor_watch_scans.length : 0;
        const riskFlags = Array.isArray(data.risk_flags) ? data.risk_flags.join(', ') : 'none';
        return `${localizeText(preference, 'Client match scans', '客戶配對掃描')}: ${clientMatchScans} | ${localizeText(preference, 'Competitor watch scans', '競品監測掃描')}: ${competitorWatchScans} | ${localizeText(preference, 'Risk flags', '風險標記')}: ${riskFlags}`;
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
        return summary || localizeText(preference, 'Provider failure metadata recorded.', '已記錄提供者失敗中繼資料。');
    }

    if (action === 'daily_market_scan_run_completed') {
        const riskFlags = Array.isArray(data.risk_flags) ? data.risk_flags.join(', ') : 'none';
        return `${localizeText(preference, 'Run completed. Risk flags', '執行完成。風險標記')}: ${riskFlags}`;
    }

    if (action === 'daily_market_scan_run_failed') {
        return `${localizeText(preference, 'Run failed', '執行失敗')}: ${typeof data.error === 'string' ? data.error : 'unknown_error'}`;
    }

    return localizeText(preference, 'Internal audit detail recorded.', '已記錄內部稽核細節。');
};

const renderReport = (
    report: DailyMarketScanResultResponse,
    heading: string,
    preference: OutputLanguagePreference,
    subtitle?: string | null,
) => {
    return (
        <div className="border rounded p-3 space-y-4 bg-white/5 text-sm">
            <div className="space-y-1">
                <div className="font-medium">{heading}</div>
                {subtitle && <div className="text-xs text-gray-400">{subtitle}</div>}
                <div className="text-xs text-gray-400">
                    {localizeText(preference, 'Scan mode', '掃描模式')}: {formatAvailabilityValue(preference, report.scan_summary.scan_mode)} ·{' '}
                    {localizeText(preference, 'Run mode', '執行模式')}: {formatAvailabilityValue(preference, report.scan_summary.run_mode)}
                </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        {localizeText(preference, 'Scope', '範圍')}
                    </div>
                    <div>{localizeText(preference, 'Decision', '決策')}: {formatAvailabilityValue(preference, report.scan_summary.scope.decision)}</div>
                    <div>{localizeText(preference, 'Requested subjects', '請求主體數')}: {report.scan_summary.scope.requested_subject_count}</div>
                    <div>{localizeText(preference, 'Effective subjects', '實際主體數')}: {report.scan_summary.scope.effective_subject_count}</div>
                    <div>{localizeText(preference, 'Max subjects', '主體上限')}: {report.scan_summary.scope.max_subjects}</div>
                    {report.scan_summary.scope.notes.length > 0 && (
                        <div className="text-xs text-gray-300">{report.scan_summary.scope.notes.join(' | ')}</div>
                    )}
                </div>
                <div className="rounded border border-sky-500/20 bg-sky-500/5 p-3 space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                        {localizeText(preference, 'Execution Policy', '執行政策')}
                    </div>
                    <div>{localizeText(preference, 'Mode', '模式')}: {report.execution_policy.mode}</div>
                    <div>{localizeText(preference, 'No auto-send', '不自動發送')}: {formatBooleanValue(preference, !report.execution_policy.can_auto_send)}</div>
                    <div>{localizeText(preference, 'No auto-contact', '不自動聯絡客戶')}: {formatBooleanValue(preference, !report.execution_policy.can_auto_contact_clients)}</div>
                    <div>{localizeText(preference, 'No client outputs without approval', '未經核准不產生客戶輸出')}: {formatBooleanValue(preference, !report.execution_policy.can_create_client_outputs_without_approval)}</div>
                </div>
            </div>

            <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                    {localizeText(preference, 'Providers', '提供者')}
                </div>
                <div className="text-xs text-gray-400">
                    {localizeText(preference, 'Provider order', '提供者順序')}: {report.scan_summary.provider_order.length > 0 ? report.scan_summary.provider_order.join(' -> ') : localizeText(preference, 'none', '無')}
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                    {report.provider_catalog.map((provider) => (
                        <div key={provider.provider_key} className="rounded border border-white/10 bg-black/10 p-3 space-y-1">
                            <div className="font-medium">{provider.display_name}</div>
                            <div className="text-xs text-gray-400">
                                {localizeText(preference, 'Key', '鍵值')}: {provider.provider_key} · {localizeText(preference, 'Availability', '可用性')}:{' '}
                                {formatAvailabilityValue(preference, provider.availability)} · {localizeText(preference, 'Auth', '驗證')}:{' '}
                                {formatAvailabilityValue(preference, provider.auth_state)}
                            </div>
                            <div className="text-xs text-gray-300">
                                {localizeText(preference, 'Detail', '細節層級')}: {formatAvailabilityValue(preference, provider.detail_level)} ·{' '}
                                {localizeText(preference, 'Confidence', '信心程度')}: {formatAvailabilityValue(preference, provider.confidence_level)} ·{' '}
                                {localizeText(preference, 'Fallback capable', '可回退')}: {formatBooleanValue(preference, provider.fallback_capable)}
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
                        {localizeText(preference, 'Client Match', '客戶配對')}
                    </div>
                    {report.client_match_scans.length === 0 ? (
                        <div className="text-gray-500">{localizeText(preference, 'No client-match scans in this run.', '此執行沒有客戶配對掃描。')}</div>
                    ) : (
                        report.client_match_scans.map((scan, index) => (
                            <div key={`${scan.contact_id}-${index}`} className="rounded border border-white/10 bg-black/10 p-3 space-y-2">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="font-medium">{localizeText(preference, 'Contact', '聯絡人')} #{scan.contact_id}</div>
                                    <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(scan.status)}`}>
                                        {formatAvailabilityValue(preference, scan.status)}
                                    </div>
                                </div>
                                {scan.criteria_summary && (
                                    <div className="text-xs text-gray-300">{scan.criteria_summary}</div>
                                )}
                                <div className="text-xs text-gray-400">
                                    {localizeText(preference, 'Findings', '結果數')}: {scan.findings.length} ·{' '}
                                    {localizeText(preference, 'Fallback used', '已使用回退')}: {formatBooleanValue(preference, scan.fallback_used)}
                                </div>
                                {scan.findings.length > 0 && (
                                    <div className="space-y-2">
                                        {scan.findings.map((finding, findingIndex) => (
                                            <div key={`${finding.address}-${findingIndex}`} className="rounded border border-white/10 bg-white/5 p-2">
                                                <div className="font-medium">{finding.address}</div>
                                                <div className="text-xs text-gray-400">
                                                    {localizeText(preference, 'Source', '來源')}: {finding.source_used}
                                                    {finding.mls_number && <> · MLS: {finding.mls_number}</>}
                                                    {finding.listing_ref && <> · {localizeText(preference, 'Listing ref', '房源參考')}: {finding.listing_ref}</>}
                                                </div>
                                                {finding.why_it_matches.length > 0 && (
                                                    <div className="text-xs text-gray-300 mt-1">
                                                        {localizeText(preference, 'Match signals', '配對訊號')}: {finding.why_it_matches.join(' | ')}
                                                    </div>
                                                )}
                                                {finding.tradeoffs.length > 0 && (
                                                    <div className="text-xs text-amber-100 mt-1">
                                                        {localizeText(preference, 'Tradeoffs', '取捨')}: {finding.tradeoffs.join(' | ')}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        {localizeText(preference, 'Source Attempts', '來源嘗試')}
                                    </div>
                                    {renderSourceAttempts(scan.source_attempts, preference)}
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        {localizeText(preference, 'Failure Metadata', '失敗中繼資料')}
                                    </div>
                                    {renderFailureMetadata(scan.failure_metadata, preference, localizeText(preference, 'No failure metadata.', '沒有失敗中繼資料。'))}
                                </div>
                            </div>
                        ))
                    )}
                </div>

                <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        {localizeText(preference, 'Competitor Watch', '競品監測')}
                    </div>
                    {report.competitor_watch_scans.length === 0 ? (
                        <div className="text-gray-500">{localizeText(preference, 'No competitor-watch scans in this run.', '此執行沒有競品監測掃描。')}</div>
                    ) : (
                        report.competitor_watch_scans.map((scan, index) => (
                            <div key={`${scan.subject.property_id ?? scan.subject.listing_ref ?? index}-${index}`} className="rounded border border-white/10 bg-black/10 p-3 space-y-2">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="font-medium">
                                        {scan.subject.listing_ref
                                            ? `${localizeText(preference, 'Listing', '房源')} ${scan.subject.listing_ref}`
                                            : `${localizeText(preference, 'Property', '物件')} #${scan.subject.property_id ?? localizeText(preference, 'n/a', '未提供')}`}
                                    </div>
                                    <div className={`rounded border px-2 py-0.5 text-xs ${getWorkflowBadgeClass(scan.status)}`}>
                                        {formatAvailabilityValue(preference, scan.status)}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400">
                                    {localizeText(preference, 'Competitor mode', '競品模式')}: {formatAvailabilityValue(preference, scan.subject.competitor_mode)} ·{' '}
                                    {localizeText(preference, 'Findings', '結果數')}: {scan.findings.length} · {localizeText(preference, 'Fallback used', '已使用回退')}:{' '}
                                    {formatBooleanValue(preference, scan.fallback_used)}
                                </div>
                                {scan.findings.length > 0 && (
                                    <div className="space-y-2">
                                        {scan.findings.map((finding, findingIndex) => (
                                            <div key={`${finding.address}-${findingIndex}`} className="rounded border border-white/10 bg-white/5 p-2">
                                                <div className="font-medium">{finding.address}</div>
                                                <div className="text-xs text-gray-400">
                                                    {localizeText(preference, 'Source', '來源')}: {finding.source_used}
                                                    {finding.mls_number && <> · MLS: {finding.mls_number}</>}
                                                    {finding.listing_ref && <> · {localizeText(preference, 'Listing ref', '房源參考')}: {finding.listing_ref}</>}
                                                </div>
                                                {finding.why_relevant.length > 0 && (
                                                    <div className="text-xs text-gray-300 mt-1">
                                                        {localizeText(preference, 'Relevance', '相關性')}: {finding.why_relevant.join(' | ')}
                                                    </div>
                                                )}
                                                {finding.competitor_notes.length > 0 && (
                                                    <div className="text-xs text-amber-100 mt-1">
                                                        {localizeText(preference, 'Notes', '備註')}: {finding.competitor_notes.join(' | ')}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        {localizeText(preference, 'Source Attempts', '來源嘗試')}
                                    </div>
                                    {renderSourceAttempts(scan.source_attempts, preference)}
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                                        {localizeText(preference, 'Failure Metadata', '失敗中繼資料')}
                                    </div>
                                    {renderFailureMetadata(scan.failure_metadata, preference, localizeText(preference, 'No failure metadata.', '沒有失敗中繼資料。'))}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        {localizeText(preference, 'Risk Flags', '風險標記')}
                    </div>
                    {report.risk_flags.length === 0 ? (
                        <div className="text-gray-500">{localizeText(preference, 'No risk flags.', '沒有風險標記。')}</div>
                    ) : (
                        report.risk_flags.map((flag) => (
                            <div key={flag} className="text-gray-300">{flag}</div>
                        ))
                    )}
                </div>
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        {localizeText(preference, 'Top-Level Failure Metadata', '頂層失敗中繼資料')}
                    </div>
                    {renderFailureMetadata(report.failure_metadata, preference, localizeText(preference, 'No failure metadata.', '沒有失敗中繼資料。'))}
                </div>
            </div>

            {report.operator_notes.length > 0 && (
                <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                        {localizeText(preference, 'Operator Notes', '操作員備註')}
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
    const [outputLanguagePreference, setOutputLanguagePreference] = useState<OutputLanguagePreference>(() =>
        coerceLanguagePreference(
            readSessionValue(LANGUAGE_PREFERENCE_STORAGE_KEY, 'english'),
        ),
    );
    const [contactIds, setContactIds] = useState('');
    const [propertyIds, setPropertyIds] = useState('');
    const [listingRefs, setListingRefs] = useState('');
    const [maxSubjects, setMaxSubjects] = useState('25');
    const [runLanguagePreferences, setRunLanguagePreferences] = useState<Record<number, OutputLanguagePreference>>(
        () => readStoredRunLanguagePreferences(),
    );

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
        writeSessionValue(LANGUAGE_PREFERENCE_STORAGE_KEY, outputLanguagePreference);
    }, [outputLanguagePreference]);

    useEffect(() => {
        writeSessionValue(
            RUN_LANGUAGE_PREFERENCES_STORAGE_KEY,
            runLanguagePreferences,
        );
    }, [runLanguagePreferences]);

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
            setRunLanguagePreferences((current) => ({
                ...current,
                [run.id]: outputLanguagePreference,
            }));
            setSelectedRunId(run.id);
            await loadData('refresh');
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Daily Market Scan.'));
        } finally {
            setTriggering(false);
        }
    };

    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const getRunLanguagePreference = (runId?: number | null): OutputLanguagePreference => {
        if (!runId) {
            return 'english';
        }
        return runLanguagePreferences[runId] ?? 'english';
    };
    const latestPreference =
        latest.run_id === null ? outputLanguagePreference : getRunLanguagePreference(latest.run_id);
    const selectedRunPreference =
        selectedRunId === null ? outputLanguagePreference : getRunLanguagePreference(selectedRunId);

    return (
        <section className="space-y-4 border border-cyan-500/20 rounded-lg p-4 bg-cyan-500/5">
            <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                    <h2 className="text-lg font-medium">{localizeText(outputLanguagePreference, 'Daily Market Scan', '每日市場掃描')}</h2>
                    <div className="text-sm text-gray-300">
                        {localizeText(
                            outputLanguagePreference,
                            'Internal-only market scan workspace. Manual or simulated only. No auto-send. No hidden automation.',
                            '僅供內部使用的市場掃描工作區。僅限手動或模擬模式。不自動發送。沒有隱藏自動化。',
                        )}
                    </div>
                    <div className="text-xs text-gray-400">
                        {localizeText(
                            outputLanguagePreference,
                            'This panel does not perform real provider retrieval, browser automation, CRM writeback, or TRREB integration yet.',
                            '此面板目前不執行真實提供者擷取、瀏覽器自動化、CRM 回寫或 TRREB 整合。',
                        )}
                    </div>
                </div>
                <button
                    onClick={() => void loadData('refresh')}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || triggering}
                >
                    {refreshing
                        ? localizeText(outputLanguagePreference, 'Refreshing...', '重新整理中...')
                        : localizeText(outputLanguagePreference, 'Refresh', '重新整理')}
                </button>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            <div className="border rounded p-3 bg-white/5 space-y-3">
                <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                    <div className="text-sm font-medium">
                        {localizeText(outputLanguagePreference, 'Manual / Simulated Run', '手動 / 模擬執行')}
                    </div>
                    <label className="space-y-1 text-sm md:min-w-[280px]">
                        <div className="text-gray-300">
                            {localizeText(outputLanguagePreference, 'Output language preference', '輸出語言偏好')}
                        </div>
                        <select
                            value={outputLanguagePreference}
                            onChange={(event) =>
                                setOutputLanguagePreference(
                                    coerceLanguagePreference(event.target.value),
                                )
                            }
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="english">
                                {localizeText(outputLanguagePreference, 'English only', '僅限英文')}
                            </option>
                            <option value="traditional_chinese">
                                {localizeText(outputLanguagePreference, 'Traditional Chinese only', '僅限繁體中文')}
                            </option>
                            <option value="both">
                                {localizeText(
                                    outputLanguagePreference,
                                    'Both English and Traditional Chinese',
                                    '英文與繁體中文並列',
                                )}
                            </option>
                        </select>
                    </label>
                </div>
                <div className="text-xs text-gray-400">
                    {localizeText(
                        outputLanguagePreference,
                        'Captured once per run in this browser session. Historical runs without a stored preference render in English only.',
                        '每次執行會在此瀏覽器工作階段記錄一次。若歷史執行沒有儲存的偏好，會安全地以英文顯示。',
                    )}
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Scan mode', '掃描模式')}</div>
                        <select
                            value={scanMode}
                            onChange={(event) => setScanMode(event.target.value as typeof scanMode)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="full_daily_scan">{formatAvailabilityValue(outputLanguagePreference, 'full_daily_scan')}</option>
                            <option value="client_match">{formatAvailabilityValue(outputLanguagePreference, 'client_match')}</option>
                            <option value="competitor_watch">{formatAvailabilityValue(outputLanguagePreference, 'competitor_watch')}</option>
                        </select>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Run mode', '執行模式')}</div>
                        <select
                            value={runMode}
                            onChange={(event) => setRunMode(event.target.value as typeof runMode)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="manual_preview">{formatAvailabilityValue(outputLanguagePreference, 'manual_preview')}</option>
                            <option value="simulated_preview">{formatAvailabilityValue(outputLanguagePreference, 'simulated_preview')}</option>
                        </select>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Source preference', '來源偏好')}</div>
                        <select
                            value={sourcePreference}
                            onChange={(event) => setSourcePreference(event.target.value as typeof sourcePreference)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                        >
                            <option value="auto">{formatAvailabilityValue(outputLanguagePreference, 'auto')}</option>
                            <option value="authenticated_mls_browser_first">{formatAvailabilityValue(outputLanguagePreference, 'authenticated_mls_browser_first')}</option>
                            <option value="public_only">{formatAvailabilityValue(outputLanguagePreference, 'public_only')}</option>
                        </select>
                    </label>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Contact IDs', '聯絡人 ID')}</div>
                        <input
                            value={contactIds}
                            onChange={(event) => setContactIds(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder="12, 18, 51"
                        />
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Property IDs', '物件 ID')}</div>
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
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Listing refs', '房源參考')}</div>
                        <textarea
                            value={listingRefs}
                            onChange={(event) => setListingRefs(event.target.value)}
                            rows={4}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-cyan-400"
                            placeholder={'manual:listing:20-stewart|17|20 Stewart St #706\nmanual:property:88|88|88 King St W'}
                        />
                        <div className="text-xs text-gray-400">
                            {localizeText(outputLanguagePreference, 'One per line. Format: listing_ref|property_id|label', '每行一筆。格式：listing_ref|property_id|label')}
                        </div>
                    </label>

                    <label className="space-y-1 text-sm">
                        <div className="text-gray-300">{localizeText(outputLanguagePreference, 'Max subjects', '主體上限')}</div>
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
                        {localizeText(
                            outputLanguagePreference,
                            'Review-only. Stable result shapes include zero findings, no providers, and partial failures without treating them as crashes.',
                            '僅供審閱。穩定結果形態包含零結果、無可用提供者與部分失敗，不會把它們視為系統崩潰。',
                        )}
                    </div>
                    <button
                        onClick={handleTrigger}
                        className="px-3 py-2 text-sm rounded bg-cyan-600 text-white hover:bg-cyan-700 disabled:opacity-60"
                        disabled={isBusy || triggering}
                    >
                        {triggering
                            ? localizeText(outputLanguagePreference, 'Running...', '執行中...')
                            : localizeText(outputLanguagePreference, 'Run Daily Market Scan', '執行每日市場掃描')}
                    </button>
                </div>
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">{localizeText(latestPreference, 'Latest Scan Result', '最新掃描結果')}</h3>
                {latest.run_id === null ? (
                    <div className="text-sm text-gray-500">{localizeText(latestPreference, 'No Daily Market Scan runs yet.', '尚無每日市場掃描執行記錄。')}</div>
                ) : latest.result ? (
                    renderReport(
                        latest.result,
                        localizeText(latestPreference, `Latest run #${latest.run_id}`, `最新執行 #${latest.run_id}`),
                        latestPreference,
                        latest.status ? `${localizeText(latestPreference, 'Status', '狀態')}: ${formatAvailabilityValue(latestPreference, latest.status)}` : null,
                    )
                ) : (
                    <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                        {localizeText(latestPreference, `Latest run #${latest.run_id} is`, `最新執行 #${latest.run_id} 為`)} {formatAvailabilityValue(latestPreference, latest.status || 'unknown')}.
                        {latest.error && <span className="text-rose-200"> {localizeText(latestPreference, 'Error', '錯誤')}: {latest.error}</span>}
                        {!latest.error && <span> {localizeText(latestPreference, 'Structured result is unavailable for this run.', '此執行沒有可用的結構化結果。')}</span>}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">{localizeText(outputLanguagePreference, 'Recent Runs', '最近執行')}</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">{localizeText(outputLanguagePreference, 'No Daily Market Scan runs yet.', '尚無每日市場掃描執行記錄。')}</div>
                ) : (
                    <div className="border rounded p-3 space-y-2 bg-white/5">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between gap-3 border-b border-gray-700/40 pb-2 last:border-b-0 ${selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''}`}
                            >
                                <div>
                                    <div className="font-medium">{localizeText(outputLanguagePreference, 'Run', '執行')} #{run.id} - {formatAvailabilityValue(outputLanguagePreference, run.status)}</div>
                                    <div className="text-xs text-gray-400">
                                        {localizeText(outputLanguagePreference, 'Created', '建立時間')}: {formatTimestamp(run.created_at)}
                                        {run.finished_at && <> · {localizeText(outputLanguagePreference, 'Finished', '完成時間')}: {formatTimestamp(run.finished_at)}</>}
                                    </div>
                                    {run.summary && <div className="text-xs text-gray-300">{run.summary}</div>}
                                    {run.error && <div className="text-xs text-rose-300">{localizeText(outputLanguagePreference, 'Error', '錯誤')}: {run.error}</div>}
                                </div>
                                <button
                                    onClick={() => setSelectedRunId(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering}
                                >
                                    {selectedRunId === run.id
                                        ? localizeText(outputLanguagePreference, 'Inspecting', '檢視中')
                                        : localizeText(outputLanguagePreference, 'Inspect', '檢視')}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">{localizeText(selectedRunPreference, 'Selected Run Report', '所選執行報告')}</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        {localizeText(selectedRunPreference, 'Inspecting run', '檢視執行')} #{selectedRun.id} ({formatAvailabilityValue(selectedRunPreference, selectedRun.status)})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">{localizeText(selectedRunPreference, 'Select a run to inspect its report and audit history.', '選擇一筆執行記錄以檢視其報告與稽核歷史。')}</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        {localizeText(selectedRunPreference, 'Run failure reason', '執行失敗原因')}: {selectedRun.error}
                    </div>
                )}
                {reportError && <div className="text-sm text-amber-300">{reportError}</div>}
                {reportLoading ? (
                    <div className="text-sm text-gray-400">{localizeText(selectedRunPreference, 'Loading Daily Market Scan report...', '正在載入每日市場掃描報告...')}</div>
                ) : selectedRunId === null ? null : selectedReport ? (
                    renderReport(selectedReport, localizeText(selectedRunPreference, `Selected run #${selectedRunId}`, `所選執行 #${selectedRunId}`), selectedRunPreference)
                ) : (
                    <div className="text-sm text-gray-500">{localizeText(selectedRunPreference, 'Structured report is unavailable for this run.', '此執行沒有可用的結構化報告。')}</div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">{localizeText(selectedRunPreference, 'Selected Run Audit History', '所選執行稽核歷史')}</h3>
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">{localizeText(selectedRunPreference, 'Loading audit history...', '正在載入稽核歷史...')}</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">{localizeText(selectedRunPreference, 'No audit history found for this run.', '此執行沒有稽核歷史。')}</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => (
                            <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{humanizeValue(log.action)}</div>
                                    <div className="text-xs text-gray-400">
                                        {formatTimestamp(log.created_at)}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400 mt-0.5">
                                    {localizeText(selectedRunPreference, 'Actor', '執行者')}: {humanizeValue(log.actor_type)}
                                </div>
                                <div className="mt-2 text-xs text-gray-300">
                                    {summarizeAuditDetails(log.action, log.details, selectedRunPreference)}
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
