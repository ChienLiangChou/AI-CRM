import React, { useState } from 'react';
import { X, Plus, Loader2 } from 'lucide-react';
import { crmService } from '../services/api';
import type { Contact } from '../services/api';

interface Props {
    onClose: () => void;
    onCreated: (contact: Contact) => void;
}

const STAGES = [
    { id: 1, name: 'Lead' },
    { id: 2, name: 'Qualified' },
    { id: 3, name: 'Proposal' },
    { id: 4, name: 'Negotiation' },
    { id: 5, name: 'Closed Won' },
];

const AddContactModal: React.FC<Props> = ({ onClose, onCreated }) => {
    const [loading, setLoading] = useState(false);
    const [form, setForm] = useState({
        name: '',
        email: '',
        phone: '',
        company: '',
        notes: '',
        stage_id: 1,
    });

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setForm(prev => ({ ...prev, [name]: name === 'stage_id' ? Number(value) : value }));
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form.name.trim()) return;

        setLoading(true);
        try {
            const created = await crmService.createContact(form);
            onCreated(created);
            onClose();
        } catch (error) {
            console.error('Failed to create contact:', error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-lg shadow-2xl relative overflow-hidden">

                {/* Glow */}
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-32 bg-green-500/20 blur-[100px] pointer-events-none"></div>

                {/* Header */}
                <div className="flex justify-between items-center p-6 border-b border-white/10 relative z-10">
                    <h2 className="text-xl font-bold flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center">
                            <Plus size={20} />
                        </div>
                        Add New Contact
                    </h2>
                    <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-white">
                        <X size={24} />
                    </button>
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="p-6 space-y-4 relative z-10">
                    <div className="input-group">
                        <label className="input-label">Name *</label>
                        <input
                            type="text"
                            name="name"
                            value={form.name}
                            onChange={handleChange}
                            placeholder="John Doe"
                            className="input-field"
                            required
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="input-group">
                            <label className="input-label">Email</label>
                            <input
                                type="email"
                                name="email"
                                value={form.email}
                                onChange={handleChange}
                                placeholder="john@example.com"
                                className="input-field"
                            />
                        </div>
                        <div className="input-group">
                            <label className="input-label">Phone</label>
                            <input
                                type="text"
                                name="phone"
                                value={form.phone}
                                onChange={handleChange}
                                placeholder="+1 (555) 123-4567"
                                className="input-field"
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="input-group">
                            <label className="input-label">Company</label>
                            <input
                                type="text"
                                name="company"
                                value={form.company}
                                onChange={handleChange}
                                placeholder="Acme Inc."
                                className="input-field"
                            />
                        </div>
                        <div className="input-group">
                            <label className="input-label">Pipeline Stage</label>
                            <select
                                name="stage_id"
                                value={form.stage_id}
                                onChange={handleChange}
                                className="input-field"
                            >
                                {STAGES.map(s => (
                                    <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="input-group">
                        <label className="input-label">Notes</label>
                        <textarea
                            name="notes"
                            value={form.notes}
                            onChange={handleChange}
                            placeholder="Background info, deal details, etc."
                            className="input-field"
                            rows={3}
                        />
                    </div>

                    <div className="flex justify-end gap-3 pt-2">
                        <button type="button" onClick={onClose} className="btn btn-ghost">
                            Cancel
                        </button>
                        <button type="submit" disabled={loading || !form.name.trim()} className="btn btn-primary">
                            {loading ? <><Loader2 className="animate-spin" size={18} /> Creating...</> : <><Plus size={18} /> Create Contact</>}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default AddContactModal;
