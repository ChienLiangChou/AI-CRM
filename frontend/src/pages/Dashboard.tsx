import { useEffect, useState } from 'react';
import { crmService } from '../services/api';
import type { Contact, Nudge, SegmentGroup, PipelineInsightsResponse, VoiceMemoResponse } from '../services/api';
import { Target, TrendingUp, Users, Phone, Mail, ArrowRight, RefreshCw, AlertTriangle, Zap, Flame, Snowflake, Moon, Mic, Send } from 'lucide-react';
import './Dashboard.css';

const Dashboard = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [nudges, setNudges] = useState<Nudge[]>([]);
    const [segments, setSegments] = useState<SegmentGroup[]>([]);
    const [insights, setInsights] = useState<PipelineInsightsResponse | null>(null);
    const [loading, setLoading] = useState(true);

    // Voice memo state
    const [memoText, setMemoText] = useState('');
    const [memoProcessing, setMemoProcessing] = useState(false);
    const [memoResult, setMemoResult] = useState<VoiceMemoResponse | null>(null);

    const loadAll = async () => {
        setLoading(true);
        try {
            const [contactsData, nudgesData, segmentsData, insightsData] = await Promise.all([
                crmService.getContacts(),
                crmService.getNudges(),
                crmService.getSegments(),
                crmService.getPipelineInsights(),
            ]);
            setContacts(contactsData);
            setNudges(nudgesData.nudges);
            setSegments(segmentsData.segments);
            setInsights(insightsData);
        } catch (error) {
            console.error('Failed to load dashboard:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAll();
    }, []);

    const totalLeads = contacts.length;
    const hotLeads = contacts.filter(c => c.lead_score >= 80).length;
    const avgScore = contacts.length ? Math.round(contacts.reduce((a, b) => a + b.lead_score, 0) / contacts.length) : 0;

    const urgencyStyles: Record<string, { bg: string; text: string; border: string; icon: string }> = {
        high: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30', icon: '🔴' },
        medium: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30', icon: '🟡' },
        low: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30', icon: '🔵' },
    };

    const actionIcons: Record<string, React.ReactNode> = {
        call: <Phone size={14} />,
        email: <Mail size={14} />,
        advance: <ArrowRight size={14} />,
        're-engage': <RefreshCw size={14} />,
    };

    const segmentIcons: Record<string, React.ReactNode> = {
        iron_fan: <Flame size={18} className="text-orange-400" />,
        high_potential: <Zap size={18} className="text-yellow-400" />,
        sleeping: <Moon size={18} className="text-indigo-400" />,
        cold: <Snowflake size={18} className="text-cyan-400" />,
    };

    const segmentColors: Record<string, string> = {
        iron_fan: 'from-orange-500/20 to-red-500/10',
        high_potential: 'from-yellow-500/20 to-amber-500/10',
        sleeping: 'from-indigo-500/20 to-purple-500/10',
        cold: 'from-cyan-500/20 to-blue-500/10',
    };

    if (loading) return <div className="p-8 text-center text-gray-400"><div className="spinner mx-auto mb-3"></div>Loading AI Dashboard...</div>;

    return (
        <div className="dashboard-page animate-fade-in p-2 sm:p-6">
            <header className="mb-6 sm:mb-8">
                <div className="flex justify-between items-start gap-3">
                    <div className="min-w-0">
                        <h1 className="text-xl sm:text-3xl font-bold mb-1 sm:mb-2">Welcome back, <span className="text-gradient">Kevin</span></h1>
                        <p className="text-gray-400 text-sm sm:text-base">Here is what's happening in your pipeline today.</p>
                    </div>
                    <button onClick={loadAll} className="btn btn-ghost text-xs sm:text-sm gap-2 flex items-center shrink-0">
                        <RefreshCw size={14} /> Refresh
                    </button>
                </div>
            </header>

            {/* Voice Memo Quick Input */}
            <div className="glass-panel mb-6 sm:mb-8">
                <div className="p-4 sm:p-5 border-b border-white/10">
                    <h2 className="text-base sm:text-lg font-bold flex items-center gap-2">
                        <Mic size={18} className="text-green-400" /> 語音備忘錄 Quick Entry
                    </h2>
                </div>
                <div className="p-4 sm:p-5">
                    <div className="flex flex-col sm:flex-row gap-3">
                        <textarea
                            value={memoText}
                            onChange={(e) => setMemoText(e.target.value)}
                            placeholder="貼上語音轉文字... 例如：王太太今天看了萬錦獨立屋，嫌廚房小但喜歡學區，預算1.5M"
                            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm resize-none outline-none focus:border-purple-500 transition-colors"
                            rows={2}
                        />
                        <button
                            onClick={async () => {
                                if (!memoText.trim()) return;
                                setMemoProcessing(true);
                                setMemoResult(null);
                                try {
                                    const result = await crmService.voiceMemo(memoText);
                                    setMemoResult(result);
                                    if (result.success) {
                                        setMemoText('');
                                        loadAll();
                                    }
                                } catch (e) {
                                    console.error('Voice memo failed:', e);
                                } finally {
                                    setMemoProcessing(false);
                                }
                            }}
                            disabled={memoProcessing || !memoText.trim()}
                            className="px-5 py-3 bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 rounded-xl font-semibold text-sm transition-all disabled:opacity-50 flex items-center gap-2 shrink-0"
                        >
                            <Send size={14} />
                            {memoProcessing ? 'Processing...' : 'Analyze'}
                        </button>
                    </div>
                    {memoResult && (
                        <div className={`mt-4 p-4 rounded-xl border ${memoResult.success ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
                            <p className="text-sm font-medium mb-2">{memoResult.message}</p>
                            {memoResult.extracted_data && (
                                <div className="text-xs text-gray-400 space-y-1">
                                    {(() => {
                                        const d = memoResult.extracted_data as any; return (<>
                                            {d.areas && <p>📍 Areas: {d.areas.join(', ')}</p>}
                                            {d.budget && <p>💰 Budget: ${Number(d.budget).toLocaleString()}</p>}
                                            {d.likes && <p>👍 Likes: {d.likes.join(', ')}</p>}
                                            {d.dislikes && <p>👎 Dislikes: {d.dislikes.join(', ')}</p>}
                                        </>);
                                    })()}
                                </div>
                            )}
                            {memoResult.email_draft && (
                                <div className="mt-3 p-3 bg-white/5 rounded-lg">
                                    <p className="text-xs text-purple-400 font-medium mb-1">📧 {memoResult.email_draft.subject}</p>
                                    <p className="text-xs text-gray-400 whitespace-pre-line">{memoResult.email_draft.body.substring(0, 200)}...</p>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Metrics Row */}
            <div className="grid grid-cols-3 gap-3 sm:gap-6 mb-6 sm:mb-8">
                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6">
                    <div className="p-2 sm:p-3 bg-blue-500/20 rounded-xl text-blue-400">
                        <Users size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Total</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{totalLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6 border-l-2 sm:border-l-4 border-l-red-500">
                    <div className="p-2 sm:p-3 bg-red-500/20 rounded-xl text-red-500">
                        <Target size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Hot Leads</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{hotLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6 border-l-2 sm:border-l-4 border-l-purple-500">
                    <div className="p-2 sm:p-3 bg-purple-500/20 rounded-xl text-purple-400">
                        <TrendingUp size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Avg Score</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{avgScore}</h3>
                    </div>
                </div>
            </div>

            {/* Two-column layout: Nudges + Segments */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 mb-6 sm:mb-8">

                {/* AI Smart Nudges */}
                <div className="glass-panel">
                    <div className="p-5 border-b border-white/10 flex items-center justify-between">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            <AlertTriangle size={18} className="text-yellow-400" /> AI Smart Nudges
                        </h2>
                        <span className="text-xs text-gray-500 bg-white/5 px-2 py-1 rounded-full">
                            {nudges.length} actions
                        </span>
                    </div>
                    <div className="divide-y divide-white/5 max-h-[400px] overflow-y-auto">
                        {nudges.length > 0 ? nudges.map((nudge, i) => {
                            const style = urgencyStyles[nudge.urgency] || urgencyStyles.low;
                            return (
                                <div key={i} className={`p-4 hover:bg-white/5 transition-colors ${style.bg}`}>
                                    <div className="flex items-start gap-3">
                                        <span className="text-lg mt-0.5">{style.icon}</span>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="font-semibold text-sm">{nudge.contact_name}</span>
                                                {nudge.company && <span className="text-xs text-gray-500">• {nudge.company}</span>}
                                            </div>
                                            <p className="text-sm text-gray-300">{nudge.message}</p>
                                        </div>
                                        <div className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full border ${style.border} ${style.text}`}>
                                            {actionIcons[nudge.action]}
                                            <span className="capitalize">{nudge.action}</span>
                                        </div>
                                    </div>
                                </div>
                            );
                        }) : (
                            <div className="p-8 text-center text-gray-500">
                                ✅ No urgent actions needed. Pipeline looks great!
                            </div>
                        )}
                    </div>
                </div>

                {/* Customer Segments */}
                <div className="glass-panel">
                    <div className="p-5 border-b border-white/10">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            🏷️ Customer Segments
                        </h2>
                    </div>
                    <div className="p-5 space-y-4">
                        {segments.length > 0 ? segments.map((seg) => {
                            const total = contacts.length || 1;
                            const pct = Math.round(seg.count / total * 100);
                            const gradient = segmentColors[seg.key] || 'from-gray-500/20 to-gray-500/10';
                            return (
                                <div key={seg.key} className={`rounded-xl p-4 bg-gradient-to-r ${gradient} border border-white/5`}>
                                    <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2">
                                            {segmentIcons[seg.key]}
                                            <span className="font-semibold">{seg.label}</span>
                                        </div>
                                        <span className="text-lg font-bold">{seg.count}</span>
                                    </div>
                                    <div className="w-full bg-white/10 rounded-full h-2">
                                        <div
                                            className="h-2 rounded-full bg-white/30 transition-all"
                                            style={{ width: `${pct}%` }}
                                        ></div>
                                    </div>
                                    <p className="text-xs text-gray-400 mt-1">{pct}% of pipeline</p>
                                </div>
                            );
                        }) : (
                            <div className="p-8 text-center text-gray-500">
                                No contacts yet. Add some to see segmentation.
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Pipeline Insights */}
            {insights && (
                <div className="glass-panel mb-8">
                    <div className="p-5 border-b border-white/10">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            📊 Pipeline Insights
                        </h2>
                    </div>
                    <div className="p-5">
                        {/* Conversion summary */}
                        <div className="bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border border-purple-500/20 rounded-xl p-4 mb-5">
                            <p className="text-sm font-medium text-purple-300">{insights.conversion_summary}</p>
                        </div>

                        {/* Stage breakdown bars */}
                        {insights.stage_breakdown.length > 0 && (
                            <div className="space-y-3 mb-5">
                                {insights.stage_breakdown.map((stage) => (
                                    <div key={stage.name} className="flex items-center gap-3">
                                        <span className="text-sm font-medium text-gray-300 w-28 truncate">{stage.name}</span>
                                        <div className="flex-1 bg-white/10 rounded-full h-3">
                                            <div
                                                className="h-3 rounded-full bg-gradient-to-r from-purple-500 to-indigo-500 transition-all"
                                                style={{ width: `${stage.percentage}%` }}
                                            ></div>
                                        </div>
                                        <span className="text-sm font-bold w-12 text-right">{stage.count}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Bottleneck warning */}
                        {insights.bottleneck && (
                            <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-3 mb-4 flex items-center gap-2">
                                <AlertTriangle size={16} className="text-orange-400 shrink-0" />
                                <p className="text-sm text-orange-300">{insights.bottleneck}</p>
                            </div>
                        )}

                        {/* AI Recommendations */}
                        <div>
                            <h3 className="text-sm font-semibold text-gray-400 mb-2">💡 AI Recommendations</h3>
                            <ul className="space-y-2">
                                {insights.recommendations.map((rec, i) => (
                                    <li key={i} className="text-sm text-gray-300 flex items-start gap-2">
                                        <span className="text-purple-400 mt-0.5">→</span>
                                        {rec}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
