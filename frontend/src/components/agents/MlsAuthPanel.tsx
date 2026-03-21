import axios from 'axios';
import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import type {
    AgentAuditLog,
    MlsAuthHistoryResponse,
    MlsAuthStatusResponse,
} from '../../services/agents';

const DEFAULT_PROVIDER = 'stratus_authenticated' as const;

const EMPTY_STATUS: MlsAuthStatusResponse = {
    provider: DEFAULT_PROVIDER,
    state: 'unauthenticated',
    available: false,
    internal_only: true,
    mode: 'manual_simulated',
    last_checked_at: null,
    last_success_at: null,
    last_failure_at: null,
    failure_reason: null,
    session_reference: null,
    active_attempt_reference: null,
    otp_requested_at: null,
    otp_timeout_at: null,
    expires_at: null,
};

const EMPTY_HISTORY: MlsAuthHistoryResponse = {
    current_status: EMPTY_STATUS,
    attempts: [],
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

const formatFailureReason = (value?: string | null) => {
    if (!value) {
        return 'unknown_auth_failure';
    }
    return value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const getStateBadgeClass = (state: MlsAuthStatusResponse['state']) => {
    switch (state) {
        case 'available':
            return 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30';
        case 'awaiting_otp':
            return 'bg-amber-500/15 text-amber-200 border-amber-500/30';
        case 'auth_in_progress':
            return 'bg-sky-500/15 text-sky-200 border-sky-500/30';
        case 'failed':
        case 'expired':
            return 'bg-rose-500/15 text-rose-200 border-rose-500/30';
        default:
            return 'bg-white/5 text-gray-200 border-white/10';
    }
};

const MlsAuthPanel = () => {
    const [status, setStatus] = useState<MlsAuthStatusResponse>(EMPTY_STATUS);
    const [history, setHistory] = useState<MlsAuthHistoryResponse>(EMPTY_HISTORY);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
    const [otpCode, setOtpCode] = useState('');

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [starting, setStarting] = useState(false);
    const [submittingOtp, setSubmittingOtp] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [actionMessage, setActionMessage] = useState<string | null>(null);

    const isBusy = loading || refreshing;
    const canResumeOtp =
        status.state === 'awaiting_otp' &&
        typeof status.active_attempt_reference === 'string' &&
        status.active_attempt_reference.length > 0 &&
        typeof status.session_reference === 'string' &&
        status.session_reference.length > 0;

    const loadData = async (mode: 'initial' | 'refresh' = 'refresh') => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }
        setError(null);

        const [statusResult, historyResult, auditResult] = await Promise.allSettled([
            agentsService.getMlsAuthStatus(DEFAULT_PROVIDER),
            agentsService.getMlsAuthHistory(DEFAULT_PROVIDER),
            agentsService.getMlsAuthAuditLogs(DEFAULT_PROVIDER),
        ]);

        if (statusResult.status === 'fulfilled') {
            setStatus(statusResult.value);
        } else {
            setStatus(EMPTY_STATUS);
            setError(getErrorMessage(statusResult.reason, 'Failed to load MLS auth status.'));
        }

        if (historyResult.status === 'fulfilled') {
            setHistory(historyResult.value);
        } else {
            setHistory(EMPTY_HISTORY);
            setError((current) => current ?? getErrorMessage(historyResult.reason, 'Failed to load MLS auth history.'));
        }

        if (auditResult.status === 'fulfilled') {
            setAuditLogs(auditResult.value);
        } else {
            setAuditLogs([]);
            setError((current) => current ?? getErrorMessage(auditResult.reason, 'Failed to load MLS auth audit logs.'));
        }

        if (mode === 'initial') {
            setLoading(false);
        } else {
            setRefreshing(false);
        }
    };

    useEffect(() => {
        void loadData('initial');
    }, []);

    const handleStart = async () => {
        setStarting(true);
        setError(null);
        setActionMessage(null);
        try {
            const response = await agentsService.startMlsAuthAttempt({
                provider: DEFAULT_PROVIDER,
                mode: 'manual_simulated',
            });
            setActionMessage(
                response.reused_existing_attempt
                    ? 'Existing auth attempt is still active and was reused safely.'
                    : 'MLS auth attempt state created. Browser/runtime login is not wired in yet.',
            );
        } catch (startError) {
            setError(getErrorMessage(startError, 'Failed to start MLS auth attempt.'));
        } finally {
            setStarting(false);
            await loadData('refresh');
        }
    };

    const handleSubmitOtp = async () => {
        if (!canResumeOtp) {
            setError('OTP resume metadata is missing for the active auth attempt.');
            return;
        }
        if (!otpCode.trim()) {
            setError('Enter the OTP before submitting.');
            return;
        }

        setSubmittingOtp(true);
        setError(null);
        setActionMessage(null);
        try {
            const response = await agentsService.submitMlsAuthOtp({
                provider: DEFAULT_PROVIDER,
                attempt_reference: status.active_attempt_reference!,
                session_reference: status.session_reference!,
                otp_code: otpCode.trim(),
            });
            setActionMessage(
                response.otp_accepted
                    ? 'OTP was accepted and the persisted MLS auth state advanced. Real browser/session automation is still not wired in.'
                    : 'OTP was not accepted because the active attempt has already timed out.',
            );
        } catch (submitError) {
            setError(getErrorMessage(submitError, 'Failed to submit OTP for the MLS auth attempt.'));
        } finally {
            setOtpCode('');
            setSubmittingOtp(false);
            await loadData('refresh');
        }
    };

    return (
        <section className="space-y-3 border border-sky-500/20 rounded-lg p-4 bg-sky-500/5">
            <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                    <h2 className="text-lg font-medium">Authenticated MLS Access</h2>
                    <div className="text-sm text-gray-300">
                        Internal-only auth/session admin layer. Manual-simulated. No send path. No browser automation yet.
                    </div>
                    <div className="text-xs text-gray-400">
                        Stable credentials, OTP handling, and real session automation are intentionally not wired in at this step.
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => void loadData('refresh')}
                        className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                        disabled={isBusy || starting || submittingOtp}
                    >
                        {refreshing ? 'Refreshing...' : 'Refresh'}
                    </button>
                    <button
                        onClick={handleStart}
                        className="px-3 py-1.5 text-sm rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-60"
                        disabled={isBusy || starting || submittingOtp}
                    >
                        {starting ? 'Starting...' : 'Start Login Attempt'}
                    </button>
                </div>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            {actionMessage && (
                <div className="rounded border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100">
                    {actionMessage}
                </div>
            )}

            {loading ? (
                <div className="text-sm text-gray-400">Loading MLS auth panel...</div>
            ) : (
                <>
                    <div className="border rounded p-3 bg-white/5 space-y-3">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="text-xs uppercase tracking-wide text-gray-400">Current State</div>
                                <div className="text-sm text-gray-300">Provider: {status.provider}</div>
                            </div>
                            <div
                                className={`rounded border px-2.5 py-1 text-xs font-medium ${getStateBadgeClass(status.state)}`}
                            >
                                {status.state}
                            </div>
                        </div>

                        <div className="grid gap-3 md:grid-cols-2 text-sm">
                            <div className="space-y-1">
                                <div>Available: {status.available ? 'yes' : 'no'}</div>
                                <div>Mode: {status.mode}</div>
                                <div>Last checked: {formatTimestamp(status.last_checked_at)}</div>
                                <div>Last success: {formatTimestamp(status.last_success_at)}</div>
                                <div>Last failure: {formatTimestamp(status.last_failure_at)}</div>
                            </div>
                            <div className="space-y-1">
                                <div>Active attempt: {status.active_attempt_reference || 'none'}</div>
                                <div>Session reference: {status.session_reference || 'none'}</div>
                                <div>OTP requested: {formatTimestamp(status.otp_requested_at)}</div>
                                <div>OTP timeout: {formatTimestamp(status.otp_timeout_at)}</div>
                                <div>Session expiry: {formatTimestamp(status.expires_at)}</div>
                            </div>
                        </div>

                        {status.state === 'unauthenticated' && (
                            <div className="rounded border border-white/10 bg-black/10 px-3 py-2 text-sm text-gray-300">
                                No persisted MLS auth attempt exists yet. Use <span className="font-medium">Start Login Attempt</span> to create or resume the internal auth/session state.
                            </div>
                        )}

                        {status.state === 'auth_in_progress' && (
                            <div className="rounded border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-sm text-sky-100">
                                Auth is currently in progress. This step does not run real browser login yet.
                            </div>
                        )}

                        {status.state === 'available' && (
                            <div className="rounded border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
                                Persisted MLS auth/session state is currently marked available. This does not yet prove a live automated browser session.
                            </div>
                        )}

                        {(status.state === 'failed' || status.state === 'expired') && (
                            <div className="rounded border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
                                Failure reason: {formatFailureReason(status.failure_reason)}
                            </div>
                        )}
                    </div>

                    <div className="border rounded p-3 bg-amber-500/5 border-amber-500/20 space-y-3">
                        <div className="space-y-1">
                            <div className="text-sm font-medium text-amber-100">OTP Resume</div>
                            <div className="text-xs text-amber-200/80">
                                OTP must remain human-supplied. It is held only in local UI state and is cleared immediately after submit.
                            </div>
                        </div>

                        {status.state === 'awaiting_otp' ? (
                            <div className="space-y-3">
                                <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                                    This auth attempt is waiting for Kevin&apos;s OTP. Resume is ready below.
                                </div>
                                <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                                    <input
                                        type="password"
                                        inputMode="numeric"
                                        autoComplete="one-time-code"
                                        aria-label="MLS OTP code"
                                        value={otpCode}
                                        onChange={(event) => setOtpCode(event.target.value)}
                                        className="rounded border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-amber-400"
                                        placeholder="Enter OTP"
                                        spellCheck={false}
                                    />
                                    <button
                                        onClick={handleSubmitOtp}
                                        className="px-3 py-2 text-sm rounded bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                                        disabled={isBusy || starting || submittingOtp || !canResumeOtp}
                                    >
                                        {submittingOtp ? 'Submitting...' : 'Submit OTP'}
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div className="text-sm text-gray-400">
                                No active OTP resume step right now.
                            </div>
                        )}
                    </div>

                    <div className="space-y-2">
                        <h3 className="text-base font-medium">Recent Auth Attempts</h3>
                        {history.attempts.length === 0 ? (
                            <div className="text-sm text-gray-500">No auth attempts have been recorded yet.</div>
                        ) : (
                            <div className="border rounded p-3 bg-white/5 space-y-3">
                                {history.attempts.map((attempt) => (
                                    <div
                                        key={attempt.attempt_reference}
                                        className="border-b border-gray-700/40 pb-3 last:border-b-0 text-sm"
                                    >
                                        <div className="flex items-center justify-between gap-3">
                                            <div className="font-medium">{attempt.attempt_reference}</div>
                                            <div
                                                className={`rounded border px-2 py-0.5 text-xs ${getStateBadgeClass(attempt.state)}`}
                                            >
                                                {attempt.state}
                                            </div>
                                        </div>
                                        <div className="text-xs text-gray-400 mt-1">
                                            Started: {formatTimestamp(attempt.started_at)} · Updated: {formatTimestamp(attempt.updated_at)}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            Finished: {formatTimestamp(attempt.finished_at)} · OTP required:{' '}
                                            {attempt.otp_required ? 'yes' : 'no'}
                                        </div>
                                        {attempt.failure_reason && (
                                            <div className="text-xs text-rose-200 mt-1">
                                                Failure: {formatFailureReason(attempt.failure_reason)}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="space-y-2">
                        <h3 className="text-base font-medium">Audit Log</h3>
                        {auditLogs.length === 0 ? (
                            <div className="text-sm text-gray-500">No MLS auth audit logs yet.</div>
                        ) : (
                            <div className="border rounded p-3 bg-white/5 space-y-3">
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
                                        {log.details && (
                                            <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                                {formatAuditDetails(log.details)}
                                            </pre>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </>
            )}
        </section>
    );
};

export default MlsAuthPanel;
