import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents import paperwork_templates, schemas as agent_schemas
from app.agents import transaction_paperwork


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


if __name__ == "__main__":
    unittest.main()
