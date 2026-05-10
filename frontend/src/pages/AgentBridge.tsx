import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, RefreshCw, Send, Sparkles, Target, Zap } from 'lucide-react';
import { crmService } from '../services/api';
import type {
    AgentBridgeCapability,
    AgentBridgeSessionResponse,
    AgentBridgeStatusResponse,
} from '../services/api';
import './AgentBridge.css';

const defaultContext = 'Review the available SKC client and property context, prepare bounded OpenClaw research, and prepare Codex Chrome extension browser evidence review before any external action.';

const AgentBridge = () => {
    const [status, setStatus] = useState<AgentBridgeStatusResponse | null>(null);
    const [session, setSession] = useState<AgentBridgeSessionResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [copiedTarget, setCopiedTarget] = useState<string | null>(null);
    const [form, setForm] = useState({
        workflow: 'seller_listing_safety',
        client_name: '',
        property_address: '',
        requested_outcome: 'Prepare a safe operator-reviewed recommendation.',
        source_context: defaultContext,
        include_openclaw: true,
        include_codex_chrome: true,
    });

    const loadStatus = async () => {
        setLoading(true);
        setError(null);
        try {
            setStatus(await crmService.getAgentBridgeStatus());
        } catch (e) {
            console.error('Failed to load Agent Bridge status:', e);
            setError('Agent Bridge status could not be loaded.');
        } finally {
            setLoading(false);
        }
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

                    <button
                        onClick={createSession}
                        disabled={submitting || !form.source_context.trim()}
                        className="btn btn-primary bridge-submit"
                    >
                        <Send size={14} />
                        {submitting ? 'Creating...' : 'Create handoff'}
                    </button>
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
