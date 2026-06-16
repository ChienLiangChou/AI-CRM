import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    Activity,
    AlertTriangle,
    BellRing,
    CheckCircle2,
    Clock3,
    Copy,
    Database,
    MailPlus,
    Pause,
    Play,
    SearchCheck,
    ShieldCheck,
    XCircle,
} from 'lucide-react';
import { crmService } from '../services/api';
import type { ClientWatchlist, Contact, CsvDropFolderImportResult, PropertyFeedConfig, PropertyImportMatchPreview, PropertyImportReadinessPreview, PropertyImportResult, PropertySourceStatus, WatchlistAlert, WatchlistDataIntakeChecklist, WatchlistDeliveryGateList, WatchlistLaunchActionPack, WatchlistNotification, WatchlistOperatorHandoffStatus, WatchlistReadinessReport, WatchlistRunLog, WatchlistSafetyStatus, WatchlistSourceSetup, WatchlistSourceTaskList } from '../services/api';
import './Watchlists.css';

const watchTypeLabel: Record<string, string> = {
    buyer_listing_match: 'Buyer Listing Match',
    seller_listing_and_sold: 'Seller Listing + Sold Comps',
    tenant_rental_match: 'Tenant Rental Match',
    landlord_rental_market: 'Landlord Rental Market',
};

const alertTypeLabel: Record<string, string> = {
    new_listing: 'New Listing',
    sold_comp: 'Sold Comp',
    new_rental_listing: 'New Rental',
    leased_comp: 'Leased Comp',
    system_notice: 'System',
};

const defaultGmailFeedQuery = 'newer_than:14d (MLS OR listing OR sold OR leased OR REALM OR TRREB)';

const reviewModeControls = [
    { value: 'manual_review', label: 'Manual' },
    { value: 'auto_create_draft', label: 'CRM Draft' },
    { value: 'auto_gmail_draft', label: 'Gmail Draft' },
];

const reviewModeLabel: Record<string, string> = {
    manual_review: 'Manual Review',
    auto_create_draft: 'Auto CRM Draft',
    auto_gmail_draft: 'Auto Gmail Draft Only',
    auto_send_approved: 'Auto Send Armed',
};

const notificationChannelLabel: Record<string, string> = {
    codex_app: 'Codex App',
    app_push: 'Browser Push',
    in_app: 'In-App Only',
};

const notificationChannelControls = [
    { value: 'codex_app', label: 'Codex' },
    { value: 'app_push', label: 'Push' },
    { value: 'in_app', label: 'In-App' },
];

const clientEmailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i;

const deliveryStateLabel: Record<string, string> = {
    manual_review_queue: 'Manual Review',
    crm_draft_only: 'CRM Draft Only',
    gmail_draft_ready: 'Gmail Draft Ready',
    auto_send_ready: 'Auto Send Ready',
    auto_send_armed_draft_only: 'Armed, Draft Only',
    email_required: 'Email Required',
    gmail_connection_required: 'Gmail Required',
    unknown_review_mode: 'Review Mode Needed',
};

type CriteriaDraft = {
    name: string;
    watch_type: string;
    areas: string;
    types: string;
    must_haves: string;
    deal_breakers: string;
    min_price: string;
    max_price: string;
    bedrooms_min: string;
    bathrooms_min: string;
    parking_min: string;
    property_address: string;
    available_after: string;
    source_query: string;
};

type ScheduleDraft = {
    times: string;
    timezone: string;
};

const formatDateTime = (value?: string) => {
    if (!value) return 'Not scheduled';
    return new Date(value).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
};

const formatRunTime = (value?: string) => {
    if (!value) return 'Never';
    return new Date(value).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
};

const fileSizeLabel = (bytes: number) => {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    return `${Math.round(bytes / 102.4) / 10} KB`;
};

const arrayValue = (value: unknown): string[] => {
    if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
    if (typeof value === 'string' && value.trim()) return [value.trim()];
    return [];
};

const criteriaSummary = (criteria: Record<string, unknown>) => {
    const chips: string[] = [];
    arrayValue(criteria.areas).forEach((area) => chips.push(area));
    arrayValue(criteria.types).forEach((type) => chips.push(type));
    arrayValue(criteria.must_haves).slice(0, 3).forEach((item) => chips.push(item));
    if (criteria.max_price) chips.push(`Max $${Number(criteria.max_price).toLocaleString()}`);
    if (criteria.bedrooms_min) chips.push(`${criteria.bedrooms_min}+ bed`);
    if (criteria.parking_min) chips.push(`${criteria.parking_min}+ parking`);
    if (criteria.property_address) chips.push(String(criteria.property_address));
    return chips.length ? chips : ['Criteria pending'];
};

const scheduleSummary = (schedule: Record<string, unknown>) => {
    const times = arrayValue(schedule.times);
    return `${times.length ? times.join(', ') : '09:00'} ${schedule.timezone || 'America/Toronto'}`;
};

const scheduleDraftFromWatchlist = (watchlist: ClientWatchlist): ScheduleDraft => ({
    times: arrayValue(watchlist.schedule.times).join(', ') || '09:00',
    timezone: String(watchlist.schedule.timezone || 'America/Toronto'),
});

const clientScheduleBusyKey = (watchlist: ClientWatchlist) => `client-schedule-${watchlist.contact_id}`;
const clientNotificationBusyKey = (watchlist: ClientWatchlist) => `client-notify-${watchlist.contact_id}`;
const clientReviewModeBusyKey = (watchlist: ClientWatchlist) => `client-review-${watchlist.contact_id}`;

const parseScheduleTimes = (value: string): string[] => value
    .split(/[,;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);

const csvValue = (value: unknown) => arrayValue(value).join(', ');

const numberDraft = (value: unknown) => {
    if (value === undefined || value === null || value === '') return '';
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? String(numberValue) : '';
};

const filenameFromPath = (value?: string) => (value || '').split(/[\\/]/).filter(Boolean).pop() || 'CSV file';

const dropFolderFailureMessages = (result: CsvDropFolderImportResult) => result.failed.flatMap((item) => {
    const file = filenameFromPath(item.file);
    const messages = item.result?.errors?.length ? item.result.errors : [item.error || item.status || 'Import failed'];
    return messages.map((message) => `${file}: ${message}`);
});

const splitCsv = (value: string) => value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const draftFromWatchlist = (watchlist: ClientWatchlist): CriteriaDraft => ({
    name: watchlist.name || '',
    watch_type: watchlist.watch_type || 'buyer_listing_match',
    areas: csvValue(watchlist.criteria.areas),
    types: csvValue(watchlist.criteria.types),
    must_haves: csvValue(watchlist.criteria.must_haves),
    deal_breakers: csvValue(watchlist.criteria.deal_breakers),
    min_price: numberDraft(watchlist.criteria.min_price),
    max_price: numberDraft(watchlist.criteria.max_price),
    bedrooms_min: numberDraft(watchlist.criteria.bedrooms_min),
    bathrooms_min: numberDraft(watchlist.criteria.bathrooms_min),
    parking_min: numberDraft(watchlist.criteria.parking_min),
    property_address: String(watchlist.criteria.property_address || ''),
    available_after: String(watchlist.criteria.available_after || ''),
    source_query: String(watchlist.source_query || ''),
});

const numberOrUndefined = (value: string) => {
    if (!value.trim()) return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
};

const moneyLabel = (value: unknown) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `$${parsed.toLocaleString()}` : '';
};

const previewPrice = (row: Record<string, unknown>) => (
    moneyLabel(row.sold_price) || moneyLabel(row.listing_price) || moneyLabel(row.monthly_rent) || 'No price'
);

const isContactEmailPreviewRow = (row: Record<string, unknown>) => row.action === 'update_contact_email';

const statusClass = (status: string) => {
    if (status === 'active') return 'status-active';
    if (status === 'success') return 'status-active';
    if (status === 'failed') return 'status-pending';
    if (status === 'draft_created') return 'status-draft';
    if (status === 'sent') return 'status-sent';
    if (status === 'dismissed') return 'status-muted';
    return 'status-pending';
};

const sourceReadinessClass = (readiness?: string) => {
    if (readiness === 'ready') return 'source-ready';
    if (readiness === 'needs_fields') return 'source-warning';
    if (readiness === 'missing_statuses') return 'source-warning';
    return 'source-blocked';
};

const sourceReadinessLabel = (readiness?: string) => {
    if (readiness === 'ready') return 'Ready';
    if (readiness === 'needs_fields') return 'Needs fields';
    if (readiness === 'missing_statuses') return 'Missing statuses';
    return 'Missing rows';
};

const importReadinessClass = (delta?: string) => {
    if (delta === 'becomes_ready' || delta === 'unchanged_ready') return 'source-ready';
    if (delta === 'improves') return 'source-warning';
    return 'source-blocked';
};

const importReadinessLabel = (delta?: string) => {
    if (delta === 'becomes_ready') return 'Becomes ready';
    if (delta === 'unchanged_ready') return 'Already ready';
    if (delta === 'improves') return 'Improves';
    return 'Still missing';
};

const importDeliveryClass = (state?: string) => {
    if (
        state === 'manual_review_after_import'
        || state === 'crm_draft_after_import'
        || state === 'gmail_draft_recipient_ready_after_import'
        || state === 'auto_send_ready_after_import'
    ) {
        return 'delivery-ready';
    }
    if (state === 'auto_send_armed_draft_only_after_import') return 'delivery-warning';
    return 'delivery-blocked';
};

const importDeliveryLabel = (state?: string) => {
    if (state === 'manual_review_after_import') return 'Manual review ready';
    if (state === 'crm_draft_after_import') return 'CRM draft ready';
    if (state === 'gmail_draft_recipient_ready_after_import') return 'Gmail draft recipient ready';
    if (state === 'auto_send_armed_draft_only_after_import') return 'Auto Send draft-only';
    if (state === 'auto_send_ready_after_import') return 'Auto Send ready';
    if (state === 'email_required_after_import') return 'Email required';
    if (state === 'source_not_ready') return 'Source still missing';
    return 'Delivery needs review';
};

const readinessClass = (severity?: string) => {
    if (severity === 'ready') return 'readiness-ready';
    if (severity === 'warning') return 'readiness-warning';
    return 'readiness-blocked';
};

const readinessLabel = (severity?: string) => {
    if (severity === 'ready') return 'Ready';
    if (severity === 'warning') return 'Needs attention';
    return 'Blocked';
};

const statusLabel = (status: string) => status.replaceAll('_', ' ');

const statusList = (statuses?: string[]) => (
    statuses?.length ? statuses.map(statusLabel).join(', ') : 'matching source rows'
);

const statusCountsLine = (counts?: Record<string, number>) => {
    const entries = Object.entries(counts || {});
    if (!entries.length) return '';
    return entries.map(([status, count]) => `${statusLabel(status)}: ${count}`).join(', ');
};

const readinessLine = (watchlist: ClientWatchlist) => {
    const readiness = watchlist.readiness;
    if (!readiness) return 'Readiness not available';
    const statuses = statusList(readiness.required_statuses);
    const counts = statusCountsLine(readiness.matching_status_counts);
    const missing = statusList(readiness.missing_required_statuses);
    const channel = notificationChannelLabel[readiness.notification_channel] || readiness.notification_channel || 'Codex App';
    const pushText = readiness.notification_channel === 'app_push'
        ? ` ${readiness.push_subscriptions || 0} push subscription(s).`
        : '';
    const missingText = readiness.missing_required_statuses?.length ? ` Missing: ${missing}.` : '';
    const countsText = counts ? ` (${counts})` : '';
    const deliveryText = readiness.delivery_ready === false ? ' Delivery: client email missing.' : '';
    return `${readiness.matching_source_rows || 0} source row(s) for ${statuses}${countsText}.${missingText} Notify: ${channel}.${pushText}${deliveryText}`;
};

const sourceChecklistText = (title: string, savedSearchName?: string, criteria: string[] = [], steps: string[] = []) => {
    const lines = [
        title,
        savedSearchName ? `Saved search: ${savedSearchName}` : '',
        criteria.length ? 'Criteria:' : '',
        ...criteria.map((item) => `- ${item}`),
        steps.length ? 'Steps:' : '',
        ...steps.map((item, index) => `${index + 1}. ${item}`),
    ];
    return lines.filter(Boolean).join('\n');
};

const notificationStatusChips = (alert: WatchlistAlert) => (
    Object.entries(alert.notification_statuses || {}).map(([channel, status]) => ({
        channel: notificationChannelLabel[channel] || channel,
        status: status.replaceAll('_', ' '),
    }))
);

const hasReviewedGmailDraft = (alert: WatchlistAlert) => (
    alert.draft_status === 'gmail_draft_created' && Boolean(alert.gmail_draft_id)
);

const codexAlertCommand = (alert: WatchlistAlert) => {
    const script = '/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/review_watchlist_alert.py';
    const action = hasReviewedGmailDraft(alert)
        ? `send --alert-id ${alert.id} --confirm '沒有問題'`
        : `draft --alert-id ${alert.id}`;
    return `python3 ${script} ${action}`;
};

const shortId = (value?: string | null) => {
    if (!value) return '';
    return value.length > 12 ? `${value.slice(0, 6)}...${value.slice(-4)}` : value;
};

const draftStateItems = (alert: WatchlistAlert) => {
    const crmLabel = alert.interaction_id
        ? (alert.draft_status === 'sent' ? 'sent' : 'ready')
        : 'missing';
    const gmailLabel = alert.gmail_draft_id
        ? (alert.draft_status === 'sent' || alert.status === 'sent' ? 'sent' : 'created')
        : 'not created';

    return [
        { label: 'CRM draft', value: crmLabel, tone: alert.interaction_id ? 'ready' : 'muted' },
        {
            label: 'Gmail draft',
            value: alert.gmail_draft_id ? `${gmailLabel} ${shortId(alert.gmail_draft_id)}` : gmailLabel,
            tone: alert.gmail_draft_id ? 'ready' : 'muted',
        },
        {
            label: 'Send',
            value: alert.status === 'sent' ? 'sent' : 'review required',
            tone: alert.status === 'sent' ? 'ready' : 'warning',
        },
    ];
};

const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
};

const importResultWroteRows = (result: Pick<PropertyImportResult, 'created' | 'updated'>) => (
    (result.created || 0) > 0 || (result.updated || 0) > 0
);

const filenameLabel = (label: string) => (
    label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'watchlist'
);

const downloadCsvTemplate = async () => {
    try {
        const blob = await crmService.downloadPropertyCsvTemplate();
        downloadBlob(blob, 'skc-watchlist-import-template.csv');
    } catch (error) {
        console.error('Failed to download CSV template', error);
    }
};

const Watchlists = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [watchlists, setWatchlists] = useState<ClientWatchlist[]>([]);
    const [alerts, setAlerts] = useState<WatchlistAlert[]>([]);
    const [selectedContactId, setSelectedContactId] = useState<number | ''>('');
    const [sourceStatus, setSourceStatus] = useState<PropertySourceStatus | null>(null);
    const [sourceSetups, setSourceSetups] = useState<WatchlistSourceSetup[]>([]);
    const [runLogs, setRunLogs] = useState<WatchlistRunLog[]>([]);
    const [codexNotifications, setCodexNotifications] = useState<WatchlistNotification[]>([]);
    const [safetyStatus, setSafetyStatus] = useState<WatchlistSafetyStatus | null>(null);
    const [deliveryGates, setDeliveryGates] = useState<WatchlistDeliveryGateList | null>(null);
    const [readinessReport, setReadinessReport] = useState<WatchlistReadinessReport | null>(null);
    const [dataIntakeChecklist, setDataIntakeChecklist] = useState<WatchlistDataIntakeChecklist | null>(null);
    const [sourceTasks, setSourceTasks] = useState<WatchlistSourceTaskList | null>(null);
    const [launchActionPack, setLaunchActionPack] = useState<WatchlistLaunchActionPack | null>(null);
    const [operatorHandoff, setOperatorHandoff] = useState<WatchlistOperatorHandoffStatus | null>(null);
    const [contactEmailDrafts, setContactEmailDrafts] = useState<Record<number, string>>({});
    const [feedConfig, setFeedConfig] = useState<PropertyFeedConfig | null>(null);
    const [importFile, setImportFile] = useState<File | null>(null);
    const [feedText, setFeedText] = useState('');
    const [resoJsonText, setResoJsonText] = useState('');
    const [gmailFeedQuery, setGmailFeedQuery] = useState(defaultGmailFeedQuery);
    const [gmailFeedMaxResults, setGmailFeedMaxResults] = useState(10);
    const [lastImportPreview, setLastImportPreview] = useState<Record<string, unknown>[]>([]);
    const [lastMatchPreview, setLastMatchPreview] = useState<PropertyImportMatchPreview[]>([]);
    const [lastReadinessPreview, setLastReadinessPreview] = useState<PropertyImportReadinessPreview[]>([]);
    const [lastImportErrors, setLastImportErrors] = useState<string[]>([]);
    const [lastImportWarnings, setLastImportWarnings] = useState<string[]>([]);
    const [lastDropFolderResult, setLastDropFolderResult] = useState<CsvDropFolderImportResult | null>(null);
    const [editingWatchlistId, setEditingWatchlistId] = useState<number | null>(null);
    const [criteriaDraft, setCriteriaDraft] = useState<CriteriaDraft | null>(null);
    const [editingScheduleId, setEditingScheduleId] = useState<number | null>(null);
    const [scheduleDraft, setScheduleDraft] = useState<ScheduleDraft | null>(null);
    const [loading, setLoading] = useState(true);
    const [busyKey, setBusyKey] = useState<string | null>(null);
    const [message, setMessage] = useState('');
    const [searchParams] = useSearchParams();
    const [deepLinkHandled, setDeepLinkHandled] = useState(false);
    const focusedContactId = Number(searchParams.get('contact_id') || '');
    const focusedAlertId = Number(searchParams.get('alert_id') || '');

    const activeContacts = useMemo(
        () => contacts.filter((contact) => (contact.status || 'active') === 'active'),
        [contacts],
    );

    const pendingAlertCounts = useMemo(() => {
        const counts = new Map<number, number>();
        alerts.forEach((alert) => {
            if (alert.status === 'pending_review') {
                counts.set(alert.watchlist_id, (counts.get(alert.watchlist_id) || 0) + 1);
            }
        });
        return counts;
    }, [alerts]);

    const draftNeedsGmailAlerts = useMemo(() => {
        const alertsByWatchlist = new Map<number, WatchlistAlert[]>();
        const seenInteractionIds = new Set<number>();
        alerts.forEach((alert) => {
            if (
                alert.interaction_id
                && !alert.gmail_draft_id
                && alert.status !== 'sent'
                && alert.status !== 'dismissed'
                && !seenInteractionIds.has(alert.interaction_id)
            ) {
                seenInteractionIds.add(alert.interaction_id);
                const watchlistAlerts = alertsByWatchlist.get(alert.watchlist_id) || [];
                alertsByWatchlist.set(alert.watchlist_id, [...watchlistAlerts, alert]);
            }
        });
        return alertsByWatchlist;
    }, [alerts]);

    const queuedCodexNotifications = useMemo(
        () => codexNotifications.filter((item) => item.status === 'queued_for_codex_report'),
        [codexNotifications],
    );

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const [contactsData, watchlistsData, alertsData, sourceStatusData, sourceSetupsData, runLogsData, codexNotificationsData, safetyStatusData, deliveryGatesData, readinessReportData, dataIntakeData, sourceTasksData, launchActionPackData, operatorHandoffData, feedConfigData] = await Promise.all([
                crmService.getContacts(),
                crmService.getWatchlists(),
                crmService.getWatchlistAlerts(),
                crmService.getPropertySourceStatus(),
                crmService.getWatchlistSourceSetups(),
                crmService.getWatchlistRunLogs(8),
                crmService.getWatchlistNotifications({ channel: 'codex_app', limit: 12 }),
                crmService.getWatchlistSafetyStatus(),
                crmService.getWatchlistDeliveryGates(),
                crmService.getWatchlistReadinessReport(),
                crmService.getWatchlistDataIntakeChecklist(),
                crmService.getWatchlistSourceTasks(),
                crmService.getWatchlistLaunchActionPack(),
                crmService.getWatchlistOperatorHandoff(),
                crmService.getPropertyFeedConfig(),
            ]);
            setContacts(contactsData);
            setWatchlists(watchlistsData);
            setAlerts(alertsData);
            setSourceStatus(sourceStatusData);
            setSourceSetups(sourceSetupsData);
            setRunLogs(runLogsData);
            setCodexNotifications(codexNotificationsData);
            setSafetyStatus(safetyStatusData);
            setDeliveryGates(deliveryGatesData);
            setReadinessReport(readinessReportData);
            setDataIntakeChecklist(dataIntakeData);
            setSourceTasks(sourceTasksData);
            setLaunchActionPack(launchActionPackData);
            setOperatorHandoff(operatorHandoffData);
            setContactEmailDrafts(Object.fromEntries(
                contactsData.map((contact) => [contact.id, contact.email || '']),
            ));
            setFeedConfig(feedConfigData);
            setGmailFeedQuery(feedConfigData.gmail_query || defaultGmailFeedQuery);
            setGmailFeedMaxResults(feedConfigData.gmail_max_results || 10);
            setSelectedContactId((current) => current || contactsData[0]?.id || '');
        } catch (error) {
            console.error('Failed to load watchlists', error);
            setMessage('Failed to load watchlists.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadData();
    }, [loadData]);

    useEffect(() => {
        if (deepLinkHandled || !focusedContactId || !contacts.length) return;
        const focusedContact = contacts.find((contact) => contact.id === focusedContactId);
        if (!focusedContact) return;
        setSelectedContactId(focusedContact.id);
        setMessage(`Focused watchlists for ${focusedContact.name}${focusedAlertId ? ` · alert #${focusedAlertId}` : ''}.`);
        setDeepLinkHandled(true);
    }, [contacts, deepLinkHandled, focusedAlertId, focusedContactId]);

    const createDefaultWatchlist = async () => {
        if (!selectedContactId) return;
        setBusyKey('create-default');
        try {
            const created = await crmService.createDefaultWatchlist(Number(selectedContactId));
            setMessage(`Created watchlist: ${created.name}`);
            await loadData();
        } catch (error) {
            console.error('Failed to create watchlist', error);
            setMessage('Could not create the default watchlist.');
        } finally {
            setBusyKey(null);
        }
    };

    const updateContactEmailDraft = (contactId: number, email: string) => {
        setContactEmailDrafts((current) => ({
            ...current,
            [contactId]: email,
        }));
    };

    const saveChecklistContactEmail = async (contactId: number, label: string) => {
        const email = (contactEmailDrafts[contactId] || '').trim();
        if (!email) {
            setMessage(`Enter ${label}'s client email before saving.`);
            return;
        }
        if (!clientEmailPattern.test(email)) {
            setMessage('Enter a valid email address.');
            return;
        }

        setBusyKey(`email-${contactId}`);
        try {
            await crmService.updateContact(contactId, { email });
            setContactEmailDrafts((current) => {
                const next = { ...current };
                delete next[contactId];
                return next;
            });
            setMessage(`Saved client email for ${label}. This only updates the CRM contact; it does not create or send Gmail.`);
            await loadData();
        } catch (error) {
            console.error('Failed to update contact email', error);
            setMessage(`Could not save client email for ${label}.`);
        } finally {
            setBusyKey(null);
        }
    };

    const renderClientEmailPrompt = (contactId: number, label: string, className = '') => (
        <div className={`data-intake-email-row ${className}`.trim()}>
            <input
                aria-label={`Client email for ${label}`}
                autoComplete="email"
                className="input-field"
                inputMode="email"
                type="email"
                value={contactEmailDrafts[contactId] || ''}
                onChange={(event) => updateContactEmailDraft(contactId, event.target.value)}
                placeholder="Client email"
            />
            <button
                className="mini-control"
                onClick={() => saveChecklistContactEmail(contactId, label)}
                disabled={busyKey === `email-${contactId}`}
            >
                Save Email
            </button>
        </div>
    );

    const copyToClipboard = async (text: string, label: string) => {
        if (!text.trim()) {
            setMessage(`No ${label} to copy.`);
            return;
        }

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
            }
            setMessage(`Copied ${label}.`);
        } catch (error) {
            console.error('Failed to copy text', error);
            setMessage(`Could not copy ${label}.`);
        }
    };

    const importProperties = async (dryRun = false) => {
        if (!importFile) return;
        setBusyKey(dryRun ? 'preview-properties' : 'import-properties');
        try {
            const result = await crmService.importPropertiesCsv(importFile, dryRun);
            setLastImportPreview(result.preview_rows || []);
            setLastMatchPreview(result.watchlist_match_preview || []);
            setLastReadinessPreview(result.watchlist_readiness_preview || []);
            setLastImportErrors(result.errors || []);
            setLastImportWarnings(result.warnings || []);
            const prefix = result.dry_run ? 'Preview only. No rows were written.' : 'Import completed.';
            let nextMessage = `${prefix} ${result.message} Skipped: ${result.skipped}.`;
            if (result.errors?.length) {
                nextMessage += ` Issues: ${result.errors.length}.`;
            }
            if (result.warnings?.length) {
                nextMessage += ` Warnings: ${result.warnings.length}.`;
            }
            if (!dryRun && importResultWroteRows(result)) {
                const checkResult = await crmService.checkAllWatchlists();
                nextMessage += ` Checked ${checkResult.checked} active watchlists and created ${checkResult.created_alerts} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so immediate watchlist check was skipped.';
            }
            if (!dryRun) {
                setImportFile(null);
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import properties', error);
            setMessage(dryRun ? 'Could not preview the CSV file.' : 'Could not import the CSV file.');
        } finally {
            setBusyKey(null);
        }
    };

    const importDropFolder = async (dryRun = true) => {
        setBusyKey(dryRun ? 'preview-drop-folder' : 'import-drop-folder');
        try {
            const result = await crmService.importPropertiesCsvFolder(dryRun, 10);
            setLastDropFolderResult(result);
            const importResults = result.imported
                .map((item) => item.result)
                .filter((item): item is NonNullable<typeof item> => Boolean(item));
            setLastImportPreview(importResults.flatMap((item) => item.preview_rows || []));
            setLastMatchPreview(importResults.flatMap((item) => item.watchlist_match_preview || []));
            setLastReadinessPreview(importResults.flatMap((item) => item.watchlist_readiness_preview || []));
            const failedMessages = dropFolderFailureMessages(result);
            setLastImportErrors(failedMessages);
            setLastImportWarnings(importResults.flatMap((item) => item.warnings || []));
            let nextMessage = result.message;
            if (failedMessages.length) {
                nextMessage += ` Issues: ${failedMessages.length}.`;
            }
            const warningCount = importResults.reduce((total, item) => total + (item.warnings?.length || 0), 0);
            if (warningCount) {
                nextMessage += ` Warnings: ${warningCount}.`;
            }
            const wroteRows = importResults.some(importResultWroteRows);
            if (!dryRun && wroteRows) {
                const checkResult = await crmService.checkAllWatchlists();
                nextMessage += ` Checked ${checkResult.checked} active watchlists and created ${checkResult.created_alerts} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so immediate watchlist check was skipped.';
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import drop folder', error);
            setMessage(dryRun ? 'Could not preview the CSV drop folder.' : 'Could not import the CSV drop folder.');
        } finally {
            setBusyKey(null);
        }
    };

    const importFeedText = async (dryRun = true) => {
        if (!feedText.trim()) return;
        setBusyKey(dryRun ? 'preview-feed' : 'import-feed');
        try {
            const result = await crmService.importPropertiesFeedText(feedText, dryRun);
            setLastImportPreview(result.preview_rows || []);
            setLastMatchPreview(result.watchlist_match_preview || []);
            setLastReadinessPreview(result.watchlist_readiness_preview || []);
            setLastImportErrors(result.errors || []);
            setLastImportWarnings(result.warnings || []);
            const prefix = result.dry_run ? 'Feed preview only. No rows were written.' : 'Feed import completed.';
            let nextMessage = `${prefix} ${result.message} Skipped: ${result.skipped}.`;
            if (result.errors?.length) {
                nextMessage += ` Issues: ${result.errors.length}.`;
            }
            if (result.warnings?.length) {
                nextMessage += ` Warnings: ${result.warnings.length}.`;
            }
            if (!dryRun && importResultWroteRows(result)) {
                const checkResult = await crmService.checkAllWatchlists();
                nextMessage += ` Checked ${checkResult.checked} active watchlists and created ${checkResult.created_alerts} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so immediate watchlist check was skipped.';
            }
            if (!dryRun) {
                setFeedText('');
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import feed text', error);
            setMessage(dryRun ? 'Could not preview the pasted listing feed.' : 'Could not import the pasted listing feed.');
        } finally {
            setBusyKey(null);
        }
    };

    const importResoJson = async (dryRun = true) => {
        if (!resoJsonText.trim()) return;
        setBusyKey(dryRun ? 'preview-reso-json' : 'import-reso-json');
        try {
            const result = await crmService.importPropertiesResoJson(resoJsonText, dryRun);
            setLastImportPreview(result.preview_rows || []);
            setLastMatchPreview(result.watchlist_match_preview || []);
            setLastReadinessPreview(result.watchlist_readiness_preview || []);
            setLastImportErrors(result.errors || []);
            setLastImportWarnings(result.warnings || []);
            const prefix = result.dry_run ? 'RESO JSON preview only. No rows were written.' : 'RESO JSON import completed.';
            let nextMessage = `${prefix} ${result.message} Skipped: ${result.skipped}.`;
            if (result.errors?.length) {
                nextMessage += ` Issues: ${result.errors.length}.`;
            }
            if (result.warnings?.length) {
                nextMessage += ` Warnings: ${result.warnings.length}.`;
            }
            if (!dryRun && importResultWroteRows(result)) {
                const checkResult = await crmService.checkAllWatchlists();
                nextMessage += ` Checked ${checkResult.checked} active watchlists and created ${checkResult.created_alerts} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so immediate watchlist check was skipped.';
            }
            if (!dryRun) {
                setResoJsonText('');
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import RESO JSON', error);
            setMessage(dryRun ? 'Could not preview the RESO/MLS JSON.' : 'Could not import the RESO/MLS JSON.');
        } finally {
            setBusyKey(null);
        }
    };

    const requestManualGmailReadConfirmation = () => {
        if (feedConfig?.gmail_feed_enabled) return undefined;
        const typed = window.prompt(
            'Type READ GMAIL to preview/import Gmail saved-search listing emails. This reads matching Gmail messages only; it does not approve alerts or send email.'
        );
        if ((typed || '').trim().toUpperCase() !== 'READ GMAIL') {
            setMessage('Gmail feed was not read. Type READ GMAIL exactly to authorize this manual preview/import.');
            return null;
        }
        return typed || 'READ GMAIL';
    };

    const importGmailFeed = async (dryRun = true) => {
        const gmailReadConfirmation = requestManualGmailReadConfirmation();
        if (gmailReadConfirmation === null) return;
        setBusyKey(dryRun ? 'preview-gmail-feed' : 'import-gmail-feed');
        try {
            const result = await crmService.importPropertiesGmailFeed(gmailFeedQuery, gmailFeedMaxResults, dryRun, gmailReadConfirmation);
            setLastImportPreview(result.preview_rows || []);
            setLastMatchPreview(result.watchlist_match_preview || []);
            setLastReadinessPreview(result.watchlist_readiness_preview || []);
            setLastImportErrors(result.errors || []);
            setLastImportWarnings(result.warnings || []);
            const prefix = result.dry_run ? 'Gmail feed preview only. No rows were written.' : 'Gmail feed import completed.';
            let nextMessage = `${prefix} ${result.message} Skipped: ${result.skipped}.`;
            if (result.errors?.length) {
                nextMessage += ` Issues: ${result.errors.length}.`;
            }
            if (result.warnings?.length) {
                nextMessage += ` Warnings: ${result.warnings.length}.`;
            }
            if (!dryRun && importResultWroteRows(result)) {
                const checkResult = await crmService.checkAllWatchlists();
                nextMessage += ` Checked ${checkResult.checked} active watchlists and created ${checkResult.created_alerts} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so immediate watchlist check was skipped.';
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import Gmail feed', error);
            setMessage('Could not import Gmail listing feed. Check Gmail connection and query.');
        } finally {
            setBusyKey(null);
        }
    };

    const saveGmailFeedConfig = async (enabled = feedConfig?.gmail_feed_enabled || false) => {
        let gmailFeedConfirmation: string | undefined;
        if (enabled && !feedConfig?.gmail_feed_enabled) {
            const typed = window.prompt(
                'Type READ GMAIL to enable scheduled Gmail saved-search import. Future automation runs may read matching listing emails from Gmail, but will still not send email or approve alerts automatically.'
            );
            if ((typed || '').trim().toUpperCase() !== 'READ GMAIL') {
                setMessage('Scheduled Gmail import was not enabled. Type READ GMAIL exactly to authorize this data-source setting.');
                return;
            }
            gmailFeedConfirmation = typed || undefined;
        }

        setBusyKey('feed-config');
        try {
            const updated = await crmService.updatePropertyFeedConfig({
                gmail_feed_enabled: enabled,
                gmail_feed_confirmation: gmailFeedConfirmation,
                gmail_query: gmailFeedQuery,
                gmail_max_results: gmailFeedMaxResults,
            });
            setFeedConfig(updated);
            setGmailFeedQuery(updated.gmail_query);
            setGmailFeedMaxResults(updated.gmail_max_results);
            setMessage(updated.gmail_feed_enabled
                ? 'Scheduled Gmail saved-search feed is enabled. Future automation runs may read matching listing emails.'
                : 'Scheduled Gmail saved-search feed is disabled. Automation will not read Gmail.');
        } catch (error) {
            console.error('Failed to update feed config', error);
            setMessage('Could not save Gmail feed settings.');
        } finally {
            setBusyKey(null);
        }
    };

    const markCodexNotificationsReported = async () => {
        const queuedIds = codexNotifications
            .filter((item) => item.status === 'queued_for_codex_report')
            .map((item) => item.id);
        if (!queuedIds.length) return;
        setBusyKey('mark-codex-notifications');
        try {
            const result = await crmService.markWatchlistNotificationsReported(queuedIds);
            setMessage(`Marked ${result.updated} Codex notification(s) as reported. Alerts and drafts were not approved or sent.`);
            await loadData();
        } catch (error) {
            console.error('Failed to mark Codex notifications reported', error);
            setMessage('Could not mark Codex notifications as reported.');
        } finally {
            setBusyKey(null);
        }
    };

    const checkAllWatchlists = async () => {
        setBusyKey('check-all');
        try {
            const result = await crmService.checkAllWatchlists();
            setMessage(`Checked ${result.checked} active watchlists. Created ${result.created_alerts} alert(s), matched ${result.matched_properties} property row(s).`);
            await loadData();
        } catch (error) {
            console.error('Failed to check all watchlists', error);
            setMessage('Could not check all watchlists.');
        } finally {
            setBusyKey(null);
        }
    };

    const checkWatchlist = async (watchlist: ClientWatchlist) => {
        setBusyKey(`check-${watchlist.id}`);
        try {
            const result = await crmService.checkWatchlist(watchlist.id);
            setMessage(result.message);
            await loadData();
        } catch (error) {
            console.error('Failed to check watchlist', error);
            setMessage('Watchlist check failed.');
        } finally {
            setBusyKey(null);
        }
    };

    const createWatchlistDigestDraft = async (watchlist: ClientWatchlist) => {
        setBusyKey(`digest-${watchlist.id}`);
        try {
            const result = await crmService.createWatchlistDigestDraft(watchlist.id);
            setMessage(result.message);
            await loadData();
        } catch (error) {
            console.error('Failed to create watchlist digest draft', error);
            setMessage('Could not create digest draft for this watchlist.');
        } finally {
            setBusyKey(null);
        }
    };

    const createWatchlistDigestGmailDraft = async (watchlist: ClientWatchlist) => {
        setBusyKey(`digest-gmail-${watchlist.id}`);
        try {
            const result = await crmService.createWatchlistDigestGmailDraft(watchlist.id);
            setMessage(`${result.message} To: ${result.to_email || 'missing recipient'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to create watchlist digest Gmail draft', error);
            setMessage('Could not create digest Gmail draft. Confirm pending alerts exist, contact email exists, and Gmail is connected.');
        } finally {
            setBusyKey(null);
        }
    };

    const resumeWatchlistGmailDrafts = async (watchlist: ClientWatchlist) => {
        const candidates = draftNeedsGmailAlerts.get(watchlist.id) || [];
        if (!candidates.length) {
            setMessage('No existing CRM drafts need Gmail drafts for this watchlist.');
            return;
        }
        setBusyKey(`resume-gmail-${watchlist.id}`);
        try {
            const results = [];
            for (const alert of candidates) {
                const result = await crmService.createWatchlistAlertGmailDraft(alert.id);
                results.push(result);
            }
            const recipients = Array.from(new Set(results.map((result) => result.to_email).filter(Boolean)));
            setMessage(`Created or reused ${results.length} Gmail draft(s) from existing CRM draft(s). To: ${recipients.join(', ') || 'missing recipient'}. No email was sent.`);
            await loadData();
        } catch (error) {
            console.error('Failed to resume Gmail drafts from existing CRM drafts', error);
            setMessage('Could not create Gmail draft from the existing CRM draft. Confirm the contact email is saved and Gmail is connected.');
        } finally {
            setBusyKey(null);
        }
    };

    const toggleWatchlist = async (watchlist: ClientWatchlist) => {
        setBusyKey(`toggle-${watchlist.id}`);
        try {
            const nextStatus = watchlist.status === 'active' ? 'paused' : 'active';
            await crmService.updateWatchlist(watchlist.id, { status: nextStatus });
            await loadData();
        } catch (error) {
            console.error('Failed to update watchlist', error);
            setMessage('Could not update watchlist status.');
        } finally {
            setBusyKey(null);
        }
    };

    const setClientSchedule = async (watchlist: ClientWatchlist, times: string[]) => {
        setBusyKey(clientScheduleBusyKey(watchlist));
        try {
            const schedule = {
                times,
                timezone: watchlist.schedule.timezone || 'America/Toronto',
            };
            const updated = await crmService.updateContactWatchlistSchedule(watchlist.contact_id, {
                schedule,
            });
            setMessage(`${watchlist.contact_name || watchlist.name} client schedule updated to ${scheduleSummary(schedule)} for ${updated.length} watchlist${updated.length === 1 ? '' : 's'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to update client schedule', error);
            setMessage('Could not update this client schedule.');
        } finally {
            setBusyKey(null);
        }
    };

    const startEditSchedule = (watchlist: ClientWatchlist) => {
        setEditingScheduleId(watchlist.id);
        setScheduleDraft(scheduleDraftFromWatchlist(watchlist));
    };

    const updateScheduleDraft = (field: keyof ScheduleDraft, value: string) => {
        setScheduleDraft((current) => current ? { ...current, [field]: value } : current);
    };

    const cancelEditSchedule = () => {
        setEditingScheduleId(null);
        setScheduleDraft(null);
    };

    const saveScheduleDraft = async (watchlist: ClientWatchlist) => {
        if (!scheduleDraft) return;
        const times = parseScheduleTimes(scheduleDraft.times);
        if (!times.length) {
            setMessage('Add at least one schedule time, for example 09:00 or 09:00, 15:00, 18:00.');
            return;
        }

        setBusyKey(clientScheduleBusyKey(watchlist));
        try {
            const schedule = {
                times,
                timezone: scheduleDraft.timezone.trim() || 'America/Toronto',
            };
            const updated = await crmService.updateContactWatchlistSchedule(watchlist.contact_id, {
                schedule,
            });
            setMessage(`${watchlist.contact_name || watchlist.name} client schedule updated to ${scheduleSummary(schedule)} for ${updated.length} watchlist${updated.length === 1 ? '' : 's'}.`);
            cancelEditSchedule();
            await loadData();
        } catch (error) {
            console.error('Failed to update custom client schedule', error);
            setMessage('Could not update custom client schedule. Use HH:MM times like 09:00, 15:00, 18:00.');
        } finally {
            setBusyKey(null);
        }
    };

    const setClientNotificationChannel = async (watchlist: ClientWatchlist, channel: string) => {
        setBusyKey(clientNotificationBusyKey(watchlist));
        try {
            const updated = await crmService.updateContactWatchlistNotificationChannel(watchlist.contact_id, {
                notification_channel: channel,
            });
            setMessage(`${watchlist.contact_name || watchlist.name} client notifications set to ${notificationChannelLabel[channel] || channel} for ${updated.length} watchlist${updated.length === 1 ? '' : 's'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to update client notification channel', error);
            setMessage('Could not update this client notification channel.');
        } finally {
            setBusyKey(null);
        }
    };

    const loadWatchlistSourceQuery = (watchlist: ClientWatchlist) => {
        const query = watchlist.source_query?.trim() || defaultGmailFeedQuery;
        setGmailFeedQuery(query);
        setMessage(`Loaded source query for ${watchlist.contact_name || watchlist.name}. Preview Gmail or save the feed query when ready.`);
    };

    const importGmailForWatchlist = async (watchlist: ClientWatchlist, dryRun = true) => {
        const query = watchlist.source_query?.trim() || defaultGmailFeedQuery;
        const gmailReadConfirmation = requestManualGmailReadConfirmation();
        if (gmailReadConfirmation === null) return;
        setBusyKey(`${dryRun ? 'preview' : 'import'}-watchlist-gmail-${watchlist.id}`);
        try {
            const result = await crmService.importPropertiesGmailFeed(query, gmailFeedMaxResults, dryRun, gmailReadConfirmation);
            setLastImportPreview(result.preview_rows || []);
            setLastMatchPreview(result.watchlist_match_preview || []);
            setLastReadinessPreview(result.watchlist_readiness_preview || []);
            setLastImportErrors(result.errors || []);
            setLastImportWarnings(result.warnings || []);
            const prefix = result.dry_run
                ? `${watchlist.contact_name || watchlist.name} Gmail preview only. No rows were written.`
                : `${watchlist.contact_name || watchlist.name} Gmail import completed.`;
            let nextMessage = `${prefix} ${result.message} Skipped: ${result.skipped}.`;
            if (result.errors?.length) {
                nextMessage += ` Issues: ${result.errors.length}.`;
            }
            if (result.warnings?.length) {
                nextMessage += ` Warnings: ${result.warnings.length}.`;
            }
            if (!dryRun && importResultWroteRows(result)) {
                const checkResult = await crmService.checkWatchlist(watchlist.id);
                nextMessage += ` Checked this watchlist and created ${checkResult.created_count} alert(s).`;
            } else if (!dryRun) {
                nextMessage += ' No source rows changed, so this watchlist check was skipped.';
            }
            setMessage(nextMessage);
            await loadData();
        } catch (error) {
            console.error('Failed to import Gmail for watchlist', error);
            setMessage(`Could not import Gmail feed for ${watchlist.contact_name || watchlist.name}. Check Gmail connection and source query.`);
        } finally {
            setBusyKey(null);
        }
    };

    const downloadWatchlistTemplate = async (watchlistId: number, label: string) => {
        setBusyKey(`template-${watchlistId}`);
        try {
            const blob = await crmService.downloadWatchlistSourceTemplate(watchlistId);
            downloadBlob(blob, `skc-watchlist-source-template-${filenameLabel(label)}.csv`);
            setMessage(`Downloaded source template for ${label}.`);
        } catch (error) {
            console.error('Failed to download watchlist template', error);
            setMessage('Could not download the watchlist source template.');
        } finally {
            setBusyKey(null);
        }
    };

    const downloadSourceKit = async () => {
        setBusyKey('source-kit');
        try {
            const blob = await crmService.downloadWatchlistSourceKit();
            downloadBlob(blob, 'skc-watchlist-source-kit.zip');
            setMessage('Downloaded the full watchlist source kit with templates and REALM/TRREB import instructions.');
        } catch (error) {
            console.error('Failed to download watchlist source kit', error);
            setMessage('Could not download the watchlist source kit.');
        } finally {
            setBusyKey(null);
        }
    };

    const downloadClientEmailTasks = async () => {
        setBusyKey('client-email-tasks');
        try {
            const blob = await crmService.downloadWatchlistClientEmailTasks();
            downloadBlob(blob, 'client-email-tasks.csv');
            setMessage('Downloaded client-email-tasks.csv. Fill client_email for blocked contacts and place it in the CSV drop folder.');
        } catch (error) {
            console.error('Failed to download client email tasks', error);
            setMessage('Could not download client-email-tasks.csv.');
        } finally {
            setBusyKey(null);
        }
    };

    const startEditCriteria = (watchlist: ClientWatchlist) => {
        setEditingWatchlistId(watchlist.id);
        setCriteriaDraft(draftFromWatchlist(watchlist));
    };

    const updateCriteriaDraft = (field: keyof CriteriaDraft, value: string) => {
        setCriteriaDraft((current) => current ? { ...current, [field]: value } : current);
    };

    const saveCriteria = async (watchlist: ClientWatchlist) => {
        if (!criteriaDraft) return;
        setBusyKey(`criteria-${watchlist.id}`);
        const criteria: Record<string, unknown> = {
            areas: splitCsv(criteriaDraft.areas),
            types: splitCsv(criteriaDraft.types),
            must_haves: splitCsv(criteriaDraft.must_haves),
            deal_breakers: splitCsv(criteriaDraft.deal_breakers),
            min_price: numberOrUndefined(criteriaDraft.min_price),
            max_price: numberOrUndefined(criteriaDraft.max_price),
            bedrooms_min: numberOrUndefined(criteriaDraft.bedrooms_min),
            bathrooms_min: numberOrUndefined(criteriaDraft.bathrooms_min),
            parking_min: numberOrUndefined(criteriaDraft.parking_min),
            property_address: criteriaDraft.property_address.trim() || undefined,
            available_after: criteriaDraft.available_after.trim() || undefined,
        };
        Object.keys(criteria).forEach((key) => {
            const value = criteria[key];
            if (value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)) {
                delete criteria[key];
            }
        });

        try {
            const updated = await crmService.updateWatchlist(watchlist.id, {
                name: criteriaDraft.name.trim() || watchlist.name,
                watch_type: criteriaDraft.watch_type,
                criteria,
                source_query: criteriaDraft.source_query.trim() || null,
            });
            setMessage(`Updated criteria for ${updated.name}.`);
            setEditingWatchlistId(null);
            setCriteriaDraft(null);
            await loadData();
        } catch (error) {
            console.error('Failed to update criteria', error);
            setMessage('Could not update watchlist criteria.');
        } finally {
            setBusyKey(null);
        }
    };

    const setReviewMode = async (watchlist: ClientWatchlist, reviewMode: string) => {
        if (watchlist.review_mode === reviewMode) return;
        setBusyKey(clientReviewModeBusyKey(watchlist));
        try {
            const contactName = watchlist.contact_name || watchlist.name;
            const updated = await crmService.updateContactWatchlistReviewMode(watchlist.contact_id, { review_mode: reviewMode });
            const updatedCount = updated.filter((item) => item.review_mode === reviewMode).length;
            const modeLabel = reviewModeLabel[reviewMode] || 'Manual Review';
            const action = watchlist.review_mode === 'auto_send_approved' && reviewMode !== 'auto_send_approved'
                ? 'Auto Send disarmed'
                : `approval mode set to ${modeLabel}`;
            setMessage(`${contactName} ${action} for ${updatedCount} client watchlist${updatedCount === 1 ? '' : 's'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to update review mode', error);
            setMessage('Could not update this client approval mode.');
        } finally {
            setBusyKey(null);
        }
    };

    const armAutoSend = async (watchlist: ClientWatchlist) => {
        const safetyLine = safetyStatus?.can_auto_send
            ? 'Current server safety status allows automatic Gmail sending for armed watchlists.'
            : 'Current server safety status is draft-only, so armed watchlists will still create Gmail drafts for review.';
        const confirmation = window.prompt(
            `Type AUTO SEND to arm Client Auto Send for ${watchlist.contact_name || watchlist.name}. This applies to all watchlists for this client. ${safetyLine}`
        );
        if (confirmation === null) return;
        if (confirmation.trim().toLowerCase() !== 'auto send') {
            setMessage('Auto Send was not armed. Type AUTO SEND exactly to confirm this client-level setting.');
            return;
        }
        const confirmed = window.confirm(
            `Arm Client Auto Send for ${watchlist.contact_name || watchlist.name}? This applies to all watchlists for this client. ${safetyLine}`
        );
        if (!confirmed) return;

        setBusyKey(`auto-send-${watchlist.id}`);
        try {
            const updated = await crmService.updateContactWatchlistReviewMode(watchlist.contact_id, {
                review_mode: 'auto_send_approved',
                auto_send_confirmation: confirmation,
            });
            const armedCount = updated.filter((item) => item.review_mode === 'auto_send_approved').length;
            setMessage(`${watchlist.contact_name || watchlist.name} is set to Client Auto Send Armed for ${armedCount} watchlist${armedCount === 1 ? '' : 's'}. ${safetyStatus?.message || 'Check the safety banner for the current send mode.'}`);
            await loadData();
        } catch (error) {
            console.error('Failed to arm auto send', error);
            setMessage('Could not arm auto send for this client.');
        } finally {
            setBusyKey(null);
        }
    };

    const createDraft = async (alert: WatchlistAlert) => {
        setBusyKey(`draft-${alert.id}`);
        try {
            const result = await crmService.createWatchlistAlertDraft(alert.id);
            setMessage(result.message);
            await loadData();
        } catch (error) {
            console.error('Failed to create draft', error);
            setMessage('Could not create Gmail review draft.');
        } finally {
            setBusyKey(null);
        }
    };

    const createGmailDraft = async (alert: WatchlistAlert) => {
        setBusyKey(`gmail-draft-${alert.id}`);
        try {
            const result = await crmService.createWatchlistAlertGmailDraft(alert.id);
            setMessage(`${result.message} To: ${result.to_email || 'missing recipient'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to create Gmail draft', error);
            setMessage('Could not create Gmail draft. Check that the contact has an email and Gmail is connected.');
        } finally {
            setBusyKey(null);
        }
    };

    const sendWatchlistAlert = async (alert: WatchlistAlert) => {
        if (!hasReviewedGmailDraft(alert)) {
            setMessage('Create and review a Gmail draft first. Send will not create a draft automatically.');
            return;
        }
        const reviewConfirmation = window.prompt(
            `Type 沒有問題 or OK to send the existing Gmail draft to ${alert.contact_name || 'the contact'} now.`
        );
        const normalizedConfirmation = reviewConfirmation?.trim();
        if (!normalizedConfirmation || !['沒有問題', '没问题', 'ok'].includes(normalizedConfirmation.toLowerCase())) {
            setMessage('Send cancelled. Type 沒有問題 or OK only after reviewing the Gmail draft.');
            return;
        }

        setBusyKey(`send-alert-${alert.id}`);
        try {
            const result = await crmService.sendWatchlistAlertGmail(alert.id, {
                confirm_send: true,
                review_confirmation: normalizedConfirmation,
            });
            setMessage(`${result.message} To: ${result.to_email || 'missing recipient'}.`);
            await loadData();
        } catch (error) {
            console.error('Failed to send Gmail draft', error);
            setMessage('Could not send Gmail draft. Confirm Gmail is connected, recipient email exists, and draft is ready.');
        } finally {
            setBusyKey(null);
        }
    };

    const dismissAlert = async (alert: WatchlistAlert) => {
        setBusyKey(`dismiss-${alert.id}`);
        try {
            await crmService.updateWatchlistAlert(alert.id, 'dismissed');
            await loadData();
        } catch (error) {
            console.error('Failed to dismiss alert', error);
            setMessage('Could not dismiss alert.');
        } finally {
            setBusyKey(null);
        }
    };

    if (loading) {
        return (
            <div className="watchlists-page animate-fade-in">
                <div className="p-8 text-center text-gray-400">
                    <div className="spinner mx-auto mb-3"></div>
                    Loading watchlists...
                </div>
            </div>
        );
    }

    return (
        <div className="watchlists-page animate-fade-in">
            <div className="page-header watchlists-header">
                <div>
                    <h1>Watchlists</h1>
                    <p className="subtitle">Listing alerts, sold comps, rental matches, and review drafts.</p>
                </div>
                <div className="watchlist-create glass-panel">
                    <button
                        className="btn btn-accent watchlist-action"
                        onClick={checkAllWatchlists}
                        disabled={busyKey === 'check-all'}
                    >
                        <SearchCheck size={16} />
                        Check All
                    </button>
                    <select
                        className="input-field"
                        value={selectedContactId}
                        onChange={(event) => setSelectedContactId(Number(event.target.value))}
                    >
                        {activeContacts.map((contact) => (
                            <option key={contact.id} value={contact.id}>{contact.name}</option>
                        ))}
                    </select>
                    <button
                        className="btn btn-primary watchlist-action"
                        onClick={createDefaultWatchlist}
                        disabled={!selectedContactId || busyKey === 'create-default'}
                    >
                        <BellRing size={16} />
                        Default Watch
                    </button>
                </div>
            </div>

            {message && (
                <div className="watchlist-message">
                    <ShieldCheck size={16} />
                    <span>{message}</span>
                </div>
            )}

            {safetyStatus ? (
                <section className={`watchlist-safety ${safetyStatus.can_auto_send ? 'safety-send-enabled' : 'safety-draft-only'}`}>
                    <div className="safety-icon">
                        {safetyStatus.can_auto_send ? <CheckCircle2 size={18} /> : <ShieldCheck size={18} />}
                    </div>
                    <div className="safety-copy">
                        <strong>{safetyStatus.can_auto_send ? 'Auto-send enabled' : 'Draft-only safety mode'}</strong>
                        <span>{safetyStatus.message}</span>
                    </div>
                    <div className="safety-badges">
                        <span>{safetyStatus.auto_send_armed_count} armed</span>
                        <span>{safetyStatus.gmail_connected ? `Gmail: ${safetyStatus.gmail_account_email || 'connected'}` : 'Gmail not connected'}</span>
                        <span>{safetyStatus.auto_send_server_enabled ? `${safetyStatus.required_server_flag}=true` : `${safetyStatus.required_server_flag}=off`}</span>
                    </div>
                    {safetyStatus.auto_send_armed_watchlists.length ? (
                        <div className="safety-armed-list">
                            {safetyStatus.auto_send_armed_watchlists.map((item) => (
                                <span
                                    className={item.can_auto_send ? 'armed-ready' : 'armed-gated'}
                                    key={item.watchlist_id}
                                >
                                    {item.contact_name || item.watchlist_name}: {item.action_required || 'ready to auto-send when a new match is created'}
                                </span>
                            ))}
                        </div>
                    ) : null}
                </section>
            ) : null}

            {operatorHandoff ? (
                <section className={`operator-handoff ${operatorHandoff.helper_files_ready ? 'operator-handoff-ready' : 'operator-handoff-blocked'}`}>
                    <div className="operator-handoff-main">
                        <div className="operator-handoff-icon">
                            {operatorHandoff.helper_files_ready ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
                        </div>
                        <div className="operator-handoff-copy">
                            <div className="operator-handoff-title">
                                <h2>Operator Handoff</h2>
                                <span>{operatorHandoff.automation_status}</span>
                            </div>
                            <p>{operatorHandoff.message}</p>
                            <div className="operator-handoff-meta">
                                <span><Clock3 size={14} /> {operatorHandoff.schedule_summary}</span>
                                <span><Activity size={14} /> {operatorHandoff.automation_id}</span>
                                <span><Database size={14} /> {operatorHandoff.pending_csv_count} CSV pending</span>
                                <span>{operatorHandoff.non_importable_file_count} helper/template</span>
                            </div>
                            <code>{operatorHandoff.drop_folder}</code>
                            <div className="operator-handoff-actions">
                                <button
                                    className="mini-control"
                                    onClick={() => copyToClipboard(operatorHandoff.drop_folder, 'watchlist drop folder path')}
                                >
                                    <Copy size={13} />
                                    Copy Folder
                                </button>
                                <button
                                    className="mini-control"
                                    onClick={() => copyToClipboard(operatorHandoff.next_step, 'operator handoff next step')}
                                >
                                    <Copy size={13} />
                                    Copy Next Step
                                </button>
                            </div>
                        </div>
                    </div>
                    <div className="operator-file-list">
                        {operatorHandoff.files.map((file) => (
                            <article className={`operator-file ${file.exists ? 'operator-file-ready' : 'operator-file-missing'}`} key={file.key}>
                                <div className="operator-file-top">
                                    <strong>{file.label}</strong>
                                    <span>{file.exists ? 'ready' : 'missing'}</span>
                                </div>
                                <code>{file.filename}</code>
                                <p>{file.description}</p>
                                <div className="operator-file-meta">
                                    <span>{fileSizeLabel(file.size_bytes)}</span>
                                    <span>{file.updated_at ? formatRunTime(file.updated_at) : 'Not generated'}</span>
                                    <span>{file.importable_csv ? 'importable source' : 'not auto-imported'}</span>
                                </div>
                                <button
                                    className="mini-control"
                                    onClick={() => copyToClipboard(file.path, `${file.label} path`)}
                                >
                                    <Copy size={13} />
                                    Copy Path
                                </button>
                            </article>
                        ))}
                    </div>
                    {operatorHandoff.source_kit_files.length ? (
                        <div className="source-kit-manifest">
                            <div className="source-kit-manifest-header">
                                <div>
                                    <strong>Source Kit Manifest</strong>
                                    <span>Included when you download Source Kit</span>
                                </div>
                                <button
                                    className="mini-control"
                                    onClick={downloadSourceKit}
                                    disabled={busyKey === 'source-kit'}
                                >
                                    Source Kit
                                </button>
                            </div>
                            <div className="source-kit-file-list">
                                {operatorHandoff.source_kit_files.map((file) => (
                                    <article className={`source-kit-file ${file.included ? 'source-kit-file-ready' : 'source-kit-file-missing'}`} key={file.key}>
                                        <div className="source-kit-file-top">
                                            <strong>{file.label}</strong>
                                            <span>{file.importable ? 'importable when completed' : 'reference'}</span>
                                        </div>
                                        <code>{file.filename}</code>
                                        <p>{file.description}</p>
                                    </article>
                                ))}
                            </div>
                        </div>
                    ) : null}
                    <div className="operator-handoff-next">{operatorHandoff.next_step}</div>
                </section>
            ) : null}

            {launchActionPack ? (
                <section className={`launch-action-pack launch-action-${launchActionPack.overall_status}`}>
                    <div className="launch-action-header">
                        <div>
                            <h2>Launch Action Pack</h2>
                            <p>{launchActionPack.summary}</p>
                        </div>
                        <div className="launch-action-buttons">
                            <span>{formatRunTime(launchActionPack.generated_at)}</span>
                            <button
                                className="mini-control"
                                onClick={() => copyToClipboard(launchActionPack.copy_text, 'launch action pack')}
                            >
                                Copy Full Pack
                            </button>
                            <button
                                className="mini-control"
                                onClick={downloadSourceKit}
                                disabled={busyKey === 'source-kit'}
                            >
                                Source Kit
                            </button>
                            <button
                                className="mini-control"
                                onClick={downloadClientEmailTasks}
                                disabled={busyKey === 'client-email-tasks'}
                            >
                                Email CSV
                            </button>
                        </div>
                    </div>
                    <div className="launch-method">
                        <ShieldCheck size={15} />
                        <span>{launchActionPack.recommended_method}</span>
                    </div>
                    <div className="launch-action-metrics">
                        <span>{launchActionPack.ready_count}/{launchActionPack.active_count} ready</span>
                        <span>{launchActionPack.source_rows} source rows</span>
                        <span>{launchActionPack.pending_csv_count} pending CSV</span>
                        <span>{launchActionPack.missing_email_count} email needed</span>
                        <span title={launchActionPack.reso_connector.message}>
                            RESO connector {launchActionPack.reso_connector.status.replaceAll('_', ' ')}
                        </span>
                        <span>{launchActionPack.gmail_feed_enabled ? 'Gmail feed on' : 'Gmail feed off'}</span>
                        <span>{launchActionPack.auto_send_server_enabled ? 'Auto-send server on' : 'Auto-send off'}</span>
                    </div>
                    {launchActionPack.next_actions.length ? (
                        <div className="launch-next-actions">
                            {launchActionPack.next_actions.slice(0, 5).map((action) => (
                                <span key={action}>{action}</span>
                            ))}
                        </div>
                    ) : null}
                    {launchActionPack.preflight_checks.length ? (
                        <div className="launch-preflight-grid">
                            {launchActionPack.preflight_checks.map((check) => (
                                <article
                                    className={`launch-preflight-check preflight-${check.status.replaceAll('_', '-')}`}
                                    key={check.key}
                                >
                                    <div>
                                        <strong>{check.label}</strong>
                                        <span>{check.status.replaceAll('_', ' ')}</span>
                                    </div>
                                    <p>{check.detail}</p>
                                    {check.next_step ? <small>{check.next_step}</small> : null}
                                </article>
                            ))}
                        </div>
                    ) : null}
                    <div className="launch-action-grid">
                        {launchActionPack.items.slice(0, 4).map((item) => (
                            <article className={`launch-action-card launch-priority-${item.priority}`} key={item.watchlist_id}>
                                <div className="launch-action-card-top">
                                    <div>
                                        <strong>{item.contact_name || item.watchlist_name}</strong>
                                        <span>{watchTypeLabel[item.watch_type] || item.watch_type}</span>
                                    </div>
                                    <b>{item.priority.replaceAll('_', ' ')}</b>
                                </div>
                                <div className="launch-action-statuses">
                                    <span className={item.source_ready ? 'intake-ok' : 'intake-blocked'}>
                                        Source {item.source_ready ? 'ready' : 'needed'}
                                    </span>
                                    <span className={item.delivery_ready ? 'intake-ok' : 'intake-blocked'}>
                                        Delivery {item.delivery_ready ? 'ready' : 'blocked'}
                                    </span>
                                </div>
                                <div className="launch-saved-search">
                                    <span>Saved search</span>
                                    <strong>{item.saved_search_name}</strong>
                                </div>
                                <div className="launch-task-goal">{item.source_goal}</div>
                                {item.missing_required_statuses.length ? (
                                    <div className="coverage-missing">Missing: {statusList(item.missing_required_statuses)}</div>
                                ) : null}
                                {item.client_email_needed ? (
                                    renderClientEmailPrompt(item.contact_id, item.contact_name || item.watchlist_name)
                                ) : null}
                                <code>{item.gmail_query}</code>
                                <div className="launch-action-steps">
                                    {item.actions.slice(0, 4).map((action) => (
                                        <span key={`${item.watchlist_id}-${action}`}>{action}</span>
                                    ))}
                                </div>
                                <div className="setup-actions">
                                    <button
                                        className="mini-control"
                                        onClick={() => {
                                            setGmailFeedQuery(item.gmail_query);
                                            setMessage(`Loaded launch query for ${item.contact_name || item.watchlist_name}.`);
                                        }}
                                    >
                                        Use Query
                                    </button>
                                    <button
                                        className="mini-control"
                                        onClick={() => copyToClipboard(item.copy_text, `${item.contact_name || item.watchlist_name} launch task`)}
                                    >
                                        Copy Task
                                    </button>
                                    {item.drop_folder ? (
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(item.drop_folder || '', 'CSV drop folder path')}
                                        >
                                            Copy Path
                                        </button>
                                    ) : null}
                                </div>
                            </article>
                        ))}
                    </div>
                </section>
            ) : null}

            {deliveryGates ? (
                <section className={`delivery-gates delivery-gates-${deliveryGates.overall_status}`}>
                    <div className="delivery-gates-header">
                        <div>
                            <h2>Delivery Gates</h2>
                            <p>{deliveryGates.message}</p>
                        </div>
                        <div className="delivery-gates-badges">
                            <span>{deliveryGates.ready_count}/{deliveryGates.active_count} ready</span>
                            <span>{deliveryGates.warning_count} warning</span>
                            <span>{deliveryGates.blocked_count} blocked</span>
                        </div>
                    </div>
                    <div className="delivery-gates-grid">
                        {deliveryGates.items.map((gate) => (
                            <article className={`delivery-gate-card delivery-state-${gate.delivery_state}`} key={gate.watchlist_id}>
                                <div className="delivery-gate-top">
                                    <div>
                                        <strong>{gate.contact_name || gate.watchlist_name}</strong>
                                        <span>{reviewModeLabel[gate.review_mode] || gate.review_mode}</span>
                                    </div>
                                    <b>{deliveryStateLabel[gate.delivery_state] || gate.delivery_state.replaceAll('_', ' ')}</b>
                                </div>
                                <div className="delivery-gate-chips">
                                    <span className={gate.contact_email_present ? 'gate-ok' : 'gate-blocked'}>
                                        {gate.contact_email_present ? 'Email ready' : 'Email needed'}
                                    </span>
                                    <span className={gate.gmail_connected ? 'gate-ok' : 'gate-blocked'}>
                                        {gate.gmail_connected ? 'Gmail connected' : 'Gmail needed'}
                                    </span>
                                    <span className={gate.can_auto_send ? 'gate-ok' : 'gate-muted'}>
                                        {gate.can_auto_send ? 'Can auto-send' : 'Draft/review gated'}
                                    </span>
                                    <span className={gate.notification_ready ? 'gate-ok' : 'gate-blocked'}>
                                        Notify: {notificationChannelLabel[gate.notification_channel] || gate.notification_channel}
                                    </span>
                                </div>
                                {gate.action_required ? (
                                    <div className="delivery-gate-action">{gate.action_required}</div>
                                ) : null}
                                {!gate.contact_email_present ? (
                                    renderClientEmailPrompt(gate.contact_id, gate.contact_name || gate.watchlist_name, 'delivery-gate-email-row')
                                ) : null}
                                <div className="delivery-gate-note">{gate.safety_note}</div>
                            </article>
                        ))}
                    </div>
                </section>
            ) : null}

            {readinessReport ? (
                <section className={`readiness-report readiness-${readinessReport.overall_status}`}>
                    <div className="readiness-report-header">
                        <div>
                            <h2>Launch Readiness</h2>
                            <p>{readinessReport.message}</p>
                        </div>
                        <div className="readiness-report-badges">
                            <span>{readinessReport.overall_status}</span>
                            <span>{readinessReport.ready_count}/{readinessReport.active_count} ready</span>
                            <span>{readinessReport.property_rows} source rows</span>
                            <span>{readinessReport.pending_csv_count} pending CSV</span>
                        </div>
                    </div>
                    {readinessReport.next_actions.length ? (
                        <div className="readiness-next-actions">
                            {readinessReport.next_actions.slice(0, 4).map((action) => (
                                <span key={action}>{action}</span>
                            ))}
                        </div>
                    ) : null}
                    <div className="readiness-report-grid">
                        {readinessReport.items.map((item) => (
                            <div className={`readiness-report-item ${readinessClass(item.severity)}`} key={item.watchlist_id}>
                                <div className="readiness-item-topline">
                                    <strong>{item.contact_name || item.watchlist_name}</strong>
                                    <span>{readinessLabel(item.severity)}</span>
                                </div>
                                <div className="readiness-item-meta">
                                    {item.matching_source_rows} source row(s) · {statusList(item.required_statuses)}
                                </div>
                                {Object.keys(item.matching_status_counts || {}).length ? (
                                    <div className="readiness-item-steps">{statusCountsLine(item.matching_status_counts)}</div>
                                ) : null}
                                {item.missing_required_statuses?.length ? (
                                    <div className="coverage-missing">
                                        Missing: {statusList(item.missing_required_statuses)}
                                    </div>
                                ) : null}
                                {item.delivery_issues?.length ? (
                                    <div className="coverage-missing">
                                        Delivery: {item.delivery_issues.join(' · ')}
                                    </div>
                                ) : null}
                                {item.next_steps.length ? (
                                    <div className="readiness-item-steps">{item.next_steps.slice(0, 2).join(' · ')}</div>
                                ) : null}
                            </div>
                        ))}
                    </div>
                </section>
            ) : null}

            {dataIntakeChecklist ? (
                <section className={`data-intake-checklist data-intake-${dataIntakeChecklist.overall_status}`}>
                    <div className="data-intake-header">
                        <div>
                            <h2>Data Intake Checklist</h2>
                            <p>{dataIntakeChecklist.message}</p>
                        </div>
                        <div className="data-intake-badges">
                            <span>{dataIntakeChecklist.ready_count}/{dataIntakeChecklist.active_count} usable</span>
                            <span>{dataIntakeChecklist.source_rows} source rows</span>
                            <span>{dataIntakeChecklist.pending_csv_count} pending CSV</span>
                        </div>
                    </div>
                    {dataIntakeChecklist.recommended_next_action ? (
                        <div className="data-intake-next">{dataIntakeChecklist.recommended_next_action}</div>
                    ) : null}
                    <div className="data-intake-grid">
                        {dataIntakeChecklist.items.map((item) => {
                            const relatedWatchlist = watchlists.find((watchlist) => watchlist.id === item.watchlist_id);
                            const watchlistForAction: ClientWatchlist = relatedWatchlist || {
                                id: item.watchlist_id,
                                contact_id: item.contact_id,
                                contact_name: item.contact_name,
                                name: item.watchlist_name,
                                watch_type: item.watch_type,
                                status: 'active',
                                criteria: {},
                                schedule: {},
                                notification_channel: 'codex_app',
                                review_mode: 'manual_review',
                                data_source: 'internal_properties',
                                source_query: item.gmail_query,
                                created_at: '',
                                updated_at: '',
                            };
                            return (
                                <article className={`data-intake-card ${readinessClass(item.readiness)}`} key={item.watchlist_id}>
                                    <div className="data-intake-card-top">
                                        <div>
                                            <strong>{item.contact_name || item.watchlist_name}</strong>
                                            <span>{watchTypeLabel[item.watch_type] || item.watch_type}</span>
                                        </div>
                                        <b>{readinessLabel(item.readiness)}</b>
                                    </div>
                                    <div className="data-intake-statuses">
                                        <span className={item.source_ready ? 'intake-ok' : 'intake-blocked'}>
                                            Source: {item.current_matching_rows} row(s)
                                        </span>
                                        <span className={item.delivery_ready ? 'intake-ok' : 'intake-blocked'}>
                                            Delivery: {item.delivery_ready ? 'ready' : 'client email needed'}
                                        </span>
                                    </div>
                                    <div className="data-intake-meta">
                                        Needs {statusList(item.required_statuses)}
                                        {Object.keys(item.matching_status_counts || {}).length ? ` · ${statusCountsLine(item.matching_status_counts)}` : ''}
                                    </div>
                                    {item.missing_required_statuses.length ? (
                                        <div className="coverage-missing">Missing: {statusList(item.missing_required_statuses)}</div>
                                    ) : null}
                                    {item.blockers.length ? (
                                        <div className="data-intake-blockers">
                                            {item.blockers.slice(0, 2).map((blocker) => (
                                                <span key={blocker}>{blocker}</span>
                                            ))}
                                        </div>
                                    ) : null}
                                    {!item.delivery_ready ? (
                                        renderClientEmailPrompt(item.contact_id, item.contact_name || item.watchlist_name)
                                    ) : null}
                                    <div className="data-intake-primary">{item.primary_next_step}</div>
                                    <div className="data-intake-fields">
                                        {item.required_fields.slice(0, 8).map((field) => (
                                            <span key={`${item.watchlist_id}-${field}`}>{field}</span>
                                        ))}
                                    </div>
                                    <code>{item.gmail_query}</code>
                                    <div className="setup-actions">
                                        <button
                                            className="mini-control"
                                            onClick={() => downloadWatchlistTemplate(item.watchlist_id, item.contact_name || item.watchlist_name)}
                                            disabled={busyKey === `template-${item.watchlist_id}`}
                                        >
                                            Template
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => {
                                                setGmailFeedQuery(item.gmail_query);
                                                setMessage(`Loaded source query for ${item.contact_name || item.watchlist_name}.`);
                                            }}
                                        >
                                            Use Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(item.gmail_query, `${item.contact_name || item.watchlist_name} source query`)}
                                        >
                                            Copy Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => importGmailForWatchlist(watchlistForAction, true)}
                                            disabled={busyKey === `preview-watchlist-gmail-${item.watchlist_id}`}
                                        >
                                            Preview Gmail
                                        </button>
                                    </div>
                                </article>
                            );
                        })}
                    </div>
                </section>
            ) : null}

            {sourceTasks ? (
                <section className={`source-task-list source-task-${sourceTasks.overall_status}`}>
                    <div className="source-task-header">
                        <div>
                            <h2>Source Tasks</h2>
                            <p>{sourceTasks.message}</p>
                        </div>
                        <div className="source-task-badges">
                            <span>{sourceTasks.ready_count}/{sourceTasks.task_count} ready</span>
                            <span>{sourceTasks.source_rows} source rows</span>
                            <span>{sourceTasks.pending_csv_count} pending CSV</span>
                        </div>
                    </div>
                    <div className="source-task-grid">
                        {sourceTasks.tasks.map((task) => {
                            const relatedWatchlist = watchlists.find((watchlist) => watchlist.id === task.watchlist_id);
                            const watchlistForAction: ClientWatchlist = relatedWatchlist || {
                                id: task.watchlist_id,
                                contact_id: task.contact_id,
                                contact_name: task.contact_name,
                                name: task.watchlist_name,
                                watch_type: task.watch_type,
                                status: 'active',
                                criteria: {},
                                schedule: {},
                                notification_channel: 'codex_app',
                                review_mode: 'manual_review',
                                data_source: 'internal_properties',
                                source_query: task.gmail_query,
                                created_at: '',
                                updated_at: '',
                            };
                            return (
                                <article className={`source-task-card source-task-priority-${task.priority}`} key={task.task_id}>
                                    <div className="source-task-card-top">
                                        <div>
                                            <strong>{task.contact_name || task.watchlist_name}</strong>
                                            <span>{watchTypeLabel[task.watch_type] || task.watch_type}</span>
                                        </div>
                                        <b>{task.priority.replaceAll('_', ' ')}</b>
                                    </div>
                                    <p>{task.source_goal}</p>
                                    <div className="source-task-meta">
                                        <span>Needs: {statusList(task.required_statuses)}</span>
                                        {task.missing_required_statuses.length ? (
                                            <span>Missing: {statusList(task.missing_required_statuses)}</span>
                                        ) : null}
                                        {task.client_email_needed ? <span>Email needed</span> : null}
                                    </div>
                                    {task.client_email_needed ? (
                                        renderClientEmailPrompt(task.contact_id, task.contact_name || task.watchlist_name, 'source-task-email-row')
                                    ) : null}
                                    <div className="source-task-fields">
                                        {task.required_fields.slice(0, 8).map((field) => (
                                            <span key={`${task.task_id}-${field}`}>{field}</span>
                                        ))}
                                    </div>
                                    <div className="source-checklist">
                                        <div className="source-checklist-title">
                                            <span>REALM/TRREB saved search</span>
                                            <b>{task.saved_search_name}</b>
                                        </div>
                                        {task.realm_criteria?.length ? (
                                            <div className="source-checklist-list">
                                                {task.realm_criteria.slice(0, 6).map((item) => (
                                                    <span key={`${task.task_id}-criteria-${item}`}>{item}</span>
                                                ))}
                                            </div>
                                        ) : null}
                                        {task.realm_steps?.length ? (
                                            <div className="source-checklist-steps">
                                                {task.realm_steps.slice(0, 4).map((step, index) => (
                                                    <span key={`${task.task_id}-realm-step-${step}`}>{index + 1}. {step}</span>
                                                ))}
                                            </div>
                                        ) : null}
                                    </div>
                                    <code>{task.gmail_query}</code>
                                    {task.drop_folder ? <code>{task.drop_folder}</code> : null}
                                    <div className="source-task-steps">
                                        {task.steps.slice(0, 5).map((step) => (
                                            <span key={`${task.task_id}-${step}`}>{step}</span>
                                        ))}
                                    </div>
                                    <div className="setup-actions">
                                        <button
                                            className="mini-control"
                                            onClick={() => downloadWatchlistTemplate(task.watchlist_id, task.contact_name || task.watchlist_name)}
                                            disabled={busyKey === `template-${task.watchlist_id}`}
                                        >
                                            Template
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => {
                                                setGmailFeedQuery(task.gmail_query);
                                                setMessage(`Loaded source task query for ${task.contact_name || task.watchlist_name}.`);
                                            }}
                                        >
                                            Use Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(task.gmail_query, `${task.contact_name || task.watchlist_name} source query`)}
                                        >
                                            Copy Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(
                                                sourceChecklistText(
                                                    task.contact_name || task.watchlist_name,
                                                    task.saved_search_name,
                                                    task.realm_criteria,
                                                    task.realm_steps,
                                                ),
                                                `${task.contact_name || task.watchlist_name} REALM/TRREB checklist`,
                                            )}
                                        >
                                            Copy Checklist
                                        </button>
                                        {task.drop_folder ? (
                                            <button
                                                className="mini-control"
                                                onClick={() => copyToClipboard(task.drop_folder || '', 'CSV drop folder path')}
                                            >
                                                Copy Path
                                            </button>
                                        ) : null}
                                        <button
                                            className="mini-control"
                                            onClick={() => importGmailForWatchlist(watchlistForAction, true)}
                                            disabled={busyKey === `preview-watchlist-gmail-${task.watchlist_id}`}
                                        >
                                            Preview Gmail
                                        </button>
                                    </div>
                                </article>
                            );
                        })}
                    </div>
                </section>
            ) : null}

            <section className="watchlist-source glass-panel">
                <div className="source-icon">
                    <Database size={18} />
                </div>
                <div className="source-content">
                    <div className="source-title">Data Source: Internal Properties + CSV/RESO Import</div>
                    <div className="source-copy">{sourceStatus?.message || 'Checking source status...'}</div>
                    <div className="source-badges">
                        <span>{sourceStatus?.properties_count ?? 0} rows</span>
                        <span>CSV import ready</span>
                        <span>RESO JSON ready</span>
                        <span title={sourceStatus?.reso_connector.message}>
                            RESO connector {sourceStatus?.reso_connector.status.replaceAll('_', ' ') || 'unknown'}
                        </span>
                        <span>{sourceStatus?.csv_drop_folder_pending_count ?? 0} pending source</span>
                        <span>{sourceStatus?.csv_drop_folder_non_importable_count ?? 0} helper/template</span>
                        <span>{sourceStatus?.external_mls_connector_ready ? 'MLS connector ready' : 'MLS connector not connected'}</span>
                    </div>
                    {sourceStatus?.reso_connector.endpoint ? (
                        <code className="source-connector-endpoint">
                            RESO endpoint: {sourceStatus.reso_connector.endpoint}
                        </code>
                    ) : null}
                    {sourceStatus ? (
                        <div className={`csv-drop-folder ${sourceStatus.csv_drop_folder_pending_count > 0 ? 'has-pending' : ''}`}>
                            <div className="drop-folder-topline">
                                <span>CSV Drop Folder</span>
                                <strong>
                                    {sourceStatus.csv_drop_folder_exists
                                        ? `${sourceStatus.csv_drop_folder_pending_count} pending`
                                        : 'folder missing'}
                                </strong>
                            </div>
                            <code>{sourceStatus.csv_drop_folder || 'Not configured'}</code>
                            <div className="drop-folder-meta">
                                {sourceStatus.csv_drop_folder_exists
                                    ? `${sourceStatus.csv_drop_folder_importable_count ?? sourceStatus.csv_drop_folder_file_count} importable CSV/JSON source file(s) in the drop folder or source subfolders, ${sourceStatus.csv_drop_folder_processed_count ?? 0} already processed. ${
                                        sourceStatus.csv_drop_folder_pending_count > 0
                                            ? 'Next scheduled check imports pending source files before matching.'
                                            : 'No pending source files.'
                                    } ${sourceStatus.csv_drop_folder_non_importable_count ?? 0} helper/template file(s) are ignored by import; ${sourceStatus.csv_drop_folder_disabled_template_count ?? 0} disabled template(s), ${sourceStatus.csv_drop_folder_instruction_file_count ?? 0} instruction file(s). Save completed per-client source files as .csv or .json beside their disabled template or in the drop folder root.`
                                    : 'Create this folder or use the manual CSV upload below.'}
                            </div>
                            <div className="drop-folder-actions">
                                <button
                                    className="mini-control"
                                    onClick={() => importDropFolder(true)}
                                    disabled={!sourceStatus.csv_drop_folder_exists || busyKey === 'preview-drop-folder'}
                                >
                                    Preview Folder
                                </button>
                                <button
                                    className="mini-control"
                                    onClick={() => importDropFolder(false)}
                                    disabled={!sourceStatus.csv_drop_folder_exists || sourceStatus.csv_drop_folder_pending_count === 0 || busyKey === 'import-drop-folder'}
                                >
                                    Import Folder + Check
                                </button>
                                {sourceStatus.csv_drop_folder ? (
                                    <button
                                        className="mini-control"
                                        onClick={() => copyToClipboard(sourceStatus.csv_drop_folder || '', 'CSV drop folder path')}
                                    >
                                        Copy Path
                                    </button>
                                ) : null}
                            </div>
                            {lastDropFolderResult ? (
                                <div className="drop-folder-result">
                                    <span>{lastDropFolderResult.dry_run ? 'Preview' : 'Import'}: {lastDropFolderResult.processed_count} processed</span>
                                    <span>{lastDropFolderResult.pending_after} pending after</span>
                                    {lastDropFolderResult.failed.length ? (
                                        <span>{lastDropFolderResult.failed.length} need attention</span>
                                    ) : null}
                                </div>
                            ) : null}
                        </div>
                    ) : null}
                    {sourceStatus?.watch_type_coverage?.length ? (
                        <div className="source-coverage-grid">
                            {sourceStatus.watch_type_coverage.map((item) => (
                                <div className={`source-coverage-card ${sourceReadinessClass(item.readiness)}`} key={item.watch_type}>
                                    <div className="coverage-topline">
                                        <span>{item.label}</span>
                                        <strong>{sourceReadinessLabel(item.readiness)}</strong>
                                    </div>
                                    <div className="coverage-counts">
                                        {item.usable_rows} usable / {item.matching_rows} matching rows
                                    </div>
                                    <div className="coverage-statuses">
                                        {statusList(item.required_statuses)}
                                    </div>
                                    {item.missing_fields.length ? (
                                        <div className="coverage-missing">
                                            Missing: {item.missing_fields.join(', ')}
                                        </div>
                                    ) : null}
                                </div>
                            ))}
                        </div>
                    ) : null}
                    {sourceStatus?.recommended_next_import ? (
                        <div className="source-next-step">{sourceStatus.recommended_next_import}</div>
                    ) : null}
                    {sourceSetups.length ? (
                        <div className="source-setup-grid">
                            {sourceSetups.map((setup) => (
                                <div className={`source-setup-card ${setup.readiness === 'ready' ? 'source-ready' : 'source-blocked'}`} key={setup.watchlist_id}>
                                    <div className="setup-topline">
                                        <strong>{setup.contact_name || setup.watchlist_name}</strong>
                                        <span>{setup.current_matching_rows} source rows</span>
                                    </div>
                                    <div className="setup-meta">
                                        {statusList(setup.required_statuses)}
                                    </div>
                                    {Object.keys(setup.matching_status_counts || {}).length ? (
                                        <div className="setup-meta">{statusCountsLine(setup.matching_status_counts)}</div>
                                    ) : null}
                                    {setup.missing_required_statuses?.length ? (
                                        <div className="coverage-missing">
                                            Missing: {statusList(setup.missing_required_statuses)}
                                        </div>
                                    ) : null}
                                    <div className="setup-fields">
                                        {setup.required_fields.map((field) => (
                                            <span key={`${setup.watchlist_id}-${field}`}>{field}</span>
                                        ))}
                                    </div>
                                    <div className="source-checklist compact">
                                        <div className="source-checklist-title">
                                            <span>Saved search</span>
                                            <b>{setup.saved_search_name}</b>
                                        </div>
                                        {setup.realm_criteria?.length ? (
                                            <div className="source-checklist-list">
                                                {setup.realm_criteria.slice(0, 5).map((item) => (
                                                    <span key={`${setup.watchlist_id}-setup-criteria-${item}`}>{item}</span>
                                                ))}
                                            </div>
                                        ) : null}
                                    </div>
                                    <code>{setup.gmail_query}</code>
                                    <div className="setup-actions">
                                        <button
                                            className="mini-control"
                                            onClick={() => downloadWatchlistTemplate(setup.watchlist_id, setup.contact_name || setup.watchlist_name)}
                                            disabled={busyKey === `template-${setup.watchlist_id}`}
                                        >
                                            Template
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => {
                                                setGmailFeedQuery(setup.gmail_query);
                                                setMessage(`Loaded source query for ${setup.contact_name || setup.watchlist_name}.`);
                                            }}
                                        >
                                            Use Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(setup.gmail_query, `${setup.contact_name || setup.watchlist_name} source query`)}
                                        >
                                            Copy Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => copyToClipboard(
                                                sourceChecklistText(
                                                    setup.contact_name || setup.watchlist_name,
                                                    setup.saved_search_name,
                                                    setup.realm_criteria,
                                                    setup.realm_steps,
                                                ),
                                                `${setup.contact_name || setup.watchlist_name} REALM/TRREB checklist`,
                                            )}
                                        >
                                            Checklist
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => importGmailForWatchlist(
                                                watchlists.find((item) => item.id === setup.watchlist_id) || {
                                                    id: setup.watchlist_id,
                                                    contact_id: setup.contact_id,
                                                    contact_name: setup.contact_name,
                                                    name: setup.watchlist_name,
                                                    watch_type: setup.watch_type,
                                                    status: 'active',
                                                    criteria: {},
                                                    schedule: {},
                                                    notification_channel: 'codex_app',
                                                    review_mode: 'manual_review',
                                                    data_source: 'internal_properties',
                                                    source_query: setup.gmail_query,
                                                    created_at: '',
                                                    updated_at: '',
                                                },
                                                true,
                                            )}
                                            disabled={busyKey === `preview-watchlist-gmail-${setup.watchlist_id}`}
                                        >
                                            Preview
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : null}
                </div>
                <div className="source-import">
                    <input
                        className="csv-input"
                        type="file"
                        accept=".csv,text/csv"
                        onChange={(event) => setImportFile(event.target.files?.[0] || null)}
                    />
                    <button
                        className="btn btn-ghost watchlist-action"
                        onClick={downloadCsvTemplate}
                    >
                        Template
                    </button>
                    <button
                        className="btn btn-ghost watchlist-action"
                        onClick={downloadSourceKit}
                        disabled={busyKey === 'source-kit'}
                    >
                        Source Kit
                    </button>
                    <button
                        className="btn btn-ghost watchlist-action"
                        onClick={downloadClientEmailTasks}
                        disabled={busyKey === 'client-email-tasks'}
                    >
                        Email CSV
                    </button>
                    <button
                        className="btn btn-ghost watchlist-action"
                        onClick={() => importProperties(true)}
                        disabled={!importFile || busyKey === 'preview-properties'}
                    >
                        Preview CSV
                    </button>
                    <button
                        className="btn btn-accent watchlist-action"
                        onClick={() => importProperties(false)}
                        disabled={!importFile || busyKey === 'import-properties'}
                    >
                        Import CSV + Check
                    </button>
                </div>
                <div className="source-feed-tools">
                    <textarea
                        className="input-field feed-textarea"
                        value={feedText}
                        onChange={(event) => setFeedText(event.target.value)}
                        placeholder="Paste REALM/TRREB/MLS listing email text here..."
                    />
                    <div className="feed-tool-actions">
                        <button
                            className="btn btn-ghost watchlist-action"
                            onClick={() => importFeedText(true)}
                            disabled={!feedText.trim() || busyKey === 'preview-feed'}
                        >
                            Preview Feed
                        </button>
                        <button
                            className="btn btn-accent watchlist-action"
                            onClick={() => importFeedText(false)}
                            disabled={!feedText.trim() || busyKey === 'import-feed'}
                        >
                            Import Feed + Check
                        </button>
                    </div>
                    <textarea
                        className="input-field feed-textarea"
                        value={resoJsonText}
                        onChange={(event) => setResoJsonText(event.target.value)}
                        placeholder='Paste authorized RESO/OData MLS JSON here, for example { "value": [...] }'
                    />
                    <div className="feed-tool-actions">
                        <button
                            className="btn btn-ghost watchlist-action"
                            onClick={() => importResoJson(true)}
                            disabled={!resoJsonText.trim() || busyKey === 'preview-reso-json'}
                        >
                            Preview RESO JSON
                        </button>
                        <button
                            className="btn btn-accent watchlist-action"
                            onClick={() => importResoJson(false)}
                            disabled={!resoJsonText.trim() || busyKey === 'import-reso-json'}
                        >
                            Import RESO + Check
                        </button>
                    </div>
                    <input
                        className="input-field"
                        value={gmailFeedQuery}
                        onChange={(event) => setGmailFeedQuery(event.target.value)}
                        placeholder="Gmail query for saved-search emails"
                    />
                    <div className="feed-tool-actions">
                        <button
                            className="btn btn-ghost watchlist-action"
                            onClick={() => importGmailFeed(true)}
                            disabled={busyKey === 'preview-gmail-feed'}
                        >
                            Preview Gmail
                        </button>
                        <button
                            className="btn btn-primary watchlist-action"
                            onClick={() => importGmailFeed(false)}
                            disabled={busyKey === 'import-gmail-feed'}
                        >
                            Import Gmail + Check
                        </button>
                    </div>
                    <div className="feed-config-row">
                        <span className={`status-pill ${feedConfig?.gmail_feed_enabled ? 'status-active' : 'status-muted'}`}>
                            {feedConfig?.gmail_feed_enabled ? 'Scheduled Gmail: Global + Watchlists' : 'Scheduled Gmail Off'}
                        </span>
                        <label className="feed-max-results">
                            Max emails
                            <input
                                className="input-field"
                                type="number"
                                min={1}
                                max={50}
                                value={gmailFeedMaxResults}
                                onChange={(event) => setGmailFeedMaxResults(Number(event.target.value) || 10)}
                            />
                        </label>
                        <button
                            className="btn btn-ghost watchlist-action"
                            onClick={() => saveGmailFeedConfig(feedConfig?.gmail_feed_enabled || false)}
                            disabled={busyKey === 'feed-config'}
                        >
                            Save Feed Query
                        </button>
                        <button
                            className="btn btn-primary watchlist-action"
                            onClick={() => saveGmailFeedConfig(!(feedConfig?.gmail_feed_enabled || false))}
                            disabled={busyKey === 'feed-config'}
                        >
                            {feedConfig?.gmail_feed_enabled ? 'Disable Scheduled Gmail' : 'Enable Scheduled Gmail Feeds'}
                        </button>
                        {feedConfig?.last_import_message ? (
                            <span className="feed-last-import">{feedConfig.last_import_message}</span>
                        ) : null}
                    </div>
                </div>
                {lastImportErrors.length ? (
                    <div className="import-issues">
                        <div className="import-preview-title">Import issues</div>
                        <div className="import-issue-list">
                            {lastImportErrors.slice(0, 8).map((issue, index) => (
                                <span key={`${issue}-${index}`}>{issue}</span>
                            ))}
                            {lastImportErrors.length > 8 ? (
                                <span>{lastImportErrors.length - 8} more issue(s) not shown.</span>
                            ) : null}
                        </div>
                    </div>
                ) : null}
                {lastImportWarnings.length ? (
                    <div className="import-warnings">
                        <div className="import-preview-title">Import warnings</div>
                        <div className="import-warning-list">
                            {lastImportWarnings.slice(0, 8).map((warning, index) => (
                                <span key={`${warning}-${index}`}>{warning}</span>
                            ))}
                            {lastImportWarnings.length > 8 ? (
                                <span>{lastImportWarnings.length - 8} more warning(s) not shown.</span>
                            ) : null}
                        </div>
                    </div>
                ) : null}
                {lastImportPreview.length ? (
                    <div className="import-preview">
                        <div className="import-preview-title">Last parsed rows</div>
                        <div className="import-preview-list">
                            {lastImportPreview.map((row, index) => {
                                if (isContactEmailPreviewRow(row)) {
                                    return (
                                        <div
                                            className="import-preview-row contact-email-preview-row"
                                            key={`${row.contact_id || row.contact_name || index}-email`}
                                        >
                                            <span className="preview-action">Email</span>
                                            <span>{String(row.contact_name || `Contact #${row.contact_id || ''}`)}</span>
                                            <span>{String(row.email || 'No email')}</span>
                                            <span>Updates CRM contact email only</span>
                                        </div>
                                    );
                                }

                                return (
                                    <div className="import-preview-row" key={`${row.mls_number || row.street || index}`}>
                                        <span className="preview-action">{String(row.action || 'preview')}</span>
                                        <span>{String(row.mls_number || 'No MLS')}</span>
                                        <span>{String(row.street || 'No address')}</span>
                                        <span>{String(row.city || '')}</span>
                                        <span>{String(row.status || '')}</span>
                                        <span>{String(row.property_type || '')}</span>
                                        <span>{previewPrice(row)}</span>
                                        <span>{[row.bedrooms && `${row.bedrooms} bed`, row.bathrooms && `${row.bathrooms} bath`, row.parking && `${row.parking} parking`].filter(Boolean).join(' / ')}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ) : null}
                {lastReadinessPreview.length ? (
                    <div className="import-preview readiness-preview">
                        <div className="import-preview-title">Import readiness impact</div>
                        <div className="readiness-preview-list">
                            {lastReadinessPreview.map((item) => (
                                <div
                                    className={`readiness-preview-row ${importReadinessClass(item.readiness_delta)}`}
                                    key={`readiness-${item.watchlist_id}`}
                                >
                                    <div className="readiness-preview-topline">
                                        <strong>{item.contact_name || `Contact #${item.contact_id}`}</strong>
                                        <span>{item.watchlist_name}</span>
                                        <b>{importReadinessLabel(item.readiness_delta)}</b>
                                    </div>
                                    <div className="readiness-preview-grid">
                                        <span>Required: {statusList(item.required_statuses)}</span>
                                        <span>Current: {statusCountsLine(item.current_status_counts) || 'none'}</span>
                                        <span>Preview adds: {statusCountsLine(item.preview_status_counts) || 'none'}</span>
                                        <span>After import: {statusCountsLine(item.projected_status_counts) || 'none'}</span>
                                    </div>
                                    {item.missing_after?.length ? (
                                        <div className="coverage-missing">
                                            Still missing: {statusList(item.missing_after)}
                                        </div>
                                    ) : (
                                        <div className="readiness-preview-ready">
                                            Source rows would be complete for scheduled matching.
                                        </div>
                                    )}
                                    <div className={`readiness-preview-delivery ${importDeliveryClass(item.delivery_state_after)}`}>
                                        <div>
                                            <strong>{importDeliveryLabel(item.delivery_state_after)}</strong>
                                            <span>
                                                {reviewModeLabel[item.review_mode] || item.review_mode}
                                                {' '}via {notificationChannelLabel[item.notification_channel] || item.notification_channel}
                                            </span>
                                        </div>
                                        <div className="readiness-preview-delivery-meta">
                                            <span>Email: {item.contact_email_present ? 'ready' : 'missing'}</span>
                                            <span>Gmail recipient: {item.draft_recipient_ready_after ? 'ready' : 'blocked'}</span>
                                            <span>Auto-send: {item.can_auto_send_after ? 'ready' : item.auto_send_server_enabled ? 'server on' : 'server off'}</span>
                                        </div>
                                        {item.delivery_blockers_after?.length ? (
                                            <div className="readiness-preview-delivery-blockers">
                                                {item.delivery_blockers_after.join(' ')}
                                            </div>
                                        ) : null}
                                        <div className="readiness-preview-delivery-next">{item.delivery_next_step}</div>
                                    </div>
                                    <div className="readiness-preview-next">{item.primary_next_step}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : null}
                {lastMatchPreview.length ? (
                    <div className="import-preview match-preview">
                        <div className="import-preview-title">Predicted watchlist matches</div>
                        <div className="match-preview-list">
                            {lastMatchPreview.map((match, index) => (
                                <div className="match-preview-row" key={`${match.watchlist_id}-${match.property?.mls_number || index}`}>
                                    <div className="match-preview-topline">
                                        <strong>{match.contact_name || `Contact #${match.contact_id}`}</strong>
                                        <span>{match.watchlist_name}</span>
                                        <b>{match.match_score}</b>
                                    </div>
                                    <div className="match-preview-property">
                                        {[match.property?.mls_number, match.property?.street, match.property?.city, previewPrice(match.property || {})]
                                            .filter(Boolean)
                                            .map((item) => String(item))
                                            .join(' · ')}
                                    </div>
                                    {match.reasons?.length ? (
                                        <div className="match-preview-reasons">{match.reasons.join(' · ')}</div>
                                    ) : null}
                                    {match.analysis ? (
                                        <div className="match-preview-analysis">{match.analysis}</div>
                                    ) : null}
                                </div>
                            ))}
                        </div>
                    </div>
                ) : null}
            </section>

            <section className="automation-history glass-panel">
                <div className="section-heading history-heading">
                    <div>
                        <h2><Activity size={18} /> Automation Run History</h2>
                        <p>Recent evidence from scheduled/manual watchlist checks.</p>
                    </div>
                    <span className="count-pill">{runLogs.length}</span>
                </div>
                <div className="run-log-list">
                    {runLogs.length ? runLogs.map((run) => (
                        <div className="run-log-row" key={run.id}>
                            <div className="run-log-main">
                                <span className={`status-pill ${statusClass(run.status)}`}>{run.status}</span>
                                <strong>{run.run_type.replaceAll('_', ' ')}</strong>
                                <span>{formatRunTime(run.finished_at || run.created_at)}</span>
                            </div>
                            <div className="run-log-metrics">
                                <span>checked {run.checked_count}</span>
                                <span>matched {run.matched_properties}</span>
                                <span>alerts {run.created_alerts}</span>
                                <span>pending {run.pending_alert_count}</span>
                            </div>
                            <div className="run-log-message">
                                {run.message || run.error || run.source_status || 'No run message recorded.'}
                            </div>
                        </div>
                    )) : (
                        <div className="run-log-empty">No automation run evidence recorded yet.</div>
                    )}
                </div>
            </section>

            <section className="codex-notifications glass-panel">
                <div className="section-heading history-heading">
                    <div>
                        <h2><BellRing size={18} /> Codex Notification Queue</h2>
                        <p>Review-only app notifications from watchlist alerts. This does not approve or send client email.</p>
                    </div>
                    <div className="notification-heading-actions">
                        <span className="count-pill">{queuedCodexNotifications.length}</span>
                        <button
                            className="mini-control"
                            onClick={markCodexNotificationsReported}
                            disabled={!queuedCodexNotifications.length || busyKey === 'mark-codex-notifications'}
                        >
                            Mark Reported
                        </button>
                    </div>
                </div>
                <div className="notification-log-list">
                    {codexNotifications.length ? codexNotifications.map((notification) => (
                        <div
                            className={`notification-log-row ${focusedAlertId && notification.alert_id === focusedAlertId ? 'notification-log-row-focused' : ''}`}
                            key={notification.id}
                        >
                            <div className="notification-log-main">
                                <span className={`status-pill ${statusClass(notification.status)}`}>{notification.status.replaceAll('_', ' ')}</span>
                                <strong>{notification.title}</strong>
                            </div>
                            <div className="notification-log-body">{notification.body}</div>
                            <div className="notification-log-meta">
                                alert #{notification.alert_id} · {formatRunTime(notification.delivered_at || notification.created_at)}
                            </div>
                        </div>
                    )) : (
                        <div className="run-log-empty">No Codex app notifications recorded yet.</div>
                    )}
                </div>
            </section>

            <div className="watchlist-grid">
                <section className="watchlist-column glass-panel">
                    <div className="section-heading">
                        <h2>Client Watchlists</h2>
                        <span className="count-pill">{watchlists.length}</span>
                    </div>

                    <div className="watchlist-stack">
                        {watchlists.length ? watchlists.map((watchlist) => (
                            <article
                                className={`watchlist-card ${focusedContactId && watchlist.contact_id === focusedContactId ? 'watchlist-card-focused' : ''}`}
                                key={watchlist.id}
                            >
                                <div className="watchlist-card-top">
                                    <div>
                                        <h3>{watchlist.name}</h3>
                                        <div className="watchlist-meta">{watchlist.contact_name} · {watchTypeLabel[watchlist.watch_type] || watchlist.watch_type}</div>
                                    </div>
                                    <span className={`status-pill ${statusClass(watchlist.status)}`}>{watchlist.status}</span>
                                </div>

                                <div className="criteria-chips">
                                    {criteriaSummary(watchlist.criteria).map((chip) => (
                                        <span key={chip}>{chip}</span>
                                    ))}
                                </div>

                                {watchlist.readiness ? (
                                    <div className={`watchlist-readiness ${readinessClass(watchlist.readiness.severity)}`}>
                                        <div className="readiness-heading">
                                            {watchlist.readiness.severity === 'ready' ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                                            <span>{readinessLabel(watchlist.readiness.severity)}</span>
                                        </div>
                                        <div className="readiness-copy">{readinessLine(watchlist)}</div>
                                        {watchlist.readiness.delivery_issues?.length ? (
                                            <div className="coverage-missing">
                                                Delivery: {watchlist.readiness.delivery_issues.join(' · ')}
                                            </div>
                                        ) : null}
                                        {watchlist.readiness.next_steps?.length ? (
                                            <div className="readiness-steps">
                                                {watchlist.readiness.next_steps.slice(0, 2).map((step) => (
                                                    <span key={step}>{step}</span>
                                                ))}
                                            </div>
                                        ) : null}
                                    </div>
                                ) : null}

                                <div className="watchlist-source-query">
                                    <div>
                                        <span>Source query</span>
                                        <code>{watchlist.source_query || defaultGmailFeedQuery}</code>
                                    </div>
                                    <div className="source-query-actions">
                                        <button
                                            className="mini-control"
                                            onClick={() => loadWatchlistSourceQuery(watchlist)}
                                        >
                                            Use Query
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => downloadWatchlistTemplate(watchlist.id, watchlist.contact_name || watchlist.name)}
                                            disabled={busyKey === `template-${watchlist.id}`}
                                        >
                                            Template
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => importGmailForWatchlist(watchlist, true)}
                                            disabled={busyKey === `preview-watchlist-gmail-${watchlist.id}`}
                                        >
                                            Preview Gmail
                                        </button>
                                        <button
                                            className="mini-control"
                                            onClick={() => importGmailForWatchlist(watchlist, false)}
                                            disabled={busyKey === `import-watchlist-gmail-${watchlist.id}`}
                                        >
                                            Import + Check
                                        </button>
                                    </div>
                                </div>

                                {editingWatchlistId === watchlist.id && criteriaDraft ? (
                                    <div className="criteria-editor">
                                        <div className="criteria-editor-grid">
                                            <label>
                                                Name
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.name}
                                                    onChange={(event) => updateCriteriaDraft('name', event.target.value)}
                                                />
                                            </label>
                                            <label>
                                                Type
                                                <select
                                                    className="input-field"
                                                    value={criteriaDraft.watch_type}
                                                    onChange={(event) => updateCriteriaDraft('watch_type', event.target.value)}
                                                >
                                                    {Object.entries(watchTypeLabel).map(([value, label]) => (
                                                        <option key={value} value={value}>{label}</option>
                                                    ))}
                                                </select>
                                            </label>
                                            <label>
                                                Areas
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.areas}
                                                    onChange={(event) => updateCriteriaDraft('areas', event.target.value)}
                                                    placeholder="Thornhill, Milton"
                                                />
                                            </label>
                                            <label>
                                                Property Types
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.types}
                                                    onChange={(event) => updateCriteriaDraft('types', event.target.value)}
                                                    placeholder="townhouse, detached"
                                                />
                                            </label>
                                            <label>
                                                Max Price
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.max_price}
                                                    onChange={(event) => updateCriteriaDraft('max_price', event.target.value)}
                                                    inputMode="numeric"
                                                />
                                            </label>
                                            <label>
                                                Min Price
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.min_price}
                                                    onChange={(event) => updateCriteriaDraft('min_price', event.target.value)}
                                                    inputMode="numeric"
                                                />
                                            </label>
                                            <label>
                                                Bedrooms
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.bedrooms_min}
                                                    onChange={(event) => updateCriteriaDraft('bedrooms_min', event.target.value)}
                                                    inputMode="numeric"
                                                />
                                            </label>
                                            <label>
                                                Bathrooms
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.bathrooms_min}
                                                    onChange={(event) => updateCriteriaDraft('bathrooms_min', event.target.value)}
                                                    inputMode="numeric"
                                                />
                                            </label>
                                            <label>
                                                Parking
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.parking_min}
                                                    onChange={(event) => updateCriteriaDraft('parking_min', event.target.value)}
                                                    inputMode="numeric"
                                                />
                                            </label>
                                            <label>
                                                Property Address
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.property_address}
                                                    onChange={(event) => updateCriteriaDraft('property_address', event.target.value)}
                                                />
                                            </label>
                                            <label>
                                                Must Haves
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.must_haves}
                                                    onChange={(event) => updateCriteriaDraft('must_haves', event.target.value)}
                                                    placeholder="garage, freehold"
                                                />
                                            </label>
                                            <label>
                                                Deal Breakers
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.deal_breakers}
                                                    onChange={(event) => updateCriteriaDraft('deal_breakers', event.target.value)}
                                                    placeholder="Malton"
                                                />
                                            </label>
                                            <label>
                                                Available After
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.available_after}
                                                    onChange={(event) => updateCriteriaDraft('available_after', event.target.value)}
                                                />
                                            </label>
                                            <label className="criteria-editor-wide">
                                                Source Query
                                                <input
                                                    className="input-field"
                                                    value={criteriaDraft.source_query}
                                                    onChange={(event) => updateCriteriaDraft('source_query', event.target.value)}
                                                    placeholder="newer_than:14d (REALM OR TRREB OR MLS) Thornhill townhouse"
                                                />
                                            </label>
                                        </div>
                                        <div className="criteria-editor-actions">
                                            <button
                                                className="btn btn-accent watchlist-action"
                                                onClick={() => saveCriteria(watchlist)}
                                                disabled={busyKey === `criteria-${watchlist.id}`}
                                            >
                                                Save Criteria
                                            </button>
                                            <button
                                                className="btn btn-ghost watchlist-action"
                                                onClick={() => {
                                                    setEditingWatchlistId(null);
                                                    setCriteriaDraft(null);
                                                }}
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    </div>
                                ) : null}

                                <div className="watchlist-timing">
                                    <div><Clock3 size={14} /> {scheduleSummary(watchlist.schedule)}</div>
                                    <div>Next: {formatDateTime(watchlist.next_check_at)}</div>
                                    <div>Last: {formatDateTime(watchlist.last_checked_at)}</div>
                                </div>

                                <div className="watchlist-quick-controls">
                                    <button
                                        className="mini-control"
                                        onClick={() => setClientSchedule(watchlist, ['09:00'])}
                                        disabled={busyKey === clientScheduleBusyKey(watchlist)}
                                    >
                                        Client 9 AM
                                    </button>
                                    <button
                                        className="mini-control"
                                        onClick={() => setClientSchedule(watchlist, ['09:00', '15:00', '18:00'])}
                                        disabled={busyKey === clientScheduleBusyKey(watchlist)}
                                    >
                                        Client 9 / 3 / 6
                                    </button>
                                    <button
                                        className="mini-control"
                                        onClick={() => startEditSchedule(watchlist)}
                                        disabled={editingScheduleId === watchlist.id || busyKey === clientScheduleBusyKey(watchlist)}
                                    >
                                        Custom Client Schedule
                                    </button>
                                    <div className="notification-channel-controls" aria-label={`Client notification channel for ${watchlist.contact_name || watchlist.name}`}>
                                        <span>Notify</span>
                                        {notificationChannelControls.map((channel) => (
                                            <button
                                                key={`${watchlist.id}-${channel.value}`}
                                                className={`mini-control ${watchlist.notification_channel === channel.value ? 'mini-control-active' : ''}`}
                                                onClick={() => setClientNotificationChannel(watchlist, channel.value)}
                                                disabled={busyKey === clientNotificationBusyKey(watchlist)}
                                                title={`Set all ${watchlist.contact_name || watchlist.name} watchlists to ${notificationChannelLabel[channel.value] || channel.label}`}
                                            >
                                                {channel.label}
                                            </button>
                                        ))}
                                    </div>
                                    <button
                                        className="mini-control"
                                        onClick={() => startEditCriteria(watchlist)}
                                        disabled={editingWatchlistId === watchlist.id}
                                    >
                                        Edit Criteria
                                    </button>
                                </div>

                                {editingScheduleId === watchlist.id && scheduleDraft ? (
                                    <div className="schedule-editor">
                                        <label>
                                            Check times
                                            <input
                                                value={scheduleDraft.times}
                                                onChange={(event) => updateScheduleDraft('times', event.target.value)}
                                                placeholder="09:00, 15:00, 18:00"
                                            />
                                        </label>
                                        <label>
                                            Timezone
                                            <input
                                                value={scheduleDraft.timezone}
                                                onChange={(event) => updateScheduleDraft('timezone', event.target.value)}
                                                placeholder="America/Toronto"
                                            />
                                        </label>
                                        <div className="schedule-editor-actions">
                                            <button
                                                className="mini-control mini-control-active"
                                                onClick={() => saveScheduleDraft(watchlist)}
                                                disabled={busyKey === clientScheduleBusyKey(watchlist)}
                                            >
                                                Save Client Schedule
                                            </button>
                                            <button
                                                className="mini-control"
                                                onClick={cancelEditSchedule}
                                                disabled={busyKey === clientScheduleBusyKey(watchlist)}
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    </div>
                                ) : null}

                                <div className="approval-mode-panel">
                                    <div className="approval-mode-topline">
                                        <span>Client Approval Mode</span>
                                        <strong>{reviewModeLabel[watchlist.review_mode] || 'Manual Review'}</strong>
                                    </div>
                                    <div className="approval-mode-controls">
                                        {reviewModeControls.map((mode) => (
                                            <button
                                                key={`${watchlist.id}-${mode.value}`}
                                                className={`mini-control ${watchlist.review_mode === mode.value ? 'mini-control-active' : ''}`}
                                                onClick={() => setReviewMode(watchlist, mode.value)}
                                                disabled={busyKey === clientReviewModeBusyKey(watchlist)}
                                                title={`Set all ${watchlist.contact_name || watchlist.name} watchlists to ${reviewModeLabel[mode.value] || mode.label}`}
                                            >
                                                {mode.label}
                                            </button>
                                        ))}
                                        {watchlist.review_mode === 'auto_send_approved' ? (
                                            <button
                                                className="mini-control mini-control-warn mini-control-active"
                                                onClick={() => setReviewMode(watchlist, 'auto_gmail_draft')}
                                                disabled={busyKey === clientReviewModeBusyKey(watchlist)}
                                            >
                                                Disarm Client Auto Send
                                            </button>
                                        ) : (
                                            <button
                                                className="mini-control mini-control-warn"
                                                onClick={() => armAutoSend(watchlist)}
                                                disabled={busyKey === `auto-send-${watchlist.id}`}
                                            >
                                                Arm Client Auto Send
                                            </button>
                                        )}
                                    </div>
                                    {watchlist.review_mode === 'auto_send_approved' ? (
                                        <div className="approval-safety-note">
                                            {safetyStatus?.can_auto_send
                                                ? 'Server send is enabled for this armed client.'
                                                : 'Draft-only safety is active; this client will still get Gmail drafts until server auto-send is enabled.'}
                                        </div>
                                    ) : null}
                                </div>

                                <div className="watchlist-card-actions">
                                    <button
                                        className="btn btn-accent watchlist-action"
                                        onClick={() => checkWatchlist(watchlist)}
                                        disabled={busyKey === `check-${watchlist.id}`}
                                    >
                                        <SearchCheck size={16} />
                                        Check Now
                                    </button>
                                    <button
                                        className="btn btn-ghost watchlist-action"
                                        onClick={() => createWatchlistDigestDraft(watchlist)}
                                        disabled={!pendingAlertCounts.get(watchlist.id) || busyKey === `digest-${watchlist.id}`}
                                    >
                                        <MailPlus size={16} />
                                        Digest Draft ({pendingAlertCounts.get(watchlist.id) || 0})
                                    </button>
                                    <button
                                        className="btn btn-primary watchlist-action"
                                        onClick={() => createWatchlistDigestGmailDraft(watchlist)}
                                        disabled={!pendingAlertCounts.get(watchlist.id) || busyKey === `digest-gmail-${watchlist.id}`}
                                    >
                                        <MailPlus size={16} />
                                        Digest Gmail
                                    </button>
                                    {draftNeedsGmailAlerts.get(watchlist.id)?.length ? (
                                        <button
                                            className="btn btn-primary watchlist-action"
                                            onClick={() => resumeWatchlistGmailDrafts(watchlist)}
                                            disabled={busyKey === `resume-gmail-${watchlist.id}`}
                                            title="Create Gmail draft from existing CRM draft after email/Gmail is ready. This does not send email."
                                        >
                                            <MailPlus size={16} />
                                            Resume Gmail ({draftNeedsGmailAlerts.get(watchlist.id)?.length || 0})
                                        </button>
                                    ) : null}
                                    <button
                                        className="btn btn-ghost watchlist-icon-button"
                                        onClick={() => toggleWatchlist(watchlist)}
                                        disabled={busyKey === `toggle-${watchlist.id}`}
                                        title={watchlist.status === 'active' ? 'Pause' : 'Resume'}
                                    >
                                        {watchlist.status === 'active' ? <Pause size={16} /> : <Play size={16} />}
                                    </button>
                                </div>
                                {draftNeedsGmailAlerts.get(watchlist.id)?.length ? (
                                    <div className="watchlist-recovery-note">
                                        Existing CRM draft is ready; Gmail draft still needs to be created after the client email is saved.
                                    </div>
                                ) : null}
                            </article>
                        )) : (
                            <div className="empty-state">No watchlists yet.</div>
                        )}
                    </div>
                </section>

                <section className="watchlist-column glass-panel">
                    <div className="section-heading">
                        <h2>Alert Queue</h2>
                        <span className="count-pill">{alerts.length}</span>
                    </div>

                    <div className="watchlist-stack">
                        {alerts.length ? alerts.map((alert) => (
                            <article
                                className={`alert-card ${focusedAlertId && alert.id === focusedAlertId ? 'alert-card-focused' : ''}`}
                                key={alert.id}
                            >
                                <div className="watchlist-card-top">
                                    <div>
                                        <div className="alert-label">{alertTypeLabel[alert.alert_type] || alert.alert_type}</div>
                                        <h3>{alert.title}</h3>
                                        <div className="watchlist-meta">{alert.contact_name} · {formatDateTime(alert.created_at)}</div>
                                    </div>
                                    <span className={`status-pill ${statusClass(alert.status)}`}>{alert.status}</span>
                                </div>

                                <p className="alert-summary">{alert.summary}</p>
                                <p className="alert-analysis">{alert.analysis}</p>
                                {notificationStatusChips(alert).length ? (
                                    <div className="alert-notifications">
                                        {notificationStatusChips(alert).map((item) => (
                                            <span key={`${item.channel}-${item.status}`}>
                                                {item.channel}: {item.status}
                                            </span>
                                        ))}
                                    </div>
                                ) : null}
                                <div className="alert-draft-state">
                                    {draftStateItems(alert).map((item) => (
                                        <span className={`draft-state-${item.tone}`} key={`${alert.id}-${item.label}`}>
                                            <strong>{item.label}</strong>
                                            {item.value}
                                        </span>
                                    ))}
                                </div>
                                <div className="alert-codex-command">
                                    <code>{codexAlertCommand(alert)}</code>
                                    <button
                                        className="mini-control"
                                        onClick={() => copyToClipboard(codexAlertCommand(alert), `alert #${alert.id} Codex command`)}
                                    >
                                        <Copy size={13} />
                                        Copy
                                    </button>
                                </div>

                                <div className="watchlist-card-actions">
                                    <button
                                        className="btn btn-ghost watchlist-action"
                                        onClick={() => createDraft(alert)}
                                        disabled={Boolean(alert.interaction_id) || busyKey === `draft-${alert.id}`}
                                    >
                                        <MailPlus size={16} />
                                        {alert.interaction_id ? 'CRM Draft Ready' : 'Create CRM Review Draft'}
                                    </button>
                                    <button
                                        className="btn btn-primary watchlist-action"
                                        onClick={() => createGmailDraft(alert)}
                                        disabled={alert.status === 'sent' || Boolean(alert.gmail_draft_id) || busyKey === `gmail-draft-${alert.id}`}
                                    >
                                        <MailPlus size={16} />
                                        {alert.gmail_draft_id ? 'Gmail Draft Ready' : 'Create Gmail Draft'}
                                    </button>
                                    <button
                                        className="btn btn-accent watchlist-action"
                                        onClick={() => sendWatchlistAlert(alert)}
                                        disabled={!hasReviewedGmailDraft(alert) || alert.status === 'sent' || busyKey === `send-alert-${alert.id}`}
                                        title={hasReviewedGmailDraft(alert) ? 'Send the existing reviewed Gmail draft' : 'Create a Gmail draft before sending'}
                                    >
                                        <MailPlus size={16} />
                                        {alert.status === 'sent' ? 'Sent' : 'Send Reviewed Gmail Draft'}
                                    </button>
                                    {alert.status !== 'dismissed' && (
                                        <button
                                            className="btn btn-ghost watchlist-icon-button"
                                            onClick={() => dismissAlert(alert)}
                                            disabled={busyKey === `dismiss-${alert.id}`}
                                            title="Dismiss"
                                        >
                                            <XCircle size={16} />
                                        </button>
                                    )}
                                </div>
                            </article>
                        )) : (
                            <div className="empty-state">No alerts yet.</div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
};

export default Watchlists;
