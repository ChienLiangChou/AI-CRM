import axios from 'axios';
import { useEffect, useState } from 'react';
import { crmService } from '../../services/api';
import type { Contact, Property } from '../../services/api';
import { agentsService } from '../../services/agents';
import type {
    AgentApproval,
    AgentAuditLog,
    AgentRun,
    ListingCmaComparableInput,
    ListingCmaLatestResponse,
    ListingCmaRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: ListingCmaLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

type ComparableRow = {
    address: string;
    status: string;
    price: string;
    notes: string;
};

type ListingApprovalPayload = {
    subject?: string;
    body?: string;
    contact_id?: number;
    property_id?: number;
    variant?: string;
    pricing_framing?: string;
    internal_price_discussion_range?: string;
};

const createEmptyComparable = (): ComparableRow => ({
    address: '',
    status: 'sold',
    price: '',
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

const parseApprovalPayload = (payload?: string): ListingApprovalPayload => {
    const parsed = parseJsonText(payload);
    if (!parsed || typeof parsed !== 'object') {
        return {};
    }

    return parsed as ListingApprovalPayload;
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

const formatPropertyLabel = (property: Property) => {
    const unit = property.unit ? ` #${property.unit}` : '';
    const location = [property.city, property.province].filter(Boolean).join(', ');
    return `${property.street}${unit}${location ? `, ${location}` : ''}`;
};

const ListingCmaPanel = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [properties, setProperties] = useState<Property[]>([]);
    const [contactId, setContactId] = useState<number | ''>('');
    const [propertyId, setPropertyId] = useState<number | ''>('');
    const [meetingGoal, setMeetingGoal] = useState('listing_appointment_prep');
    const [subjectPropertyNotes, setSubjectPropertyNotes] = useState('');
    const [sellerContextNotes, setSellerContextNotes] = useState('');
    const [comparables, setComparables] = useState<ComparableRow[]>([createEmptyComparable()]);

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<ListingCmaLatestResponse>(EMPTY_LATEST);
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
            const logs = await agentsService.getListingCmaRunAuditLogs(runId);
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
            const [contactsData, propertiesData, runsData, latestData, approvalsData] =
                await Promise.all([
                    crmService.getContacts(),
                    crmService.getProperties(),
                    agentsService.getListingCmaRuns(),
                    agentsService.getLatestListingCmaResult(),
                    agentsService.getListingCmaPendingApprovals(),
                ]);

            setContacts([...contactsData].sort((a, b) => a.name.localeCompare(b.name)));
            setProperties(
                [...propertiesData].sort((a, b) =>
                    formatPropertyLabel(a).localeCompare(formatPropertyLabel(b)),
                ),
            );
            setRuns(runsData);
            setLatest(latestData);
            setApprovals(approvalsData);

            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? null);
            setSelectedRunId(preferredRunId);

            try {
                const history = await agentsService.getListingCmaApprovalHistory();
                setRecentDecisions(history);
                setDecisionError(null);
            } catch (historyError) {
                setRecentDecisions([]);
                setDecisionError(
                    getErrorMessage(historyError, 'Recent approval history is unavailable.'),
                );
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load Listing / CMA Agent data.'));
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

    const sanitizeComparables = (): ListingCmaComparableInput[] => {
        return comparables
            .map((item) => ({
                address: item.address.trim(),
                status: item.status || 'sold',
                price: item.price.trim() ? Number(item.price) : undefined,
                notes: item.notes.trim() || undefined,
            }))
            .filter((item) => item.address);
    };

    const handleTrigger = async () => {
        if (!contactId) {
            setError('Select a contact before running the Listing / CMA Agent.');
            return;
        }

        const payload: ListingCmaRunRequest = {
            contact_id: contactId,
            property_id: propertyId || undefined,
            meeting_goal: meetingGoal,
            subject_property_notes: subjectPropertyNotes.trim() || undefined,
            seller_context_notes: sellerContextNotes.trim() || undefined,
            comparables: sanitizeComparables(),
        };

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerListingCmaRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData();
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Listing / CMA Agent.'));
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

    const updateComparable = (index: number, field: keyof ComparableRow, value: string) => {
        setComparables((current) =>
            current.map((item, itemIndex) =>
                itemIndex === index ? { ...item, [field]: value } : item,
            ),
        );
    };

    const addComparable = () => {
        setComparables((current) => [...current, createEmptyComparable()]);
    };

    const removeComparable = (index: number) => {
        setComparables((current) => {
            if (current.length === 1) {
                return [createEmptyComparable()];
            }
            return current.filter((_, itemIndex) => itemIndex !== index);
        });
    };

    const latestRun = runs[0] ?? null;
    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
    const pageStatus = loading
        ? 'Loading Listing / CMA Agent data...'
        : refreshing
            ? 'Refreshing Listing / CMA Agent data...'
            : null;

    return (
        <section className="space-y-6 border-t border-white/10 pt-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-xl font-semibold">Listing / CMA Agent</h2>
                    <p className="text-sm text-gray-400">
                        Manual seller-prep and CMA-support review surface. Pricing output stays internal discussion support only.
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
                        className="px-3 py-1.5 text-sm rounded bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                        disabled={isBusy || triggering || activeApprovalId !== null}
                    >
                        {triggering ? 'Running...' : 'Run Listing / CMA Agent'}
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
                            <label htmlFor="lc-contact" className="block text-sm font-medium mb-1">
                                Contact
                            </label>
                            <select
                                id="lc-contact"
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
                            <label htmlFor="lc-property" className="block text-sm font-medium mb-1">
                                Property (Optional)
                            </label>
                            <select
                                id="lc-property"
                                value={propertyId}
                                onChange={(event) =>
                                    setPropertyId(event.target.value ? Number(event.target.value) : '')
                                }
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="">No property selected</option>
                                {properties.map((property) => (
                                    <option key={property.id} value={property.id}>
                                        {formatPropertyLabel(property)}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-3">
                        <div>
                            <label htmlFor="lc-meeting-goal" className="block text-sm font-medium mb-1">
                                Meeting Goal
                            </label>
                            <select
                                id="lc-meeting-goal"
                                value={meetingGoal}
                                onChange={(event) => setMeetingGoal(event.target.value)}
                                className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                <option value="listing_appointment_prep">Listing appointment prep</option>
                                <option value="post_walkthrough_summary">Post-walkthrough summary</option>
                                <option value="pricing_discussion_prep">Pricing discussion prep</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label htmlFor="lc-subject-notes" className="block text-sm font-medium mb-1">
                            Subject Property Notes
                        </label>
                        <textarea
                            id="lc-subject-notes"
                            value={subjectPropertyNotes}
                            onChange={(event) => setSubjectPropertyNotes(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-24"
                            placeholder="Optional property facts, upgrades, layout notes, or seller-provided details."
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        />
                    </div>

                    <div>
                        <label htmlFor="lc-seller-context" className="block text-sm font-medium mb-1">
                            Seller Context Notes
                        </label>
                        <textarea
                            id="lc-seller-context"
                            value={sellerContextNotes}
                            onChange={(event) => setSellerContextNotes(event.target.value)}
                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-20"
                            placeholder="Optional notes about seller concerns, timing, or what you want help framing."
                            disabled={isBusy || triggering || activeApprovalId !== null}
                        />
                    </div>

                    <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium">Operator-Entered Comparables</div>
                                <div className="text-xs text-gray-400">
                                    Manual input only for v1. Leave blank if you want internal-only output with missing-data flags.
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={addComparable}
                                className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                disabled={isBusy || triggering || activeApprovalId !== null}
                            >
                                Add Comparable
                            </button>
                        </div>

                        {comparables.map((comparable, index) => (
                            <div
                                key={`listing-cma-comparable-${index}`}
                                className="rounded border border-white/10 bg-black/20 p-3 space-y-3"
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="text-xs font-semibold text-gray-300">
                                        Comparable #{index + 1}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => removeComparable(index)}
                                        className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || triggering || activeApprovalId !== null}
                                    >
                                        Remove
                                    </button>
                                </div>

                                <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
                                    <div>
                                        <label
                                            htmlFor={`lc-comparable-address-${index}`}
                                            className="block text-xs font-medium mb-1"
                                        >
                                            Address
                                        </label>
                                        <input
                                            id={`lc-comparable-address-${index}`}
                                            value={comparable.address}
                                            onChange={(event) =>
                                                updateComparable(index, 'address', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="123 King St W #1205"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>

                                    <div>
                                        <label
                                            htmlFor={`lc-comparable-status-${index}`}
                                            className="block text-xs font-medium mb-1"
                                        >
                                            Status
                                        </label>
                                        <select
                                            id={`lc-comparable-status-${index}`}
                                            value={comparable.status}
                                            onChange={(event) =>
                                                updateComparable(index, 'status', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        >
                                            <option value="sold">Sold</option>
                                            <option value="active">Active</option>
                                            <option value="leased">Leased</option>
                                            <option value="expired">Expired</option>
                                        </select>
                                    </div>

                                    <div>
                                        <label
                                            htmlFor={`lc-comparable-price-${index}`}
                                            className="block text-xs font-medium mb-1"
                                        >
                                            Price
                                        </label>
                                        <input
                                            id={`lc-comparable-price-${index}`}
                                            value={comparable.price}
                                            onChange={(event) =>
                                                updateComparable(index, 'price', event.target.value)
                                            }
                                            className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm"
                                            placeholder="845000"
                                            inputMode="numeric"
                                            disabled={isBusy || triggering || activeApprovalId !== null}
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label
                                        htmlFor={`lc-comparable-notes-${index}`}
                                        className="block text-xs font-medium mb-1"
                                    >
                                        Notes
                                    </label>
                                    <textarea
                                        id={`lc-comparable-notes-${index}`}
                                        value={comparable.notes}
                                        onChange={(event) =>
                                            updateComparable(index, 'notes', event.target.value)
                                        }
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-sm min-h-16"
                                        placeholder="Optional notes about condition, layout, parking, or differences."
                                        disabled={isBusy || triggering || activeApprovalId !== null}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Latest Result</h3>
                {!latest.run_id ? (
                    <div className="text-sm text-gray-500">No Listing / CMA runs yet.</div>
                ) : (
                    <div className="border rounded p-3 bg-white/5 space-y-3 text-sm">
                        <div className="text-gray-300">
                            Latest run #{latest.run_id} is{' '}
                            <span className="font-medium">{latest.status ?? 'unknown'}</span>
                        </div>
                        {latest.error && (
                            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                                Run error: {latest.error}
                            </div>
                        )}
                        {!latest.result ? (
                            <div className="text-sm text-gray-400">
                                No parsed result is available for the latest run yet.
                            </div>
                        ) : (
                            <>
                                <div className="grid gap-3 md:grid-cols-2">
                                    <div className="rounded border border-white/10 bg-black/20 p-3">
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Listing Brief
                                        </div>
                                        <div className="text-sm">{latest.result.listing_brief.summary}</div>
                                        {latest.result.listing_brief.property_highlights.length > 0 && (
                                            <ul className="mt-2 list-disc pl-5 space-y-1 text-sm">
                                                {latest.result.listing_brief.property_highlights.map((item, index) => (
                                                    <li key={`${item}-${index}`}>{item}</li>
                                                ))}
                                            </ul>
                                        )}
                                        {latest.result.listing_brief.seller_context.length > 0 && (
                                            <div className="mt-2 text-xs text-gray-300">
                                                Seller context: {latest.result.listing_brief.seller_context.join(' · ')}
                                            </div>
                                        )}
                                    </div>

                                    <div className="rounded border border-white/10 bg-black/20 p-3">
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            CMA Support
                                        </div>
                                        <div>
                                            Internal discussion range:{' '}
                                            {latest.result.cma_support.internal_price_discussion_range || 'Not available'}
                                        </div>
                                        <div className="mt-1 text-xs text-amber-200">
                                            {latest.result.cma_support.range_framing}
                                        </div>
                                        {latest.result.cma_support.missing_data_flags.length > 0 && (
                                            <div className="mt-2 text-xs text-amber-300">
                                                Missing data: {latest.result.cma_support.missing_data_flags.join(', ')}
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div className="grid gap-3 md:grid-cols-2">
                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Comparable Narrative
                                        </div>
                                        {latest.result.cma_support.comparable_narrative.length === 0 ? (
                                            <div className="text-gray-500">No comparable narrative available.</div>
                                        ) : (
                                            <ul className="list-disc pl-5 space-y-1">
                                                {latest.result.cma_support.comparable_narrative.map((item, index) => (
                                                    <li key={`${item}-${index}`}>{item}</li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold text-gray-300 mb-1">
                                            Talking Points / Notes
                                        </div>
                                        {latest.result.talking_points.length === 0 ? (
                                            <div className="text-gray-500">No talking points.</div>
                                        ) : (
                                            <ul className="list-disc pl-5 space-y-1">
                                                {latest.result.talking_points.map((item, index) => (
                                                    <li key={`${item}-${index}`}>{item}</li>
                                                ))}
                                            </ul>
                                        )}
                                        <div className="mt-3">
                                            {latest.result.risk_flags.length > 0 ? (
                                                <div className="mb-2 text-amber-200">
                                                    {latest.result.risk_flags.join(', ')}
                                                </div>
                                            ) : (
                                                <div className="mb-2 text-gray-500">No risk flags.</div>
                                            )}
                                            {latest.result.operator_notes.length === 0 ? (
                                                <div className="text-gray-500">No operator notes.</div>
                                            ) : (
                                                <ul className="list-disc pl-5 space-y-1">
                                                    {latest.result.operator_notes.map((item, index) => (
                                                        <li key={`${item}-${index}`}>{item}</li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div>
                                    <div className="text-xs font-semibold text-gray-300 mb-1">
                                        Seller Draft Preview
                                    </div>
                                    {latest.result.seller_drafts.length === 0 ? (
                                        <div className="text-gray-500">
                                            No seller-facing draft was generated for the latest run.
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {latest.result.seller_drafts.map((draft, index) => (
                                                <div
                                                    key={`${draft.variant}-${index}`}
                                                    className="rounded border border-white/10 bg-black/20 p-3"
                                                >
                                                    <div className="font-medium">{draft.variant}</div>
                                                    {draft.subject && (
                                                        <div className="mt-1 text-sm text-gray-300">
                                                            Subject: {draft.subject}
                                                        </div>
                                                    )}
                                                    <pre className="mt-2 text-xs whitespace-pre-wrap rounded bg-black/20 p-2 overflow-auto">
                                                        {draft.body}
                                                    </pre>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Pending Approvals</h3>
                <p className="text-sm text-gray-400">
                    Approve or reject only resolves review status. It does not send anything.
                </p>
                {approvals.length === 0 ? (
                    <div className="text-sm text-gray-500">No pending approvals.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {approvals.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            const isSubmitting = activeApprovalId === approval.id;
                            return (
                                <div
                                    key={approval.id}
                                    className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0"
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {payload.variant || approval.action_type}
                                        </div>
                                        <div className="space-x-2">
                                            <button
                                                onClick={() => handleApprove(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700"
                                                disabled={isBusy || triggering || activeApprovalId !== null}
                                            >
                                                {isSubmitting ? 'Working...' : 'Approve'}
                                            </button>
                                            <button
                                                onClick={() => handleReject(approval.id)}
                                                className="px-2 py-1 text-xs rounded bg-rose-600 text-white hover:bg-rose-700"
                                                disabled={isBusy || triggering || activeApprovalId !== null}
                                            >
                                                Reject
                                            </button>
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Risk: {approval.risk_level} · Status: {approval.status}
                                    </div>
                                    {(payload.contact_id || payload.property_id) && (
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            {payload.contact_id ? `Contact ID: ${payload.contact_id}` : 'Contact ID: n/a'}
                                            {payload.property_id ? ` · Property ID: ${payload.property_id}` : ''}
                                        </div>
                                    )}
                                    {payload.internal_price_discussion_range && (
                                        <div className="text-xs text-amber-200 mt-1">
                                            Internal range: {payload.internal_price_discussion_range}
                                        </div>
                                    )}
                                    {payload.pricing_framing && (
                                        <div className="text-xs text-amber-300 mt-1">
                                            {payload.pricing_framing}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Subject</div>
                                            <div>{payload.subject}</div>
                                        </div>
                                    )}
                                    {payload.body && (
                                        <div className="mt-1">
                                            <div className="text-xs font-semibold text-gray-300">Body</div>
                                            <pre className="text-xs whitespace-pre-wrap bg-black/20 rounded p-2 max-h-48 overflow-auto">
                                                {payload.body}
                                            </pre>
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
                <p className="text-sm text-gray-400">
                    Recent manual review outcomes for the Listing / CMA Agent.
                </p>
                {decisionError && <div className="text-sm text-amber-300">{decisionError}</div>}
                {recentDecisions.length === 0 ? (
                    <div className="text-sm text-gray-500">No approval decisions yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {recentDecisions.map((approval) => {
                            const payload = parseApprovalPayload(approval.payload);
                            return (
                                <div
                                    key={approval.id}
                                    className="text-sm border-b border-gray-700/40 pb-3 last:border-b-0"
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="font-medium">
                                            #{approval.id} – {payload.variant || approval.action_type}
                                        </div>
                                        <div
                                            className={`text-xs font-medium ${
                                                approval.status === 'approved'
                                                    ? 'text-emerald-300'
                                                    : 'text-rose-300'
                                            }`}
                                        >
                                            {approval.status}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Run #{approval.run_id} · {getDecisionMeta(approval)}
                                    </div>
                                    {approval.approved_by && (
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            Reviewed by: {approval.approved_by}
                                        </div>
                                    )}
                                    {approval.rejection_reason && (
                                        <div className="text-xs text-rose-200 mt-1">
                                            Rejection reason: {approval.rejection_reason}
                                        </div>
                                    )}
                                    {payload.subject && (
                                        <div className="text-xs text-gray-300 mt-1">
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
                    <div className="text-sm text-gray-500">No runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-1 bg-white/5 text-sm">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between border-b border-gray-700/40 pb-2 last:border-b-0 ${
                                    selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''
                                }`}
                            >
                                <div>
                                    <div className="font-medium">
                                        Run #{run.id} – {run.status}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Created: {new Date(run.created_at).toLocaleString()}
                                        {run.finished_at && (
                                            <> · Finished: {new Date(run.finished_at).toLocaleString()}</>
                                        )}
                                    </div>
                                    {run.error && (
                                        <div className="text-xs text-rose-300 mt-0.5">
                                            Error: {run.error}
                                        </div>
                                    )}
                                </div>
                                <button
                                    onClick={() => setSelectedRunId(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering || activeApprovalId !== null}
                                >
                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h3 className="text-lg font-medium">Run Audit History</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({selectedRun.status})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">
                        Select a run to inspect its audit history.
                    </div>
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
                            <div
                                key={log.id}
                                className="border-b border-gray-700/40 pb-3 last:border-b-0"
                            >
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

            {latestRun && latestRun.id !== latest.run_id && (
                <div className="text-xs text-amber-300">
                    Latest result payload is from run #{latest.run_id}, while the newest run in the list is #{latestRun.id}.
                </div>
            )}
        </section>
    );
};

export default ListingCmaPanel;
