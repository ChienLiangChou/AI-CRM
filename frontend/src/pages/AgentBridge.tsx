import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, CalendarClock, Database, RefreshCw, RotateCcw, Send, ShieldCheck, Sparkles, Target, Zap } from 'lucide-react';
import { crmService } from '../services/api';
import type {
    AgentBridgeAuditDashboardResponse,
    AgentBridgeAutomationCadence,
    AgentBridgeAutomationResponse,
    AgentBridgeAutomationStatus,
    AgentBridgeCapability,
    AgentBridgeExecutionResponse,
    AgentBridgeMemoryEntry,
    AgentBridgeTarget,
    AgentBridgeSessionResponse,
    AgentBridgeStatusResponse,
} from '../services/api';
import './AgentBridge.css';

const defaultContext = 'Review the available SKC client and property context, prepare bounded OpenClaw research, and prepare Codex Chrome extension browser evidence review before any external action.';

const executionProfileOptions: Record<AgentBridgeTarget, { value: string; label: string }[]> = {
    openclaw: [
        { value: 'standalone_sop', label: 'OpenClaw standalone SOP' },
        { value: 'browsertest_public_research', label: 'OpenClaw public research' },
        { value: 'formtest_dummy_listing_package', label: 'OpenClaw dummy listing package' },
        { value: 'emaildrafttest_dummy_email', label: 'OpenClaw dummy email draft' },
        { value: 'localfilestest_one_file_summary', label: 'OpenClaw one-file summary' },
    ],
    codex_chrome_extension: [
        { value: 'skc_ui_test', label: 'Chrome SKC UI test' },
        { value: 'gmail_draft_check', label: 'Chrome Gmail draft check' },
        { value: 'gmail_thread_summary', label: 'Chrome approved Gmail thread summary' },
        { value: 'listing_tab_comparison', label: 'Chrome listing tab comparison' },
    ],
    skc_agent_os: [
        { value: 'internal_review', label: 'SKC internal review' },
    ],
};

const AgentBridge = () => {
    const [status, setStatus] = useState<AgentBridgeStatusResponse | null>(null);
    const [session, setSession] = useState<AgentBridgeSessionResponse | null>(null);
    const [executions, setExecutions] = useState<AgentBridgeExecutionResponse[]>([]);
    const [memoryEntries, setMemoryEntries] = useState<AgentBridgeMemoryEntry[]>([]);
    const [auditDashboard, setAuditDashboard] = useState<AgentBridgeAuditDashboardResponse | null>(null);
    const [automations, setAutomations] = useState<AgentBridgeAutomationResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [executionSubmitting, setExecutionSubmitting] = useState(false);
    const [automationSubmitting, setAutomationSubmitting] = useState(false);
    const [automationRunning, setAutomationRunning] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [copiedTarget, setCopiedTarget] = useState<string | null>(null);
    const [resultDrafts, setResultDrafts] = useState<Record<string, string>>({});
    const [form, setForm] = useState({
        workflow: 'seller_listing_safety',
        client_name: '',
        property_address: '',
        requested_outcome: 'Prepare a safe operator-reviewed recommendation.',
        source_context: defaultContext,
        include_openclaw: true,
        include_codex_chrome: true,
    });
    const [executionForm, setExecutionForm] = useState<{
        target: AgentBridgeTarget;
        execution_profile: string;
        approved_by_kevin: boolean;
        operator_notes: string;
    }>({
        target: 'openclaw',
        execution_profile: 'browsertest_public_research',
        approved_by_kevin: false,
        operator_notes: '',
    });
    const [automationForm, setAutomationForm] = useState<{
        name: string;
        target: AgentBridgeTarget;
        execution_profile: string;
        cadence: AgentBridgeAutomationCadence;
        status: AgentBridgeAutomationStatus;
        max_retries: number;
        operator_notes: string;
    }>({
        name: 'Daily public research prep',
        target: 'openclaw',
        execution_profile: 'browsertest_public_research',
        cadence: 'daily',
        status: 'active',
        max_retries: 2,
        operator_notes: '',
    });

    const loadStatus = async () => {
        setLoading(true);
        setError(null);
        try {
            const [bridgeStatus, executionData, memoryData, auditData, automationData] = await Promise.all([
                crmService.getAgentBridgeStatus(),
                crmService.listAgentBridgeExecutions(),
                crmService.listAgentBridgeMemory(),
                crmService.getAgentBridgeAuditDashboard(),
                crmService.listAgentBridgeAutomations(),
            ]);
            setStatus(bridgeStatus);
            setExecutions(executionData);
            setMemoryEntries(memoryData.entries);
            setAuditDashboard(auditData);
            setAutomations(automationData.automations);
        } catch (e) {
            console.error('Failed to load Agent Bridge status:', e);
            setError('Agent Bridge status could not be loaded.');
        } finally {
            setLoading(false);
        }
    };

    const refreshOperationalState = async () => {
        const [executionData, memoryData, auditData, automationData] = await Promise.all([
            crmService.listAgentBridgeExecutions(),
            crmService.listAgentBridgeMemory(),
            crmService.getAgentBridgeAuditDashboard(),
            crmService.listAgentBridgeAutomations(),
        ]);
        setExecutions(executionData);
        setMemoryEntries(memoryData.entries);
        setAuditDashboard(auditData);
        setAutomations(automationData.automations);
    };

    useEffect(() => {
        loadStatus();
    }, []);

    const createSession = async () => {
        if (!form.source_context.trim()) {
            setError('Source context is required.');
            return;
        }

        setSubmitting(true);
        setError(null);
        setCopiedTarget(null);
        try {
            const result = await crmService.createAgentBridgeSession({
                workflow: form.workflow,
                client_name: form.client_name || undefined,
                property_address: form.property_address || undefined,
                requested_outcome: form.requested_outcome || undefined,
                source_context: form.source_context,
                include_openclaw: form.include_openclaw,
                include_codex_chrome: form.include_codex_chrome,
            });
            setSession(result);
        } catch (e) {
            console.error('Failed to create Agent Bridge session:', e);
            setError('Agent Bridge session could not be created.');
        } finally {
            setSubmitting(false);
        }
    };

    const createExecution = async () => {
        if (!form.source_context.trim()) {
            setError('Source context is required.');
            return;
        }

        setExecutionSubmitting(true);
        setError(null);
        try {
            const execution = await crmService.createAgentBridgeExecution({
                target: executionForm.target,
                workflow: form.workflow,
                execution_profile: executionForm.execution_profile,
                client_name: form.client_name || undefined,
                property_address: form.property_address || undefined,
                requested_outcome: form.requested_outcome || undefined,
                source_context: form.source_context,
                approved_by_kevin: executionForm.approved_by_kevin,
                operator_notes: executionForm.operator_notes || undefined,
            });
            setExecutions((current) => [execution, ...current.filter((item) => item.run_id !== execution.run_id)]);
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to create Agent Bridge execution:', e);
            setError('Agent Bridge execution ticket could not be created.');
        } finally {
            setExecutionSubmitting(false);
        }
    };

    const approveExecution = async (runId: string) => {
        setError(null);
        try {
            const execution = await crmService.approveAgentBridgeExecution(runId, {
                approved_by_kevin: true,
                operator_notes: 'Kevin approval confirmed in SKC Agent OS.',
            });
            setExecutions((current) => current.map((item) => item.run_id === runId ? execution : item));
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to approve Agent Bridge execution:', e);
            setError('Agent Bridge execution could not be approved.');
        }
    };

    const recordResult = async (execution: AgentBridgeExecutionResponse) => {
        const resultSummary = resultDrafts[execution.run_id]?.trim();
        if (!resultSummary) {
            setError('Result summary is required before recording an external result.');
            return;
        }

        setError(null);
        try {
            const updated = await crmService.recordAgentBridgeExecutionResult(execution.run_id, {
                status: 'completed',
                result_summary: resultSummary,
                result_payload: {
                    target: execution.target,
                    execution_profile: execution.execution_profile,
                    external_action_taken: false,
                    recorded_from: 'Agent Bridge UI',
                },
            });
            setExecutions((current) => current.map((item) => item.run_id === execution.run_id ? updated : item));
            setResultDrafts((current) => ({ ...current, [execution.run_id]: '' }));
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to record Agent Bridge execution result:', e);
            setError('Agent Bridge execution result could not be recorded.');
        }
    };

    const createAutomation = async () => {
        if (!automationForm.name.trim() || !form.source_context.trim()) {
            setError('Automation name and SKC context are required.');
            return;
        }

        setAutomationSubmitting(true);
        setError(null);
        try {
            const automation = await crmService.createAgentBridgeAutomation({
                name: automationForm.name,
                workflow: form.workflow,
                target: automationForm.target,
                execution_profile: automationForm.execution_profile,
                source_context: form.source_context,
                requested_outcome: form.requested_outcome || undefined,
                cadence: automationForm.cadence,
                status: automationForm.status,
                max_retries: automationForm.max_retries,
                operator_notes: automationForm.operator_notes || undefined,
            });
            setAutomations((current) => [automation, ...current.filter((item) => item.automation_id !== automation.automation_id)]);
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to create Agent Bridge automation:', e);
            setError('Agent Bridge automation rule could not be created.');
        } finally {
            setAutomationSubmitting(false);
        }
    };

    const runDueAutomations = async () => {
        setAutomationRunning(true);
        setError(null);
        try {
            await crmService.runDueAgentBridgeAutomations();
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to run due Agent Bridge automations:', e);
            setError('Due automation check could not be completed.');
        } finally {
            setAutomationRunning(false);
        }
    };

    const retryAutomation = async (automationId: string) => {
        setError(null);
        try {
            await crmService.retryAgentBridgeAutomation(automationId);
            await refreshOperationalState();
        } catch (e) {
            console.error('Failed to retry Agent Bridge automation:', e);
            setError('Automation retry could not be prepared.');
        }
    };

    const copyPrompt = async (target: string, prompt: string) => {
        if (!navigator.clipboard) {
            setError('Clipboard is not available in this browser.');
            return;
        }
        await navigator.clipboard.writeText(prompt);
        setCopiedTarget(target);
    };

    if (loading) {
        return (
            <div className="agent-bridge-page p-2 sm:p-6">
                <div className="p-8 text-center text-gray-400">
                    <div className="spinner mx-auto mb-3"></div>
                    Loading Agent Bridge...
                </div>
            </div>
        );
    }

    return (
        <div className="agent-bridge-page animate-fade-in p-2 sm:p-6">
            <header className="agent-bridge-header">
                <div className="min-w-0">
                    <p className="page-kicker">SKC Agent OS</p>
                    <h1>Agent Bridge</h1>
                    <p className="page-subtitle">OpenClaw and Codex Chrome extension handoffs with operator review.</p>
                </div>
                <button onClick={loadStatus} className="btn btn-ghost refresh-button">
                    <RefreshCw size={14} /> Refresh
                </button>
            </header>

            {error && (
                <div className="bridge-alert">
                    <AlertTriangle size={16} />
                    <span>{error}</span>
                </div>
            )}

            {status && (
                <section className="bridge-status-grid">
                    <div className="bridge-status-card bridge-status-card-main">
                        <div>
                            <p className="status-label">Bridge status</p>
                            <h2>{status.bridge_status.replaceAll('_', ' ')}</h2>
                        </div>
                        <div className="status-pill">{status.mode.replaceAll('_', ' ')}</div>
                        <p>{status.safety_boundary}</p>
                    </div>
                    {status.capabilities.map((capability) => (
                        <CapabilityCard key={capability.key} capability={capability} />
                    ))}
                </section>
            )}

            <section className="bridge-workspace">
                <div className="bridge-composer glass-panel">
                    <div className="panel-header">
                        <h2><Sparkles size={18} /> Create bridge session</h2>
                    </div>
                    <div className="composer-grid">
                        <label className="field">
                            <span>Workflow</span>
                            <input
                                value={form.workflow}
                                onChange={(e) => setForm({ ...form, workflow: e.target.value })}
                                className="input-field"
                            />
                        </label>
                        <label className="field">
                            <span>Client</span>
                            <input
                                value={form.client_name}
                                onChange={(e) => setForm({ ...form, client_name: e.target.value })}
                                className="input-field"
                                placeholder="Optional"
                            />
                        </label>
                        <label className="field composer-wide">
                            <span>Property / task handle</span>
                            <input
                                value={form.property_address}
                                onChange={(e) => setForm({ ...form, property_address: e.target.value })}
                                className="input-field"
                                placeholder="Optional"
                            />
                        </label>
                        <label className="field composer-wide">
                            <span>Requested outcome</span>
                            <input
                                value={form.requested_outcome}
                                onChange={(e) => setForm({ ...form, requested_outcome: e.target.value })}
                                className="input-field"
                            />
                        </label>
                        <label className="field composer-wide">
                            <span>SKC context</span>
                            <textarea
                                value={form.source_context}
                                onChange={(e) => setForm({ ...form, source_context: e.target.value })}
                                className="input-field"
                                rows={5}
                            />
                        </label>
                    </div>

                    <div className="bridge-toggle-row">
                        <label className="bridge-toggle">
                            <input
                                type="checkbox"
                                checked={form.include_openclaw}
                                onChange={(e) => setForm({ ...form, include_openclaw: e.target.checked })}
                            />
                            <span>OpenClaw handoff</span>
                        </label>
                        <label className="bridge-toggle">
                            <input
                                type="checkbox"
                                checked={form.include_codex_chrome}
                                onChange={(e) => setForm({ ...form, include_codex_chrome: e.target.checked })}
                            />
                            <span>Codex Chrome handoff</span>
                        </label>
                    </div>

                    <div className="bridge-action-row">
                        <button
                            onClick={createSession}
                            disabled={submitting || !form.source_context.trim()}
                            className="btn btn-primary"
                        >
                            <Send size={14} />
                            {submitting ? 'Creating...' : 'Create handoff'}
                        </button>
                    </div>
                </div>

                <aside className="bridge-review glass-panel">
                    <div className="panel-header">
                        <h2><Target size={18} /> Review state</h2>
                    </div>
                    {session ? (
                        <div className="review-content">
                            <div className="review-session">
                                <span>{session.status.replaceAll('_', ' ')}</span>
                                <strong>{session.session_id}</strong>
                            </div>
                            <p className="review-summary">{session.summary}</p>
                            <div className="review-list">
                                <h3>Approvals required</h3>
                                {session.approvals_required.map((approval) => (
                                    <p key={approval}><ArrowRight size={13} /> {approval}</p>
                                ))}
                            </div>
                            <div className="review-list">
                                <h3>Audit notes</h3>
                                {session.audit_notes.map((note) => (
                                    <p key={note}><Zap size={13} /> {note}</p>
                                ))}
                            </div>
                        </div>
                    ) : (
                        <div className="empty-review">
                            <Zap size={28} />
                            <p>No bridge session created yet.</p>
                        </div>
                    )}
                </aside>
            </section>

            <section className="execution-layer glass-panel">
                <div className="panel-header execution-header">
                    <div>
                        <p className="status-label">Controlled execution layer v1</p>
                        <h2><Zap size={18} /> External runner tickets</h2>
                    </div>
                    <span className="status-pill">approval gated</span>
                </div>

                <div className="execution-create">
                    <label className="field">
                        <span>Target</span>
                        <select
                            value={executionForm.target}
                            onChange={(e) => {
                                const nextTarget = e.target.value as AgentBridgeTarget;
                                setExecutionForm({
                                    ...executionForm,
                                    target: nextTarget,
                                    execution_profile: executionProfileOptions[nextTarget][0].value,
                                });
                            }}
                            className="input-field"
                        >
                            <option value="openclaw">OpenClaw</option>
                            <option value="codex_chrome_extension">Codex Chrome</option>
                            <option value="skc_agent_os">SKC internal review</option>
                        </select>
                    </label>
                    <label className="field">
                        <span>Execution profile</span>
                        <select
                            value={executionForm.execution_profile}
                            onChange={(e) => setExecutionForm({ ...executionForm, execution_profile: e.target.value })}
                            className="input-field"
                        >
                            {executionProfileOptions[executionForm.target].map((profile) => (
                                <option key={profile.value} value={profile.value}>{profile.label}</option>
                            ))}
                        </select>
                    </label>
                    <label className="field execution-notes">
                        <span>Operator notes</span>
                        <input
                            value={executionForm.operator_notes}
                            onChange={(e) => setExecutionForm({ ...executionForm, operator_notes: e.target.value })}
                            className="input-field"
                            placeholder="Optional approval scope notes"
                        />
                    </label>
                    <label className="bridge-toggle execution-approval">
                        <input
                            type="checkbox"
                            checked={executionForm.approved_by_kevin}
                            onChange={(e) => setExecutionForm({ ...executionForm, approved_by_kevin: e.target.checked })}
                        />
                        <span>Kevin approval confirmed</span>
                    </label>
                    <button
                        onClick={createExecution}
                        disabled={executionSubmitting || !form.source_context.trim()}
                        className="btn btn-accent execution-create-button"
                    >
                        <Zap size={14} />
                        {executionSubmitting ? 'Creating...' : 'Create execution ticket'}
                    </button>
                </div>

                <div className="execution-list">
                    {executions.length > 0 ? executions.map((execution) => (
                        <article key={execution.run_id} className="execution-card">
                            <div className="execution-card-top">
                                <div>
                                    <p className="status-label">{execution.target_label}</p>
                                    <h3>{execution.workflow}</h3>
                                    <small>{execution.run_id}</small>
                                </div>
                                <span className="status-pill">{execution.status.replaceAll('_', ' ')}</span>
                            </div>
                            <p className="execution-summary">{execution.summary}</p>
                            <div className="execution-command">
                                <span>Execution package</span>
                                <pre>{execution.command_text || execution.handoff_prompt}</pre>
                            </div>
                            <div className="execution-card-actions">
                                {!execution.approved_by_kevin && (
                                    <button onClick={() => approveExecution(execution.run_id)} className="btn btn-primary">
                                        Approve ticket
                                    </button>
                                )}
                                <button
                                    onClick={() => copyPrompt(execution.run_id, execution.command_text || execution.handoff_prompt)}
                                    className="btn btn-ghost"
                                >
                                    {copiedTarget === execution.run_id ? 'Copied' : 'Copy execution package'}
                                </button>
                            </div>
                            <div className="execution-result">
                                <textarea
                                    value={resultDrafts[execution.run_id] || ''}
                                    onChange={(e) => setResultDrafts({ ...resultDrafts, [execution.run_id]: e.target.value })}
                                    className="input-field"
                                    rows={3}
                                    placeholder="Paste external runner or browser result summary for SKC review..."
                                />
                                <button onClick={() => recordResult(execution)} className="btn btn-ghost">
                                    Record result
                                </button>
                            </div>
                            {execution.result_summary && (
                                <div className="recorded-result">
                                    <span>Recorded result</span>
                                    <p>{execution.result_summary}</p>
                                </div>
                            )}
                        </article>
                    )) : (
                        <div className="empty-executions">
                            <Zap size={24} />
                            <p>No execution tickets yet.</p>
                        </div>
                    )}
                </div>
            </section>

            {auditDashboard && (
                <section className="memory-audit-layer">
                    <div className="audit-dashboard glass-panel">
                        <div className="panel-header execution-header">
                            <div>
                                <p className="status-label">Source-of-truth memory layer v1</p>
                                <h2><Database size={18} /> Audit dashboard</h2>
                            </div>
                            <span className="status-pill">review visible</span>
                        </div>
                        <div className="audit-metrics">
                            <Metric label="Executions" value={auditDashboard.execution_count} />
                            <Metric label="Memory events" value={auditDashboard.memory_event_count} />
                            <Metric label="Waiting approval" value={auditDashboard.waiting_approval_count} />
                            <Metric label="Needs review" value={auditDashboard.needs_review_count} />
                            <Metric label="Active automations" value={auditDashboard.active_automation_count} />
                            <Metric label="Due now" value={auditDashboard.due_automation_count} />
                        </div>
                        <div className="guardrail-list">
                            {auditDashboard.guardrails.map((guardrail) => (
                                <p key={guardrail}><ShieldCheck size={14} /> {guardrail}</p>
                            ))}
                        </div>
                    </div>

                    <div className="memory-feed glass-panel">
                        <div className="panel-header">
                            <h2><Database size={18} /> Recent memory</h2>
                        </div>
                        <div className="memory-list">
                            {memoryEntries.length > 0 ? memoryEntries.slice(0, 8).map((entry) => (
                                <article key={entry.memory_id} className="memory-event">
                                    <div>
                                        <p className="status-label">{entry.event_type.replaceAll('_', ' ')}</p>
                                        <h3>{entry.workflow}</h3>
                                    </div>
                                    <p>{entry.summary}</p>
                                    <small>
                                        {entry.decision_status.replaceAll('_', ' ')}
                                        {entry.run_id ? ` / ${entry.run_id}` : ''}
                                    </small>
                                </article>
                            )) : (
                                <div className="empty-executions">
                                    <Database size={24} />
                                    <p>No memory events yet.</p>
                                </div>
                            )}
                        </div>
                    </div>
                </section>
            )}

            <section className="automation-layer glass-panel">
                <div className="panel-header execution-header">
                    <div>
                        <p className="status-label">Automation engine v1</p>
                        <h2><CalendarClock size={18} /> Preparation scheduler</h2>
                    </div>
                    <button onClick={runDueAutomations} disabled={automationRunning} className="btn btn-ghost">
                        <RefreshCw size={14} />
                        {automationRunning ? 'Checking...' : 'Run due checks'}
                    </button>
                </div>

                <div className="automation-create">
                    <label className="field">
                        <span>Name</span>
                        <input
                            value={automationForm.name}
                            onChange={(e) => setAutomationForm({ ...automationForm, name: e.target.value })}
                            className="input-field"
                        />
                    </label>
                    <label className="field">
                        <span>Target</span>
                        <select
                            value={automationForm.target}
                            onChange={(e) => {
                                const nextTarget = e.target.value as AgentBridgeTarget;
                                setAutomationForm({
                                    ...automationForm,
                                    target: nextTarget,
                                    execution_profile: executionProfileOptions[nextTarget][0].value,
                                });
                            }}
                            className="input-field"
                        >
                            <option value="openclaw">OpenClaw</option>
                            <option value="codex_chrome_extension">Codex Chrome</option>
                            <option value="skc_agent_os">SKC internal review</option>
                        </select>
                    </label>
                    <label className="field">
                        <span>Profile</span>
                        <select
                            value={automationForm.execution_profile}
                            onChange={(e) => setAutomationForm({ ...automationForm, execution_profile: e.target.value })}
                            className="input-field"
                        >
                            {executionProfileOptions[automationForm.target].map((profile) => (
                                <option key={profile.value} value={profile.value}>{profile.label}</option>
                            ))}
                        </select>
                    </label>
                    <label className="field">
                        <span>Cadence</span>
                        <select
                            value={automationForm.cadence}
                            onChange={(e) => setAutomationForm({ ...automationForm, cadence: e.target.value as AgentBridgeAutomationCadence })}
                            className="input-field"
                        >
                            <option value="manual">Manual</option>
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                        </select>
                    </label>
                    <label className="field">
                        <span>Status</span>
                        <select
                            value={automationForm.status}
                            onChange={(e) => setAutomationForm({ ...automationForm, status: e.target.value as AgentBridgeAutomationStatus })}
                            className="input-field"
                        >
                            <option value="active">Active</option>
                            <option value="paused">Paused</option>
                        </select>
                    </label>
                    <label className="field">
                        <span>Retries</span>
                        <input
                            type="number"
                            min={0}
                            max={5}
                            value={automationForm.max_retries}
                            onChange={(e) => setAutomationForm({ ...automationForm, max_retries: Number(e.target.value) })}
                            className="input-field"
                        />
                    </label>
                    <label className="field automation-notes">
                        <span>Operator notes</span>
                        <input
                            value={automationForm.operator_notes}
                            onChange={(e) => setAutomationForm({ ...automationForm, operator_notes: e.target.value })}
                            className="input-field"
                            placeholder="Optional scope notes"
                        />
                    </label>
                    <button
                        onClick={createAutomation}
                        disabled={automationSubmitting || !automationForm.name.trim() || !form.source_context.trim()}
                        className="btn btn-accent automation-create-button"
                    >
                        <CalendarClock size={14} />
                        {automationSubmitting ? 'Creating...' : 'Create automation rule'}
                    </button>
                </div>

                <div className="automation-list">
                    {automations.length > 0 ? automations.map((automation) => (
                        <article key={automation.automation_id} className="automation-row">
                            <div>
                                <p className="status-label">{automation.target_label}</p>
                                <h3>{automation.name}</h3>
                                <small>{automation.automation_id}</small>
                            </div>
                            <div className="automation-meta">
                                <span>{automation.cadence}</span>
                                <span>{automation.status}</span>
                                <span>retry {automation.retry_count}/{automation.max_retries}</span>
                            </div>
                            <div className="automation-meta">
                                <span>next {automation.next_due_at ? new Date(automation.next_due_at).toLocaleString() : 'manual'}</span>
                                <span>last {automation.last_run_id || 'none'}</span>
                            </div>
                            <button onClick={() => retryAutomation(automation.automation_id)} className="btn btn-ghost">
                                <RotateCcw size={14} /> Retry
                            </button>
                        </article>
                    )) : (
                        <div className="empty-executions">
                            <CalendarClock size={24} />
                            <p>No automation rules yet.</p>
                        </div>
                    )}
                </div>
            </section>

            {session && (
                <section className="handoff-grid">
                    {session.handoffs.map((handoff) => (
                        <article key={handoff.target} className="handoff-card glass-panel">
                            <div className="handoff-topline">
                                <div>
                                    <span className="status-label">{handoff.target_label}</span>
                                    <h2>{handoff.title}</h2>
                                </div>
                                <span className="status-pill">{handoff.status.replaceAll('_', ' ')}</span>
                            </div>
                            <div className="handoff-instructions">
                                {handoff.instructions.map((instruction) => (
                                    <p key={instruction}><ArrowRight size={13} /> {instruction}</p>
                                ))}
                            </div>
                            <pre>{handoff.prompt}</pre>
                            <button onClick={() => copyPrompt(handoff.target, handoff.prompt)} className="btn btn-ghost copy-button">
                                {copiedTarget === handoff.target ? 'Copied' : 'Copy prompt'}
                            </button>
                        </article>
                    ))}
                </section>
            )}
        </div>
    );
};

const Metric = ({ label, value }: { label: string; value: number }) => (
    <div className="audit-metric">
        <span>{label}</span>
        <strong>{value}</strong>
    </div>
);

const CapabilityCard = ({ capability }: { capability: AgentBridgeCapability }) => (
    <article className="bridge-status-card">
        <div className="capability-heading">
            <span className="status-dot"></span>
            <div>
                <p className="status-label">{capability.product_surface}</p>
                <h2>{capability.label}</h2>
            </div>
        </div>
        <p>{capability.description}</p>
        <div className="capability-footer">
            <span>{capability.status.replaceAll('_', ' ')}</span>
            <small>{capability.next_action}</small>
        </div>
    </article>
);

export default AgentBridge;
