import React, { useState, useEffect } from 'react';
import { X, Mail, Globe, Sparkles, Loader2, Pencil, Trash2, Save, Phone, MessageSquare, Calendar, Plus } from 'lucide-react';
import { crmService } from '../services/api';
import type { Contact, EmailDraftResponse, Interaction } from '../services/api';

interface Props {
    contact: Contact;
    onClose: () => void;
    onUpdate: (updatedContact: Contact) => void;
    onDelete: (contactId: number) => void;
}

const STAGES = [
    { id: 1, name: 'Lead' },
    { id: 2, name: 'Qualified' },
    { id: 3, name: 'Proposal' },
    { id: 4, name: 'Negotiation' },
    { id: 5, name: 'Closed Won' },
];

const INTERACTION_TYPES = ['email', 'call', 'meeting'];

const ContactModal: React.FC<Props> = ({ contact, onClose, onUpdate, onDelete }) => {
    // AI features
    const [loadingEmail, setLoadingEmail] = useState(false);
    const [loadingEnrich, setLoadingEnrich] = useState(false);
    const [emailDraft, setEmailDraft] = useState<EmailDraftResponse | null>(null);

    // Edit mode
    const [editing, setEditing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [editForm, setEditForm] = useState({
        name: contact.name,
        email: contact.email || '',
        phone: contact.phone || '',
        company: contact.company || '',
        notes: contact.notes || '',
        stage_id: contact.stage_id || 1,
    });

    // Delete confirmation
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [deleting, setDeleting] = useState(false);

    // Interactions
    const [interactions, setInteractions] = useState<Interaction[]>([]);
    const [loadingInteractions, setLoadingInteractions] = useState(true);
    const [showAddInteraction, setShowAddInteraction] = useState(false);
    const [newInteraction, setNewInteraction] = useState({ interaction_type: 'email', notes: '' });
    const [addingInteraction, setAddingInteraction] = useState(false);

    useEffect(() => {
        loadInteractions();
    }, [contact.id]);

    const loadInteractions = async () => {
        setLoadingInteractions(true);
        try {
            const data = await crmService.getInteractions(contact.id);
            setInteractions(data);
        } catch (error) {
            console.error('Failed to load interactions:', error);
        } finally {
            setLoadingInteractions(false);
        }
    };

    const handleDraftEmail = async () => {
        setLoadingEmail(true);
        try {
            const result = await crmService.draftEmail(contact.id);
            setEmailDraft(result);
        } catch (error) {
            console.error(error);
        } finally {
            setLoadingEmail(false);
        }
    };

    const handleEnrich = async () => {
        setLoadingEnrich(true);
        try {
            const result = await crmService.enrichProfile(contact.id);
            onUpdate({ ...contact, notes: result.updated_notes });
        } catch (error) {
            console.error(error);
        } finally {
            setLoadingEnrich(false);
        }
    };

    const handleEditChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setEditForm(prev => ({ ...prev, [name]: name === 'stage_id' ? Number(value) : value }));
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            const updated = await crmService.updateContact(contact.id, editForm);
            onUpdate(updated);
            setEditing(false);
        } catch (error) {
            console.error('Failed to update contact:', error);
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        setDeleting(true);
        try {
            await crmService.deleteContact(contact.id);
            onDelete(contact.id);
            onClose();
        } catch (error) {
            console.error('Failed to delete contact:', error);
        } finally {
            setDeleting(false);
        }
    };

    const handleAddInteraction = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newInteraction.notes.trim()) return;
        setAddingInteraction(true);
        try {
            const created = await crmService.createInteraction(contact.id, newInteraction);
            setInteractions(prev => [created, ...prev]);
            setNewInteraction({ interaction_type: 'email', notes: '' });
            setShowAddInteraction(false);
        } catch (error) {
            console.error('Failed to add interaction:', error);
        } finally {
            setAddingInteraction(false);
        }
    };

    const getInteractionIcon = (type: string) => {
        switch (type) {
            case 'call': return <Phone size={14} />;
            case 'meeting': return <Calendar size={14} />;
            default: return <Mail size={14} />;
        }
    };

    const getInteractionColor = (type: string) => {
        switch (type) {
            case 'call': return 'bg-green-500/20 text-green-400 border-green-500/30';
            case 'meeting': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
            default: return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
        }
    };

    const stageName = STAGES.find(s => s.id === contact.stage_id)?.name || 'Unassigned';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl relative overflow-hidden">

                {/* Glow effect */}
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-32 bg-purple-500/30 blur-[100px] pointer-events-none"></div>

                {/* Header */}
                <div className="flex justify-between items-center p-6 border-b border-white/10 relative z-10">
                    <div>
                        <h2 className="text-2xl font-bold flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-sm">
                                {contact.name.charAt(0)}
                            </div>
                            <div>
                                {editing ? (
                                    <input
                                        type="text"
                                        name="name"
                                        value={editForm.name}
                                        onChange={handleEditChange}
                                        className="bg-white/5 border border-white/20 rounded-lg px-3 py-1 text-xl font-bold outline-none focus:border-purple-500"
                                    />
                                ) : contact.name}
                                {!editing && contact.tags && (
                                    <div className="text-xs text-gray-400 mt-0.5">{contact.tags}</div>
                                )}
                            </div>
                        </h2>
                        {!editing && (
                            <p className="text-gray-400 mt-1 ml-13 flex items-center gap-2">
                                <span>{contact.company || 'No Company'}</span> • <span>{contact.email || 'No Email'}</span>
                                <span className="ml-2 text-xs bg-white/10 px-2 py-0.5 rounded-full">{stageName}</span>
                            </p>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        {!editing ? (
                            <>
                                <button onClick={() => setEditing(true)} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-blue-400" title="Edit">
                                    <Pencil size={18} />
                                </button>
                                <button onClick={() => setShowDeleteConfirm(true)} className="p-2 hover:bg-red-500/20 rounded-full transition-colors text-gray-400 hover:text-red-400" title="Delete">
                                    <Trash2 size={18} />
                                </button>
                            </>
                        ) : (
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="btn bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30 text-sm py-1.5 px-4"
                            >
                                {saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
                                Save
                            </button>
                        )}
                        <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-white">
                            <X size={24} />
                        </button>
                    </div>
                </div>

                {/* Delete Confirmation */}
                {showDeleteConfirm && (
                    <div className="mx-6 mt-4 p-4 rounded-xl bg-red-500/10 border border-red-500/30 animate-fade-in relative z-10">
                        <p className="text-red-300 mb-3">Are you sure you want to delete <strong>{contact.name}</strong>? This cannot be undone.</p>
                        <div className="flex gap-3 justify-end">
                            <button onClick={() => setShowDeleteConfirm(false)} className="btn btn-ghost text-sm py-1.5 px-4">Cancel</button>
                            <button onClick={handleDelete} disabled={deleting} className="btn bg-red-600 hover:bg-red-700 text-white text-sm py-1.5 px-4">
                                {deleting ? <Loader2 className="animate-spin" size={16} /> : <Trash2 size={16} />}
                                Delete
                            </button>
                        </div>
                    </div>
                )}

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6 relative z-10">

                    {/* Edit Form */}
                    {editing && (
                        <div className="grid grid-cols-2 gap-4 bg-white/5 p-4 rounded-xl border border-white/10 animate-fade-in">
                            <div className="input-group">
                                <label className="input-label">Email</label>
                                <input type="email" name="email" value={editForm.email} onChange={handleEditChange} className="input-field" placeholder="Email" />
                            </div>
                            <div className="input-group">
                                <label className="input-label">Phone</label>
                                <input type="text" name="phone" value={editForm.phone} onChange={handleEditChange} className="input-field" placeholder="Phone" />
                            </div>
                            <div className="input-group">
                                <label className="input-label">Company</label>
                                <input type="text" name="company" value={editForm.company} onChange={handleEditChange} className="input-field" placeholder="Company" />
                            </div>
                            <div className="input-group">
                                <label className="input-label">Stage</label>
                                <select name="stage_id" value={editForm.stage_id} onChange={handleEditChange} className="input-field">
                                    {STAGES.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                </select>
                            </div>
                            <div className="input-group col-span-2">
                                <label className="input-label">Notes</label>
                                <textarea name="notes" value={editForm.notes} onChange={handleEditChange} className="input-field" rows={3} placeholder="Notes" />
                            </div>
                        </div>
                    )}

                    {/* Lead Score + AI Actions */}
                    {!editing && (
                        <div className="flex items-center justify-between bg-white/5 p-4 rounded-xl border border-white/5">
                            <div>
                                <div className="text-sm text-gray-400 mb-1">AI Lead Score</div>
                                <div className={`text-3xl font-bold ${contact.lead_score >= 80 ? 'text-red-400' : contact.lead_score >= 50 ? 'text-orange-400' : 'text-blue-400'}`}>
                                    {Math.round(contact.lead_score)}
                                </div>
                            </div>
                            <div className="flex gap-3">
                                <button
                                    onClick={handleEnrich}
                                    disabled={loadingEnrich}
                                    className="btn bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 border border-blue-500/30">
                                    {loadingEnrich ? <Loader2 className="animate-spin" size={18} /> : <Globe size={18} />}
                                    Enrich Lead
                                </button>
                                <button
                                    onClick={handleDraftEmail}
                                    disabled={loadingEmail}
                                    className="btn bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 border border-purple-500/30">
                                    {loadingEmail ? <Loader2 className="animate-spin" size={18} /> : <Sparkles size={18} />}
                                    Draft Email
                                </button>
                            </div>
                        </div>
                    )}

                    {/* AI Email Draft */}
                    {emailDraft && (
                        <div className="bg-purple-900/20 border border-purple-500/30 rounded-xl p-5 animate-fade-in relative group">
                            <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                                <button className="text-xs bg-purple-500/30 hover:bg-purple-500/50 text-white px-3 py-1 rounded-md" onClick={() => navigator.clipboard.writeText(emailDraft.body)}>Copy</button>
                            </div>
                            <h3 className="text-sm font-semibold text-purple-300 mb-3 flex items-center gap-2 uppercase tracking-wider">
                                <Mail size={16} /> AI Email Draft
                            </h3>
                            <div className="mb-4 bg-black/30 p-3 rounded-lg border border-white/5">
                                <span className="text-gray-400 text-sm">Subject:</span> <span className="font-semibold">{emailDraft.subject}</span>
                            </div>
                            <div className="whitespace-pre-wrap text-gray-300 bg-black/30 p-4 rounded-lg border border-white/5 text-sm leading-relaxed">
                                {emailDraft.body}
                            </div>
                        </div>
                    )}

                    {/* Notes */}
                    {!editing && (
                        <div>
                            <h3 className="text-lg font-semibold mb-3">Notes</h3>
                            <div className="bg-black/30 p-5 rounded-xl border border-white/5 whitespace-pre-wrap text-gray-300 text-sm leading-relaxed min-h-[80px]">
                                {contact.notes || 'No notes available for this contact.'}
                            </div>
                        </div>
                    )}

                    {/* Interactions Section */}
                    <div>
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-lg font-semibold flex items-center gap-2">
                                <MessageSquare size={18} className="text-purple-400" /> Interactions
                            </h3>
                            <button
                                onClick={() => setShowAddInteraction(!showAddInteraction)}
                                className="btn bg-white/5 hover:bg-white/10 text-sm py-1.5 px-3 border border-white/10"
                            >
                                <Plus size={16} /> Log Interaction
                            </button>
                        </div>

                        {/* Add Interaction Form */}
                        {showAddInteraction && (
                            <form onSubmit={handleAddInteraction} className="mb-4 p-4 bg-white/5 rounded-xl border border-white/10 animate-fade-in space-y-3">
                                <div className="flex gap-3">
                                    <select
                                        value={newInteraction.interaction_type}
                                        onChange={(e) => setNewInteraction(prev => ({ ...prev, interaction_type: e.target.value }))}
                                        className="input-field w-auto"
                                    >
                                        {INTERACTION_TYPES.map(t => (
                                            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                                        ))}
                                    </select>
                                    <input
                                        type="text"
                                        value={newInteraction.notes}
                                        onChange={(e) => setNewInteraction(prev => ({ ...prev, notes: e.target.value }))}
                                        placeholder="What happened?"
                                        className="input-field flex-1"
                                        required
                                    />
                                    <button type="submit" disabled={addingInteraction || !newInteraction.notes.trim()} className="btn btn-primary text-sm py-2 px-4">
                                        {addingInteraction ? <Loader2 className="animate-spin" size={16} /> : 'Add'}
                                    </button>
                                </div>
                            </form>
                        )}

                        {/* Interactions List */}
                        <div className="space-y-2">
                            {loadingInteractions ? (
                                <div className="p-6 text-center text-gray-500"><div className="spinner mx-auto mb-2"></div>Loading...</div>
                            ) : interactions.length > 0 ? (
                                interactions.map(ix => (
                                    <div key={ix.id} className="flex items-start gap-3 p-3 rounded-lg bg-black/20 border border-white/5 hover:bg-white/5 transition-colors">
                                        <div className={`p-1.5 rounded-lg border ${getInteractionColor(ix.interaction_type)} shrink-0 mt-0.5`}>
                                            {getInteractionIcon(ix.interaction_type)}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-0.5">
                                                <span className="text-sm font-medium capitalize">{ix.interaction_type}</span>
                                                <span className="text-xs text-gray-500">{new Date(ix.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                                            </div>
                                            <p className="text-sm text-gray-400">{ix.notes}</p>
                                        </div>
                                    </div>
                                ))
                            ) : (
                                <div className="p-6 text-center text-gray-500 bg-black/20 rounded-xl border border-dashed border-white/10">
                                    No interactions recorded yet. Click "Log Interaction" to add one.
                                </div>
                            )}
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
};

export default ContactModal;
