import { useEffect, useState, useRef } from 'react';
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
    const [draggedContactId, setDraggedContactId] = useState<number | null>(null);
    const [dragOverStageId, setDragOverStageId] = useState<number | null>(null);
    const dragCounter = useRef<{ [key: number]: number }>({});

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

    // --- Drag & Drop Handlers ---
    const handleDragStart = (e: React.DragEvent, contactId: number) => {
        setDraggedContactId(contactId);
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(contactId));
        // Add a slight delay for the dragging visual
        const target = e.currentTarget as HTMLElement;
        setTimeout(() => target.classList.add('dragging'), 0);
    };

    const handleDragEnd = (e: React.DragEvent) => {
        setDraggedContactId(null);
        setDragOverStageId(null);
        dragCounter.current = {};
        (e.currentTarget as HTMLElement).classList.remove('dragging');
    };

    const handleDragEnter = (e: React.DragEvent, stageId: number) => {
        e.preventDefault();
        if (!dragCounter.current[stageId]) dragCounter.current[stageId] = 0;
        dragCounter.current[stageId]++;
        setDragOverStageId(stageId);
    };

    const handleDragLeave = (_e: React.DragEvent, stageId: number) => {
        dragCounter.current[stageId]--;
        if (dragCounter.current[stageId] <= 0) {
            dragCounter.current[stageId] = 0;
            if (dragOverStageId === stageId) {
                setDragOverStageId(null);
            }
        }
    };

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    };

    const handleDrop = async (e: React.DragEvent, targetStageId: number) => {
        e.preventDefault();
        setDragOverStageId(null);
        dragCounter.current = {};

        if (draggedContactId === null) return;

        const contact = contacts.find(c => c.id === draggedContactId);
        if (!contact || contact.stage_id === targetStageId) {
            setDraggedContactId(null);
            return;
        }

        // Optimistic update
        setContacts(prev =>
            prev.map(c => c.id === draggedContactId ? { ...c, stage_id: targetStageId } : c)
        );
        setDraggedContactId(null);

        // Persist to backend
        try {
            await crmService.updateContactStage(draggedContactId, targetStageId);
        } catch (error) {
            console.error('Failed to update stage:', error);
            // Revert on error
            setContacts(prev =>
                prev.map(c => c.id === draggedContactId ? { ...c, stage_id: contact.stage_id } : c)
            );
        }
    };

    if (loading) return <div className="p-8 text-center text-gray-400">Loading pipeline...</div>;

    return (
        <div className="pipeline-page animate-fade-in">
            <div className="page-header mb-8">
                <div>
                    <h1>Pipeline Stages</h1>
                    <p className="subtitle">Drag and drop leads to move them through the sales cycle.</p>
                </div>
            </div>

            <div className="kanban-board overflow-x-auto pb-4">
                <div className="flex gap-6 min-w-max">
                    {STAGES.map(stage => {
                        const stageContacts = getContactsForStage(stage.id);
                        const isOver = dragOverStageId === stage.id;
                        return (
                            <div
                                key={stage.id}
                                className={`kanban-column glass-panel ${isOver ? 'drag-over' : ''}`}
                                onDragEnter={(e) => handleDragEnter(e, stage.id)}
                                onDragLeave={(e) => handleDragLeave(e, stage.id)}
                                onDragOver={handleDragOver}
                                onDrop={(e) => handleDrop(e, stage.id)}
                            >
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
                                        <div
                                            key={contact.id}
                                            className={`kanban-card glass-card !p-4 cursor-grab active:cursor-grabbing hover:border-purple-500/50 transition-colors ${draggedContactId === contact.id ? 'dragging' : ''}`}
                                            draggable
                                            onDragStart={(e) => handleDragStart(e, contact.id)}
                                            onDragEnd={handleDragEnd}
                                        >
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
                                        <div className={`border border-dashed rounded-lg h-24 flex items-center justify-center text-sm text-gray-500 transition-colors ${isOver ? 'border-purple-500/50 bg-purple-500/5 text-purple-400' : 'border-white/10'}`}>
                                            {isOver ? 'Drop here' : 'Empty'}
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
