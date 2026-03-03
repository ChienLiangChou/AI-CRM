import { useEffect, useState } from 'react';
import { crmService } from '../services/api';
import type { Contact } from '../services/api';
import { Trello } from 'lucide-react';
import './Pipeline.css';

interface Stage {
    id: number;
    name: string;
}

const STAGES: Stage[] = [
    { id: 1, name: 'Lead' },
    { id: 2, name: 'Qualified' },
    { id: 3, name: 'Proposal' },
    { id: 4, name: 'Negotiation' },
    { id: 5, name: 'Closed Won' },
];

const Pipeline = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadContacts();
    }, []);

    const loadContacts = async () => {
        try {
            const data = await crmService.getContacts();
            setContacts(data);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    const getContactsForStage = (stageId: number) => {
        return contacts.filter(c => c.stage_id === stageId);
    };

    if (loading) return <div className="p-8 text-center text-gray-400">Loading pipeline...</div>;

    return (
        <div className="pipeline-page animate-fade-in">
            <div className="page-header mb-8">
                <div>
                    <h1>Pipeline Stages</h1>
                    <p className="subtitle">Track your leads through the sales cycle.</p>
                </div>
            </div>

            <div className="kanban-board overflow-x-auto pb-4">
                <div className="flex gap-6 min-w-max">
                    {STAGES.map(stage => {
                        const stageContacts = getContactsForStage(stage.id);
                        return (
                            <div key={stage.id} className="kanban-column glass-panel">
                                <div className="column-header mb-4 flex justify-between items-center">
                                    <h3 className="font-bold flex items-center gap-2">
                                        <Trello size={16} className="text-purple-400" />
                                        {stage.name}
                                    </h3>
                                    <span className="count bg-white/10 px-2 py-0.5 rounded-full text-xs font-semibold">
                                        {stageContacts.length}
                                    </span>
                                </div>

                                <div className="column-body flex flex-col gap-3 min-h-[300px]">
                                    {stageContacts.map(contact => (
                                        <div key={contact.id} className="kanban-card glass-card !p-4 cursor-grab active:cursor-grabbing hover:border-purple-500/50 transition-colors">
                                            <div className="font-semibold text-[15px] mb-1">{contact.name}</div>
                                            <div className="text-xs text-gray-400 mb-3">{contact.company || 'No Company'}</div>

                                            <div className="flex justify-between items-center mt-auto border-t border-white/5 pt-3">
                                                <div className="text-xs text-gray-500">Score</div>
                                                <div className={`text-sm font-bold ${contact.lead_score >= 80 ? 'text-red-400' : contact.lead_score >= 50 ? 'text-orange-400' : 'text-blue-400'}`}>
                                                    {Math.round(contact.lead_score)}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                    {stageContacts.length === 0 && (
                                        <div className="border border-dashed border-white/10 rounded-lg h-24 flex items-center justify-center text-sm text-gray-500">
                                            Empty
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default Pipeline;
