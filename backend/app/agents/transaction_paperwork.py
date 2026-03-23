from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import paperwork_templates, schemas as agent_schemas


PDFINFO_CANDIDATE_PATHS = (
    "/opt/homebrew/bin/pdfinfo",
    "pdfinfo",
)
SUPPORTED_SOURCE_DOC_TYPES = frozenset({"aps", "agreement_to_lease"})
LOW_CONFIDENCE_THRESHOLD = 0.85
DATE_INPUT_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


@dataclass(frozen=True)
class _FactSpec:
    field_key: str
    section_key: str
    label: str


@dataclass(frozen=True)
class _QuestionSpec:
    field_key: str
    prompt: str
    reason: agent_schemas.TransactionPaperworkQuestionReason


@dataclass(frozen=True)
class _ExtractionCandidate:
    field_key: str
    section_key: str
    label: str
    value: str
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType
    confidence: float
    evidence: agent_schemas.TransactionPaperworkEvidenceReference
    normalized_value: str
    notes: tuple[str, ...] = ()


FIELD_SPECS: dict[str, _FactSpec] = {
    "mls_number": _FactSpec("mls_number", "deal_summary", "MLS Number"),
    "property_address": _FactSpec(
        "property_address", "deal_summary", "Property Address"
    ),
    "offer_date": _FactSpec("offer_date", "deal_summary", "Offer Date"),
    "closing_date": _FactSpec("closing_date", "deal_summary", "Closing Date"),
    "occupancy_date": _FactSpec("occupancy_date", "deal_summary", "Occupancy Date"),
    "conditional_status": _FactSpec(
        "conditional_status", "deal_summary", "Conditional / Firm Status"
    ),
    "firm_date": _FactSpec("firm_date", "deal_summary", "Firm Date"),
    "sale_type": _FactSpec("sale_type", "deal_summary", "Transaction Type"),
    "client_primary_name": _FactSpec(
        "client_primary_name", "client_information", "Primary Client Name"
    ),
    "client_secondary_name": _FactSpec(
        "client_secondary_name", "client_information", "Secondary Client Name"
    ),
    "counterparty_primary_name": _FactSpec(
        "counterparty_primary_name",
        "client_information",
        "Primary Counterparty Name",
    ),
    "counterparty_secondary_name": _FactSpec(
        "counterparty_secondary_name",
        "client_information",
        "Secondary Counterparty Name",
    ),
    "sale_price_or_lease_rent": _FactSpec(
        "sale_price_or_lease_rent", "deal_summary", "Sale Price / Lease Rent"
    ),
    "deposit_amount": _FactSpec(
        "deposit_amount", "trust_information", "Deposit / Trust Amount"
    ),
    "deposit_holder": _FactSpec("deposit_holder", "trust_information", "Deposit Holder"),
    "client_solicitor_details": _FactSpec(
        "client_solicitor_details", "solicitor_information", "Client Solicitor Details"
    ),
    "counterparty_solicitor_details": _FactSpec(
        "counterparty_solicitor_details",
        "solicitor_information",
        "Counterparty Solicitor Details",
    ),
}
REQUIRED_FIELDS_BY_DOC_TYPE: dict[
    agent_schemas.TransactionPaperworkSourceDocType, tuple[str, ...]
] = {
    "aps": (
        "property_address",
        "offer_date",
        "closing_date",
        "client_primary_name",
        "counterparty_primary_name",
        "sale_price_or_lease_rent",
    ),
    "agreement_to_lease": (
        "property_address",
        "offer_date",
        "occupancy_date",
        "client_primary_name",
        "counterparty_primary_name",
        "sale_price_or_lease_rent",
    ),
}
COMMISSION_QUESTION_SPECS = (
    _QuestionSpec(
        "commission_amount",
        "Confirm the commission for this transaction.",
        "commission_confirmation_required",
    ),
    _QuestionSpec(
        "commission_split",
        "Confirm the split for this transaction.",
        "split_confirmation_required",
    ),
    _QuestionSpec(
        "referral_fee",
        "Confirm whether a referral fee applies to this transaction.",
        "referral_fee_confirmation_required",
    ),
    _QuestionSpec(
        "marketing_fee",
        "Confirm whether a marketing fee applies to this transaction.",
        "marketing_fee_confirmation_required",
    ),
)
DOCUMENT_CLASSIFICATION_RULES = (
    (
        "agreement_to_lease",
        re.compile(r"^(?:residential\s+)?agreement to lease\b", re.IGNORECASE),
    ),
    (
        "aps",
        re.compile(
            r"^(?:(?:form\s+\d+|orea)\s+)?agreement of purchase(?:\s*&\s*|\s+and\s+)sale\b",
            re.IGNORECASE,
        ),
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2].parent


def _absolute_template_path(relative_path: str) -> Path:
    return _repo_root() / relative_path


def _resolve_pdfinfo_command() -> str | None:
    for candidate in PDFINFO_CANDIDATE_PATHS:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return str(candidate_path)
    return None


def _parse_pdfinfo_output(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def inspect_registered_template(
    template: agent_schemas.TransactionPaperworkTemplateMetadata,
) -> agent_schemas.TransactionPaperworkTemplateInspection:
    absolute_path = _absolute_template_path(template.source_template_path)
    if not absolute_path.is_file():
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=False,
            inspection_method="file_check",
            overlay_fill_supported=False,
            notes=["Registered template asset is missing from the repo workspace."],
        )

    pdfinfo_command = _resolve_pdfinfo_command()
    if not pdfinfo_command:
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=True,
            inspection_method="file_check",
            overlay_fill_supported=True,
            ready_fill_modes=["overlay_coordinates"],
            notes=[
                "pdfinfo is unavailable, so form fillability could not be"
                " inspected.",
                "Overlay fill remains the safe fallback path.",
            ],
        )

    command = [pdfinfo_command, str(absolute_path)]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=True,
            inspection_method="pdfinfo",
            overlay_fill_supported=True,
            ready_fill_modes=["overlay_coordinates"],
            notes=[
                "pdfinfo inspection failed; overlay fill remains the safe"
                " fallback path.",
                completed.stderr.strip() or "pdfinfo returned a non-zero exit code.",
            ],
        )

    info = _parse_pdfinfo_output(completed.stdout)
    form_type = info.get("Form", "unknown")
    form_type_normalized = form_type.lower()
    native_field_fill_supported = form_type_normalized not in {"", "none", "unknown"}
    ready_fill_modes: list[agent_schemas.TransactionPaperworkTemplateFillMode] = []
    if native_field_fill_supported:
        ready_fill_modes.append("fill_pdf_fields")
    ready_fill_modes.append("overlay_coordinates")

    notes = []
    if native_field_fill_supported:
        notes.append(
            "Native PDF form fields are present; PDF field fill should be the"
            " preferred runtime path."
        )
    else:
        notes.append(
            "Native PDF form fields were not detected; coordinate-overlay is the"
            " safe runtime path for this template."
        )

    return agent_schemas.TransactionPaperworkTemplateInspection(
        template_id=template.template_id,
        display_name=template.display_name,
        template_version=template.template_version,
        source_template_path=template.source_template_path,
        source_template_checksum_sha256=template.source_template_checksum_sha256,
        template_present=True,
        inspection_method="pdfinfo",
        page_count=_parse_positive_int(info.get("Pages")),
        pdf_version=info.get("PDF version"),
        pdf_form_type=form_type,
        native_field_fill_supported=native_field_fill_supported,
        overlay_fill_supported=True,
        ready_fill_modes=ready_fill_modes,
        notes=notes,
    )


def inspect_paperwork_template(
    template_id: str,
) -> agent_schemas.TransactionPaperworkTemplateInspection:
    template = paperwork_templates.get_paperwork_template_by_id(template_id)
    return inspect_registered_template(template)


def inspect_trade_record_sheet_template() -> (
    agent_schemas.TransactionPaperworkTemplateInspection
):
    return inspect_registered_template(
        paperwork_templates.get_trade_record_sheet_template()
    )


def classify_source_document(
    document: agent_schemas.TransactionPaperworkSourceDocument,
) -> agent_schemas.TransactionPaperworkSourceDocumentIntake:
    pages = _document_pages(document)
    if not pages:
        return agent_schemas.TransactionPaperworkSourceDocumentIntake(
            document_label=document.document_label,
            file_name=document.file_name,
            source_doc_type="transaction_related_document",
            supported=False,
            notes=["Document has no extractable text for deterministic intake."],
        )

    leading_lines = [
        _normalize_whitespace(line)
        for line in "\n".join(page.text for page in pages if page.text).splitlines()
        if line.strip()
    ][:12]
    for line in leading_lines:
        for source_doc_type, pattern in DOCUMENT_CLASSIFICATION_RULES:
            match = pattern.search(line)
            if match:
                return agent_schemas.TransactionPaperworkSourceDocumentIntake(
                    document_label=document.document_label,
                    file_name=document.file_name,
                    source_doc_type=source_doc_type,
                    supported=True,
                    confidence=0.99,
                    classification_basis=match.group(0),
                )

    return agent_schemas.TransactionPaperworkSourceDocumentIntake(
        document_label=document.document_label,
        file_name=document.file_name,
        source_doc_type="transaction_related_document",
        supported=False,
        notes=[
            "Only APS and Agreement to Lease documents are supported in this"
            " deterministic extraction step."
        ],
    )


def prepare_transaction_paperwork_review(
    documents: list[agent_schemas.TransactionPaperworkSourceDocument],
) -> agent_schemas.TransactionPaperworkPreparationResult:
    source_documents: list[agent_schemas.TransactionPaperworkSourceDocumentIntake] = []
    intake_issues: list[agent_schemas.TransactionPaperworkIntakeIssue] = []
    operator_notes: list[str] = []
    extracted_candidates: dict[str, list[_ExtractionCandidate]] = {}
    commission_candidates: dict[str, list[_ExtractionCandidate]] = {}
    supported_doc_types: set[agent_schemas.TransactionPaperworkSourceDocType] = set()

    for document in documents:
        intake = classify_source_document(document)
        source_documents.append(intake)
        pages = _document_pages(document)
        if not pages:
            intake_issues.append(
                agent_schemas.TransactionPaperworkIntakeIssue(
                    document_label=document.document_label,
                    issue_code="missing_text",
                    detail=(
                        "Document could not be classified because no page text was"
                        " provided."
                    ),
                )
            )
            continue
        if not intake.supported:
            intake_issues.append(
                agent_schemas.TransactionPaperworkIntakeIssue(
                    document_label=document.document_label,
                    issue_code="unsupported_document_type",
                    detail=(
                        "Unsupported or unknown document type. Step 2 only accepts"
                        " APS and Agreement to Lease."
                    ),
                )
            )
            continue

        supported_doc_types.add(intake.source_doc_type)
        for candidate in _extract_document_candidates(document, intake):
            extracted_candidates.setdefault(candidate.field_key, []).append(candidate)
        for candidate in _extract_commission_candidates(document, intake):
            commission_candidates.setdefault(candidate.field_key, []).append(candidate)

    if intake_issues:
        operator_notes.append(
            "Unsupported or textless documents were ignored during deterministic"
            " extraction."
        )
    if not supported_doc_types:
        operator_notes.append(
            "No supported APS or Agreement to Lease documents were available for"
            " deterministic extraction."
        )

    canonical_deal_facts = _build_canonical_deal_facts(
        extracted_candidates=extracted_candidates,
        supported_doc_types=supported_doc_types,
    )
    question_packet = _build_question_packet(
        extracted_candidates=extracted_candidates,
        commission_candidates=commission_candidates,
        supported_doc_types=supported_doc_types,
        canonical_deal_facts=canonical_deal_facts,
    )

    return agent_schemas.TransactionPaperworkPreparationResult(
        source_documents=source_documents,
        canonical_deal_facts=canonical_deal_facts,
        question_packet=question_packet,
        intake_issues=intake_issues,
        operator_notes=operator_notes,
    )


def _parse_positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _document_pages(
    document: agent_schemas.TransactionPaperworkSourceDocument,
) -> list[agent_schemas.TransactionPaperworkSourcePage]:
    if document.pages:
        return [page for page in document.pages if page.text.strip()]
    if document.raw_text and document.raw_text.strip():
        return [
            agent_schemas.TransactionPaperworkSourcePage(
                page_number=1,
                text=document.raw_text,
            )
        ]
    return []


def _extract_document_candidates(
    document: agent_schemas.TransactionPaperworkSourceDocument,
    intake: agent_schemas.TransactionPaperworkSourceDocumentIntake,
) -> list[_ExtractionCandidate]:
    pages = _document_pages(document)
    source_doc_type = intake.source_doc_type
    candidates: list[_ExtractionCandidate] = []

    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "mls_number",
            [
                (
                    re.compile(
                        r"\bMLS(?:®)?\s*(?:No\.?|Number|#)?\s*[:\-]?\s*([A-Z0-9\-]{4,})",
                        re.IGNORECASE,
                    ),
                    0.98,
                )
            ],
        )
    )
    candidates.extend(
        _extract_property_address_candidates(document.document_label, source_doc_type, pages)
    )
    candidates.extend(
        _collect_labeled_date_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "offer_date",
            [
                (
                    re.compile(
                        r"\bOffer Date\b\s*[:\-]?\s*([A-Za-z0-9,\/\- ]+)",
                        re.IGNORECASE,
                    ),
                    0.96,
                )
            ],
        )
    )
    candidates.extend(
        _collect_labeled_date_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "closing_date",
            [
                (
                    re.compile(
                        r"\b(?:Closing|Completion) Date\b\s*[:\-]?\s*([A-Za-z0-9,\/\- ]+)",
                        re.IGNORECASE,
                    ),
                    0.96,
                )
            ],
        )
    )
    candidates.extend(
        _collect_labeled_date_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "occupancy_date",
            [
                (
                    re.compile(
                        r"\b(?:Occupancy|Commencement|Possession) Date\b\s*[:\-]?\s*([A-Za-z0-9,\/\- ]+)",
                        re.IGNORECASE,
                    ),
                    0.95,
                )
            ],
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "conditional_status",
            [
                (
                    re.compile(
                        r"\b(?:Conditional\s*/\s*Firm|Status)\b\s*[:\-]?\s*(Conditional|Firm)\b",
                        re.IGNORECASE,
                    ),
                    0.95,
                )
            ],
            value_transform=lambda raw: raw.strip().lower(),
        )
    )
    candidates.extend(
        _collect_phrase_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "conditional_status",
            [
                (
                    re.compile(r"\bthis (?:agreement|offer) is conditional\b", re.IGNORECASE),
                    "conditional",
                    0.9,
                ),
                (
                    re.compile(r"\bthis (?:agreement|offer) is firm\b", re.IGNORECASE),
                    "firm",
                    0.9,
                ),
            ],
        )
    )
    candidates.extend(
        _collect_labeled_date_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "firm_date",
            [
                (
                    re.compile(
                        r"\b(?:Firm Date|Condition Removal Date)\b\s*[:\-]?\s*([A-Za-z0-9,\/\- ]+)",
                        re.IGNORECASE,
                    ),
                    0.94,
                )
            ],
        )
    )
    candidates.extend(
        _derive_transaction_type_candidates(
            pages,
            document.document_label,
            source_doc_type,
            intake.classification_basis,
        )
    )
    candidates.extend(
        _extract_party_candidates(
            pages,
            document.document_label,
            source_doc_type,
            client_patterns=(
                r"Buyer(?:\(s\))?",
                r"Tenant(?:\(s\))?",
            ),
            counterparty_patterns=(
                r"Seller(?:\(s\))?",
                r"Landlord(?:\(s\))?",
            ),
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "sale_price_or_lease_rent",
            [
                (
                    re.compile(
                        r"\bPurchase Price\b\s*[:\-]?\s*(\$[0-9,\.\s]+)",
                        re.IGNORECASE,
                    ),
                    0.98,
                ),
                (
                    re.compile(
                        r"\b(?:Rent|Monthly Rent)\b\s*[:\-]?\s*(\$[0-9,\.\s]+(?:\s*/\s*month)?)",
                        re.IGNORECASE,
                    ),
                    0.98,
                ),
            ],
            value_transform=_normalize_currency_text,
            value_normalizer=_normalize_currency_text,
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "deposit_amount",
            [
                (
                    re.compile(
                        r"\bDeposit(?: Amount)?\b\s*[:\-]?\s*(\$[0-9,\.\s]+)",
                        re.IGNORECASE,
                    ),
                    0.96,
                )
            ],
            value_transform=_normalize_currency_text,
            value_normalizer=_normalize_currency_text,
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "deposit_holder",
            [
                (
                    re.compile(
                        r"\bDeposit Holder\b\s*[:\-]?\s*([^\n]+)",
                        re.IGNORECASE,
                    ),
                    0.95,
                ),
                (
                    re.compile(
                        r"\bHeld in trust by\b\s*[:\-]?\s*([^\n]+)",
                        re.IGNORECASE,
                    ),
                    0.93,
                ),
            ],
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "client_solicitor_details",
            [
                (
                    re.compile(
                        r"\b(?:Buyer's|Tenant's) Solicitor\b\s*[:\-]?\s*([^\n]+)",
                        re.IGNORECASE,
                    ),
                    0.95,
                )
            ],
        )
    )
    candidates.extend(
        _collect_labeled_value_candidates(
            pages,
            document.document_label,
            source_doc_type,
            "counterparty_solicitor_details",
            [
                (
                    re.compile(
                        r"\b(?:Seller's|Landlord's) Solicitor\b\s*[:\-]?\s*([^\n]+)",
                        re.IGNORECASE,
                    ),
                    0.95,
                )
            ],
        )
    )
    return candidates


def _extract_property_address_candidates(
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
) -> list[_ExtractionCandidate]:
    candidates = _collect_labeled_value_candidates(
        pages,
        document_label,
        source_doc_type,
        "property_address",
        [
            (
                re.compile(
                    r"\b(?:Property Address|Property|Municipal Address)\b\s*[:\-]?\s*([^\n]+)",
                    re.IGNORECASE,
                ),
                0.97,
            ),
            (
                re.compile(r"\bPremises\b\s*[:\-]?\s*([^\n]+)", re.IGNORECASE),
                0.78,
            ),
        ],
    )
    unit_candidates = _collect_labeled_value_candidates(
        pages,
        document_label,
        source_doc_type,
        "property_address",
        [
            (
                re.compile(r"\bUnit\b\s*[:\-]?\s*([A-Za-z0-9\-]+)", re.IGNORECASE),
                0.9,
            )
        ],
    )
    if not candidates or not unit_candidates:
        return candidates

    best_unit = unit_candidates[0]
    amended_candidates: list[_ExtractionCandidate] = []
    for candidate in candidates:
        if re.search(r"\bunit\b", candidate.value, re.IGNORECASE):
            amended_candidates.append(candidate)
            continue
        combined_value = f"{candidate.value}, Unit {best_unit.value}"
        amended_candidates.append(
            _ExtractionCandidate(
                field_key=candidate.field_key,
                section_key=candidate.section_key,
                label=candidate.label,
                value=combined_value,
                source_doc_type=candidate.source_doc_type,
                confidence=min(candidate.confidence, best_unit.confidence),
                evidence=candidate.evidence,
                normalized_value=_normalize_whitespace(combined_value).lower(),
                notes=("Unit was combined from a separately labeled field.",),
            )
        )
    return amended_candidates


def _extract_party_candidates(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    *,
    client_patterns: tuple[str, ...],
    counterparty_patterns: tuple[str, ...],
) -> list[_ExtractionCandidate]:
    candidates: list[_ExtractionCandidate] = []
    candidates.extend(
        _extract_named_parties(
            pages,
            document_label,
            source_doc_type,
            patterns=client_patterns,
            primary_field_key="client_primary_name",
            secondary_field_key="client_secondary_name",
        )
    )
    candidates.extend(
        _extract_named_parties(
            pages,
            document_label,
            source_doc_type,
            patterns=counterparty_patterns,
            primary_field_key="counterparty_primary_name",
            secondary_field_key="counterparty_secondary_name",
        )
    )
    return candidates


def _extract_named_parties(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    *,
    patterns: tuple[str, ...],
    primary_field_key: str,
    secondary_field_key: str,
) -> list[_ExtractionCandidate]:
    candidates: list[_ExtractionCandidate] = []
    pattern = re.compile(
        rf"^\s*(?:{'|'.join(patterns)})\s*[:\-]\s*([^\n]+)",
        re.IGNORECASE | re.MULTILINE,
    )
    for page in pages:
        for match in pattern.finditer(page.text):
            raw_value = _normalize_whitespace(match.group(1))
            names = _split_party_names(raw_value)
            if not names:
                continue
            primary = names[0]
            candidates.append(
                _candidate_from_match(
                    primary_field_key,
                    primary,
                    FIELD_SPECS[primary_field_key],
                    source_doc_type=source_doc_type,
                    document_label=document_label,
                    page_number=page.page_number,
                    match=match,
                    confidence=0.95,
                )
            )
            if len(names) > 1:
                secondary = " / ".join(names[1:])
                candidates.append(
                    _candidate_from_match(
                        secondary_field_key,
                        secondary,
                        FIELD_SPECS[secondary_field_key],
                        source_doc_type=source_doc_type,
                        document_label=document_label,
                        page_number=page.page_number,
                        match=match,
                        confidence=0.91,
                    )
                )
    return candidates


def _derive_transaction_type_candidates(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    classification_basis: str | None,
) -> list[_ExtractionCandidate]:
    if source_doc_type not in SUPPORTED_SOURCE_DOC_TYPES:
        return []
    label = "sale" if source_doc_type == "aps" else "lease"
    evidence = agent_schemas.TransactionPaperworkEvidenceReference(
        source_doc_type=source_doc_type,
        source_page=pages[0].page_number if pages else 1,
        evidence_anchor="Document Type",
        evidence_snippet=classification_basis,
        document_label=document_label,
    )
    return [
        _ExtractionCandidate(
            field_key="sale_type",
            section_key=FIELD_SPECS["sale_type"].section_key,
            label=FIELD_SPECS["sale_type"].label,
            value=label,
            source_doc_type=source_doc_type,
            confidence=1.0,
            evidence=evidence,
            normalized_value=label,
            notes=("Derived directly from the classified source document type.",),
        )
    ]


def _extract_commission_candidates(
    document: agent_schemas.TransactionPaperworkSourceDocument,
    intake: agent_schemas.TransactionPaperworkSourceDocumentIntake,
) -> list[_ExtractionCandidate]:
    pages = _document_pages(document)
    source_doc_type = intake.source_doc_type
    return _collect_labeled_value_candidates(
        pages,
        document.document_label,
        source_doc_type,
        "commission_amount",
        [
            (
                re.compile(
                    r"\bCommission\b\s*[:\-]?\s*([^\n]+)",
                    re.IGNORECASE,
                ),
                0.94,
            )
        ],
    ) + _collect_labeled_value_candidates(
        pages,
        document.document_label,
        source_doc_type,
        "commission_split",
        [
            (
                re.compile(
                    r"\b(?:Commission )?Split\b\s*[:\-]?\s*([^\n]+)",
                    re.IGNORECASE,
                ),
                0.94,
            )
        ],
    ) + _collect_labeled_value_candidates(
        pages,
        document.document_label,
        source_doc_type,
        "referral_fee",
        [
            (
                re.compile(
                    r"\bReferral Fee\b\s*[:\-]?\s*([^\n]+)",
                    re.IGNORECASE,
                ),
                0.94,
            )
        ],
    ) + _collect_labeled_value_candidates(
        pages,
        document.document_label,
        source_doc_type,
        "marketing_fee",
        [
            (
                re.compile(
                    r"\bMarketing Fee\b\s*[:\-]?\s*([^\n]+)",
                    re.IGNORECASE,
                ),
                0.94,
            )
        ],
    )


def _collect_labeled_date_candidates(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    field_key: str,
    patterns: list[tuple[re.Pattern[str], float]],
) -> list[_ExtractionCandidate]:
    return _collect_labeled_value_candidates(
        pages,
        document_label,
        source_doc_type,
        field_key,
        patterns,
        value_transform=_normalize_date_text,
    )


def _collect_phrase_candidates(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    field_key: str,
    patterns: list[tuple[re.Pattern[str], str, float]],
) -> list[_ExtractionCandidate]:
    spec = FIELD_SPECS[field_key]
    candidates: list[_ExtractionCandidate] = []
    for page in pages:
        for pattern, value, confidence in patterns:
            for match in pattern.finditer(page.text):
                candidates.append(
                    _candidate_from_match(
                        field_key,
                        value,
                        spec,
                        source_doc_type=source_doc_type,
                        document_label=document_label,
                        page_number=page.page_number,
                        match=match,
                        confidence=confidence,
                    )
                )
    return candidates


def _collect_labeled_value_candidates(
    pages: list[agent_schemas.TransactionPaperworkSourcePage],
    document_label: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    field_key: str,
    patterns: list[tuple[re.Pattern[str], float]],
    *,
    value_transform: Callable[[str], str | None] | None = None,
    value_normalizer: Callable[[str], str] | None = None,
) -> list[_ExtractionCandidate]:
    spec = FIELD_SPECS.get(field_key, _FactSpec(field_key, "deal_summary", field_key))
    candidates: list[_ExtractionCandidate] = []
    for page in pages:
        for pattern, confidence in patterns:
            for match in pattern.finditer(page.text):
                raw_value = match.group(1) if match.lastindex else match.group(0)
                value = _normalize_whitespace(raw_value)
                if value_transform is not None:
                    transformed = value_transform(value)
                    if not transformed:
                        continue
                    value = transformed
                normalized_value = (
                    value_normalizer(value)
                    if value_normalizer is not None
                    else value.lower()
                )
                candidates.append(
                    _candidate_from_match(
                        field_key,
                        value,
                        spec,
                        source_doc_type=source_doc_type,
                        document_label=document_label,
                        page_number=page.page_number,
                        match=match,
                        confidence=confidence,
                        normalized_value=normalized_value,
                    )
                )
    return candidates


def _build_canonical_deal_facts(
    *,
    extracted_candidates: dict[str, list[_ExtractionCandidate]],
    supported_doc_types: set[agent_schemas.TransactionPaperworkSourceDocType],
) -> agent_schemas.TransactionPaperworkCanonicalDealFacts:
    facts: list[agent_schemas.TransactionPaperworkCanonicalDealFact] = []
    unresolved_field_keys: list[str] = []
    operator_notes: list[str] = []

    for field_key, candidates in extracted_candidates.items():
        grouped = _group_candidates_by_value(candidates)
        if len(grouped) > 1:
            unresolved_field_keys.append(field_key)
            operator_notes.append(
                f"Conflicting deterministic values were detected for {field_key}."
            )
            continue

        if not grouped:
            continue

        group = next(iter(grouped.values()))
        best = max(group, key=lambda item: item.confidence)
        fact = agent_schemas.TransactionPaperworkCanonicalDealFact(
            field_key=best.field_key,
            section_key=best.section_key,
            label=best.label,
            value=best.value,
            source_doc_type=best.source_doc_type,
            confidence=best.confidence,
            confirmation_state=(
                "required"
                if best.confidence < LOW_CONFIDENCE_THRESHOLD
                else "not_required"
            ),
            requires_kevin_confirmation=best.confidence < LOW_CONFIDENCE_THRESHOLD,
            evidence=[item.evidence for item in group],
            notes=list(best.notes),
        )
        if best.confidence < LOW_CONFIDENCE_THRESHOLD:
            fact.notes.append("Low-confidence extraction; Kevin confirmation required.")
            unresolved_field_keys.append(field_key)
        facts.append(fact)

    for source_doc_type in sorted(supported_doc_types):
        for field_key in REQUIRED_FIELDS_BY_DOC_TYPE.get(source_doc_type, ()):
            if field_key not in {fact.field_key for fact in facts}:
                unresolved_field_keys.append(field_key)

    return agent_schemas.TransactionPaperworkCanonicalDealFacts(
        facts=facts,
        unresolved_field_keys=_dedupe_preserve_order(unresolved_field_keys),
        operator_notes=operator_notes,
    )


def _build_question_packet(
    *,
    extracted_candidates: dict[str, list[_ExtractionCandidate]],
    commission_candidates: dict[str, list[_ExtractionCandidate]],
    supported_doc_types: set[agent_schemas.TransactionPaperworkSourceDocType],
    canonical_deal_facts: agent_schemas.TransactionPaperworkCanonicalDealFacts,
) -> agent_schemas.TransactionPaperworkQuestionPacket:
    if not supported_doc_types:
        return agent_schemas.TransactionPaperworkQuestionPacket()

    questions: list[agent_schemas.TransactionPaperworkQuestionItem] = []
    blocking_field_keys = list(canonical_deal_facts.unresolved_field_keys)
    operator_notes: list[str] = []
    resolved_field_keys = {
        fact.field_key
        for fact in canonical_deal_facts.facts
        if fact.confirmation_state == "not_required"
    }

    for source_doc_type in sorted(supported_doc_types):
        for field_key in REQUIRED_FIELDS_BY_DOC_TYPE.get(source_doc_type, ()):
            candidates = extracted_candidates.get(field_key, [])
            grouped = _group_candidates_by_value(candidates)
            if len(grouped) > 1:
                questions.append(
                    _build_conflicting_field_question(field_key, candidates)
                )
                continue
            if field_key not in resolved_field_keys:
                if candidates:
                    questions.append(_build_low_confidence_field_question(candidates[0]))
                else:
                    questions.append(_build_missing_field_question(field_key, source_doc_type))

    for field_key, candidates in extracted_candidates.items():
        if field_key in REQUIRED_FIELDS_BY_DOC_TYPE.get("aps", ()) or field_key in REQUIRED_FIELDS_BY_DOC_TYPE.get("agreement_to_lease", ()):
            continue
        grouped = _group_candidates_by_value(candidates)
        if len(grouped) > 1:
            blocking_field_keys.append(field_key)
            questions.append(_build_conflicting_field_question(field_key, candidates))
            continue
        if not grouped:
            continue
        best = max(next(iter(grouped.values())), key=lambda item: item.confidence)
        if best.confidence < LOW_CONFIDENCE_THRESHOLD:
            blocking_field_keys.append(field_key)
            questions.append(_build_low_confidence_field_question(best))

    for question_spec in COMMISSION_QUESTION_SPECS:
        candidates = commission_candidates.get(question_spec.field_key, [])
        best_candidate = max(candidates, key=lambda item: item.confidence) if candidates else None
        questions.append(
            agent_schemas.TransactionPaperworkQuestionItem(
                field_key=question_spec.field_key,
                prompt=question_spec.prompt,
                reason=question_spec.reason,
                suggested_value=best_candidate.value if best_candidate else None,
                confidence=best_candidate.confidence if best_candidate else None,
                evidence=[item.evidence for item in candidates] if candidates else [],
            )
        )
        blocking_field_keys.append(question_spec.field_key)

    if commission_candidates:
        operator_notes.append(
            "Commission-related text was detected, but those fields remain Kevin-confirmed only."
        )

    return agent_schemas.TransactionPaperworkQuestionPacket(
        questions=_dedupe_questions(questions),
        blocking_field_keys=_dedupe_preserve_order(blocking_field_keys),
        operator_notes=operator_notes,
    )


def _build_missing_field_question(
    field_key: str,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
) -> agent_schemas.TransactionPaperworkQuestionItem:
    spec = FIELD_SPECS[field_key]
    document_label = (
        "APS" if source_doc_type == "aps" else "Agreement to Lease"
    )
    return agent_schemas.TransactionPaperworkQuestionItem(
        field_key=field_key,
        prompt=f"Provide or confirm the {spec.label.lower()} from the {document_label}.",
        reason="missing_field",
    )


def _build_low_confidence_field_question(
    candidate: _ExtractionCandidate,
) -> agent_schemas.TransactionPaperworkQuestionItem:
    return agent_schemas.TransactionPaperworkQuestionItem(
        field_key=candidate.field_key,
        prompt=(
            f"Confirm the extracted {candidate.label.lower()} before paperwork"
            " preparation continues."
        ),
        reason="low_confidence_field",
        suggested_value=candidate.value,
        confidence=candidate.confidence,
        evidence=[candidate.evidence],
    )


def _build_conflicting_field_question(
    field_key: str,
    candidates: list[_ExtractionCandidate],
) -> agent_schemas.TransactionPaperworkQuestionItem:
    spec = FIELD_SPECS[field_key]
    conflicting_values = sorted(
        {
            _normalize_whitespace(candidate.value)
            for candidate in candidates
            if candidate.value.strip()
        }
    )
    return agent_schemas.TransactionPaperworkQuestionItem(
        field_key=field_key,
        prompt=(
            f"Resolve the conflicting {spec.label.lower()} values: "
            + " | ".join(conflicting_values)
        ),
        reason="conflicting_field",
        evidence=[candidate.evidence for candidate in candidates],
    )


def _group_candidates_by_value(
    candidates: list[_ExtractionCandidate],
) -> dict[str, list[_ExtractionCandidate]]:
    grouped: dict[str, list[_ExtractionCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.normalized_value, []).append(candidate)
    return grouped


def _candidate_from_match(
    field_key: str,
    value: str,
    spec: _FactSpec,
    *,
    source_doc_type: agent_schemas.TransactionPaperworkSourceDocType,
    document_label: str,
    page_number: int,
    match: re.Match[str],
    confidence: float,
    normalized_value: str | None = None,
) -> _ExtractionCandidate:
    return _ExtractionCandidate(
        field_key=field_key,
        section_key=spec.section_key,
        label=spec.label,
        value=value,
        source_doc_type=source_doc_type,
        confidence=confidence,
        evidence=agent_schemas.TransactionPaperworkEvidenceReference(
            source_doc_type=source_doc_type,
            source_page=page_number,
            evidence_anchor=match.group(0).split(":", 1)[0].strip(),
            evidence_snippet=_snippet_for_match(match),
            document_label=document_label,
        ),
        normalized_value=normalized_value or value.lower(),
    )


def _split_party_names(raw_value: str) -> list[str]:
    cleaned = _normalize_whitespace(raw_value)
    if not cleaned:
        return []
    separators = re.compile(r"\s+(?:and|&)\s+|;\s*|,\s*(?=[A-Z][a-z])")
    names = [part.strip(" ,") for part in separators.split(cleaned) if part.strip(" ,")]
    return names or [cleaned]


def _normalize_date_text(raw_value: str) -> str | None:
    value = _normalize_whitespace(raw_value)
    value = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    value = value.replace(".", "")
    for date_format in DATE_INPUT_FORMATS:
        try:
            parsed = datetime.strptime(value, date_format)
        except ValueError:
            continue
        return parsed.date().isoformat()
    return None


def _normalize_currency_text(raw_value: str) -> str:
    value = _normalize_whitespace(raw_value)
    value = value.replace(" / ", "/")
    return value


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _snippet_for_match(match: re.Match[str]) -> str:
    snippet = match.group(0).strip()
    return _normalize_whitespace(snippet)[:240]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _dedupe_questions(
    questions: list[agent_schemas.TransactionPaperworkQuestionItem],
) -> list[agent_schemas.TransactionPaperworkQuestionItem]:
    deduped: list[agent_schemas.TransactionPaperworkQuestionItem] = []
    seen: set[tuple[str, str]] = set()
    for question in questions:
        key = (question.field_key, question.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(question)
    return deduped
