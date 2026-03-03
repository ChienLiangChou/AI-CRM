import { useEffect, useState } from 'react';
import { crmService } from '../services/api';
import type { Contact } from '../services/api';
import { Target, TrendingUp, Users } from 'lucide-react';

const Dashboard = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchContacts = async () => {
            try {
                const data = await crmService.getContacts();
                setContacts(data);
            } catch (error) {
                console.error('Failed to load contacts:', error);
            } finally {
                setLoading(false);
            }
        };
        fetchContacts();
    }, []);

    const totalLeads = contacts.length;
    const hotLeads = contacts.filter(c => c.lead_score >= 80).length;
    const avgScore = contacts.length ? Math.round(contacts.reduce((a, b) => a + b.lead_score, 0) / contacts.length) : 0;

    if (loading) return <div className="p-8 text-center text-gray-400">Loading...</div>;

    return (
        <div className="animate-fade-in p-6">
            <header className="mb-10">
                <h1 className="text-3xl font-bold mb-2">Welcome back, <span className="text-gradient">Kevin</span></h1>
                <p className="text-gray-400">Here is what's happening in your pipeline today.</p>
            </header>

            {/* Metrics Row */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                <div className="glass-card flex items-center gap-4">
                    <div className="p-3 bg-blue-500/20 rounded-xl text-blue-400">
                        <Users size={28} />
                    </div>
                    <div>
                        <p className="text-sm text-gray-400 font-medium">Total Contacts</p>
                        <h3 className="text-2xl font-bold">{totalLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex items-center gap-4 border-l-4 border-l-red-500 hover:border-l-red-400 transition-colors">
                    <div className="p-3 bg-red-500/20 rounded-xl text-red-500">
                        <Target size={28} />
                    </div>
                    <div>
                        <p className="text-sm text-gray-400 font-medium">Hot Leads ({'>'}80 Score)</p>
                        <h3 className="text-2xl font-bold">{hotLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex items-center gap-4 border-l-4 border-l-purple-500">
                    <div className="p-3 bg-purple-500/20 rounded-xl text-purple-400">
                        <TrendingUp size={28} />
                    </div>
                    <div>
                        <p className="text-sm text-gray-400 font-medium">Avg Lead Score</p>
                        <h3 className="text-2xl font-bold">{avgScore}</h3>
                    </div>
                </div>
            </div>

            {/* Top Leads List */}
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
                <Sparkles className="text-yellow-400" size={20} /> AI Top Picks
            </h2>
            <div className="glass-panel overflow-hidden">
                <div className="divide-y divide-white/5">
                    {contacts.sort((a, b) => b.lead_score - a.lead_score).slice(0, 5).map(c => (
                        <div key={c.id} className="p-4 hover:bg-white/5 transition-colors flex justify-between items-center">
                            <div>
                                <h4 className="font-semibold">{c.name}</h4>
                                <p className="text-sm text-gray-400">{c.company || 'No Company'} • {c.email}</p>
                            </div>
                            <div className="flex items-center gap-3">
                                <div className="bg-white/10 px-3 py-1 rounded-full text-sm">
                                    Score: <span className="text-yellow-400 font-bold ml-1">{Math.round(c.lead_score)}</span>
                                </div>
                                <button className="btn btn-ghost text-sm py-1 px-3">View</button>
                            </div>
                        </div>
                    ))}
                    {contacts.length === 0 && <div className="p-8 text-center text-gray-500">No leads yet! Let's find some.</div>}
                </div>
            </div>
        </div>
    );
};

// Temp Sparkles icon for the component
const Sparkles = ({ size, className }: { size: number, className: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" /></svg>
);

export default Dashboard;
