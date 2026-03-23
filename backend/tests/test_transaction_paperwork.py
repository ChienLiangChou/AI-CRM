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


if __name__ == "__main__":
    unittest.main()
