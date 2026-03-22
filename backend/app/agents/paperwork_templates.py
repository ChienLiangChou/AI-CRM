from __future__ import annotations

import hashlib
from pathlib import Path

from . import schemas as agent_schemas


TRADE_RECORD_TEMPLATE_ID = "trade_record_sheet"
TRADE_RECORD_TEMPLATE_VERSION = "trade_record_sheet_blank_v1"
TRADE_RECORD_TEMPLATE_RELATIVE_PATH = (
    "backend/assets/paperwork_templates/trade_record_blank.pdf"
)


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    return _backend_root().parent


def _trade_record_template_path() -> Path:
    return _repo_root() / TRADE_RECORD_TEMPLATE_RELATIVE_PATH


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field(
    key: str,
    label: str,
    section_key: str,
    *,
    field_type: agent_schemas.TransactionPaperworkTemplateFieldType = "text",
    canonical_fact_keys: list[str] | None = None,
    requires_kevin_confirmation: bool = False,
    notes: list[str] | None = None,
) -> agent_schemas.TransactionPaperworkTemplateFieldDescriptor:
    return agent_schemas.TransactionPaperworkTemplateFieldDescriptor(
        key=key,
        label=label,
        section_key=section_key,
        field_type=field_type,
        canonical_fact_keys=canonical_fact_keys or [],
        requires_kevin_confirmation=requires_kevin_confirmation,
        notes=notes or [],
    )


def get_trade_record_sheet_template() -> agent_schemas.TransactionPaperworkTemplateMetadata:
    asset_path = _trade_record_template_path()
    checksum = _sha256_for_file(asset_path)

    sections = [
        agent_schemas.TransactionPaperworkTemplateSection(
            key="deal_summary",
            label="Deal Summary",
            fields=[
                _field(
                    "mls_number",
                    "MLS #",
                    "deal_summary",
                    canonical_fact_keys=["mls_number"],
                ),
                _field(
                    "property_address",
                    "Property",
                    "deal_summary",
                    canonical_fact_keys=["property_address"],
                ),
                _field(
                    "offer_date",
                    "Offer Date",
                    "deal_summary",
                    field_type="date",
                    canonical_fact_keys=["offer_date"],
                ),
                _field(
                    "closing_date",
                    "Closing Date",
                    "deal_summary",
                    field_type="date",
                    canonical_fact_keys=["closing_date"],
                ),
                _field(
                    "conditional_status",
                    "Conditional / Firm",
                    "deal_summary",
                    field_type="selection",
                    canonical_fact_keys=["conditional_status"],
                ),
                _field(
                    "firm_date",
                    "Firm Date",
                    "deal_summary",
                    field_type="date",
                    canonical_fact_keys=["firm_date"],
                ),
                _field(
                    "sale_type",
                    "Sale Type",
                    "deal_summary",
                    field_type="selection",
                    canonical_fact_keys=["sale_type"],
                ),
                _field(
                    "property_type",
                    "Property Type",
                    "deal_summary",
                    field_type="selection",
                    canonical_fact_keys=["property_type"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="client_information",
            label="Client Information",
            fields=[
                _field(
                    "client_primary_name",
                    "Primary Client Name",
                    "client_information",
                    canonical_fact_keys=["client_primary_name"],
                ),
                _field(
                    "client_secondary_name",
                    "Secondary Client Name",
                    "client_information",
                    canonical_fact_keys=["client_secondary_name"],
                ),
                _field(
                    "client_contact_details",
                    "Client Contact Details",
                    "client_information",
                    field_type="multiline",
                    canonical_fact_keys=["client_contact_details"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="solicitor_information",
            label="Solicitor Information",
            fields=[
                _field(
                    "buyer_solicitor_details",
                    "Buyer Solicitor Information",
                    "solicitor_information",
                    field_type="multiline",
                    canonical_fact_keys=["buyer_solicitor_details"],
                ),
                _field(
                    "seller_solicitor_details",
                    "Seller Solicitor Information",
                    "solicitor_information",
                    field_type="multiline",
                    canonical_fact_keys=["seller_solicitor_details"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="trust_information",
            label="Trust Information",
            fields=[
                _field(
                    "deposit_amount",
                    "Deposit / Trust Amount",
                    "trust_information",
                    field_type="currency",
                    canonical_fact_keys=["deposit_amount"],
                ),
                _field(
                    "deposit_holder",
                    "Trust Holder",
                    "trust_information",
                    canonical_fact_keys=["deposit_holder"],
                ),
                _field(
                    "trust_notes",
                    "Trust Notes",
                    "trust_information",
                    field_type="multiline",
                    canonical_fact_keys=["trust_notes"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="commission_information",
            label="Commission Information",
            fields=[
                _field(
                    "commission_amount",
                    "Commission",
                    "commission_information",
                    field_type="currency",
                    canonical_fact_keys=["commission_amount"],
                    requires_kevin_confirmation=True,
                    notes=["Commission-related fields must be Kevin-confirmed."],
                ),
                _field(
                    "commission_split",
                    "Split",
                    "commission_information",
                    canonical_fact_keys=["commission_split"],
                    requires_kevin_confirmation=True,
                    notes=["Commission-related fields must be Kevin-confirmed."],
                ),
                _field(
                    "referral_fee",
                    "Referral Fee",
                    "commission_information",
                    field_type="currency",
                    canonical_fact_keys=["referral_fee"],
                    requires_kevin_confirmation=True,
                    notes=["Commission-related fields must be Kevin-confirmed."],
                ),
                _field(
                    "marketing_fee",
                    "Marketing Fee",
                    "commission_information",
                    field_type="currency",
                    canonical_fact_keys=["marketing_fee"],
                    requires_kevin_confirmation=True,
                    notes=["Commission-related fields must be Kevin-confirmed."],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="other_brokerage_information",
            label="Other Brokerage Information",
            fields=[
                _field(
                    "cooperating_brokerage_name",
                    "Other Brokerage Name",
                    "other_brokerage_information",
                    canonical_fact_keys=["cooperating_brokerage_name"],
                ),
                _field(
                    "cooperating_brokerage_contact",
                    "Other Brokerage Contact",
                    "other_brokerage_information",
                    field_type="multiline",
                    canonical_fact_keys=["cooperating_brokerage_contact"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="freeman_agent_information",
            label="Freeman Agent Information",
            fields=[
                _field(
                    "freeman_agent_name",
                    "Freeman Agent Name",
                    "freeman_agent_information",
                    canonical_fact_keys=["freeman_agent_name"],
                ),
                _field(
                    "freeman_agent_contact",
                    "Freeman Agent Contact",
                    "freeman_agent_information",
                    field_type="multiline",
                    canonical_fact_keys=["freeman_agent_contact"],
                ),
            ],
        ),
        agent_schemas.TransactionPaperworkTemplateSection(
            key="additional_instructions",
            label="Additional Instructions",
            fields=[
                _field(
                    "additional_instructions",
                    "Additional Instructions",
                    "additional_instructions",
                    field_type="multiline",
                    canonical_fact_keys=["additional_instructions"],
                ),
            ],
        ),
    ]

    return agent_schemas.TransactionPaperworkTemplateMetadata(
        template_id=TRADE_RECORD_TEMPLATE_ID,
        display_name="Trade Record Sheet",
        template_version=TRADE_RECORD_TEMPLATE_VERSION,
        source_template_path=TRADE_RECORD_TEMPLATE_RELATIVE_PATH,
        source_template_checksum_sha256=checksum,
        preserve_original_layout=True,
        sections=sections,
        notes=[
            "This registry preserves the original template and does not redesign"
            " the form.",
            "Commission-related fields remain Kevin-confirmed only.",
        ],
    )


def get_supported_paperwork_templates() -> list[
    agent_schemas.TransactionPaperworkTemplateMetadata
]:
    return [get_trade_record_sheet_template()]


def get_paperwork_template_by_id(
    template_id: str,
) -> agent_schemas.TransactionPaperworkTemplateMetadata:
    if template_id != TRADE_RECORD_TEMPLATE_ID:
        raise KeyError(f"unsupported_paperwork_template:{template_id}")
    return get_trade_record_sheet_template()
