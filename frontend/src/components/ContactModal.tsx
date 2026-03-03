import React, { useState } from 'react';
import { X, Mail, Globe, Sparkles, Loader2 } from 'lucide-react';
import { crmService } from '../services/api';
import type { Contact, EmailDraftResponse } from '../services/api';

interface Props {
    contact: Contact;
    onClose: () => void;
    onUpdate: (updatedContact: Contact) => void;
}

const ContactModal: React.FC<Props> = ({ contact, onClose, onUpdate }) => {
    const [loadingEmail, setLoadingEmail] = useState(false);
    const [loadingEnrich, setLoadingEnrich] = useState(false);
    const [emailDraft, setEmailDraft] = useState<EmailDraftResponse | null>(null);

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
            // Update local contact state with new notes
            onUpdate({ ...contact, notes: result.updated_notes });
        } catch (error) {
            console.error(error);
        } finally {
            setLoadingEnrich(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl relative overflow-hidden">

                {/* Glow effect */}
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-32 bg-purple-500/30 blur-[100px] pointer-events-none"></div>

                <div className="flex justify-between items-center p-6 border-b border-white/10 relative z-10">
                    <div>
                        <h2 className="text-2xl font-bold flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-sm">
                                {contact.name.charAt(0)}
                            </div>
                            {contact.name}
                        </h2>
                        <p className="text-gray-400 mt-1 ml-13 flex items-center gap-2">
                            <span>{contact.company || 'No Company'}</span> • <span>{contact.email || 'No Email'}</span>
                        </p>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-white">
                        <X size={24} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-6 space-y-6 relative z-10">

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

                    <div>
                        <h3 className="text-lg font-semibold mb-3">Notes & Activity</h3>
                        <div className="bg-black/30 p-5 rounded-xl border border-white/5 whitespace-pre-wrap text-gray-300 text-sm leading-relaxed min-h-[150px]">
                            {contact.notes || 'No notes available for this contact.'}
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
};

export default ContactModal;
