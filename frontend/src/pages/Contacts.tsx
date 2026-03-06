import { useEffect, useState } from 'react';
import { crmService } from '../services/api';
import type { Contact, SmartSearchResult } from '../services/api';
import { Sparkles, Filter, Plus } from 'lucide-react';
import ContactModal from '../components/ContactModal';
import AddContactModal from '../components/AddContactModal';
import './Contacts.css';

const Contacts = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [query, setQuery] = useState('');
    const [searchResult, setSearchResult] = useState<SmartSearchResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
    const [showAddModal, setShowAddModal] = useState(false);

    useEffect(() => {
        loadContacts();
    }, []);

    const loadContacts = async () => {
        setLoading(true);
        try {
            const data = await crmService.getContacts();
            setContacts(data);
        } catch (error) {
            console.error('Failed', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSmartSearch = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query.trim()) {
            setSearchResult(null);
            loadContacts();
            return;
        }

        setLoading(true);
        try {
            const result = await crmService.smartSearch(query);
            setSearchResult(result);
            setContacts(result.results);
        } catch (error) {
            console.error("Smart search failed:", error);
        } finally {
            setLoading(false);
        }
    };

    const formatScore = (score: number) => {
        const s = Math.round(score);
        if (s >= 80) return <span className="score bg-red-500/20 text-red-500 border border-red-500/30">{s}</span>;
        if (s >= 50) return <span className="score bg-orange-500/20 text-orange-400 border border-orange-500/30">{s}</span>;
        return <span className="score bg-blue-500/20 text-blue-400 border border-blue-500/30">{s}</span>;
    };

    const handleUpdateContact = (updated: Contact) => {
        setContacts(contacts.map(c => c.id === updated.id ? updated : c));
        setSelectedContact(updated);
    };

    const handleDeleteContact = (contactId: number) => {
        setContacts(contacts.filter(c => c.id !== contactId));
        setSelectedContact(null);
    };

    const handleContactCreated = (newContact: Contact) => {
        setContacts(prev => [newContact, ...prev]);
    };

    return (
        <div className="contacts-page animate-fade-in">
            <div className="page-header">
                <div>
                    <h1>Contacts & Leads</h1>
                    <p className="subtitle">Manage and search your pipeline with AI.</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
                    <Plus size={18} /> Add Contact
                </button>
            </div>

            {/* Smart Search Bar */}
            <div className="smart-search-container glass-card mb-8 relative group">
                <div className="absolute -inset-1 rounded-xl bg-gradient-to-r from-purple-500 to-yellow-500 opacity-20 group-hover:opacity-40 blur transition-opacity"></div>
                <form onSubmit={handleSmartSearch} className="relative z-10 flex items-center gap-3 w-full bg-slate-900 border border-white/10 rounded-lg p-2">
                    <Sparkles className="text-yellow-400 ml-2" size={24} />
                    <input
                        type="text"
                        className="flex-1 bg-transparent border-none text-white outline-none placeholder:text-gray-500 text-lg px-2"
                        placeholder="Ask AI: e.g. 'Show me warm real estate leads'"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                    <button type="submit" className="btn btn-accent px-6 py-2 rounded-md">Search</button>
                </form>
                {searchResult && (
                    <div className="mt-3 ml-2 text-sm text-purple-300 flex items-center gap-2">
                        <Filter size={14} /> AI Interpretation: {searchResult.interpreted_intent}
                    </div>
                )}
            </div>

            {/* Contacts List */}
            <div className="contacts-list glass-panel">
                <div className="list-header border-b border-white/10 p-4 grid grid-cols-12 gap-4 text-sm font-semibold text-gray-400">
                    <div className="col-span-3">Name</div>
                    <div className="col-span-3">Company / Email</div>
                    <div className="col-span-4">Notes Snippet</div>
                    <div className="col-span-2 text-center">Lead Score</div>
                </div>

                <div className="list-body">
                    {loading ? (
                        <div className="p-10 text-center"><div className="spinner mx-auto mb-3"></div>Loading leads...</div>
                    ) : contacts.length > 0 ? (
                        contacts.map((contact) => (
                            <div
                                key={contact.id}
                                className="contact-row grid grid-cols-12 gap-4 p-4 border-b border-white/5 hover:bg-white/5 items-center transition-colors cursor-pointer"
                                onClick={() => setSelectedContact(contact)}
                            >
                                <div className="col-span-3 font-medium">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center font-bold text-xs">
                                            {contact.name.charAt(0)}
                                        </div>
                                        <div>
                                            <div>{contact.name}</div>
                                            {contact.tags && (
                                                <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-white/5 text-gray-400">{contact.tags}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div className="col-span-3 text-sm text-gray-300">
                                    <div className="font-medium text-white">{contact.company || '-'}</div>
                                    <div className="text-gray-500">{contact.email}</div>
                                </div>
                                <div className="col-span-4 text-sm text-gray-400 truncate pr-4">
                                    {contact.notes || 'No description provided.'}
                                </div>
                                <div className="col-span-2 flex justify-center">
                                    {formatScore(contact.lead_score)}
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="p-10 text-center text-gray-500">
                            No contacts found for this search. Try a different query.
                        </div>
                    )}
                </div>
            </div>

            {selectedContact && (
                <ContactModal
                    contact={selectedContact}
                    onClose={() => setSelectedContact(null)}
                    onUpdate={handleUpdateContact}
                    onDelete={handleDeleteContact}
                />
            )}

            {showAddModal && (
                <AddContactModal
                    onClose={() => setShowAddModal(false)}
                    onCreated={handleContactCreated}
                />
            )}
        </div>
    );
};

export default Contacts;
