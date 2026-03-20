import axios from 'axios';
import { useEffect, useState } from 'react';
import { crmService } from '../../services/api';
import type { Contact } from '../../services/api';
import { agentsService } from '../../services/agents';
import type {
    AgentApproval,
    AgentAuditLog,
    AgentRun,
    BuyerMatchCandidateInput,
    BuyerMatchLatestResponse,
    BuyerMatchRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: BuyerMatchLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

const MAX_CANDIDATES = 5;

type CandidateRow = {
    address: string;
    listPrice: string;
    propertyType: string;
    bedrooms: string;
    bathrooms: string;
    sqft: string;
    area: string;
    parking: string;
    notes: string;
};

type BuyerMatchApprovalPayload = {
    subject?: string;
    body?: string;
    contact_id?: number;
    variant?: string;
    shortlist_titles?: string[];
    shortlist_framing?: string;
    review_mode?: string;
};

const createEmptyCandidate = (): CandidateRow => ({
    address: '',
    listPrice: '',
    propertyType: 'condo',
    bedrooms: '',
    bathrooms: '',
    sqft: '',
    area: '',
    parking: '',
    notes: '',
});

const parseJsonText = (value?: string) => {
    if (!value) {
        return null;
    }

    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
};

const parseApprovalPayload = (payload?: string): BuyerMatchApprovalPayload => {
    const parsed = parseJsonText(payload);
    if (!parsed || typeof parsed !== 'object') {
        return {};
    }

    return parsed as BuyerMatchApprovalPayload;
};

const getErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
    }
    return fallback;
};

const formatAuditDetails = (value?: string) => {
    const parsed = parseJsonText(value);
    if (parsed) {
        return JSON.stringify(parsed, null, 2);
    }
    return value ?? '';
};

const getDecisionMeta = (approval: AgentApproval) => {
    if (approval.status === 'approved' && approval.approved_at) {
        return `Approved ${new Date(approval.approved_at).toLocaleString()}`;
    }
    if (approval.status === 'rejected' && approval.rejected_at) {
        return `Rejected ${new Date(approval.rejected_at).toLocaleString()}`;
    }
    return `Created ${new Date(approval.created_at).toLocaleString()}`;
};

const BuyerMatchPanel = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [contactId, setContactId] = useState<number | ''>('');
    const [goal, setGoal] = useState('shortlist_prep');
    const [budgetMin, setBudgetMin] = useState('');
    const [budgetMax, setBudgetMax] = useState('');
    const [areas, setAreas] = useState('');
    const [propertyType, setPropertyType] = useState('condo');
    const [bedroomsMin, setBedroomsMin] = useState('');
    const [bathroomsMin, setBathroomsMin] = useState('');
    const [sqftMin, setSqftMin] = useState('');
    const [parkingRequired, setParkingRequired] = useState(false);
    const [timeline, setTimeline] = useState('');
    const [mustHaves, setMustHaves] = useState('');
    const [niceToHaves, setNiceToHaves] = useState('');
    const [dealBreakers, setDealBreakers] = useState('');
    const [buyerContextNotes, setBuyerContextNotes] = useState('');
    const [candidates, setCandidates] = useState<CandidateRow[]>([createEmptyCandidate()]);

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<BuyerMatchLatestResponse>(EMPTY_LATEST);
    const [approvals, setApprovals] = useState<AgentApproval[]>([]);
    const [recentDecisions, setRecentDecisions] = useState<AgentApproval[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [triggering, setTriggering] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [activeApprovalId, setActiveApprovalId] = useState<number | null>(null);

    const [error, setError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);
    const [decisionError, setDecisionError] = useState<string | null>(null);

    const isBusy = loading || refreshing;

    const loadAuditLogs = async (runId: number) => {
        setAuditLoading(true);
        setAuditError(null);
        try {
            const logs = await agentsService.getBuyerMatchRunAuditLogs(runId);
            setAuditLogs(logs);
        } catch (loadError) {
            setAuditLogs([]);
            setAuditError(getErrorMessage(loadError, 'Audit history is unavailable for this run.'));
        } finally {
            setAuditLoading(false);
        }
    };

    const loadData = async (mode: 'initial' | 'refresh' = 'refresh') => {
        if (mode === 'initial') {
            setLoading(true);
        } else {
            setRefreshing(true);
        }
        setError(null);

        try {
            const [contactsData, runsData, latestData, approvalsData] = await Promise.all([
                crmService.getContacts(),
                agentsService.getBuyerMatchRuns(),
                agentsService.getLatestBuyerMatchResult(),
                agentsService.getBuyerMatchPendingApprovals(),
            ]);

            setContacts([...contactsData].sort((a, b) => a.name.localeCompare(b.name)));
            setRuns(runsData);
            setLatest(latestData);
            setApprovals(approvalsData);

            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? null);
            setSelectedRunId(preferredRunId);

            try {
                const history = await agentsService.getBuyerMatchApprovalHistory();
                setRecentDecisions(history);
                setDecisionError(null);
            } catch (historyError) {
                setRecentDecisions([]);
                setDecisionError(
                    getErrorMessage(historyError, 'Recent approval history is unavailable.'),
                );
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load Buyer Match Agent data.'));
        } finally {
            if (mode === 'initial') {
                setLoading(false);
            } else {
                setRefreshing(false);
            }
        }
    };

    useEffect(() => {
        void loadData('initial');
    }, []);

    useEffect(() => {
        if (selectedRunId === null) {
            setAuditLogs([]);
            setAuditError(null);
            return;
        }

        void loadAuditLogs(selectedRunId);
    }, [selectedRunId]);

    const splitCsv = (value: string) => {
        return value
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
    };

    const sanitizeCandidates = (): BuyerMatchCandidateInput[] => {
        return candidates
            .map((item) => ({
                address: item.address.trim() || undefined,
                list_price: item.listPrice.trim() ? Number(item.listPrice) : undefined,
                property_type: item.propertyType.trim() || undefined,
                bedrooms: item.bedrooms.trim() ? Number(item.bedrooms) : undefined,
                bathrooms: item.bathrooms.trim() ? Number(item.bathrooms) : undefined,
                sqft: item.sqft.trim() ? Number(item.sqft) : undefined,
                area: item.area.trim() || undefined,
                parking: item.parking.trim() ? Number(item.parking) : undefined,
                notes: item.notes.trim() || undefined,
            }))
            .filter((item) => item.address);
    };

    const handleTrigger = async () => {
        if (!contactId) {
            setError('Select a contact before running the Buyer Match Agent.');
            return;
        }

        const payload: BuyerMatchRunRequest = {
            contact_id: contactId,
            goal,
            criteria: {
                budget_min: budgetMin.trim() ? Number(budgetMin) : undefined,
                budget_max: budgetMax.trim() ? Number(budgetMax) : undefined,
                areas: splitCsv(areas),
                property_type: propertyType || undefined,
                bedrooms_min: bedroomsMin.trim() ? Number(bedroomsMin) : undefined,
                bathrooms_min: bathroomsMin.trim() ? Number(bathroomsMin) : undefined,
                sqft_min: sqftMin.trim() ? Number(sqftMin) : undefined,
                parking_required: parkingRequired,
                timeline: timeline.trim() || undefined,
                must_haves: splitCsv(mustHaves),
                nice_to_haves: splitCsv(niceToHaves),
                deal_breakers: splitCsv(dealBreakers),
            },
            buyer_context_notes: buyerContextNotes.trim() || undefined,
            candidates: sanitizeCandidates(),
        };

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerBuyerMatchRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData();
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Buyer Match Agent.'));
        } finally {
            setTriggering(false);
        }
    };

    const handleApprove = async (approvalId: number) => {
        setActiveApprovalId(approvalId);
        setError(null);
        try {
            await agentsService.approve(approvalId);
            await loadData();
        } catch (approveError) {
            setError(getErrorMessage(approveError, 'Failed to approve action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const handleReject = async (approvalId: number) => {
        const promptValue = window.prompt('Rejection reason (optional):');
        if (promptValue === null) {
            return;
        }

        setActiveApprovalId(approvalId);
        setError(null);
        try {
            await agentsService.reject(approvalId, promptValue);
            await loadData();
        } catch (rejectError) {
            setError(getErrorMessage(rejectError, 'Failed to reject action.'));
        } finally {
            setActiveApprovalId(null);
        }
    };

    const updateCandidate = (index: number, field: keyof CandidateRow, value: string) => {
        setCandidates((current) =>
            current.map((item, itemIndex) =>
                itemIndex === index ? { ...item, [field]: value } : item,
            ),
        );
    };

    const addCandidate = () => {
        setCandidates((current) => {
            if (current.length >= MAX_CANDIDATES) {
                return current;
            }
            return [...current, createEmptyCandidate()];
        });
    };

    const removeCandidate = (index: number) => {
        setCandidates((current) => {
            if (current.length === 1) {
                return [createEmptyCandidate()];
            }
            return current.filter((_, itemIndex) => itemIndex !== index);
        });
    };

    const latestRun = runs[0] ?? null;
    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const pageStatus = loading
        ? 'Loading Buyer Match Agent data...'
        : refreshing
            ? 'Refreshing Buyer Match Agent data...'
            : null;

    return (
        <section className="space-y-6 border-t border-white/10 pt-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-xl font-semibold">Buyer Match Agent</h2>
                    <p className="text-sm text-gray-400">
                        Manual buyer-side shortlist support with approval-only draft summaries. No sending or hidden automation.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => void loadData()}
                        className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        Refresh
                    </button>
                    <button
                        onClick={handleTrigger}
                        className="px-3 py-1.5 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        {triggering ? 'Running...' : 'Run Buyer Match Agent'}
                    </button>
                </div>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            {pageStatus && <div className="text-sm text-gray-400">{pageStatus}</div>}

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Manual Trigger</h3>
                <div className="border rounded p-3 bg-white/5 space-y-3">
                    <div className="grid gap-3 md:grid-cols-2">
                        <div>
                            <label htmlFor="bm-contact" className="block text-sm font-medium mb-1">
                                Contact
                            </label>
                            <select
                                id="bm-contact"
                                value={contactId}
                                onChange={(event) =>
                                    setContactId(event.target.value ? Number(event.target.value) : '')
                                }
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="">Select a contact</option>
                                {contacts.map((contact) => (
                                    <option key={contact.id} value={contact.id}>
                                        {contact.name}
                                        {contact.company ? ` (${contact.company})` : ''}
                                    </option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label htmlFor="bm-goal" className="block text-sm font-medium mb-1">
                                Goal
                            </label>
                            <select
                                id="bm-goal"
                                value={goal}
                                onChange={(event) => setGoal(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="shortlist_prep">Shortlist prep</option>
                                <option value="compare_options">Compare options</option>
                                <option value="buyer_summary_draft">Buyer summary draft</option>
                            </select>
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-3">
                        <div>
                            <label htmlFor="bm-budget-min" className="block text-sm font-medium mb-1">
                                Budget Min
                            </label>
                            <input
                                id="bm-budget-min"
                                value={budgetMin}
                                onChange={(event) => setBudgetMin(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="700000"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-budget-max" className="block text-sm font-medium mb-1">
                                Budget Max
                            </label>
                            <input
                                id="bm-budget-max"
                                value={budgetMax}
                                onChange={(event) => setBudgetMax(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="900000"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-property-type" className="block text-sm font-medium mb-1">
                                Property Type
                            </label>
                            <select
                                id="bm-property-type"
                                value={propertyType}
                                onChange={(event) => setPropertyType(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="condo">Condo</option>
                                <option value="townhouse">Townhouse</option>
                                <option value="semi">Semi</option>
                                <option value="detached">Detached</option>
                                <option value="commercial">Commercial</option>
                            </select>
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-4">
                        <div>
                            <label htmlFor="bm-bedrooms-min" className="block text-sm font-medium mb-1">
                                Bedrooms Min
                            </label>
                            <input
                                id="bm-bedrooms-min"
                                value={bedroomsMin}
                                onChange={(event) => setBedroomsMin(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="2"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-bathrooms-min" className="block text-sm font-medium mb-1">
                                Bathrooms Min
                            </label>
                            <input
                                id="bm-bathrooms-min"
                                value={bathroomsMin}
                                onChange={(event) => setBathroomsMin(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="2"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-sqft-min" className="block text-sm font-medium mb-1">
                                Sqft Min
                            </label>
                            <input
                                id="bm-sqft-min"
                                value={sqftMin}
                                onChange={(event) => setSqftMin(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="700"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-timeline" className="block text-sm font-medium mb-1">
                                Timeline
                            </label>
                            <input
                                id="bm-timeline"
                                value={timeline}
                                onChange={(event) => setTimeline(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="within_90_days"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                        <div>
                            <label htmlFor="bm-areas" className="block text-sm font-medium mb-1">
                                Preferred Areas
                            </label>
                            <input
                                id="bm-areas"
                                value={areas}
                                onChange={(event) => setAreas(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="King West, CityPlace"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div className="flex items-end">
                            <label className="inline-flex items-center gap-2 text-sm">
                                <input
                                    type="checkbox"
                                    checked={parkingRequired}
                                    onChange={(event) => setParkingRequired(event.target.checked)}
                                    disabled={isBusy || triggering || activeApprovalId !== null}
                                />
                                Parking required
                            </label>
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-3">
                        <div>
                            <label htmlFor="bm-must-haves" className="block text-sm font-medium mb-1">
                                Must-Haves
                            </label>
                            <input
                                id="bm-must-haves"
                                value={mustHaves}
                                onChange={(event) => setMustHaves(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="transit access, balcony"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-nice-to-haves" className="block text-sm font-medium mb-1">
                                Nice-to-Haves
                            </label>
                            <input
                                id="bm-nice-to-haves"
                                value={niceToHaves}
                                onChange={(event) => setNiceToHaves(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="gym, concierge"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>

                        <div>
                            <label htmlFor="bm-deal-breakers" className="block text-sm font-medium mb-1">
                                Deal-Breakers
                            </label>
                            <input
                                id="bm-deal-breakers"
                                value={dealBreakers}
                                onChange={(event) => setDealBreakers(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                placeholder="ground floor, no parking"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            />
                        </div>
                    </div>

                    <div>
                        <label htmlFor="bm-context-notes" className="block text-sm font-medium mb-1">
                            Buyer Context Notes
                        </label>
                        <textarea
                            id="bm-context-notes"
                            value={buyerContextNotes}
                            onChange={(event) => setBuyerContextNotes(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-24"
                            placeholder="Buyer wants a tight practical shortlist and cares about transit more than amenities."
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        />
                    </div>

                    <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium">Candidate List</div>
                                <div className="text-xs text-gray-400">
                                    Manual shortlist-sized input only. Max {MAX_CANDIDATES} candidates in v1.
                                </div>
                            </div>
                            <button
                                onClick={addCandidate}
                                className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-50"
                                disabled={
                                    isBusy ||
                                    triggering ||
                                    activeApprovalId !== null ||
                                    candidates.length >= MAX_CANDIDATES
                                }
                            >
                                Add Candidate
                            </button>
                        </div>

                        {candidates.map((candidate, index) => (
                            <div key={index} className="border rounded p-3 bg-black/10 space-y-3">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">Candidate #{index + 1}</div>
                                    <button
                                        onClick={() => removeCandidate(index)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || triggering || activeApprovalId !== null}
                                    >
                                        Remove
                                    </button>
                                </div>

                                <div className="grid gap-3 md:grid-cols-2">
                                    <div>
                                        <label className="block text-xs font-medium mb-1">Address</label>
                                        <input
                                            value={candidate.address}
                                            onChange={(event) =>
                                                updateCandidate(index, 'address', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="20 Stewart St #706"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Area</label>
                                        <input
                                            value={candidate.area}
                                            onChange={(event) =>
                                                updateCandidate(index, 'area', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="King West"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>
                                </div>

                                <div className="grid gap-3 md:grid-cols-5">
                                    <div>
                                        <label className="block text-xs font-medium mb-1">List Price</label>
                                        <input
                                            value={candidate.listPrice}
                                            onChange={(event) =>
                                                updateCandidate(index, 'listPrice', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="859000"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Type</label>
                                        <input
                                            value={candidate.propertyType}
                                            onChange={(event) =>
                                                updateCandidate(index, 'propertyType', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="condo"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Beds</label>
                                        <input
                                            value={candidate.bedrooms}
                                            onChange={(event) =>
                                                updateCandidate(index, 'bedrooms', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="2"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Baths</label>
                                        <input
                                            value={candidate.bathrooms}
                                            onChange={(event) =>
                                                updateCandidate(index, 'bathrooms', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="2"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Sqft</label>
                                        <input
                                            value={candidate.sqft}
                                            onChange={(event) =>
                                                updateCandidate(index, 'sqft', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="800"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>
                                </div>

                                <div className="grid gap-3 md:grid-cols-2">
                                    <div>
                                        <label className="block text-xs font-medium mb-1">Parking</label>
                                        <input
                                            value={candidate.parking}
                                            onChange={(event) =>
                                                updateCandidate(index, 'parking', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="1"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1">Notes</label>
                                        <input
                                            value={candidate.notes}
                                            onChange={(event) =>
                                                updateCandidate(index, 'notes', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="Parking included and close to transit."
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Latest Result</h3>
                <div className="border rounded p-3 bg-white/5 text-sm space-y-2">
                    {latestRun ? (
                        <div className="text-gray-300">
                            Latest run #{latestRun.id} is <span className="font-medium">{latestRun.status}</span>
                            {latestRun.finished_at && <> as of {new Date(latestRun.finished_at).toLocaleString()}</>}
                        </div>
                    ) : (
                        <div className="text-gray-400">No Buyer Match runs have been created yet.</div>
                    )}
                    {latest.error && (
                        <div className="text-rose-300">Latest run error: {latest.error}</div>
                    )}
                    {!latest.result ? (
                        <div className="text-gray-500">
                            {latest.run_id
                                ? 'The latest Buyer Match run has no structured result to display.'
                                : 'No Buyer Match result yet.'}
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <div>
                                <div className="text-xs font-semibold text-gray-300">Needs Summary</div>
                                <div>{latest.result.buyer_needs_summary.summary}</div>
                            </div>

                            <div className="text-xs text-gray-400">
                                {latest.result.shortlist_framing}
                            </div>

                            <div className="grid gap-3 md:grid-cols-3">
                                <div>
                                    <div className="text-xs font-semibold text-gray-300 mb-1">Must-Haves</div>
                                    {latest.result.buyer_needs_summary.must_haves.length === 0 ? (
                                        <div className="text-xs text-gray-500">None captured.</div>
                                    ) : (
                                        <div className="space-y-1">
                                            {latest.result.buyer_needs_summary.must_haves.map((item) => (
                                                <div key={item} className="text-xs text-gray-200">
                                                    {item}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                <div>
                                    <div className="text-xs font-semibold text-gray-300 mb-1">Nice-to-Haves</div>
                                    {latest.result.buyer_needs_summary.nice_to_haves.length === 0 ? (
                                        <div className="text-xs text-gray-500">None captured.</div>
                                    ) : (
                                        <div className="space-y-1">
                                            {latest.result.buyer_needs_summary.nice_to_haves.map((item) => (
                                                <div key={item} className="text-xs text-gray-200">
                                                    {item}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                <div>
                                    <div className="text-xs font-semibold text-gray-300 mb-1">Deal-Breakers</div>
                                    {latest.result.buyer_needs_summary.deal_breakers.length === 0 ? (
                                        <div className="text-xs text-gray-500">None captured.</div>
                                    ) : (
                                        <div className="space-y-1">
                                            {latest.result.buyer_needs_summary.deal_breakers.map((item) => (
                                                <div key={item} className="text-xs text-gray-200">
                                                    {item}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div>
                                <div className="text-xs font-semibold text-gray-300 mb-1">Shortlist</div>
                                {latest.result.shortlist.length === 0 ? (
                                    <div className="text-xs text-gray-500">No shortlist candidates in the latest result.</div>
                                ) : (
                                    <div className="space-y-2">
                                        {latest.result.shortlist.map((item) => (
                                            <div key={`${item.rank}-${item.title}`} className="border rounded p-2 bg-black/10">
                                                <div className="font-medium">
                                                    #{item.rank} {item.title}
                                                </div>
                                                <div className="text-xs text-gray-400">
                                                    Match strength: {item.match_strength}
                                                    {item.property_id && <> · Property #{item.property_id}</>}
                                                </div>
                                                {item.why_it_fits.length > 0 && (
                                                    <div className="mt-1 text-xs text-gray-300">
                                                        Fits: {item.why_it_fits.join(' ')}
                                                    </div>
                                                )}
                                                {item.tradeoffs.length > 0 && (
                                                    <div className="mt-1 text-xs text-amber-200">
                                                        Tradeoffs: {item.tradeoffs.join(' ')}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div>
                                <div className="text-xs font-semibold text-gray-300 mb-1">Tradeoff Summary</div>
                                {latest.result.tradeoff_summary.length === 0 ? (
                                    <div className="text-xs text-gray-500">No tradeoff summary.</div>
                                ) : (
                                    <div className="space-y-1">
                                        {latest.result.tradeoff_summary.map((item) => (
                                            <div key={item} className="text-xs text-gray-200">
                                                {item}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div>
                                <div className="text-xs font-semibold text-gray-300 mb-1">
                                    Recommended Next Manual Action
                                </div>
                                <div>{latest.result.recommended_next_manual_action}</div>
                            </div>

                            {latest.result.buyer_drafts.length > 0 && (
                                <div className="space-y-2">
                                    <div className="text-xs font-semibold text-gray-300">Buyer Draft Preview</div>
                                    {latest.result.buyer_drafts.map((draft) => (
                                        <div key={draft.variant} className="border rounded p-2 bg-black/10">
                                            <div className="font-medium">
                                                {draft.subject || draft.variant}
                                            </div>
                                            <div className="text-xs text-gray-400">
                                                Review-only draft
                                                {draft.approval_id && <> · Approval #{draft.approval_id}</>}
                                            </div>
                                            <div className="mt-1 whitespace-pre-wrap text-sm">{draft.body}</div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {(latest.result.risk_flags.length > 0 ||
                                latest.result.missing_data_flags.length > 0 ||
                                latest.result.operator_notes.length > 0) && (
                                <div className="grid gap-3 md:grid-cols-3">
                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">Risk Flags</div>
                                        {latest.result.risk_flags.length === 0 ? (
                                            <div className="text-xs text-gray-500">None.</div>
                                        ) : (
                                            <div className="space-y-1">
                                                {latest.result.risk_flags.map((item) => (
                                                    <div key={item} className="text-xs text-amber-200">
                                                        {item}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">Missing Data</div>
                                        {latest.result.missing_data_flags.length === 0 ? (
                                            <div className="text-xs text-gray-500">None.</div>
                                        ) : (
                                            <div className="space-y-1">
                                                {latest.result.missing_data_flags.map((item) => (
                                                    <div key={item} className="text-xs text-gray-200">
                                                        {item}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">Operator Notes</div>
                                        {latest.result.operator_notes.length === 0 ? (
                                            <div className="text-xs text-gray-500">None.</div>
                                        ) : (
                                            <div className="space-y-1">
                                                {latest.result.operator_notes.map((item) => (
                                                    <div key={item} className="text-xs text-gray-200">
                                                        {item}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Pending Approvals</h3>
                <p className="text-sm text-gray-400">
                    Approving or rejecting here only resolves review status. It does not send anything.
                </p>
                {approvals.length === 0 ? (
                    <div className="text-sm text-gray-500">No pending Buyer Match approvals.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {approvals.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            const isSubmitting = activeApprovalId === approval.id;
                            return (
                                <div key={approval.id} className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {payload.variant || approval.action_type}
                                        </div>
                                        <div className="space-x-2">
                                            <button
                                                onClick={() => handleApprove(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700"
                                                disabled={isBusy || auditLoading || activeApprovalId !== null}
                                            >
                                                {isSubmitting ? 'Working...' : 'Approve'}
                                            </button>
                                            <button
                                                onClick={() => handleReject(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700"
                                                disabled={isBusy || auditLoading || activeApprovalId !== null}
                                            >
                                                Reject
                                            </button>
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-1">
                                        Risk {approval.risk_level} · Created {new Date(approval.created_at).toLocaleString()}
                                    </div>
                                    {payload.review_mode && (
                                        <div className="text-xs text-gray-400 mt-1">
                                            Review mode: {payload.review_mode}
                                        </div>
                                    )}
                                    {payload.shortlist_framing && (
                                        <div className="text-xs text-gray-400 mt-1">
                                            {payload.shortlist_framing}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="mt-2">
                                            <div className="text-xs font-semibold text-gray-300">Subject</div>
                                            <div>{payload.subject}</div>
                                        </div>
                                    )}
                                    {payload.body && (
                                        <div className="mt-2">
                                            <div className="text-xs font-semibold text-gray-300">Preview</div>
                                            <div className="text-gray-200 whitespace-pre-wrap">{payload.body}</div>
                                        </div>
                                    )}
                                    {payload.shortlist_titles && payload.shortlist_titles.length > 0 && (
                                        <div className="mt-2 text-xs text-gray-400">
                                            Shortlist: {payload.shortlist_titles.join(' · ')}
                                        </div>
                                    )}
                                    {payload.contact_id && (
                                        <div className="mt-1 text-xs text-gray-400">
                                            Contact #{payload.contact_id}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Recent Approval Decisions</h3>
                {decisionError && <div className="text-sm text-amber-300">{decisionError}</div>}
                {recentDecisions.length === 0 ? (
                    <div className="text-sm text-gray-500">No recent Buyer Match approval decisions.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentDecisions.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            return (
                                <div key={approval.id} className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            {payload.variant || approval.action_type}
                                        </div>
                                        <div className={approval.status === 'approved' ? 'text-xs font-medium text-emerald-300' : 'text-xs font-medium text-rose-300'}>
                                            {approval.status}
                                        </div>
                                    </div>
                                    <div className="mt-1 text-xs text-gray-400">{getDecisionMeta(approval)}</div>
                                    {approval.approved_by && (
                                        <div className="mt-1 text-xs text-gray-400">
                                            Reviewed by: {approval.approved_by}
                                        </div>
                                    )}
                                    {approval.rejection_reason && (
                                        <div className="mt-1 text-xs text-rose-200">
                                            Rejection reason: {approval.rejection_reason}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="mt-1 text-xs text-gray-300">
                                            Subject: {payload.subject}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Recent Runs</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No Buyer Match runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`text-sm border-b border-gray-700/40 pb-3 last:border-b-0 ${selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-2' : ''}`}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <div className="font-medium">
                                            Run #{run.id} · {run.status}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            {run.summary || 'No summary'} · {new Date(run.created_at).toLocaleString()}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => setSelectedRunId(run.id)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || auditLoading || activeApprovalId !== null}
                                    >
                                        {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                    </button>
                                </div>
                                {run.error && (
                                    <div className="mt-1 text-xs text-rose-300">Error: {run.error}</div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Audit History</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">Select a run to inspect audit history.</div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => (
                            <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-medium">{log.action}</div>
                                    <div className="text-xs text-gray-400">
                                        {new Date(log.created_at).toLocaleString()}
                                    </div>
                                </div>
                                <div className="text-xs text-gray-400 mt-0.5">
                                    Actor: {log.actor_type}
                                </div>
                                {log.details && (
                                    <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                        {formatAuditDetails(log.details)}
                                    </pre>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>
        </section>
    );
};

export default BuyerMatchPanel;
