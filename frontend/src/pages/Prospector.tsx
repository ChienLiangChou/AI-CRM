import React, { useState } from 'react';
import { Sparkles, Search, Loader2, ArrowRight } from 'lucide-react';
import { crmService } from '../services/api';
import type { Contact } from '../services/api';

const Prospector = () => {
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [resultMessage, setResultMessage] = useState('');
    const [newLeads, setNewLeads] = useState<Contact[]>([]);

    const handleScout = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query.trim()) return;

        setLoading(true);
        setResultMessage('');
        setNewLeads([]);

        try {
            const res = await crmService.scoutLeads(query);
            setResultMessage(res.message);
            setNewLeads(res.new_contacts);
        } catch (error) {
            console.error(error);
            setResultMessage('Error finding leads. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="animate-fade-in p-8">
            <div className="mb-8 flex items-center gap-3">
                <div className="p-3 bg-gradient-to-br from-indigo-500/20 to-purple-500/20 rounded-xl border border-indigo-500/30">
                    <Sparkles className="text-indigo-400" size={28} />
                </div>
                <div>
                    <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400">AI Prospector</h1>
                    <p className="text-gray-400 mt-1">Automatically find and extract highly-targeted leads from the web.</p>
                </div>
            </div>

            <div className="max-w-3xl mb-12">
                <form onSubmit={handleScout} className="relative group">
                    <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl blur opacity-25 group-hover:opacity-40 transition duration-1000 group-hover:duration-200"></div>
                    <div className="relative bg-slate-900 border border-white/10 p-2 rounded-2xl flex items-center shadow-2xl">
                        <Search className="ml-4 text-gray-400" size={24} />
                        <input
                            type="text"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="E.g., 'SaaS startups in Toronto recently funded'"
                            className="w-full bg-transparent border-none text-white focus:ring-0 p-4 outline-none text-lg"
                            disabled={loading}
                        />
                        <button
                            type="submit"
                            disabled={loading || !query.trim()}
                            className="bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold py-3 px-8 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="animate-spin" size={20} />
                                    Scouting...
                                </>
                            ) : (
                                <>
                                    Start Scouting <ArrowRight size={20} />
                                </>
                            )}
                        </button>
                    </div>
                </form>

                {loading && (
                    <div className="mt-8 flex flex-col items-center justify-center p-12 bg-black/20 rounded-2xl border border-white/5">
                        <div className="relative">
                            <div className="w-16 h-16 border-4 border-indigo-500/30 rounded-full"></div>
                            <div className="w-16 h-16 border-4 border-indigo-500 rounded-full border-t-transparent animate-spin absolute top-0 left-0"></div>
                        </div>
                        <p className="mt-6 text-xl font-medium text-indigo-300 animate-pulse">Running AI Web Search...</p>
                        <p className="text-gray-400 mt-2 text-sm">Searching the internet, extracting company data, and generating contacts.</p>
                    </div>
                )}
            </div>

            {resultMessage && !loading && (
                <div className="animate-fade-in w-full max-w-4xl">
                    <div className={`p-4 rounded-xl mb-6 border ${newLeads.length > 0 ? 'bg-green-500/10 border-green-500/30 text-green-300' : 'bg-red-500/10 border-red-500/30 text-red-300'}`}>
                        {resultMessage}
                    </div>

                    {newLeads.length > 0 && (
                        <div className="space-y-4">
                            <h3 className="text-xl font-semibold mb-4 text-white">New Leads Added to Pipeline:</h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {newLeads.map((contact) => (
                                    <div key={contact.id} className="bg-slate-800/50 p-6 rounded-xl border border-white/10 hover:border-indigo-500/50 transition-colors">
                                        <div className="flex justify-between items-start mb-4">
                                            <div>
                                                <h4 className="font-bold text-lg">{contact.name}</h4>
                                                <p className="text-indigo-400">{contact.company}</p>
                                            </div>
                                            <div className="bg-indigo-500/20 text-indigo-300 px-3 py-1 rounded-full text-xs font-semibold border border-indigo-500/30">
                                                Score: {contact.lead_score}
                                            </div>
                                        </div>
                                        <p className="text-gray-400 text-sm mb-4 line-clamp-3 leading-relaxed">
                                            {contact.notes}
                                        </p>
                                        <div className="text-xs text-gray-500 flex items-center gap-2">
                                            <div className="w-2 h-2 rounded-full bg-green-500"></div> Added to "Lead" pipeline
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default Prospector;
