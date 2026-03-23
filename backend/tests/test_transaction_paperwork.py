import json
import hashlib
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app.agents import models as agent_models
from app.agents import paperwork_templates, schemas as agent_schemas
from app.agents import router as agent_router
from app.agents import transaction_paperwork
from app.database import Base


class TransactionPaperworkTemplateRegistryTests(unittest.TestCase):
    def test_trade_record_template_registry_is_tied_to_repo_asset(self):
        template = paperwork_templates.get_trade_record_sheet_template()
        expected_path = "backend/assets/paperwork_templates/trade_record_blank.pdf"
        asset_path = Path(__file__).resolve().parents[2] / expected_path

        self.assertEqual(template.template_id, "trade_record_sheet")
        self.assertEqual(template.template_version, "trade_record_sheet_blank_v1")
        self.assertEqual(template.source_template_path, expected_path)
        self.assertTrue(asset_path.is_file())

        expected_checksum = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        self.assertEqual(template.source_template_checksum_sha256, expected_checksum)
        self.assertTrue(template.preserve_original_layout)
        self.assertEqual(
            template.preferred_fill_order,
            ["fill_pdf_fields", "overlay_coordinates"],
        )

    def test_trade_record_template_registry_covers_expected_sections(self):
        template = paperwork_templates.get_trade_record_sheet_template()
        section_keys = [section.key for section in template.sections]

        self.assertEqual(
            section_keys,
            [
                "deal_summary",
                "client_information",
                "solicitor_information",
                "trust_information",
                "commission_information",
                "other_brokerage_information",
                "freeman_agent_information",
                "additional_instructions",
            ],
        )

    def test_commission_fields_require_kevin_confirmation(self):
        template = paperwork_templates.get_trade_record_sheet_template()
        commission_section = next(
            section
            for section in template.sections
            if section.key == "commission_information"
        )

        self.assertTrue(commission_section.fields)
        self.assertTrue(
            all(field.requires_kevin_confirmation for field in commission_section.fields)
        )


class TransactionPaperworkInspectionTests(unittest.TestCase):
    def test_trade_record_blank_template_is_overlay_ready(self):
        inspection = transaction_paperwork.inspect_trade_record_sheet_template()

        self.assertTrue(inspection.template_present)
        self.assertEqual(inspection.inspection_method, "pdfinfo")
        self.assertEqual(inspection.page_count, 1)
        self.assertEqual(inspection.pdf_version, "1.4")
        self.assertEqual(inspection.pdf_form_type, "none")
        self.assertFalse(inspection.native_field_fill_supported)
        self.assertTrue(inspection.overlay_fill_supported)
        self.assertEqual(inspection.ready_fill_modes, ["overlay_coordinates"])

    def test_fillability_detection_prefers_native_fields_when_pdfinfo_reports_form(self):
        template = paperwork_templates.get_trade_record_sheet_template()
        mocked_output = "\n".join(
            [
                "Form:            AcroForm",
                "Pages:           2",
                "PDF version:     1.7",
            ]
        )

        with patch(
            "app.agents.transaction_paperwork._resolve_pdfinfo_command",
            return_value="/opt/homebrew/bin/pdfinfo",
        ), patch(
            "app.agents.transaction_paperwork.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mocked_output
            mock_run.return_value.stderr = ""

            inspection = transaction_paperwork.inspect_registered_template(template)

        self.assertTrue(inspection.native_field_fill_supported)
        self.assertTrue(inspection.overlay_fill_supported)
        self.assertEqual(
            inspection.ready_fill_modes,
            ["fill_pdf_fields", "overlay_coordinates"],
        )
        self.assertEqual(inspection.pdf_form_type, "AcroForm")
        self.assertEqual(inspection.page_count, 2)
        self.assertEqual(inspection.pdf_version, "1.7")


class TransactionPaperworkSchemaContractTests(unittest.TestCase):
    def test_canonical_fact_contract_keeps_evidence_and_confirmation(self):
        fact = agent_schemas.TransactionPaperworkCanonicalDealFact(
            field_key="closing_date",
            section_key="deal_summary",
            label="Closing Date",
            value="2026-05-30",
            confidence=0.94,
            confirmation_state="required",
            evidence=[
                agent_schemas.TransactionPaperworkEvidenceReference(
                    source_doc_type="aps",
                    source_page=4,
                    evidence_anchor="Closing Date",
                    evidence_snippet="Completion date shall be May 30, 2026.",
                )
            ],
        )

        self.assertEqual(fact.field_key, "closing_date")
        self.assertEqual(fact.confirmation_state, "required")
        self.assertEqual(fact.evidence[0].source_doc_type, "aps")
        self.assertEqual(fact.evidence[0].source_page, 4)

    def test_traceability_and_question_packet_contracts_preserve_review_flags(self):
        trace = agent_schemas.TransactionPaperworkFieldTraceability(
            template_field_key="commission_amount",
            final_value="2.5%",
            source_doc_type="aps",
            source_page=2,
            evidence_anchor="Commission",
            evidence_snippet="Commission to be confirmed separately.",
            confidence=0.61,
            transform_used="normalized_percent_text",
            confirmed_by_kevin=True,
        )
        packet = agent_schemas.TransactionPaperworkQuestionPacket(
            questions=[
                agent_schemas.TransactionPaperworkQuestionItem(
                    field_key="commission_amount",
                    prompt="Confirm the commission for this transaction.",
                    reason="commission_confirmation_required",
                    suggested_value="2.5%",
                    confidence=0.61,
                    evidence=[
                        agent_schemas.TransactionPaperworkEvidenceReference(
                            source_doc_type="aps",
                            source_page=2,
                            evidence_anchor="Commission",
                            evidence_snippet=(
                                "Commission wording is present but should be"
                                " Kevin-confirmed."
                            ),
                        )
                    ],
                )
            ],
            blocking_field_keys=["commission_amount"],
        )

        self.assertTrue(trace.confirmed_by_kevin)
        self.assertEqual(packet.blocking_field_keys, ["commission_amount"])
        self.assertEqual(
            packet.questions[0].reason,
            "commission_confirmation_required",
        )


class TransactionPaperworkIntakeAndExtractionTests(unittest.TestCase):
    def build_document(
        self,
        document_label: str,
        *pages: str,
        file_name: str | None = None,
    ) -> agent_schemas.TransactionPaperworkSourceDocument:
        return agent_schemas.TransactionPaperworkSourceDocument(
            document_label=document_label,
            file_name=file_name,
            pages=[
                agent_schemas.TransactionPaperworkSourcePage(
                    page_number=index + 1,
                    text=text,
                )
                for index, text in enumerate(pages)
            ],
        )

    def fact_map(
        self,
        result: agent_schemas.TransactionPaperworkPreparationResult,
    ) -> dict[str, agent_schemas.TransactionPaperworkCanonicalDealFact]:
        return {fact.field_key: fact for fact in result.canonical_deal_facts.facts}

    def question_map(
        self,
        result: agent_schemas.TransactionPaperworkPreparationResult,
    ) -> dict[str, agent_schemas.TransactionPaperworkQuestionItem]:
        return {question.field_key: question for question in result.question_packet.questions}

    def test_prepare_review_extracts_high_value_aps_fields_and_commission_questions(self):
        document = self.build_document(
            "Downtown APS",
            "\n".join(
                [
                    "Agreement of Purchase and Sale",
                    "MLS Number: C1234567",
                    "Property Address: 123 King St W, Toronto, ON",
                    "Unit: 1102",
                    "Offer Date: March 1, 2026",
                    "Closing Date: May 30, 2026",
                    "Conditional / Firm: Conditional",
                    "Firm Date: March 5, 2026",
                    "Buyer: Alice Buyer and Bob Buyer",
                    "Seller: Sally Seller",
                    "Purchase Price: $1,250,000",
                    "Deposit: $50,000",
                    "Deposit Holder: Freeman Real Estate Ltd.",
                    "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                    "Seller's Solicitor: North Legal PC, 416-555-0199",
                    "Commission: 2.5% to co-operating brokerage",
                    "Commission Split: 50/50",
                    "Referral Fee: 15%",
                    "Marketing Fee: $500",
                ]
            ),
        )

        result = transaction_paperwork.prepare_transaction_paperwork_review([document])
        facts = self.fact_map(result)
        questions = self.question_map(result)

        self.assertEqual(len(result.source_documents), 1)
        self.assertEqual(result.source_documents[0].source_doc_type, "aps")
        self.assertTrue(result.source_documents[0].supported)

        self.assertEqual(facts["mls_number"].value, "C1234567")
        self.assertEqual(
            facts["property_address"].value,
            "123 King St W, Toronto, ON, Unit 1102",
        )
        self.assertEqual(facts["offer_date"].value, "2026-03-01")
        self.assertEqual(facts["closing_date"].value, "2026-05-30")
        self.assertEqual(facts["conditional_status"].value, "conditional")
        self.assertEqual(facts["firm_date"].value, "2026-03-05")
        self.assertEqual(facts["sale_type"].value, "sale")
        self.assertEqual(facts["client_primary_name"].value, "Alice Buyer")
        self.assertEqual(facts["client_secondary_name"].value, "Bob Buyer")
        self.assertEqual(facts["counterparty_primary_name"].value, "Sally Seller")
        self.assertEqual(facts["sale_price_or_lease_rent"].value, "$1,250,000")
        self.assertEqual(facts["deposit_amount"].value, "$50,000")
        self.assertEqual(facts["deposit_holder"].value, "Freeman Real Estate Ltd.")
        self.assertEqual(
            facts["client_solicitor_details"].value,
            "Hart Law LLP, 416-555-0100",
        )
        self.assertEqual(
            facts["counterparty_solicitor_details"].value,
            "North Legal PC, 416-555-0199",
        )
        self.assertEqual(facts["closing_date"].source_doc_type, "aps")
        self.assertEqual(
            facts["closing_date"].evidence[0].evidence_anchor,
            "Closing Date",
        )
        self.assertEqual(result.canonical_deal_facts.unresolved_field_keys, [])

        self.assertEqual(
            questions["commission_amount"].reason,
            "commission_confirmation_required",
        )
        self.assertEqual(
            questions["commission_amount"].suggested_value,
            "2.5% to co-operating brokerage",
        )
        self.assertEqual(questions["commission_split"].suggested_value, "50/50")
        self.assertEqual(questions["referral_fee"].suggested_value, "15%")
        self.assertEqual(questions["marketing_fee"].suggested_value, "$500")
        self.assertEqual(
            result.question_packet.blocking_field_keys,
            [
                "commission_amount",
                "commission_split",
                "referral_fee",
                "marketing_fee",
            ],
        )

    def test_prepare_review_extracts_agreement_to_lease_and_flags_low_confidence_fields(self):
        document = self.build_document(
            "Harbour Lease",
            "\n".join(
                [
                    "Residential Agreement to Lease",
                    "Premises: 88 Harbour St, Toronto, ON",
                    "Offer Date: April 2, 2026",
                    "Occupancy Date: June 1, 2026",
                    "Tenant: Terry Tenant",
                    "Landlord: Larry Landlord and Linda Landlord",
                    "Rent: $3,200 / month",
                    "Deposit Holder: Harbour Realty Inc.",
                    "Tenant's Solicitor: Tenant Counsel LLP",
                    "Landlord's Solicitor: Owner Counsel LLP",
                ]
            ),
        )

        result = transaction_paperwork.prepare_transaction_paperwork_review([document])
        facts = self.fact_map(result)
        questions = self.question_map(result)

        self.assertEqual(result.source_documents[0].source_doc_type, "agreement_to_lease")
        self.assertEqual(facts["sale_type"].value, "lease")
        self.assertEqual(facts["offer_date"].value, "2026-04-02")
        self.assertEqual(facts["occupancy_date"].value, "2026-06-01")
        self.assertEqual(facts["client_primary_name"].value, "Terry Tenant")
        self.assertEqual(facts["counterparty_primary_name"].value, "Larry Landlord")
        self.assertEqual(facts["counterparty_secondary_name"].value, "Linda Landlord")
        self.assertEqual(facts["sale_price_or_lease_rent"].value, "$3,200/month")
        self.assertEqual(facts["property_address"].value, "88 Harbour St, Toronto, ON")
        self.assertEqual(facts["property_address"].confirmation_state, "required")
        self.assertIn("property_address", result.canonical_deal_facts.unresolved_field_keys)
        self.assertEqual(questions["property_address"].reason, "low_confidence_field")
        self.assertEqual(
            questions["property_address"].suggested_value,
            "88 Harbour St, Toronto, ON",
        )
        self.assertEqual(
            questions["commission_amount"].reason,
            "commission_confirmation_required",
        )

    def test_prepare_review_reports_conflicting_fields_without_silently_filling(self):
        document = self.build_document(
            "Conflicting APS",
            "\n".join(
                [
                    "Agreement of Purchase and Sale",
                    "Property Address: 10 Front St E, Toronto, ON",
                    "Offer Date: March 1, 2026",
                    "Closing Date: May 30, 2026",
                    "Closing Date: June 5, 2026",
                    "Buyer: Alice Buyer",
                    "Seller: Sally Seller",
                    "Purchase Price: $950,000",
                ]
            ),
        )

        result = transaction_paperwork.prepare_transaction_paperwork_review([document])
        facts = self.fact_map(result)
        questions = self.question_map(result)

        self.assertNotIn("closing_date", facts)
        self.assertIn("closing_date", result.canonical_deal_facts.unresolved_field_keys)
        self.assertEqual(questions["closing_date"].reason, "conflicting_field")
        self.assertIn("2026-05-30", questions["closing_date"].prompt)
        self.assertIn("2026-06-05", questions["closing_date"].prompt)

    def test_prepare_review_fail_softs_for_unsupported_document_type(self):
        document = self.build_document(
            "Unsupported Notice",
            "\n".join(
                [
                    "Notice of Fulfillment",
                    "This document is not an APS or Agreement to Lease.",
                ]
            ),
        )

        result = transaction_paperwork.prepare_transaction_paperwork_review([document])

        self.assertFalse(result.source_documents[0].supported)
        self.assertEqual(
            result.intake_issues[0].issue_code,
            "unsupported_document_type",
        )
        self.assertEqual(result.canonical_deal_facts.facts, [])
        self.assertEqual(result.question_packet.questions, [])
        self.assertTrue(result.operator_notes)


class TransactionPaperworkReviewPackageTests(unittest.TestCase):
    def build_document(
        self,
        document_label: str,
        *pages: str,
    ) -> agent_schemas.TransactionPaperworkSourceDocument:
        return agent_schemas.TransactionPaperworkSourceDocument(
            document_label=document_label,
            pages=[
                agent_schemas.TransactionPaperworkSourcePage(
                    page_number=index + 1,
                    text=text,
                )
                for index, text in enumerate(pages)
            ],
        )

    def build_aps_document(self) -> agent_schemas.TransactionPaperworkSourceDocument:
        return self.build_document(
            "Downtown APS",
            "\n".join(
                [
                    "Agreement of Purchase and Sale",
                    "MLS Number: C1234567",
                    "Property Address: 123 King St W, Toronto, ON",
                    "Unit: 1102",
                    "Offer Date: March 1, 2026",
                    "Closing Date: May 30, 2026",
                    "Conditional / Firm: Conditional",
                    "Firm Date: March 5, 2026",
                    "Buyer: Alice Buyer and Bob Buyer",
                    "Seller: Sally Seller",
                    "Purchase Price: $1,250,000",
                    "Deposit: $50,000",
                    "Deposit Holder: Freeman Real Estate Ltd.",
                    "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                    "Seller's Solicitor: North Legal PC, 416-555-0199",
                    "Commission: 2.5% to co-operating brokerage",
                    "Commission Split: 50/50",
                    "Referral Fee: 15%",
                    "Marketing Fee: $500",
                ]
            ),
        )

    def build_lease_document(self) -> agent_schemas.TransactionPaperworkSourceDocument:
        return self.build_document(
            "Harbour Lease",
            "\n".join(
                [
                    "Residential Agreement to Lease",
                    "Premises: 88 Harbour St, Toronto, ON",
                    "Offer Date: April 2, 2026",
                    "Occupancy Date: June 1, 2026",
                    "Tenant: Terry Tenant",
                    "Landlord: Larry Landlord and Linda Landlord",
                    "Rent: $3,200 / month",
                    "Deposit Holder: Harbour Realty Inc.",
                    "Tenant's Solicitor: Tenant Counsel LLP",
                    "Landlord's Solicitor: Owner Counsel LLP",
                ]
            ),
        )

    def build_conflicting_aps_document(
        self,
    ) -> agent_schemas.TransactionPaperworkSourceDocument:
        return self.build_document(
            "Conflicting APS",
            "\n".join(
                [
                    "Agreement of Purchase and Sale",
                    "Property Address: 10 Front St E, Toronto, ON",
                    "Offer Date: March 1, 2026",
                    "Closing Date: May 30, 2026",
                    "Closing Date: June 5, 2026",
                    "Buyer: Alice Buyer",
                    "Seller: Sally Seller",
                    "Purchase Price: $950,000",
                ]
            ),
        )

    def build_answers(
        self,
        **values: str,
    ) -> agent_schemas.TransactionPaperworkKevinAnswerPacket:
        return agent_schemas.TransactionPaperworkKevinAnswerPacket(
            answers=[
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key=field_key,
                    value=value,
                )
                for field_key, value in values.items()
            ]
        )

    def build_review_package(
        self,
        document: agent_schemas.TransactionPaperworkSourceDocument,
        answers: agent_schemas.TransactionPaperworkKevinAnswerPacket | None = None,
    ) -> agent_schemas.TransactionPaperworkReviewPackage:
        prep = transaction_paperwork.prepare_transaction_paperwork_review([document])
        return transaction_paperwork.build_trade_record_review_package(prep, answers)

    def test_aps_trade_record_mapping_autofills_supported_fields_but_not_commission(self):
        review = self.build_review_package(self.build_aps_document())

        self.assertEqual(review.template_id, "trade_record_sheet")
        self.assertEqual(
            review.mapped_fields["property_address"].value_source_category,
            "auto_extracted",
        )
        self.assertEqual(
            review.mapped_fields["property_address"].final_value,
            "123 King St W, Toronto, ON, Unit 1102",
        )
        self.assertEqual(
            review.mapped_fields["buyer_solicitor_details"].final_value,
            "Hart Law LLP, 416-555-0100",
        )
        self.assertEqual(
            review.mapped_fields["seller_solicitor_details"].final_value,
            "North Legal PC, 416-555-0199",
        )
        self.assertEqual(
            review.mapped_fields["commission_amount"].value_source_category,
            "unresolved",
        )
        self.assertFalse(review.review_ready)
        self.assertEqual(
            review.blocking_unresolved_field_keys,
            [
                "commission_amount",
                "commission_split",
                "referral_fee",
                "marketing_fee",
            ],
        )

    def test_kevin_confirmed_commission_merge_preserves_traceability_and_unlocks_review_ready(self):
        review = self.build_review_package(
            self.build_aps_document(),
            self.build_answers(
                commission_amount="2.5%",
                commission_split="50/50",
                referral_fee="15%",
                marketing_fee="$500",
            ),
        )

        commission = review.mapped_fields["commission_amount"]
        self.assertEqual(commission.final_value, "2.5%")
        self.assertEqual(commission.value_source_category, "kevin_confirmed")
        self.assertEqual(commission.confirmation_state, "confirmed")
        self.assertTrue(commission.traceability.confirmed_by_kevin)
        self.assertEqual(commission.traceability.transform_used, "kevin_confirmed_merge")
        self.assertTrue(commission.evidence)
        self.assertIn("Commission", commission.evidence[0].evidence_snippet)
        self.assertTrue(review.review_ready)
        self.assertEqual(review.blocking_unresolved_field_keys, [])

    def test_agreement_to_lease_mapping_keeps_low_confidence_property_unresolved(self):
        review = self.build_review_package(self.build_lease_document())

        self.assertEqual(review.mapped_fields["offer_date"].final_value, "2026-04-02")
        self.assertEqual(review.mapped_fields["sale_type"].final_value, "lease")
        self.assertEqual(
            review.mapped_fields["buyer_solicitor_details"].final_value,
            "Tenant Counsel LLP",
        )
        self.assertEqual(
            review.mapped_fields["seller_solicitor_details"].final_value,
            "Owner Counsel LLP",
        )
        self.assertIsNone(review.mapped_fields["property_address"].final_value)
        self.assertEqual(
            review.mapped_fields["property_address"].value_source_category,
            "unresolved",
        )
        self.assertIn("property_address", review.blocking_unresolved_field_keys)
        self.assertFalse(review.review_ready)

    def test_kevin_can_resolve_low_confidence_overlap_fields_without_filling_optional_blanks(self):
        review = self.build_review_package(
            self.build_lease_document(),
            self.build_answers(
                property_address="88 Harbour St, Toronto, ON",
                commission_amount="n/a",
                commission_split="n/a",
                referral_fee="none",
                marketing_fee="none",
            ),
        )

        self.assertEqual(
            review.mapped_fields["property_address"].value_source_category,
            "kevin_confirmed",
        )
        self.assertEqual(
            review.mapped_fields["property_address"].final_value,
            "88 Harbour St, Toronto, ON",
        )
        self.assertIn("closing_date", review.unresolved_field_keys)
        self.assertNotIn("closing_date", review.blocking_unresolved_field_keys)
        self.assertTrue(review.review_ready)

    def test_conflicting_fields_remain_unresolved_until_explicitly_answered(self):
        review = self.build_review_package(self.build_conflicting_aps_document())

        self.assertIsNone(review.mapped_fields["closing_date"].final_value)
        self.assertEqual(
            review.mapped_fields["closing_date"].value_source_category,
            "unresolved",
        )
        self.assertIn("closing_date", review.blocking_unresolved_field_keys)
        self.assertIn(
            "conflicting_field",
            " ".join(review.mapped_fields["closing_date"].notes),
        )


class TransactionPaperworkOverlayRenderTests(unittest.TestCase):
    def build_document(
        self,
        document_label: str,
        *pages: str,
    ) -> agent_schemas.TransactionPaperworkSourceDocument:
        return agent_schemas.TransactionPaperworkSourceDocument(
            document_label=document_label,
            pages=[
                agent_schemas.TransactionPaperworkSourcePage(
                    page_number=index + 1,
                    text=text,
                )
                for index, text in enumerate(pages)
            ],
        )

    def build_aps_document(self) -> agent_schemas.TransactionPaperworkSourceDocument:
        return self.build_document(
            "Downtown APS",
            "\n".join(
                [
                    "Agreement of Purchase and Sale",
                    "MLS Number: C1234567",
                    "Property Address: 123 King St W, Toronto, ON",
                    "Unit: 1102",
                    "Offer Date: March 1, 2026",
                    "Closing Date: May 30, 2026",
                    "Conditional / Firm: Conditional",
                    "Firm Date: March 5, 2026",
                    "Buyer: Alice Buyer and Bob Buyer",
                    "Seller: Sally Seller",
                    "Purchase Price: $1,250,000",
                    "Deposit: $50,000",
                    "Deposit Holder: Freeman Real Estate Ltd.",
                    "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                    "Seller's Solicitor: North Legal PC, 416-555-0199",
                    "Commission: 2.5% to co-operating brokerage",
                    "Commission Split: 50/50",
                    "Referral Fee: 15%",
                    "Marketing Fee: $500",
                ]
            ),
        )

    def build_answers(self) -> agent_schemas.TransactionPaperworkKevinAnswerPacket:
        return agent_schemas.TransactionPaperworkKevinAnswerPacket(
            answers=[
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_amount",
                    value="2.5%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_split",
                    value="50/50",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="referral_fee",
                    value="15%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="marketing_fee",
                    value="$500",
                ),
            ]
        )

    def build_review_package(
        self,
        answers: agent_schemas.TransactionPaperworkKevinAnswerPacket | None = None,
    ) -> agent_schemas.TransactionPaperworkReviewPackage:
        prep = transaction_paperwork.prepare_transaction_paperwork_review(
            [self.build_aps_document()]
        )
        return transaction_paperwork.build_trade_record_review_package(prep, answers)

    def test_review_ready_package_renders_overlay_draft_and_preserves_page_count(self):
        review = self.build_review_package(self.build_answers())
        template_reader = PdfReader(
            paperwork_templates._trade_record_template_path()  # type: ignore[attr-defined]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transaction_paperwork.render_trade_record_review_draft(
                review,
                output_dir=temp_dir,
            )

            self.assertEqual(result.output_status, "rendered")
            self.assertIsNotNone(result.artifact)
            self.assertEqual(result.fill_mode, "overlay_coordinates")
            self.assertEqual(result.artifact.page_count, len(template_reader.pages))
            self.assertTrue(Path(result.artifact.output_pdf_path).is_file())
            self.assertGreater(result.rendered_field_count, 0)
            self.assertEqual(
                result.rendered_field_count,
                len(result.rendered_field_keys),
            )
            rendered_reader = PdfReader(result.artifact.output_pdf_path)
            self.assertEqual(
                float(rendered_reader.pages[0].mediabox.width),
                float(template_reader.pages[0].mediabox.width),
            )
            self.assertEqual(
                float(rendered_reader.pages[0].mediabox.height),
                float(template_reader.pages[0].mediabox.height),
            )
            rendered_text = "\n".join(
                page.extract_text() or "" for page in rendered_reader.pages
            )
            self.assertIn("Alice Buyer", rendered_text)
            self.assertIn("C1234567", rendered_text)
            self.assertIn("2.5%", rendered_text)
            self.assertIn("$500", rendered_text)
            self.assertEqual(
                result.traceability_by_field_key["commission_amount"].transform_used,
                "kevin_confirmed_merge",
            )

    def test_blocked_package_does_not_render_formal_draft(self):
        review = self.build_review_package()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transaction_paperwork.render_trade_record_review_draft(
                review,
                output_dir=temp_dir,
            )

            self.assertEqual(result.output_status, "blocked")
            self.assertIsNone(result.artifact)
            self.assertEqual(result.rendered_field_count, 0)
            self.assertIn("commission_amount", result.unresolved_blocking_field_keys)
            self.assertIn("commission_split", result.unresolved_blocking_field_keys)
            self.assertEqual(result.rendered_field_keys, [])
            self.assertTrue(
                any("blocked" in note.lower() for note in result.operator_notes)
            )


class TransactionPaperworkPdfOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if shutil.which("/opt/homebrew/bin/pdftotext") is None and shutil.which(
            "pdftotext"
        ) is None:
            raise unittest.SkipTest("pdftotext is unavailable")

    def create_pdf(
        self,
        output_path: Path,
        *pages: list[str],
    ) -> Path:
        pdf = canvas.Canvas(str(output_path))
        for index, lines in enumerate(pages):
            y = 760
            for line in lines:
                pdf.drawString(72, y, line)
                y -= 16
            if index < len(pages) - 1:
                pdf.showPage()
        pdf.save()
        return output_path

    def build_aps_pdf(self, output_path: Path) -> Path:
        return self.create_pdf(
            output_path,
            [
                "Agreement of Purchase and Sale",
                "MLS Number: C1234567",
                "Property Address: 123 King St W, Toronto, ON",
                "Unit: 1102",
                "Offer Date: March 1, 2026",
                "Closing Date: May 30, 2026",
                "Conditional / Firm: Conditional",
                "Firm Date: March 5, 2026",
                "Buyer: Alice Buyer and Bob Buyer",
                "Seller: Sally Seller",
                "Purchase Price: $1,250,000",
                "Deposit: $50,000",
                "Deposit Holder: Freeman Real Estate Ltd.",
                "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                "Seller's Solicitor: North Legal PC, 416-555-0199",
                "Commission: 2.5% to co-operating brokerage",
                "Commission Split: 50/50",
                "Referral Fee: 15%",
                "Marketing Fee: $500",
            ],
        )

    def build_lease_pdf(self, output_path: Path) -> Path:
        return self.create_pdf(
            output_path,
            [
                "Residential Agreement to Lease",
                "Premises: 88 Harbour St, Toronto, ON",
                "Offer Date: April 2, 2026",
                "Occupancy Date: June 1, 2026",
                "Tenant: Terry Tenant",
                "Landlord: Larry Landlord and Linda Landlord",
                "Rent: $3,200 / month",
                "Deposit Holder: Harbour Realty Inc.",
                "Tenant's Solicitor: Tenant Counsel LLP",
                "Landlord's Solicitor: Owner Counsel LLP",
            ],
        )

    def build_answers(self) -> agent_schemas.TransactionPaperworkKevinAnswerPacket:
        return agent_schemas.TransactionPaperworkKevinAnswerPacket(
            answers=[
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_amount",
                    value="2.5%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_split",
                    value="50/50",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="referral_fee",
                    value="15%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="marketing_fee",
                    value="$500",
                ),
            ]
        )

    def test_machine_readable_aps_pdf_intake_extracts_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            source_result, source_document, issues = (
                transaction_paperwork.load_transaction_paperwork_source_pdf(pdf_path)
            )

            self.assertEqual(source_result.load_status, "loaded")
            self.assertEqual(source_result.file_name, "aps.pdf")
            self.assertTrue(source_result.extracted_text_present)
            self.assertGreaterEqual(source_result.page_count, 1)
            self.assertEqual(issues, [])
            self.assertIsNotNone(source_document)
            self.assertIn("Agreement of Purchase and Sale", source_document.pages[0].text)
            self.assertIn("MLS Number: C1234567", source_document.pages[0].text)

    def test_machine_readable_agreement_to_lease_pdf_flows_into_supported_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_lease_pdf(Path(temp_dir) / "lease.pdf")

            result = transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs(
                [pdf_path],
                render_output_dir=temp_dir,
            )

            self.assertEqual(result.pdf_sources[0].load_status, "loaded")
            self.assertEqual(
                result.preparation_result.source_documents[0].source_doc_type,
                "agreement_to_lease",
            )
            fact_map = {
                fact.field_key: fact
                for fact in result.preparation_result.canonical_deal_facts.facts
            }
            self.assertEqual(fact_map["sale_type"].value, "lease")
            self.assertEqual(fact_map["occupancy_date"].value, "2026-06-01")
            self.assertEqual(result.output_status, "blocked")

    def test_textless_pdf_fail_softs_without_source_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "textless.pdf"
            pdf = canvas.Canvas(str(pdf_path))
            pdf.showPage()
            pdf.save()

            source_result, source_document, issues = (
                transaction_paperwork.load_transaction_paperwork_source_pdf(pdf_path)
            )

            self.assertEqual(source_result.load_status, "blocked")
            self.assertFalse(source_result.extracted_text_present)
            self.assertIsNone(source_document)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].issue_code, "textless_pdf")

    def test_unsupported_pdf_fail_softs_through_orchestration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.create_pdf(
                Path(temp_dir) / "unsupported.pdf",
                [
                    "Notice of Fulfillment",
                    "This document is not an APS or Agreement to Lease.",
                ],
            )

            result = transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs(
                [pdf_path],
                render_output_dir=temp_dir,
            )

            self.assertEqual(result.pdf_sources[0].load_status, "loaded")
            self.assertFalse(result.preparation_result.source_documents[0].supported)
            self.assertEqual(
                result.preparation_result.intake_issues[0].issue_code,
                "unsupported_document_type",
            )
            self.assertEqual(result.output_status, "blocked")
            self.assertIsNone(result.render_result.artifact)

    def test_blocked_orchestration_does_not_render_without_kevin_confirmations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            result = transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs(
                [pdf_path],
                render_output_dir=temp_dir,
            )

            self.assertEqual(result.output_status, "blocked")
            self.assertFalse(result.review_package.review_ready)
            self.assertEqual(result.render_result.output_status, "blocked")
            self.assertIsNone(result.render_result.artifact)
            self.assertEqual(
                result.review_package.blocking_unresolved_field_keys,
                [
                    "commission_amount",
                    "commission_split",
                    "referral_fee",
                    "marketing_fee",
                ],
            )

    def test_rendered_orchestration_builds_review_package_and_overlay_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            result = transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs(
                [pdf_path],
                kevin_answers=self.build_answers(),
                render_output_dir=temp_dir,
            )

            self.assertEqual(result.output_status, "rendered")
            self.assertTrue(result.review_package.review_ready)
            self.assertEqual(result.render_result.output_status, "rendered")
            self.assertIsNotNone(result.render_result.artifact)
            self.assertTrue(Path(result.render_result.artifact.output_pdf_path).is_file())
            self.assertEqual(
                result.render_result.template_id,
                result.review_package.template_id,
            )
            self.assertEqual(
                result.render_result.template_version,
                result.review_package.template_version,
            )
            self.assertEqual(
                result.render_result.rendered_field_count,
                len(result.render_result.rendered_field_keys),
            )
            self.assertEqual(
                result.render_result.traceability_by_field_key[
                    "commission_amount"
                ].transform_used,
                "kevin_confirmed_merge",
            )
            rendered_reader = PdfReader(result.render_result.artifact.output_pdf_path)
            rendered_text = "\n".join(
                page.extract_text() or "" for page in rendered_reader.pages
            )
            self.assertIn("Alice Buyer", rendered_text)
            self.assertIn("2.5%", rendered_text)
            self.assertIn("$500", rendered_text)


class TransactionPaperworkRunnerPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if shutil.which("/opt/homebrew/bin/pdftotext") is None and shutil.which(
            "pdftotext"
        ) is None:
            raise unittest.SkipTest("pdftotext is unavailable")

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_pdf(
        self,
        output_path: Path,
        *pages: list[str],
    ) -> Path:
        pdf = canvas.Canvas(str(output_path))
        if not pages:
            pdf.showPage()
            pdf.save()
            return output_path
        for index, lines in enumerate(pages):
            y = 760
            for line in lines:
                pdf.drawString(72, y, line)
                y -= 16
            if index < len(pages) - 1:
                pdf.showPage()
        pdf.save()
        return output_path

    def build_aps_pdf(self, output_path: Path) -> Path:
        return self.create_pdf(
            output_path,
            [
                "Agreement of Purchase and Sale",
                "MLS Number: C1234567",
                "Property Address: 123 King St W, Toronto, ON",
                "Unit: 1102",
                "Offer Date: March 1, 2026",
                "Closing Date: May 30, 2026",
                "Conditional / Firm: Conditional",
                "Firm Date: March 5, 2026",
                "Buyer: Alice Buyer and Bob Buyer",
                "Seller: Sally Seller",
                "Purchase Price: $1,250,000",
                "Deposit: $50,000",
                "Deposit Holder: Freeman Real Estate Ltd.",
                "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                "Seller's Solicitor: North Legal PC, 416-555-0199",
                "Commission: 2.5% to co-operating brokerage",
                "Commission Split: 50/50",
                "Referral Fee: 15%",
                "Marketing Fee: $500",
            ],
        )

    def build_unsupported_pdf(self, output_path: Path) -> Path:
        return self.create_pdf(
            output_path,
            [
                "Notice of Fulfillment",
                "This document is not an APS or Agreement to Lease.",
            ],
        )

    def build_answers(self) -> agent_schemas.TransactionPaperworkKevinAnswerPacket:
        return agent_schemas.TransactionPaperworkKevinAnswerPacket(
            answers=[
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_amount",
                    value="2.5%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_split",
                    value="50/50",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="referral_fee",
                    value="15%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="marketing_fee",
                    value="$500",
                ),
            ]
        )

    def get_run(self, run_id: int) -> agent_models.AgentRun:
        run = (
            self.db.query(agent_models.AgentRun)
            .filter(agent_models.AgentRun.id == run_id)
            .first()
        )
        self.assertIsNotNone(run)
        return run

    def get_task(self, task_id: int) -> agent_models.AgentTask:
        task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == task_id)
            .first()
        )
        self.assertIsNotNone(task)
        return task

    def get_audit_actions(self, run_id: int) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )
        return [log.action for log in logs]

    def test_runner_persists_task_payload_and_blocked_result_without_approvals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            run = transaction_paperwork.run_transaction_paperwork_once(
                self.db,
                pdf_sources=[pdf_path],
                render_output_dir=temp_dir,
            )

            persisted_run = self.get_run(run.id)
            persisted_task = self.get_task(persisted_run.task_id)
            task_payload = json.loads(persisted_task.payload)
            result_payload = json.loads(persisted_run.result)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_task.agent_type, "transaction_paperwork")
            self.assertEqual(persisted_task.subject_type, "trade_record_sheet")
            self.assertEqual(persisted_task.status, "completed")
            self.assertEqual(persisted_run.status, "completed")
            self.assertIsNotNone(persisted_run.started_at)
            self.assertIsNotNone(persisted_run.finished_at)
            self.assertEqual(task_payload["template_id"], "trade_record_sheet")
            self.assertEqual(
                task_payload["requested_fill_mode"],
                "overlay_coordinates",
            )
            self.assertEqual(
                task_payload["source_pdfs"][0]["file_path"],
                str(pdf_path),
            )
            self.assertEqual(
                task_payload["kevin_answer_packet"]["answers"],
                [],
            )
            self.assertEqual(result_payload["output_status"], "blocked")
            self.assertFalse(result_payload["review_package"]["review_ready"])
            self.assertEqual(
                result_payload["review_package"]["blocking_unresolved_field_keys"],
                [
                    "commission_amount",
                    "commission_split",
                    "referral_fee",
                    "marketing_fee",
                ],
            )
            self.assertIsNone(result_payload["render_result"]["artifact"])
            self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 0)
            self.assertEqual(
                audit_actions,
                [
                    "transaction_paperwork_intake_started",
                    "transaction_paperwork_document_loaded",
                    "transaction_paperwork_preparation_completed",
                    "transaction_paperwork_question_packet_generated",
                    "transaction_paperwork_review_package_built",
                    "transaction_paperwork_blocked",
                ],
            )

    def test_runner_persists_rendered_result_and_artifact_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            run = transaction_paperwork.run_transaction_paperwork_once(
                self.db,
                pdf_sources=[pdf_path],
                kevin_answers=self.build_answers(),
                render_output_dir=temp_dir,
            )

            persisted_run = self.get_run(run.id)
            result_payload = json.loads(persisted_run.result)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_run.status, "completed")
            self.assertEqual(result_payload["output_status"], "rendered")
            self.assertTrue(result_payload["review_package"]["review_ready"])
            self.assertEqual(
                result_payload["review_package"]["mapped_fields"]["commission_amount"][
                    "value_source_category"
                ],
                "kevin_confirmed",
            )
            self.assertEqual(
                result_payload["render_result"]["output_status"],
                "rendered",
            )
            self.assertIsNotNone(result_payload["render_result"]["artifact"])
            self.assertTrue(
                Path(
                    result_payload["render_result"]["artifact"]["output_pdf_path"]
                ).is_file()
            )
            self.assertGreater(
                result_payload["render_result"]["artifact"]["page_count"],
                0,
            )
            self.assertIn("transaction_paperwork_rendered", audit_actions)
            self.assertNotIn("transaction_paperwork_blocked", audit_actions)
            self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 0)

    def test_runner_persists_missing_pdf_as_blocked_not_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.pdf"

            run = transaction_paperwork.run_transaction_paperwork_once(
                self.db,
                pdf_sources=[missing_path],
                render_output_dir=temp_dir,
            )

            persisted_run = self.get_run(run.id)
            result_payload = json.loads(persisted_run.result)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_run.status, "completed")
            self.assertEqual(result_payload["output_status"], "blocked")
            self.assertEqual(
                result_payload["preparation_result"]["intake_issues"][0]["issue_code"],
                "missing_file",
            )
            self.assertIn("transaction_paperwork_document_missing", audit_actions)
            self.assertIn("transaction_paperwork_blocked", audit_actions)

    def test_runner_persists_textless_pdf_fail_soft_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.create_pdf(Path(temp_dir) / "textless.pdf")

            run = transaction_paperwork.run_transaction_paperwork_once(
                self.db,
                pdf_sources=[pdf_path],
                render_output_dir=temp_dir,
            )

            persisted_run = self.get_run(run.id)
            result_payload = json.loads(persisted_run.result)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_run.status, "completed")
            self.assertEqual(result_payload["output_status"], "blocked")
            issue_codes = [
                issue["issue_code"]
                for issue in result_payload["preparation_result"]["intake_issues"]
            ]
            self.assertIn("textless_pdf", issue_codes)
            self.assertIn("transaction_paperwork_document_textless", audit_actions)
            self.assertIn("transaction_paperwork_blocked", audit_actions)

    def test_runner_persists_unsupported_pdf_fail_soft_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_unsupported_pdf(Path(temp_dir) / "unsupported.pdf")

            run = transaction_paperwork.run_transaction_paperwork_once(
                self.db,
                pdf_sources=[pdf_path],
                render_output_dir=temp_dir,
            )

            persisted_run = self.get_run(run.id)
            result_payload = json.loads(persisted_run.result)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_run.status, "completed")
            self.assertEqual(result_payload["output_status"], "blocked")
            self.assertEqual(
                result_payload["preparation_result"]["source_documents"][0][
                    "source_doc_type"
                ],
                "transaction_related_document",
            )
            issue_codes = [
                issue["issue_code"]
                for issue in result_payload["preparation_result"]["intake_issues"]
            ]
            self.assertIn("unsupported_document_type", issue_codes)
            self.assertIn("transaction_paperwork_document_loaded", audit_actions)
            self.assertIn("transaction_paperwork_document_unsupported", audit_actions)

    def test_runner_marks_true_runtime_failure_as_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            with patch(
                "app.agents.transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs",
                side_effect=RuntimeError("paperwork boom"),
            ):
                run = transaction_paperwork.run_transaction_paperwork_once(
                    self.db,
                    pdf_sources=[pdf_path],
                    render_output_dir=temp_dir,
                )

            persisted_run = self.get_run(run.id)
            persisted_task = self.get_task(persisted_run.task_id)
            audit_actions = self.get_audit_actions(persisted_run.id)

            self.assertEqual(persisted_run.status, "failed")
            self.assertEqual(persisted_task.status, "failed")
            self.assertIn("paperwork boom", persisted_run.error)
            self.assertIsNone(persisted_run.result)
            self.assertIn("transaction_paperwork_intake_started", audit_actions)
            self.assertIn("transaction_paperwork_run_failed", audit_actions)
            self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 0)


class TransactionPaperworkRouteSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if shutil.which("/opt/homebrew/bin/pdftotext") is None and shutil.which(
            "pdftotext"
        ) is None:
            raise unittest.SkipTest("pdftotext is unavailable")

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_pdf(
        self,
        output_path: Path,
        *pages: list[str],
    ) -> Path:
        pdf = canvas.Canvas(str(output_path))
        if not pages:
            pdf.showPage()
            pdf.save()
            return output_path
        for index, lines in enumerate(pages):
            y = 760
            for line in lines:
                pdf.drawString(72, y, line)
                y -= 16
            if index < len(pages) - 1:
                pdf.showPage()
        pdf.save()
        return output_path

    def build_aps_pdf(self, output_path: Path) -> Path:
        return self.create_pdf(
            output_path,
            [
                "Agreement of Purchase and Sale",
                "MLS Number: C1234567",
                "Property Address: 123 King St W, Toronto, ON",
                "Unit: 1102",
                "Offer Date: March 1, 2026",
                "Closing Date: May 30, 2026",
                "Conditional / Firm: Conditional",
                "Firm Date: March 5, 2026",
                "Buyer: Alice Buyer and Bob Buyer",
                "Seller: Sally Seller",
                "Purchase Price: $1,250,000",
                "Deposit: $50,000",
                "Deposit Holder: Freeman Real Estate Ltd.",
                "Buyer's Solicitor: Hart Law LLP, 416-555-0100",
                "Seller's Solicitor: North Legal PC, 416-555-0199",
                "Commission: 2.5% to co-operating brokerage",
                "Commission Split: 50/50",
                "Referral Fee: 15%",
                "Marketing Fee: $500",
            ],
        )

    def build_answers(self) -> agent_schemas.TransactionPaperworkKevinAnswerPacket:
        return agent_schemas.TransactionPaperworkKevinAnswerPacket(
            answers=[
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_amount",
                    value="2.5%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="commission_split",
                    value="50/50",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="referral_fee",
                    value="15%",
                ),
                agent_schemas.TransactionPaperworkKevinAnswer(
                    field_key="marketing_fee",
                    value="$500",
                ),
            ]
        )

    def build_request(
        self,
        *pdf_paths: Path,
        kevin_answers: agent_schemas.TransactionPaperworkKevinAnswerPacket | None = None,
        template_id: str = "trade_record_sheet",
        template_version: str = "trade_record_sheet_blank_v1",
        requested_fill_mode: agent_schemas.TransactionPaperworkTemplateFillMode = "overlay_coordinates",
    ) -> agent_schemas.TransactionPaperworkRunRequest:
        return agent_schemas.TransactionPaperworkRunRequest(
            source_pdfs=[
                agent_schemas.TransactionPaperworkPdfSourceInput(file_path=str(path))
                for path in pdf_paths
            ],
            kevin_answer_packet=kevin_answers
            or agent_schemas.TransactionPaperworkKevinAnswerPacket(),
            template_id=template_id,
            template_version=template_version,
            requested_fill_mode=requested_fill_mode,
        )

    def create_non_paperwork_run(self) -> agent_models.AgentRun:
        task = agent_models.AgentTask(
            agent_type="buyer_match",
            subject_type="contact",
            subject_id=None,
            payload="{}",
            status="completed",
            priority="normal",
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        run = agent_models.AgentRun(
            task_id=task.id,
            status="completed",
            summary="non-paperwork run",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def test_latest_returns_safe_empty_contract(self):
        payload = agent_router.get_latest_transaction_paperwork_result(db=self.db)

        self.assertEqual(
            payload,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

    def test_transaction_paperwork_route_surface_is_scoped_and_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")
            request = self.build_request(pdf_path)
            paperwork_run = agent_router.trigger_transaction_paperwork_run_once(
                request,
                self.db,
            )
            non_paperwork_run = self.create_non_paperwork_run()

            runs = agent_router.list_transaction_paperwork_runs(db=self.db)
            latest = agent_router.get_latest_transaction_paperwork_result(db=self.db)
            report = agent_router.get_transaction_paperwork_run_report(
                paperwork_run.id,
                db=self.db,
            )
            audit_logs = agent_router.list_transaction_paperwork_run_audit_logs(
                paperwork_run.id,
                db=self.db,
            )

            self.assertEqual([run.id for run in runs], [paperwork_run.id])
            self.assertEqual(latest["run_id"], paperwork_run.id)
            self.assertEqual(latest["status"], "completed")
            self.assertEqual(latest["result"]["output_status"], "blocked")
            self.assertEqual(report["output_status"], "blocked")
            self.assertIn(
                "commission_amount",
                report["review_package"]["blocking_unresolved_field_keys"],
            )
            self.assertTrue(audit_logs)
            self.assertEqual(
                audit_logs[0].action,
                "transaction_paperwork_intake_started",
            )
            self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 0)

            with self.assertRaises(HTTPException) as report_error:
                agent_router.get_transaction_paperwork_run_report(
                    non_paperwork_run.id,
                    db=self.db,
                )
            self.assertEqual(report_error.exception.status_code, 404)

            with self.assertRaises(HTTPException) as audit_error:
                agent_router.list_transaction_paperwork_run_audit_logs(
                    non_paperwork_run.id,
                    db=self.db,
                )
            self.assertEqual(audit_error.exception.status_code, 404)

    def test_route_surface_returns_rendered_report_when_kevin_confirmations_are_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")
            request = self.build_request(
                pdf_path,
                kevin_answers=self.build_answers(),
            )

            run = agent_router.trigger_transaction_paperwork_run_once(
                request,
                self.db,
            )
            latest = agent_router.get_latest_transaction_paperwork_result(db=self.db)
            report = agent_router.get_transaction_paperwork_run_report(
                run.id,
                db=self.db,
            )

            self.assertEqual(latest["status"], "completed")
            self.assertEqual(latest["result"]["output_status"], "rendered")
            self.assertEqual(report["output_status"], "rendered")
            self.assertTrue(report["review_package"]["review_ready"])
            self.assertIsNotNone(report["render_result"]["artifact"])
            self.assertEqual(
                report["review_package"]["mapped_fields"]["commission_amount"][
                    "value_source_category"
                ],
                "kevin_confirmed",
            )

    def test_route_surface_exposes_missing_pdf_intake_issue_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.pdf"
            request = self.build_request(missing_path)

            run = agent_router.trigger_transaction_paperwork_run_once(
                request,
                self.db,
            )
            report = agent_router.get_transaction_paperwork_run_report(
                run.id,
                db=self.db,
            )

            self.assertEqual(run.status, "completed")
            self.assertEqual(report["output_status"], "blocked")
            self.assertEqual(
                report["preparation_result"]["intake_issues"][0]["issue_code"],
                "missing_file",
            )

    def test_route_surface_reports_failed_run_with_error_and_no_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")
            request = self.build_request(pdf_path)

            with patch(
                "app.agents.transaction_paperwork.orchestrate_transaction_paperwork_from_pdfs",
                side_effect=RuntimeError("paperwork boom"),
            ):
                run = agent_router.trigger_transaction_paperwork_run_once(
                    request,
                    self.db,
                )

            latest = agent_router.get_latest_transaction_paperwork_result(db=self.db)

            self.assertEqual(run.status, "failed")
            self.assertEqual(latest["run_id"], run.id)
            self.assertEqual(latest["status"], "failed")
            self.assertIn("paperwork boom", latest["error"])
            self.assertIsNone(latest["result"])

            with self.assertRaises(HTTPException) as report_error:
                agent_router.get_transaction_paperwork_run_report(
                    run.id,
                    db=self.db,
                )
            self.assertEqual(report_error.exception.status_code, 404)

    def test_run_once_rejects_unsupported_template_or_fill_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self.build_aps_pdf(Path(temp_dir) / "aps.pdf")

            with self.assertRaises(HTTPException) as template_error:
                agent_router.trigger_transaction_paperwork_run_once(
                    self.build_request(pdf_path, template_id="other_template"),
                    self.db,
                )
            self.assertEqual(template_error.exception.status_code, 400)

            with self.assertRaises(HTTPException) as fill_mode_error:
                agent_router.trigger_transaction_paperwork_run_once(
                    self.build_request(
                        pdf_path,
                        requested_fill_mode="fill_pdf_fields",
                    ),
                    self.db,
                )
            self.assertEqual(fill_mode_error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
