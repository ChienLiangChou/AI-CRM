import { useEffect, useState } from 'react';
import { agentsService } from '../../services/agents';
import { getApiErrorMessage } from '../../services/httpErrors';
import type {
    AgentAuditLog,
    AgentRun,
    TransactionPaperworkCanonicalDealFact,
    TransactionPaperworkEvidenceReference,
    TransactionPaperworkIntakeIssue,
    TransactionPaperworkLatestResponse,
    TransactionPaperworkMappedField,
    TransactionPaperworkOrchestrationResult,
    TransactionPaperworkQuestionItem,
    TransactionPaperworkRunRequest,
} from '../../services/agents';

const EMPTY_LATEST: TransactionPaperworkLatestResponse = {
    run_id: null,
    status: null,
    error: null,
    result: null,
};

type SourcePdfRow = {
    filePath: string;
    documentLabel: string;
};

type KevinAnswerRow = {
    fieldKey: string;
    value: string;
    notes: string;
};

const createEmptySourcePdfRow = (): SourcePdfRow => ({
    filePath: '',
    documentLabel: '',
});

const createEmptyKevinAnswerRow = (): KevinAnswerRow => ({
    fieldKey: '',
    value: '',
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

const getErrorMessage = getApiErrorMessage;

const formatAuditDetails = (value?: string) => {
    const parsed = parseJsonText(value);
    if (parsed) {
        return JSON.stringify(parsed, null, 2);
    }
    return value ?? '';
};

const formatTimestamp = (value?: string | null) => {
    if (!value) {
        return 'n/a';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }

    return parsed.toLocaleString();
};

const formatBytes = (value?: number | null) => {
    if (typeof value !== 'number' || value <= 0) {
        return 'n/a';
    }

    if (value < 1024) {
        return `${value} B`;
    }
    if (value < 1024 * 1024) {
        return `${(value / 1024).toFixed(1)} KB`;
    }
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

const humanizeEnum = (value: string) =>
    value
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');

const parseNotes = (value: string) =>
    value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean);

const formatConfidence = (value?: number | null) =>
    typeof value === 'number' ? value.toFixed(2) : 'n/a';

const renderListSection = (title: string, items: string[], emptyText: string) => (
    <section className="space-y-2">
        <h4 className="text-sm font-semibold text-gray-200">{title}</h4>
        {items.length === 0 ? (
            <div className="text-sm text-gray-500">{emptyText}</div>
        ) : (
            <div className="rounded border border-white/10 bg-black/10 p-3">
                <ul className="space-y-1 text-sm text-gray-200">
                    {items.map((item, index) => (
                        <li key={`${title}-${index}`}>{item}</li>
                    ))}
                </ul>
            </div>
        )}
    </section>
);

const renderEvidence = (evidence: TransactionPaperworkEvidenceReference[]) => {
    if (evidence.length === 0) {
        return <div className="text-xs text-gray-500">No evidence references recorded.</div>;
    }

    return (
        <div className="space-y-2">
            {evidence.map((entry, index) => (
                <div
                    key={`${entry.document_label ?? entry.evidence_anchor ?? 'evidence'}-${index}`}
                    className="rounded border border-white/10 bg-black/10 p-2 text-xs text-gray-300"
                >
                    <div>
                        {humanizeEnum(entry.source_doc_type)} · page {entry.source_page}
                        {entry.document_label ? ` · ${entry.document_label}` : ''}
                    </div>
                    {entry.evidence_anchor && <div>Anchor: {entry.evidence_anchor}</div>}
                    {entry.evidence_snippet && <div className="text-gray-400">{entry.evidence_snippet}</div>}
                </div>
            ))}
        </div>
    );
};

const renderIssueList = (issues: TransactionPaperworkIntakeIssue[]) => {
    if (issues.length === 0) {
        return <div className="text-sm text-gray-500">No intake issues recorded.</div>;
    }

    return (
        <div className="space-y-3">
            {issues.map((issue, index) => (
                <div
                    key={`${issue.document_label}-${issue.issue_code}-${index}`}
                    className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm"
                >
                    <div className="font-medium text-amber-100">
                        {issue.document_label} · {humanizeEnum(issue.issue_code)}
                    </div>
                    <div className="mt-1 text-amber-50/90">{issue.detail}</div>
                </div>
            ))}
        </div>
    );
};

const renderCanonicalFacts = (facts: TransactionPaperworkCanonicalDealFact[]) => {
    if (facts.length === 0) {
        return <div className="text-sm text-gray-500">No canonical deal facts were extracted.</div>;
    }

    return (
        <div className="space-y-3">
            {facts.map((fact) => (
                <div
                    key={`${fact.section_key}-${fact.field_key}`}
                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                >
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <div className="font-medium text-gray-100">{fact.label}</div>
                            <div className="text-xs text-gray-400">
                                {fact.section_key} · {fact.field_key}
                            </div>
                        </div>
                        <div className="text-xs text-gray-300">
                            {humanizeEnum(fact.confirmation_state)} · confidence {formatConfidence(fact.confidence)}
                        </div>
                    </div>
                    <div className="mt-2 text-sm text-gray-200">{fact.value || 'Unresolved'}</div>
                    {fact.notes.length > 0 && (
                        <div className="mt-2 text-xs text-gray-400">{fact.notes.join(' | ')}</div>
                    )}
                    {fact.evidence.length > 0 && (
                        <div className="mt-2">
                            {renderEvidence(fact.evidence)}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
};

const renderQuestions = (questions: TransactionPaperworkQuestionItem[]) => {
    if (questions.length === 0) {
        return <div className="text-sm text-gray-500">No Kevin confirmation questions are pending.</div>;
    }

    return (
        <div className="space-y-3">
            {questions.map((question) => (
                <div
                    key={`${question.field_key}-${question.reason}`}
                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                >
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <div className="font-medium text-gray-100">{question.field_key}</div>
                            <div className="text-xs text-gray-400">{humanizeEnum(question.reason)}</div>
                        </div>
                        <div className="text-xs text-gray-300">
                            {question.required ? 'Required' : 'Optional'}
                            {question.confidence !== null && question.confidence !== undefined
                                ? ` · confidence ${formatConfidence(question.confidence)}`
                                : ''}
                        </div>
                    </div>
                    <div className="mt-2 text-gray-200">{question.prompt}</div>
                    {question.suggested_value && (
                        <div className="mt-2 text-xs text-gray-300">
                            Suggested value: {question.suggested_value}
                        </div>
                    )}
                    {question.evidence.length > 0 && (
                        <div className="mt-2">
                            {renderEvidence(question.evidence)}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
};

const renderMappedFields = (mappedFields: Record<string, TransactionPaperworkMappedField>) => {
    const entries = Object.values(mappedFields);
    if (entries.length === 0) {
        return <div className="text-sm text-gray-500">No mapped review fields are available for this run.</div>;
    }

    return (
        <div className="space-y-3 max-h-[32rem] overflow-auto pr-1">
            {entries.map((field) => (
                <div
                    key={field.template_field_key}
                    className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                >
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <div className="font-medium text-gray-100">{field.label}</div>
                            <div className="text-xs text-gray-400">
                                {field.section_key} · {field.template_field_key}
                            </div>
                        </div>
                        <div className="text-xs text-gray-300">
                            {humanizeEnum(field.value_source_category)} · confidence {formatConfidence(field.confidence)}
                        </div>
                    </div>
                    <div className="mt-2 text-gray-200">{field.final_value || 'Unresolved'}</div>
                    <div className="mt-2 text-xs text-gray-400">
                        Confirmation: {humanizeEnum(field.confirmation_state)}
                        {field.requires_kevin_confirmation ? ' · Kevin confirmation required' : ''}
                    </div>
                    {field.traceability.final_value || field.traceability.source_page ? (
                        <div className="mt-2 text-xs text-gray-400">
                            Traceability:
                            {field.traceability.source_doc_type
                                ? ` ${humanizeEnum(field.traceability.source_doc_type)}`
                                : ''}
                            {field.traceability.source_page
                                ? ` · page ${field.traceability.source_page}`
                                : ''}
                            {field.traceability.transform_used
                                ? ` · ${field.traceability.transform_used}`
                                : ''}
                            {field.traceability.confirmed_by_kevin ? ' · Kevin confirmed' : ''}
                        </div>
                    ) : null}
                    {field.notes.length > 0 && (
                        <div className="mt-2 text-xs text-gray-400">{field.notes.join(' | ')}</div>
                    )}
                    {field.evidence.length > 0 && (
                        <div className="mt-2">
                            {renderEvidence(field.evidence)}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
};

const renderReport = (
    report: TransactionPaperworkOrchestrationResult,
    title: string,
    statusLine?: string | null,
) => {
    const artifact = report.render_result.artifact;

    return (
        <div className="border rounded p-3 space-y-4 bg-white/5">
            <section className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <h4 className="text-sm font-semibold text-gray-100">{title}</h4>
                        {statusLine && <div className="text-xs text-gray-400">{statusLine}</div>}
                    </div>
                    <div
                        className={`rounded border px-2 py-1 text-xs ${
                            report.output_status === 'rendered'
                                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                                : 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                        }`}
                    >
                        {humanizeEnum(report.output_status)}
                    </div>
                </div>
                <div className="grid gap-3 md:grid-cols-4">
                    <div className="rounded border border-white/10 bg-black/10 p-3">
                        <div className="text-xs text-gray-400">Review ready</div>
                        <div className="mt-1 text-sm font-medium text-white">
                            {report.review_package.review_ready ? 'Yes' : 'No'}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3">
                        <div className="text-xs text-gray-400">Blocking unresolved</div>
                        <div className="mt-1 text-sm font-medium text-white">
                            {report.review_package.blocking_unresolved_field_keys.length}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3">
                        <div className="text-xs text-gray-400">Rendered fields</div>
                        <div className="mt-1 text-sm font-medium text-white">
                            {report.render_result.rendered_field_count}
                        </div>
                    </div>
                    <div className="rounded border border-white/10 bg-black/10 p-3">
                        <div className="text-xs text-gray-400">Skipped unresolved</div>
                        <div className="mt-1 text-sm font-medium text-white">
                            {report.render_result.skipped_unresolved_field_count}
                        </div>
                    </div>
                </div>
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">PDF Intake</h4>
                {report.pdf_sources.length === 0 ? (
                    <div className="text-sm text-gray-500">No PDF source records were returned.</div>
                ) : (
                    <div className="space-y-3">
                        {report.pdf_sources.map((source) => (
                            <div
                                key={`${source.file_path}-${source.document_label}`}
                                className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                            >
                                <div className="flex items-start justify-between gap-3">
                                    <div>
                                        <div className="font-medium text-gray-100">{source.document_label}</div>
                                        <div className="text-xs text-gray-400">{source.file_name}</div>
                                    </div>
                                    <div className="text-xs text-gray-300">
                                        {humanizeEnum(source.load_status)} · {source.page_count} page(s)
                                    </div>
                                </div>
                                <div className="mt-2 text-xs text-gray-400 break-all">
                                    {source.file_path}
                                </div>
                                <div className="mt-2 text-xs text-gray-400">
                                    Extraction: {source.extraction_method} · Text present:{' '}
                                    {source.extracted_text_present ? 'Yes' : 'No'}
                                </div>
                                {source.notes.length > 0 && (
                                    <div className="mt-2 text-xs text-gray-400">{source.notes.join(' | ')}</div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Source Classification</h4>
                {report.preparation_result.source_documents.length === 0 ? (
                    <div className="text-sm text-gray-500">No source classification data is available.</div>
                ) : (
                    <div className="space-y-3">
                        {report.preparation_result.source_documents.map((source) => (
                            <div
                                key={`${source.document_label}-${source.file_name ?? 'document'}`}
                                className="rounded border border-white/10 bg-black/10 p-3 text-sm"
                            >
                                <div className="flex items-start justify-between gap-3">
                                    <div>
                                        <div className="font-medium text-gray-100">{source.document_label}</div>
                                        <div className="text-xs text-gray-400">
                                            {humanizeEnum(source.source_doc_type)}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-300">
                                        {source.supported ? 'Supported' : 'Unsupported'} · confidence {formatConfidence(source.confidence)}
                                    </div>
                                </div>
                                {source.classification_basis && (
                                    <div className="mt-2 text-xs text-gray-400">
                                        Classification basis: {source.classification_basis}
                                    </div>
                                )}
                                {source.notes.length > 0 && (
                                    <div className="mt-2 text-xs text-gray-400">{source.notes.join(' | ')}</div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Intake Issues</h4>
                {renderIssueList(report.preparation_result.intake_issues)}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Canonical Deal Facts</h4>
                {renderCanonicalFacts(report.preparation_result.canonical_deal_facts.facts)}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Kevin Question Packet</h4>
                {report.preparation_result.question_packet.blocking_field_keys.length > 0 && (
                    <div className="text-xs text-amber-200">
                        Blocking fields: {report.preparation_result.question_packet.blocking_field_keys.join(', ')}
                    </div>
                )}
                {renderQuestions(report.preparation_result.question_packet.questions)}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Review Package</h4>
                <div className="text-xs text-gray-400">
                    Template: {report.review_package.template_id} · {report.review_package.template_version}
                </div>
                {report.review_package.unresolved_field_keys.length > 0 && (
                    <div className="text-xs text-gray-400">
                        Unresolved fields: {report.review_package.unresolved_field_keys.join(', ')}
                    </div>
                )}
                {report.review_package.blocking_unresolved_field_keys.length > 0 && (
                    <div className="text-xs text-amber-200">
                        Blocking unresolved fields:{' '}
                        {report.review_package.blocking_unresolved_field_keys.join(', ')}
                    </div>
                )}
                {renderMappedFields(report.review_package.mapped_fields)}
            </section>

            <section className="space-y-2">
                <h4 className="text-sm font-semibold text-gray-200">Render Output</h4>
                <div className="rounded border border-white/10 bg-black/10 p-3 text-sm space-y-2">
                    <div className="text-gray-200">
                        Fill mode: {humanizeEnum(report.render_result.fill_mode)} · Output:{' '}
                        {humanizeEnum(report.render_result.output_status)}
                    </div>
                    <div className="text-xs text-gray-400">
                        Rendered fields: {report.render_result.rendered_field_count} · Skipped unresolved:{' '}
                        {report.render_result.skipped_unresolved_field_count}
                    </div>
                    {report.render_result.unresolved_blocking_field_keys.length > 0 && (
                        <div className="text-xs text-amber-200">
                            Blocking render fields:{' '}
                            {report.render_result.unresolved_blocking_field_keys.join(', ')}
                        </div>
                    )}
                    {report.render_result.rendered_field_keys.length > 0 && (
                        <div className="text-xs text-gray-400">
                            Rendered keys: {report.render_result.rendered_field_keys.join(', ')}
                        </div>
                    )}
                    {artifact && (
                        <div className="rounded border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-emerald-100 space-y-1">
                            <div className="font-medium">Rendered artifact</div>
                            <div className="break-all">{artifact.output_pdf_path}</div>
                            <div>
                                {formatBytes(artifact.file_size_bytes)} · {artifact.page_count} page(s)
                            </div>
                            <div className="break-all text-emerald-50/80">{artifact.checksum_sha256}</div>
                        </div>
                    )}
                </div>
            </section>

            {renderListSection(
                'Operator Notes',
                [
                    ...report.operator_notes,
                    ...report.preparation_result.operator_notes,
                    ...report.preparation_result.canonical_deal_facts.operator_notes,
                    ...report.preparation_result.question_packet.operator_notes,
                    ...report.review_package.operator_notes,
                    ...report.render_result.operator_notes,
                ],
                'No operator notes were recorded for this run.',
            )}
        </div>
    );
};

const TransactionPaperworkPanel = () => {
    const [sourcePdfs, setSourcePdfs] = useState<SourcePdfRow[]>([createEmptySourcePdfRow()]);
    const [kevinAnswers, setKevinAnswers] = useState<KevinAnswerRow[]>([]);

    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [latest, setLatest] = useState<TransactionPaperworkLatestResponse>(EMPTY_LATEST);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedReport, setSelectedReport] = useState<TransactionPaperworkOrchestrationResult | null>(null);
    const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [triggering, setTriggering] = useState(false);
    const [reportLoading, setReportLoading] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [reportError, setReportError] = useState<string | null>(null);
    const [auditError, setAuditError] = useState<string | null>(null);

    const isBusy = loading || refreshing;

    const loadSelectedRunData = async (runId: number) => {
        setReportLoading(true);
        setAuditLoading(true);
        setReportError(null);
        setAuditError(null);

        try {
            const [reportResult, auditResult] = await Promise.allSettled([
                agentsService.getTransactionPaperworkRunReport(runId),
                agentsService.getTransactionPaperworkRunAuditLogs(runId),
            ]);

            if (reportResult.status === 'fulfilled') {
                setSelectedReport(reportResult.value);
            } else {
                setSelectedReport(null);
                setReportError(
                    getErrorMessage(
                        reportResult.reason,
                        'Structured Transaction Paperwork report is unavailable for this run.',
                    ),
                );
            }

            if (auditResult.status === 'fulfilled') {
                setAuditLogs(auditResult.value);
            } else {
                setAuditLogs([]);
                setAuditError(
                    getErrorMessage(
                        auditResult.reason,
                        'Audit history is unavailable for this Transaction Paperwork run.',
                    ),
                );
            }
        } finally {
            setReportLoading(false);
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
            const [runsData, latestData] = await Promise.all([
                agentsService.getTransactionPaperworkRuns(),
                agentsService.getLatestTransactionPaperworkResult(),
            ]);
            setRuns(runsData);
            setLatest(latestData);

            const preferredRunId = runsData.some((run) => run.id === selectedRunId)
                ? selectedRunId
                : (runsData[0]?.id ?? latestData.run_id ?? null);
            setSelectedRunId(preferredRunId);

            if (preferredRunId !== null) {
                await loadSelectedRunData(preferredRunId);
            } else {
                setSelectedReport(null);
                setAuditLogs([]);
                setReportError(null);
                setAuditError(null);
            }
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Failed to load Transaction Paperwork data.'));
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
            setSelectedReport(null);
            setAuditLogs([]);
            setReportError(null);
            setAuditError(null);
            return;
        }

        void loadSelectedRunData(selectedRunId);
    }, [selectedRunId]);

    const handleSourcePdfChange = (
        index: number,
        field: keyof SourcePdfRow,
        value: string,
    ) => {
        setSourcePdfs((current) =>
            current.map((row, rowIndex) =>
                rowIndex === index ? { ...row, [field]: value } : row,
            ),
        );
    };

    const handleKevinAnswerChange = (
        index: number,
        field: keyof KevinAnswerRow,
        value: string,
    ) => {
        setKevinAnswers((current) =>
            current.map((row, rowIndex) =>
                rowIndex === index ? { ...row, [field]: value } : row,
            ),
        );
    };

    const sanitizePayload = (): TransactionPaperworkRunRequest => {
        return {
            source_pdfs: sourcePdfs
                .map((row) => ({
                    file_path: row.filePath.trim(),
                    document_label: row.documentLabel.trim() || undefined,
                }))
                .filter((row) => row.file_path),
            kevin_answer_packet: {
                answers: kevinAnswers
                    .map((row) => ({
                        field_key: row.fieldKey.trim(),
                        value: row.value.trim(),
                        notes: parseNotes(row.notes),
                    }))
                    .filter((row) => row.field_key && row.value),
            },
            template_id: 'trade_record_sheet',
            template_version: 'trade_record_sheet_blank_v1',
            requested_fill_mode: 'overlay_coordinates',
        };
    };

    const handleTrigger = async () => {
        const payload = sanitizePayload();

        if (payload.source_pdfs.length === 0) {
            setError('Add at least one backend-readable PDF file path before running Transaction Paperwork.');
            return;
        }

        setTriggering(true);
        setError(null);
        try {
            const run = await agentsService.triggerTransactionPaperworkRunOnce(payload);
            setSelectedRunId(run.id);
            await loadData('refresh');
        } catch (triggerError) {
            setError(getErrorMessage(triggerError, 'Failed to run Transaction Paperwork.'));
        } finally {
            setTriggering(false);
        }
    };

    const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;

    return (
        <section className="space-y-4 border border-fuchsia-500/20 rounded-lg p-4 bg-fuchsia-500/5">
            <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                    <h2 className="text-lg font-medium">Transaction Paperwork</h2>
                    <div className="text-sm text-gray-300">
                        Manual review workspace for Trade Record Sheet preparation. No filing, no submission, no sending, and no hidden automation.
                    </div>
                    <div className="text-xs text-gray-400">
                        v1 accepts backend-readable machine-readable PDF file paths only. Browser upload is not part of this step.
                    </div>
                </div>
                <button
                    onClick={() => void loadData('refresh')}
                    className="px-3 py-1.5 text-sm rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                    disabled={isBusy || triggering}
                >
                    {refreshing ? 'Refreshing...' : 'Refresh'}
                </button>
            </div>

            {error && (
                <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {error}
                </div>
            )}

            <div className="border rounded p-3 bg-white/5 space-y-4">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <div className="text-sm font-medium text-white">Manual Intake</div>
                        <div className="text-xs text-gray-400">
                            Fixed contract: `trade_record_sheet` + `trade_record_sheet_blank_v1` + `overlay_coordinates`
                        </div>
                    </div>
                    <div className="text-xs text-gray-400">
                        This flow creates no approvals in v1. Output stays in the review package, render result, and audit trail.
                    </div>
                </div>

                <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium text-gray-200">Source PDFs</div>
                        <button
                            type="button"
                            onClick={() => setSourcePdfs((current) => [...current, createEmptySourcePdfRow()])}
                            className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                            disabled={isBusy || triggering}
                        >
                            Add PDF
                        </button>
                    </div>
                    {sourcePdfs.map((row, index) => (
                        <div
                            key={`source-pdf-${index}`}
                            className="grid gap-3 md:grid-cols-[1fr_240px_auto]"
                        >
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">PDF file path</div>
                                <input
                                    value={row.filePath}
                                    onChange={(event) => handleSourcePdfChange(index, 'filePath', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-fuchsia-400"
                                    placeholder="/absolute/path/to/aps.pdf"
                                />
                            </label>
                            <label className="space-y-1 text-sm">
                                <div className="text-gray-300">Document label</div>
                                <input
                                    value={row.documentLabel}
                                    onChange={(event) => handleSourcePdfChange(index, 'documentLabel', event.target.value)}
                                    className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-fuchsia-400"
                                    placeholder="Downtown APS"
                                />
                            </label>
                            <div className="flex items-end">
                                <button
                                    type="button"
                                    onClick={() =>
                                        setSourcePdfs((current) =>
                                            current.length === 1
                                                ? [createEmptySourcePdfRow()]
                                                : current.filter((_, rowIndex) => rowIndex !== index),
                                        )
                                    }
                                    className="px-2 py-2 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering}
                                >
                                    Remove
                                </button>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium text-gray-200">Optional Kevin confirmations</div>
                        <button
                            type="button"
                            onClick={() => setKevinAnswers((current) => [...current, createEmptyKevinAnswerRow()])}
                            className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                            disabled={isBusy || triggering}
                        >
                            Add answer
                        </button>
                    </div>
                    {kevinAnswers.length === 0 ? (
                        <div className="text-sm text-gray-500">
                            Leave this empty for the first run if you want the question packet to surface unresolved blocking fields.
                        </div>
                    ) : (
                        kevinAnswers.map((row, index) => (
                            <div
                                key={`kevin-answer-${index}`}
                                className="grid gap-3 md:grid-cols-[180px_1fr_1fr_auto]"
                            >
                                <label className="space-y-1 text-sm">
                                    <div className="text-gray-300">Field key</div>
                                    <input
                                        value={row.fieldKey}
                                        onChange={(event) => handleKevinAnswerChange(index, 'fieldKey', event.target.value)}
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-fuchsia-400"
                                        placeholder="commission_amount"
                                    />
                                </label>
                                <label className="space-y-1 text-sm">
                                    <div className="text-gray-300">Confirmed value</div>
                                    <input
                                        value={row.value}
                                        onChange={(event) => handleKevinAnswerChange(index, 'value', event.target.value)}
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-fuchsia-400"
                                        placeholder="2.5%"
                                    />
                                </label>
                                <label className="space-y-1 text-sm">
                                    <div className="text-gray-300">Notes</div>
                                    <input
                                        value={row.notes}
                                        onChange={(event) => handleKevinAnswerChange(index, 'notes', event.target.value)}
                                        className="w-full rounded border border-white/10 bg-black/20 px-3 py-2 text-white outline-none focus:border-fuchsia-400"
                                        placeholder="Comma or newline separated"
                                    />
                                </label>
                                <div className="flex items-end">
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setKevinAnswers((current) =>
                                                current.filter((_, rowIndex) => rowIndex !== index),
                                            )
                                        }
                                        className="px-2 py-2 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                        disabled={isBusy || triggering}
                                    >
                                        Remove
                                    </button>
                                </div>
                            </div>
                        ))
                    )}
                </div>

                <div className="flex items-center justify-between gap-3">
                    <div className="text-xs text-gray-400">
                        Review-first only. Unsupported PDFs, missing files, unresolved commission questions, and other blocked states are expected to surface explicitly instead of silently passing.
                    </div>
                    <button
                        onClick={handleTrigger}
                        className="px-3 py-2 text-sm rounded bg-fuchsia-600 text-white hover:bg-fuchsia-700 disabled:opacity-60"
                        disabled={isBusy || triggering}
                    >
                        {triggering ? 'Running...' : 'Run Transaction Paperwork'}
                    </button>
                </div>
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Latest Result</h3>
                {latest.run_id === null ? (
                    <div className="text-sm text-gray-500">No Transaction Paperwork runs yet.</div>
                ) : latest.result ? (
                    renderReport(
                        latest.result,
                        `Latest run #${latest.run_id}`,
                        latest.status ? `Status: ${humanizeEnum(latest.status)}` : null,
                    )
                ) : (
                    <div className="rounded border border-white/10 bg-white/5 p-3 text-sm text-gray-300">
                        Latest run #{latest.run_id} is {humanizeEnum(latest.status || 'unknown')}.
                        {latest.error ? (
                            <span className="text-rose-200"> Error: {latest.error}</span>
                        ) : (
                            <span> Structured result is unavailable for this run.</span>
                        )}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Recent Runs</h3>
                {runs.length === 0 ? (
                    <div className="text-sm text-gray-500">No Transaction Paperwork runs yet.</div>
                ) : (
                    <div className="border rounded p-3 space-y-2 bg-white/5">
                        {runs.map((run) => (
                            <div
                                key={run.id}
                                className={`flex items-center justify-between gap-3 border-b border-gray-700/40 pb-2 last:border-b-0 ${
                                    selectedRunId === run.id ? 'rounded bg-white/5 px-2 py-1' : ''
                                }`}
                            >
                                <div>
                                    <div className="font-medium">
                                        Run #{run.id} - {humanizeEnum(run.status)}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        Created: {formatTimestamp(run.created_at)}
                                        {run.finished_at && <> · Finished: {formatTimestamp(run.finished_at)}</>}
                                    </div>
                                    {run.summary && <div className="text-xs text-gray-300">{run.summary}</div>}
                                    {run.error && <div className="text-xs text-rose-300">Error: {run.error}</div>}
                                </div>
                                <button
                                    onClick={() => setSelectedRunId(run.id)}
                                    className="px-2 py-1 text-xs rounded border border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    disabled={isBusy || triggering}
                                >
                                    {selectedRunId === run.id ? 'Inspecting' : 'Inspect'}
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Selected Run Report</h3>
                {selectedRun ? (
                    <div className="text-sm text-gray-400">
                        Inspecting run #{selectedRun.id} ({humanizeEnum(selectedRun.status)})
                    </div>
                ) : (
                    <div className="text-sm text-gray-500">
                        Select a run to inspect its report and audit history.
                    </div>
                )}
                {selectedRun?.error && (
                    <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                        Run failure reason: {selectedRun.error}
                    </div>
                )}
                {reportError && <div className="text-sm text-amber-300">{reportError}</div>}
                {reportLoading ? (
                    <div className="text-sm text-gray-400">Loading Transaction Paperwork report...</div>
                ) : selectedRunId === null ? null : selectedReport ? (
                    renderReport(selectedReport, `Selected run #${selectedRunId}`)
                ) : (
                    <div className="text-sm text-gray-500">
                        Structured report is unavailable for this run.
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <h3 className="text-base font-medium">Selected Run Audit History</h3>
                {auditError && <div className="text-sm text-amber-300">{auditError}</div>}
                {auditLoading ? (
                    <div className="text-sm text-gray-400">Loading audit history...</div>
                ) : selectedRunId === null ? null : auditLogs.length === 0 ? (
                    <div className="text-sm text-gray-500">No audit history found for this run.</div>
                ) : (
                    <div className="border rounded p-3 space-y-3 bg-white/5">
                        {auditLogs.map((log) => {
                            const renderedDetails = formatAuditDetails(log.details);
                            return (
                                <div key={log.id} className="border-b border-gray-700/40 pb-3 last:border-b-0">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-sm font-medium">{humanizeEnum(log.action)}</div>
                                        <div className="text-xs text-gray-400">
                                            {formatTimestamp(log.created_at)}
                                        </div>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-0.5">
                                        Actor: {log.actor_type}
                                    </div>
                                    {renderedDetails && (
                                        <pre className="mt-2 text-xs whitespace-pre-wrap bg-black/20 rounded p-2 overflow-auto">
                                            {renderedDetails}
                                        </pre>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
};

export default TransactionPaperworkPanel;
