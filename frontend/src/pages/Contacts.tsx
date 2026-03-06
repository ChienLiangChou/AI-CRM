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
            <div className="page-header flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-4 sm:mb-6">
                <div>
                    <h1 className="text-xl sm:text-2xl">Contacts & Leads</h1>
                    <p className="subtitle text-sm">Manage and search your pipeline with AI.</p>
                </div>
                <button className="btn btn-primary text-sm px-4 py-2" onClick={() => setShowAddModal(true)}>
                    <Plus size={16} /> Add Contact
                </button>
            </div>

            {/* Smart Search Bar */}
            <div className="smart-search-container glass-card mb-6 sm:mb-8 relative group">
                <div className="absolute -inset-1 rounded-xl bg-gradient-to-r from-purple-500 to-yellow-500 opacity-20 group-hover:opacity-40 blur transition-opacity"></div>
                <form onSubmit={handleSmartSearch} className="relative z-10 flex items-center gap-2 sm:gap-3 w-full bg-slate-900 border border-white/10 rounded-lg p-2">
                    <Sparkles className="text-yellow-400 ml-1 sm:ml-2 shrink-0" size={20} />
                    <input
                        type="text"
                        className="flex-1 bg-transparent border-none text-white outline-none placeholder:text-gray-500 text-sm sm:text-lg px-1 sm:px-2 min-w-0"
                        placeholder="Ask AI to search..."
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                    <button type="submit" className="btn btn-accent px-3 sm:px-6 py-2 rounded-md text-sm shrink-0">Search</button>
                </form>
                {searchResult && (
                    <div className="mt-3 ml-2 text-xs sm:text-sm text-purple-300 flex items-center gap-2">
                        <Filter size={14} /> AI: {searchResult.interpreted_intent}
                    </div>
                )}
            </div>

            {/* Contacts List — Desktop: table, Mobile: cards */}
            <div className="contacts-list glass-panel">
                {/* Desktop table header */}
                <div className="list-header border-b border-white/10 p-4 hidden sm:grid grid-cols-12 gap-4 text-sm font-semibold text-gray-400">
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
                                className="contact-row border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                                onClick={() => setSelectedContact(contact)}
                            >
                                {/* Desktop row */}
                                <div className="hidden sm:grid grid-cols-12 gap-4 p-4 items-center">
                                    <div className="col-span-3 font-medium">
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center font-bold text-xs shrink-0">
                                                {contact.name.charAt(0)}
                                            </div>
                                            <div className="min-w-0">
                                                <div className="truncate">{contact.name}</div>
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
                                {/* Mobile card */}
                                <div className="sm:hidden flex items-center gap-3 p-3">
                                    <div className="w-10 h-10 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center font-bold text-sm shrink-0">
                                        {contact.name.charAt(0)}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-sm truncate">{contact.name}</div>
                                        <div className="text-xs text-gray-500 truncate">{contact.company || contact.email || 'No info'}</div>
                                    </div>
                                    <div className="shrink-0">
                                        {formatScore(contact.lead_score)}
                                    </div>
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="p-10 text-center text-gray-500">
                            No contacts found. Try a different query.
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
