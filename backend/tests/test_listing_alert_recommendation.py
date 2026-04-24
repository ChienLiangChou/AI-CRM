import json
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app import models as crm_models
from app.agents import listing_alert_recommendation
from app.agents import listing_alert_recommendation_gmail
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ListingAlertRecommendationStepOneTests(unittest.TestCase):
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

        self.stage = crm_models.PipelineStage(name="Lead", order=1)
        self.db.add(self.stage)
        self.db.commit()
        self.db.refresh(self.stage)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_contact(self, **overrides):
        defaults = {
            "name": "Alex Buyer",
            "email": "alex@example.com",
            "client_type": "buyer",
            "status": "active",
            "stage_id": self.stage.id,
            "preferred_language": "en",
            "budget_min": 700000,
            "budget_max": 900000,
            "preferred_areas": json.dumps(["King West", "CityPlace"]),
            "property_preferences": json.dumps({"types": ["condo"]}),
            "created_at": utcnow_naive() - timedelta(days=10),
            "last_contacted_at": utcnow_naive() - timedelta(days=2),
        }
        defaults.update(overrides)
        contact = crm_models.Contact(**defaults)
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def create_interaction(self, contact_id: int, **overrides):
        defaults = {
            "contact_id": contact_id,
            "channel": "email",
            "direction": "inbound",
            "interaction_type": "email",
            "notes": "Client wants a practical shortlist near transit.",
            "date": utcnow_naive() - timedelta(days=1),
        }
        defaults.update(overrides)
        interaction = crm_models.Interaction(**defaults)
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def sale_alert_message(
        self,
        *,
        subject: str = "Toronto MLS Alert",
        to_addresses: list[str] | None = None,
        label_ids: list[str] | None = None,
    ) -> agent_schemas.ListingAlertGmailMessageInput:
        return agent_schemas.ListingAlertGmailMessageInput(
            message_id="msg-sale-1",
            thread_id="thread-sale-1",
            received_at=utcnow_naive(),
            subject=subject,
            from_address="alerts@mls.example",
            to_addresses=to_addresses or ["kevin@skc.example"],
            label_ids=label_ids or ["mls-alerts"],
            plain_text_body=(
                "Toronto MLS Saved Search Results\n\n"
                "123 King St W #1208\n"
                "MLS#: C1234567\n"
                "For Sale\n"
                "Price: $859,000\n"
                "Condo\n"
                "2 Bed | 2 Bath\n"
                "Area: King West\n"
                "https://example.com/listings/123-king\n\n"
                "87 Fort York Blvd #1908\n"
                "MLS#: C7654321\n"
                "For Sale\n"
                "Price: $889,000\n"
                "Condo\n"
                "2 Bed | 2 Bath\n"
                "Area: CityPlace\n"
                "https://example.com/listings/87-fort-york\n"
            ),
        )

    def rent_alert_message(
        self,
        *,
        subject: str = "Toronto MLS Rental Alert",
        to_addresses: list[str] | None = None,
        label_ids: list[str] | None = None,
    ) -> agent_schemas.ListingAlertGmailMessageInput:
        return agent_schemas.ListingAlertGmailMessageInput(
            message_id="msg-rent-1",
            thread_id="thread-rent-1",
            received_at=utcnow_naive(),
            subject=subject,
            from_address="alerts@mls.example",
            to_addresses=to_addresses or ["rent-filter@skc.example"],
            label_ids=label_ids or ["rent-alerts"],
            plain_text_body=(
                "Toronto MLS Lease Alerts\n\n"
                "15 Iceboat Terr #903\n"
                "MLS#: C2000001\n"
                "For Lease\n"
                "Lease: $2,800/mo\n"
                "Condo\n"
                "1 Bed | 1 Bath\n"
                "Area: CityPlace\n"
                "https://example.com/listings/15-iceboat\n"
            ),
        )

    def unknown_market_alert_message(self) -> agent_schemas.ListingAlertGmailMessageInput:
        return agent_schemas.ListingAlertGmailMessageInput(
            message_id="msg-unknown-1",
            thread_id="thread-unknown-1",
            received_at=utcnow_naive(),
            subject="Toronto MLS Alert",
            from_address="alerts@mls.example",
            to_addresses=["kevin@skc.example"],
            label_ids=["mls-alerts"],
            plain_text_body=(
                "Toronto MLS Results\n\n"
                "123 King St W #1208\n"
                "MLS#: C3000001\n"
                "Price: $859,000\n"
                "Condo\n"
                "2 Bed | 2 Bath\n"
                "Area: King West\n"
                "https://example.com/listings/123-king\n"
            ),
        )

    def capped_sale_alert_message(self) -> agent_schemas.ListingAlertGmailMessageInput:
        blocks: list[str] = []
        for index in range(12):
            blocks.append(
                "\n".join(
                    [
                        f"{100 + index} Example St",
                        f"MLS#: C9000{index}",
                        "For Sale",
                        f"Price: ${800000 + (index * 5000):,}",
                        "Condo",
                        "2 Bed | 2 Bath",
                        "Area: King West",
                        f"https://example.com/listings/{index}",
                    ]
                )
            )
        return agent_schemas.ListingAlertGmailMessageInput(
            message_id="msg-cap-1",
            thread_id="thread-cap-1",
            received_at=utcnow_naive(),
            subject="Toronto MLS Alert",
            from_address="alerts@mls.example",
            to_addresses=["kevin@skc.example"],
            label_ids=["mls-alerts"],
            plain_text_body="\n\n".join(blocks),
        )

    def build_request(self, **overrides) -> agent_schemas.ListingAlertRunRequest:
        defaults = {
            "execution_mode": "manual",
            "gmail_alert": self.sale_alert_message(),
            "expected_contact_id": None,
            "explicit_contact_mappings": [],
            "operator_notes": "Prepare manual packet only.",
        }
        defaults.update(overrides)
        return agent_schemas.ListingAlertRunRequest(**defaults)

    def build_gmail_read_config(self, **overrides) -> agent_schemas.ListingAlertGmailReadConfig:
        defaults = {
            "access_token": "",
            "gmail_user_id": "me",
            "query_policy": agent_schemas.ListingAlertGmailReadQueryPolicy(
                allowed_sender="alerts@mls.example",
                label_ids=["mls-alerts"],
                subject_keywords=["Toronto MLS Alert"],
                max_results=10,
            ),
        }
        defaults.update(overrides)
        return agent_schemas.ListingAlertGmailReadConfig(**defaults)

    def build_automatic_request(
        self,
        **overrides,
    ) -> agent_schemas.ListingAlertAutomaticRunRequest:
        defaults = {
            "gmail_read_config": self.build_gmail_read_config(),
            "operator_notes": "Automatic Mode v1 run once.",
            "max_messages": 3,
        }
        defaults.update(overrides)
        return agent_schemas.ListingAlertAutomaticRunRequest(**defaults)

    def automatic_candidate(
        self,
        *,
        message_id: str,
        thread_id: str,
        subject: str,
        existing_task_id: int | None = None,
        existing_run_id: int | None = None,
    ) -> agent_schemas.ListingAlertGmailCandidateMessage:
        return agent_schemas.ListingAlertGmailCandidateMessage(
            message_id=message_id,
            thread_id=thread_id,
            received_at=utcnow_naive(),
            subject=subject,
            from_address="alerts@mls.example",
            label_ids=["mls-alerts"],
            existing_task_id=existing_task_id,
            existing_run_id=existing_run_id,
        )

    def automatic_resolved_gmail_config(
        self,
    ) -> listing_alert_recommendation_gmail.ResolvedGmailReadConfig:
        return listing_alert_recommendation_gmail.ResolvedGmailReadConfig(
            config=self.build_gmail_read_config(),
            credential_source="stored_oauth",
        )

    def run_automatic_waiting_approval_batch(
        self,
        *,
        message_id: str,
        thread_id: str,
        subject: str = "Toronto MLS Alert for Mia Chen",
    ) -> agent_schemas.ListingAlertAutomaticBatchResult:
        self.create_contact(
            name="Mia Chen",
            email="mia@example.com",
        )
        message = self.sale_alert_message(subject=subject)
        message.message_id = message_id
        message.thread_id = thread_id
        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Alert"',
                matched_message_count=1,
                candidate_count=1,
                candidates=[
                    self.automatic_candidate(
                        message_id=message_id,
                        thread_id=thread_id,
                        subject=subject,
                    )
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            return_value=message,
        ):
            return listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(),
            )

    def run_automatic_completed_no_draft_batch(
        self,
        *,
        message_id: str,
        thread_id: str,
        subject: str = "Toronto MLS Rental Alert for Avery Tenant",
    ) -> agent_schemas.ListingAlertAutomaticBatchResult:
        self.create_contact(
            name="Avery Tenant",
            email=f"{message_id}@example.com",
            client_type="tenant",
            budget_min=2200,
            budget_max=3200,
            preferred_areas=json.dumps(["CityPlace"]),
            property_preferences=json.dumps({"types": ["condo"]}),
        )
        message = self.rent_alert_message(subject=subject)
        message.message_id = message_id
        message.thread_id = thread_id
        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Rental Alert"',
                matched_message_count=1,
                candidate_count=1,
                candidates=[
                    self.automatic_candidate(
                        message_id=message_id,
                        thread_id=thread_id,
                        subject=subject,
                    )
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            return_value=message,
        ):
            return listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(),
            )

    def get_audit_actions(self, run_id: int) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )
        return [log.action for log in logs]

    def get_all_audit_actions(self) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )
        return [log.action for log in logs]

    def prepare_packet_run(
        self,
        *,
        request: agent_schemas.ListingAlertRunRequest | None = None,
    ):
        packet_request = request
        if packet_request is None:
            contact = self.create_contact()
            packet_request = self.build_request(expected_contact_id=contact.id)
        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            packet_request,
        )
        return run

    def test_expected_contact_override_prepares_manual_packet_without_approval(self):
        contact = self.create_contact()
        self.create_interaction(contact.id)
        request = self.build_request(expected_contact_id=contact.id)

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)
        task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == run.task_id)
            .first()
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.subject_type, "contact")
        self.assertEqual(task.subject_id, contact.id)
        self.assertEqual(result["execution_status"], "packet_ready")
        self.assertEqual(result["association"]["method"], "expected_contact_id")
        self.assertEqual(result["association"]["representation_intent"], "buyer_purchase")
        self.assertEqual(result["manual_review_packet"]["extracted_listing_count"], 2)
        self.assertEqual(result["manual_review_packet"]["shortlist_cap"], 3)
        self.assertEqual(result["manual_review_packet"]["draft_output_cap"], 1)
        self.assertEqual(
            self.db.query(agent_models.AgentApproval).count(),
            0,
        )
        self.assertIn(
            "listing_alert_manual_packet_prepared",
            self.get_audit_actions(run.id),
        )

    def test_explicit_contact_mapping_matches_renter_alert(self):
        contact = self.create_contact(
            name="Avery Tenant",
            email="avery@example.com",
            client_type="tenant",
            budget_min=2200,
            budget_max=3200,
            preferred_areas=json.dumps(["CityPlace"]),
        )
        request = self.build_request(
            gmail_alert=self.rent_alert_message(
                to_addresses=["rent-filter@skc.example"],
                label_ids=["rent-alerts"],
            ),
            explicit_contact_mappings=[
                agent_schemas.ListingAlertExplicitContactMappingInput(
                    contact_id=contact.id,
                    recipient_address="rent-filter@skc.example",
                    sender_address="alerts@mls.example",
                    label_id="rent-alerts",
                    representation_intent="renter_representation",
                )
            ],
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "packet_ready")
        self.assertEqual(result["association"]["method"], "explicit_mapping")
        self.assertEqual(
            result["association"]["representation_intent"],
            "renter_representation",
        )
        self.assertEqual(result["extracted_listings"][0]["market_type"], "rent")

    def test_deterministic_metadata_match_uses_contact_name_in_subject(self):
        contact = self.create_contact(name="Mia Chen")
        request = self.build_request(
            gmail_alert=self.sale_alert_message(
                subject="Toronto MLS Alert for Mia Chen",
            )
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "packet_ready")
        self.assertEqual(result["association"]["contact_id"], contact.id)
        self.assertEqual(result["association"]["method"], "deterministic_metadata")

    def test_heuristic_fallback_uses_budget_area_and_property_type(self):
        matching_contact = self.create_contact(
            name="Jordan Buyer",
            budget_min=800000,
            budget_max=910000,
            preferred_areas=json.dumps(["King West", "CityPlace"]),
            property_preferences=json.dumps({"types": ["condo"]}),
        )
        self.create_contact(
            name="Mismatch Buyer",
            budget_min=1500000,
            budget_max=1800000,
            preferred_areas=json.dumps(["North York"]),
            property_preferences=json.dumps({"types": ["detached"]}),
            email="other@example.com",
        )
        request = self.build_request()

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "packet_ready")
        self.assertEqual(result["association"]["contact_id"], matching_contact.id)
        self.assertEqual(result["association"]["method"], "heuristic_fallback")

    def test_ambiguous_client_association_blocks_safely(self):
        self.create_contact(name="Buyer One", email="buyer1@example.com")
        self.create_contact(name="Buyer Two", email="buyer2@example.com")
        request = self.build_request()

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(result["execution_status"], "blocked_ambiguous_client_match")
        self.assertIsNone(result["manual_review_packet"])
        self.assertEqual(result["association"]["status"], "blocked_ambiguous")
        self.assertEqual(result["association"]["diagnostics"]["match_stage"], "heuristic_fallback")
        self.assertEqual(len(result["association"]["candidate_contacts"]), 2)

    def test_ambiguous_buyer_vs_renter_intent_blocks_safely(self):
        contact = self.create_contact(
            client_type="buyer,tenant",
        )
        request = self.build_request(
            gmail_alert=self.unknown_market_alert_message(),
            expected_contact_id=contact.id,
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "blocked_ambiguous_intent")
        self.assertIsNone(result["manual_review_packet"])
        self.assertEqual(
            result["association"]["blocked_reason"],
            "buyer_vs_renter_intent_ambiguous",
        )
        self.assertIn(
            "buyer_vs_renter_intent_ambiguous",
            result["association"]["failed_checks"],
        )

    def test_blocked_no_client_match_reports_missing_criteria_diagnostics(self):
        contact = self.create_contact(
            name="Sparse Buyer",
            email="sparse@example.com",
            budget_min=None,
            budget_max=None,
            preferred_areas="[]",
            property_preferences="{}",
        )
        request = self.build_request(
            gmail_alert=self.sale_alert_message(subject="Toronto MLS Alert for Unknown Client"),
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "blocked_no_client_match")
        self.assertEqual(result["association"]["status"], "blocked_no_match")
        self.assertEqual(result["association"]["blocked_reason"], "no_safe_contact_match")
        self.assertEqual(result["association"]["diagnostics"]["match_stage"], "heuristic_fallback")
        self.assertIn("preferred_areas", result["association"]["missing_criteria"])
        self.assertIn("property_preferences.types", result["association"]["missing_criteria"])
        self.assertIn("budget_range", result["association"]["missing_criteria"])
        self.assertEqual(result["association"]["candidate_contacts"][0]["contact_id"], contact.id)

    def test_blocked_no_client_match_reports_failed_checks_for_mismatched_criteria(self):
        contact = self.create_contact(
            name="Mismatch Buyer",
            email="mismatch@example.com",
            budget_min=1_500_000,
            budget_max=1_800_000,
            preferred_areas=json.dumps(["North York"]),
            property_preferences=json.dumps({"types": ["detached"]}),
        )
        request = self.build_request(
            gmail_alert=self.sale_alert_message(subject="Toronto MLS Alert for Unknown Client"),
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "blocked_no_client_match")
        self.assertEqual(result["association"]["status"], "blocked_no_match")
        self.assertIn("preferred_areas_no_overlap", result["association"]["failed_checks"])
        self.assertIn("property_type_no_overlap", result["association"]["failed_checks"])
        self.assertIn("budget_out_of_range", result["association"]["failed_checks"])
        self.assertEqual(result["association"]["candidate_contacts"][0]["contact_id"], contact.id)

    def test_expected_contact_id_recovers_from_otherwise_blocked_no_match(self):
        contact = self.create_contact(
            name="Manual Override Buyer",
            email="override@example.com",
            budget_min=None,
            budget_max=None,
            preferred_areas="[]",
            property_preferences="{}",
        )
        request_without_override = self.build_request(
            gmail_alert=self.sale_alert_message(subject="Toronto MLS Alert for Unknown Client"),
        )
        blocked_run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request_without_override,
        )
        blocked_result = json.loads(blocked_run.result)
        self.assertEqual(blocked_result["execution_status"], "blocked_no_client_match")

        recovered_request = self.build_request(
            gmail_alert=self.sale_alert_message(subject="Toronto MLS Alert for Unknown Client"),
            expected_contact_id=contact.id,
        )
        recovered_run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            recovered_request,
        )
        recovered_result = json.loads(recovered_run.result)

        self.assertEqual(recovered_result["execution_status"], "packet_ready")
        self.assertEqual(recovered_result["association"]["method"], "expected_contact_id")
        self.assertEqual(recovered_result["association"]["contact_id"], contact.id)
        self.assertTrue(recovered_result["association"]["diagnostics"]["operator_override"])
        self.assertIn("budget_range", recovered_result["association"]["missing_criteria"])

    def test_expected_contact_id_intent_mismatch_reports_diagnostics(self):
        contact = self.create_contact(
            name="Tenant Contact",
            client_type="tenant",
            email="tenant@example.com",
        )
        request = self.build_request(expected_contact_id=contact.id)

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "blocked_intent_mismatch")
        self.assertEqual(result["association"]["status"], "blocked_intent_mismatch")
        self.assertEqual(
            result["association"]["blocked_reason"],
            "contact_not_configured_for_sale_alerts",
        )
        self.assertTrue(result["association"]["diagnostics"]["operator_override"])
        self.assertIn(
            "contact_not_configured_for_sale_alerts",
            result["association"]["failed_checks"],
        )
        self.assertEqual(result["association"]["candidate_contacts"][0]["contact_id"], contact.id)

    def test_extraction_caps_candidates_at_ten(self):
        contact = self.create_contact()
        request = self.build_request(
            gmail_alert=self.capped_sale_alert_message(),
            expected_contact_id=contact.id,
        )

        run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            request,
        )
        result = json.loads(run.result)

        self.assertEqual(result["execution_status"], "packet_ready")
        self.assertEqual(len(result["extracted_listings"]), 10)
        self.assertEqual(
            result["manual_review_packet"]["extracted_listing_count"],
            10,
        )

    def test_automatic_batch_enforces_hard_message_cap_of_three(self):
        self.create_contact(name="Mia Chen", email="mia@example.com")
        candidates: list[agent_schemas.ListingAlertGmailCandidateMessage] = []
        normalized_messages: list[agent_schemas.ListingAlertGmailMessageInput] = []
        for index in range(4):
            message_id = f"auto-cap-{index}"
            thread_id = f"thread-auto-cap-{index}"
            candidates.append(
                self.automatic_candidate(
                    message_id=message_id,
                    thread_id=thread_id,
                    subject="Toronto MLS Alert for Mia Chen",
                )
            )
            message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
            message.message_id = message_id
            message.thread_id = thread_id
            normalized_messages.append(message)

        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Alert"',
                matched_message_count=4,
                candidate_count=4,
                candidates=candidates,
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ) as resolve_mock, patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            side_effect=normalized_messages[:3],
        ) as fetch_mock:
            result = listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(max_messages=10),
            )

        self.assertEqual(result.message_cap, 3)
        self.assertEqual(result.processed_message_count, 3)
        self.assertEqual(len(result.outcomes), 3)
        self.assertEqual(fetch_mock.call_count, 3)
        self.assertEqual(resolve_mock.call_count, 1)
        self.assertEqual(
            [item.message_id for item in result.outcomes],
            ["auto-cap-0", "auto-cap-1", "auto-cap-2"],
        )
        self.assertTrue(
            all(item.status == "waiting_approval" for item in result.outcomes)
        )
        self.assertTrue(all(item.review_run_id is not None for item in result.outcomes))
        self.assertEqual(self.db.query(agent_models.AgentTask).count(), 3)
        self.assertEqual(self.db.query(agent_models.AgentRun).count(), 6)
        self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 3)

    def test_automatic_batch_summarizes_duplicate_blocked_and_waiting_approval(self):
        contact = self.create_contact(
            name="Mia Chen",
            email="mia@example.com",
            budget_min=None,
            budget_max=None,
            preferred_areas="[]",
            property_preferences="{}",
        )

        duplicate_message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
        duplicate_message.message_id = "auto-dup-1"
        duplicate_message.thread_id = "thread-auto-dup-1"
        existing_run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            self.build_request(
                gmail_alert=duplicate_message,
                expected_contact_id=contact.id,
            ),
        )

        blocked_message = self.sale_alert_message(
            subject="Toronto MLS Alert for Unknown Client"
        )
        blocked_message.message_id = "auto-block-1"
        blocked_message.thread_id = "thread-auto-block-1"

        ready_message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
        ready_message.message_id = "auto-ready-1"
        ready_message.thread_id = "thread-auto-ready-1"

        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Alert"',
                matched_message_count=3,
                candidate_count=3,
                candidates=[
                    self.automatic_candidate(
                        message_id="auto-dup-1",
                        thread_id="thread-auto-dup-1",
                        subject="Toronto MLS Alert for Mia Chen",
                        existing_task_id=existing_run.task_id,
                        existing_run_id=existing_run.id,
                    ),
                    self.automatic_candidate(
                        message_id="auto-block-1",
                        thread_id="thread-auto-block-1",
                        subject="Toronto MLS Alert for Unknown Client",
                    ),
                    self.automatic_candidate(
                        message_id="auto-ready-1",
                        thread_id="thread-auto-ready-1",
                        subject="Toronto MLS Alert for Mia Chen",
                    ),
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            side_effect=[blocked_message, ready_message],
        ):
            result = listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(),
            )

        self.assertEqual(result.duplicate_skipped_count, 1)
        self.assertEqual(result.blocked_count, 1)
        self.assertEqual(result.waiting_approval_count, 1)
        self.assertEqual(result.completed_no_draft_count, 0)

        duplicate_outcome, blocked_outcome, review_outcome = result.outcomes
        self.assertEqual(duplicate_outcome.status, "duplicate_skipped")
        self.assertEqual(duplicate_outcome.reason, "message_id_already_imported")
        self.assertEqual(duplicate_outcome.task_id, existing_run.task_id)
        self.assertEqual(duplicate_outcome.run_id, existing_run.id)
        self.assertIsNone(duplicate_outcome.execution_status)

        self.assertEqual(blocked_outcome.status, "blocked")
        self.assertEqual(blocked_outcome.execution_status, "blocked_no_client_match")
        self.assertEqual(blocked_outcome.association_status, "blocked_no_match")
        self.assertEqual(blocked_outcome.reason, "no_safe_contact_match")
        self.assertFalse(blocked_outcome.packet_ready)
        self.assertIsNotNone(blocked_outcome.task_id)
        self.assertIsNotNone(blocked_outcome.run_id)
        self.assertIsNone(blocked_outcome.review_run_id)

        self.assertEqual(review_outcome.status, "waiting_approval")
        self.assertEqual(review_outcome.execution_status, "packet_ready")
        self.assertEqual(review_outcome.association_status, "matched")
        self.assertEqual(review_outcome.review_outcome, "waiting_approval")
        self.assertTrue(review_outcome.packet_ready)
        self.assertIsNotNone(review_outcome.task_id)
        self.assertIsNotNone(review_outcome.run_id)
        self.assertIsNotNone(review_outcome.review_run_id)
        self.assertIsNotNone(review_outcome.approval_id)

        blocked_task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == blocked_outcome.task_id)
            .first()
        )
        review_task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == review_outcome.task_id)
            .first()
        )
        self.assertEqual(json.loads(blocked_task.payload)["execution_mode"], "automatic")
        self.assertEqual(json.loads(review_task.payload)["execution_mode"], "automatic")
        review_task_runs = (
            self.db.query(agent_models.AgentRun)
            .filter(agent_models.AgentRun.task_id == review_task.id)
            .order_by(agent_models.AgentRun.id.asc())
            .all()
        )
        self.assertEqual(len(review_task_runs), 2)
        self.assertEqual(review_task_runs[0].id, review_outcome.run_id)
        self.assertEqual(review_task_runs[1].id, review_outcome.review_run_id)

    def test_automatic_batch_can_complete_with_no_draft_for_safe_packet_ready_message(self):
        contact = self.create_contact(
            name="Avery Tenant",
            email="avery@example.com",
            client_type="tenant",
            budget_min=2200,
            budget_max=3200,
            preferred_areas=json.dumps(["CityPlace"]),
            property_preferences=json.dumps({"types": ["condo"]}),
        )
        rent_message = self.rent_alert_message(subject="Toronto MLS Rental Alert for Avery Tenant")
        rent_message.message_id = "auto-rent-1"
        rent_message.thread_id = "thread-auto-rent-1"

        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Rental Alert"',
                matched_message_count=1,
                candidate_count=1,
                candidates=[
                    self.automatic_candidate(
                        message_id="auto-rent-1",
                        thread_id="thread-auto-rent-1",
                        subject="Toronto MLS Rental Alert for Avery Tenant",
                    )
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            return_value=rent_message,
        ):
            result = listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(),
            )

        self.assertEqual(result.completed_no_draft_count, 1)
        self.assertEqual(result.waiting_approval_count, 0)
        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, "completed_no_draft")
        self.assertEqual(outcome.review_outcome, "completed_no_draft")
        self.assertTrue(outcome.packet_ready)
        self.assertIsNotNone(outcome.review_run_id)
        self.assertIsNone(outcome.approval_id)
        review_run = (
            self.db.query(agent_models.AgentRun)
            .filter(agent_models.AgentRun.id == outcome.review_run_id)
            .first()
        )
        review_result = json.loads(review_run.result)
        self.assertEqual(review_run.status, "completed")
        self.assertEqual(review_result["workflow_mode"], "automatic")
        self.assertEqual(review_result["review_outcome"], "completed_no_draft")
        self.assertEqual(len(review_result["client_facing_drafts"]), 0)

    def test_automatic_batch_writes_batch_and_per_message_audit_logs(self):
        contact = self.create_contact(
            name="Mia Chen",
            email="mia@example.com",
            budget_min=None,
            budget_max=None,
            preferred_areas="[]",
            property_preferences="{}",
        )
        duplicate_message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
        duplicate_message.message_id = "audit-dup-1"
        duplicate_message.thread_id = "thread-audit-dup-1"
        existing_run = listing_alert_recommendation.run_listing_alert_manual_packet_once(
            self.db,
            self.build_request(
                gmail_alert=duplicate_message,
                expected_contact_id=contact.id,
            ),
        )

        blocked_message = self.sale_alert_message(
            subject="Toronto MLS Alert for Unknown Client"
        )
        blocked_message.message_id = "audit-block-1"
        blocked_message.thread_id = "thread-audit-block-1"

        ready_message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
        ready_message.message_id = "audit-ready-1"
        ready_message.thread_id = "thread-audit-ready-1"

        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Alert"',
                matched_message_count=3,
                candidate_count=3,
                candidates=[
                    self.automatic_candidate(
                        message_id="audit-dup-1",
                        thread_id="thread-audit-dup-1",
                        subject="Toronto MLS Alert for Mia Chen",
                        existing_task_id=existing_run.task_id,
                        existing_run_id=existing_run.id,
                    ),
                    self.automatic_candidate(
                        message_id="audit-block-1",
                        thread_id="thread-audit-block-1",
                        subject="Toronto MLS Alert for Unknown Client",
                    ),
                    self.automatic_candidate(
                        message_id="audit-ready-1",
                        thread_id="thread-audit-ready-1",
                        subject="Toronto MLS Alert for Mia Chen",
                    ),
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            side_effect=[blocked_message, ready_message],
        ):
            result = listing_alert_recommendation.run_listing_alert_automatic_batch_once(
                self.db,
                self.build_automatic_request(),
            )

        all_actions = self.get_all_audit_actions()
        self.assertIn("listing_alert_automatic_batch_started", all_actions)
        self.assertEqual(
            all_actions.count("listing_alert_automatic_message_outcome_recorded"),
            3,
        )
        self.assertIn("listing_alert_automatic_message_duplicate_skipped", all_actions)
        self.assertIn("listing_alert_automatic_message_blocked", all_actions)
        self.assertIn("listing_alert_automatic_message_waiting_approval", all_actions)
        self.assertIn("listing_alert_automatic_batch_completed", all_actions)

        blocked_outcome = next(item for item in result.outcomes if item.status == "blocked")
        ready_outcome = next(
            item for item in result.outcomes if item.status == "waiting_approval"
        )
        blocked_actions = self.get_audit_actions(blocked_outcome.run_id)
        packet_actions = self.get_audit_actions(ready_outcome.run_id)
        review_actions = self.get_audit_actions(ready_outcome.review_run_id)

        self.assertIn("listing_alert_automatic_packet_planning_started", blocked_actions)
        self.assertIn("listing_alert_automatic_candidates_extracted", blocked_actions)
        self.assertIn(
            "listing_alert_automatic_client_association_blocked",
            blocked_actions,
        )
        self.assertIn("listing_alert_automatic_packet_blocked", blocked_actions)

        self.assertIn("listing_alert_automatic_packet_planning_started", packet_actions)
        self.assertIn("listing_alert_automatic_candidates_extracted", packet_actions)
        self.assertIn(
            "listing_alert_automatic_client_association_resolved",
            packet_actions,
        )
        self.assertIn("listing_alert_automatic_packet_prepared", packet_actions)
        self.assertIn("listing_alert_automatic_review_started", review_actions)
        self.assertIn("listing_alert_automatic_shortlist_generated", review_actions)
        self.assertIn("listing_alert_automatic_draft_generated", review_actions)
        self.assertIn(
            "listing_alert_automatic_review_approval_created",
            review_actions,
        )

    def test_automatic_review_failure_writes_failed_audit_log(self):
        contact = self.create_contact(
            name="Sparse Buyer",
            email="sparse@example.com",
            budget_min=None,
            budget_max=None,
            preferred_areas="[]",
            property_preferences="{}",
        )
        blocked_run = listing_alert_recommendation.run_listing_alert_automatic_packet_once(
            self.db,
            self.build_request(
                execution_mode="automatic",
                gmail_alert=self.sale_alert_message(
                    subject="Toronto MLS Alert for Unknown Client"
                ),
                expected_contact_id=None,
            ),
        )

        review_run = listing_alert_recommendation.run_listing_alert_automatic_review_once(
            self.db,
            source_run=blocked_run,
        )

        self.assertEqual(blocked_run.task.subject_id, None)
        self.assertEqual(review_run.status, "failed")
        self.assertIn(
            "listing_alert_automatic_review_failed",
            self.get_audit_actions(review_run.id),
        )

    def test_manual_review_submission_with_draft_creates_review_only_approval(self):
        contact = self.create_contact()
        packet_run = self.prepare_packet_run(
            request=self.build_request(expected_contact_id=contact.id)
        )
        packet_result = json.loads(packet_run.result)
        extracted = packet_result["extracted_listings"]

        submission = agent_schemas.ListingAlertManualReviewSubmissionRequest(
            source_run_id=packet_run.id,
            shortlisted_listings=[
                agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                    listing_ref=extracted[0]["listing_ref"],
                    rank=1,
                    why_selected=["Strong area and budget fit."],
                ),
                agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                    listing_ref=extracted[1]["listing_ref"],
                    rank=2,
                    why_selected=["Useful fallback option with similar fit."],
                ),
            ],
            tradeoff_notes=["Parking should be confirmed before sharing externally."],
            recommendation_reasoning=(
                "These two listings are the strongest fit against the current budget,"
                " area, and condo preference."
            ),
            client_facing_drafts=[
                agent_schemas.ListingAlertClientDraftSubmissionItem(
                    variant="shortlist_summary",
                    subject="Listings worth reviewing",
                    body="I pulled together two options that look worth reviewing together.",
                )
            ],
            operator_notes=["Reviewed in ChatGPT Pro externally before submission."],
        )

        submission_run = listing_alert_recommendation.submit_listing_alert_manual_review(
            self.db,
            submission,
        )
        result = json.loads(submission_run.result)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == submission_run.id)
            .all()
        )
        task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == submission_run.task_id)
            .first()
        )

        self.assertEqual(submission_run.task_id, packet_run.task_id)
        self.assertEqual(submission_run.status, "waiting_approval")
        self.assertEqual(task.status, "waiting_approval")
        self.assertEqual(result["review_outcome"], "waiting_approval")
        self.assertEqual(len(result["shortlisted_listings"]), 2)
        self.assertEqual(len(result["client_facing_drafts"]), 1)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(
            approvals[0].action_type,
            "send_listing_alert_recommendation_draft",
        )
        approval_payload = json.loads(approvals[0].payload)
        self.assertEqual(approval_payload["contact_id"], contact.id)
        self.assertEqual(approval_payload["review_mode"], "manual_only")
        self.assertEqual(approval_payload["source_run_id"], packet_run.id)
        self.assertEqual(
            result["client_facing_drafts"][0]["approval_id"],
            approvals[0].id,
        )
        actions = self.get_audit_actions(submission_run.id)
        self.assertIn("listing_alert_manual_review_submitted", actions)
        self.assertIn("listing_alert_manual_review_approval_created", actions)

    def test_manual_review_submission_without_draft_completes_without_approval(self):
        contact = self.create_contact()
        packet_run = self.prepare_packet_run(
            request=self.build_request(expected_contact_id=contact.id)
        )
        packet_result = json.loads(packet_run.result)
        extracted = packet_result["extracted_listings"]

        submission_run = listing_alert_recommendation.submit_listing_alert_manual_review(
            self.db,
            {
                "source_run_id": packet_run.id,
                "shortlisted_listings": [
                    {
                        "listing_ref": extracted[0]["listing_ref"],
                        "rank": 1,
                        "why_selected": ["Best fit after manual review."],
                    }
                ],
                "tradeoff_notes": ["Need to confirm maintenance fees manually."],
                "recommendation_reasoning": "Only one listing feels strong enough to keep.",
                "client_facing_drafts": [],
                "operator_notes": ["Do not send anything yet."],
            },
        )
        result = json.loads(submission_run.result)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == submission_run.id)
            .all()
        )

        self.assertEqual(submission_run.status, "completed")
        self.assertEqual(result["review_outcome"], "completed_no_draft")
        self.assertEqual(result["client_facing_drafts"], [])
        self.assertEqual(approvals, [])
        self.assertIn(
            "listing_alert_manual_review_completed_no_draft",
            self.get_audit_actions(submission_run.id),
        )

    def test_manual_review_submission_validation_failure_fails_safely(self):
        contact = self.create_contact()
        packet_run = self.prepare_packet_run(
            request=self.build_request(expected_contact_id=contact.id)
        )
        packet_task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == packet_run.task_id)
            .first()
        )

        submission_run = listing_alert_recommendation.submit_listing_alert_manual_review(
            self.db,
            {
                "source_run_id": packet_run.id,
                "shortlisted_listings": [],
                "tradeoff_notes": [],
                "recommendation_reasoning": "   ",
                "client_facing_drafts": [
                    {
                        "variant": "shortlist_summary",
                        "subject": "One",
                        "body": "Draft one",
                    },
                    {
                        "variant": "shortlist_summary",
                        "subject": "Two",
                        "body": "Draft two",
                    },
                ],
                "operator_notes": [],
            },
        )
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == submission_run.id)
            .all()
        )

        self.assertEqual(submission_run.status, "failed")
        self.assertEqual(packet_task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertIn(
            submission_run.error,
            {"recommendation_reasoning_missing", "draft_limit_exceeded"},
        )
        self.assertIn(
            "listing_alert_manual_review_validation_failed",
            self.get_audit_actions(submission_run.id),
        )

    def test_manual_review_submission_from_blocked_source_run_cannot_create_approval(self):
        self.create_contact(name="Buyer One", email="buyer1@example.com")
        self.create_contact(name="Buyer Two", email="buyer2@example.com")
        blocked_packet_run = self.prepare_packet_run(request=self.build_request())

        submission_run = listing_alert_recommendation.submit_listing_alert_manual_review(
            self.db,
            {
                "source_run_id": blocked_packet_run.id,
                "shortlisted_listings": [],
                "tradeoff_notes": [],
                "recommendation_reasoning": "The source packet was not reviewable.",
                "client_facing_drafts": [],
                "operator_notes": [],
            },
        )
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == submission_run.id)
            .all()
        )

        self.assertEqual(submission_run.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(submission_run.error, "source_packet_not_reviewable")
        self.assertIn(
            "listing_alert_manual_review_validation_failed",
            self.get_audit_actions(submission_run.id),
        )

    def test_router_latest_returns_safe_empty_contract(self):
        payload = agent_router.get_latest_listing_alert_recommendation_result(db=self.db)

        self.assertEqual(
            payload,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

    def test_router_prepare_and_read_packet_run_report(self):
        contact = self.create_contact()
        request = self.build_request(expected_contact_id=contact.id)

        run = agent_router.prepare_listing_alert_manual_packet(request, db=self.db)
        latest = agent_router.get_latest_listing_alert_recommendation_result(db=self.db)
        report = agent_router.get_listing_alert_recommendation_run_report(run.id, db=self.db)
        logs = agent_router.list_listing_alert_recommendation_run_audit_logs(
            run.id,
            db=self.db,
        )

        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["result"]["execution_status"], "packet_ready")
        self.assertEqual(report["run_id"], run.id)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["result"]["execution_status"], "packet_ready")
        self.assertIn(
            "listing_alert_manual_packet_prepared",
            [log.action for log in logs],
        )

    def test_router_submit_review_and_surface_pending_then_history_approvals(self):
        contact = self.create_contact()
        packet_run = agent_router.prepare_listing_alert_manual_packet(
            self.build_request(expected_contact_id=contact.id),
            db=self.db,
        )
        packet_result = json.loads(packet_run.result)
        extracted = packet_result["extracted_listings"]

        submission_run = agent_router.submit_listing_alert_manual_review(
            agent_schemas.ListingAlertManualReviewSubmissionRequest(
                source_run_id=packet_run.id,
                shortlisted_listings=[
                    agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                        listing_ref=extracted[0]["listing_ref"],
                        rank=1,
                        why_selected=["Strongest match after manual review."],
                    )
                ],
                tradeoff_notes=["Confirm exact maintenance fee before sending."],
                recommendation_reasoning="One listing clearly stands out.",
                client_facing_drafts=[
                    agent_schemas.ListingAlertClientDraftSubmissionItem(
                        subject="One listing to review",
                        body="I found one listing that looks worth reviewing together.",
                    )
                ],
                operator_notes=["Prepared from external ChatGPT review."],
            ),
            db=self.db,
        )

        pending = agent_router.list_listing_alert_recommendation_pending_approvals(
            db=self.db
        )
        report = agent_router.get_listing_alert_recommendation_run_report(
            submission_run.id,
            db=self.db,
        )

        self.assertEqual(submission_run.status, "waiting_approval")
        self.assertEqual({item.run_id for item in pending}, {submission_run.id})
        self.assertEqual(report["status"], "waiting_approval")
        self.assertEqual(report["result"]["review_outcome"], "waiting_approval")

        agent_router.approve_agent_action(pending[0].id, db=self.db)
        history = agent_router.list_listing_alert_recommendation_approval_history(
            db=self.db
        )
        latest = agent_router.get_latest_listing_alert_recommendation_result(db=self.db)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "approved")
        self.assertEqual(latest["run_id"], submission_run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["result"]["review_outcome"], "waiting_approval")

    def test_router_report_surfaces_failed_submission_without_hiding_error(self):
        self.create_contact(name="Buyer One", email="buyer1@example.com")
        self.create_contact(name="Buyer Two", email="buyer2@example.com")
        blocked_packet_run = agent_router.prepare_listing_alert_manual_packet(
            self.build_request(),
            db=self.db,
        )

        failed_submission_run = agent_router.submit_listing_alert_manual_review(
            agent_schemas.ListingAlertManualReviewSubmissionRequest(
                source_run_id=blocked_packet_run.id,
                shortlisted_listings=[],
                tradeoff_notes=[],
                recommendation_reasoning="This should fail because the packet was blocked.",
                client_facing_drafts=[],
                operator_notes=[],
            ),
            db=self.db,
        )
        report = agent_router.get_listing_alert_recommendation_run_report(
            failed_submission_run.id,
            db=self.db,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error"], "source_packet_not_reviewable")
        self.assertIsNone(report["result"])

    def test_router_audit_logs_and_report_stay_scoped_to_listing_alert_runs(self):
        contact = self.create_contact()
        listing_run = agent_router.prepare_listing_alert_manual_packet(
            self.build_request(expected_contact_id=contact.id),
            db=self.db,
        )
        other_task = agent_models.AgentTask(agent_type="buyer_match", status="completed")
        self.db.add(other_task)
        self.db.commit()
        self.db.refresh(other_task)
        other_run = agent_models.AgentRun(
            task_id=other_task.id,
            status="completed",
            summary="other",
            result="{}",
        )
        self.db.add(other_run)
        self.db.commit()
        self.db.refresh(other_run)

        with self.assertRaises(HTTPException) as error:
            agent_router.list_listing_alert_recommendation_run_audit_logs(
                other_run.id,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 404)

        scoped_report = agent_router.get_listing_alert_recommendation_run_report(
            listing_run.id,
            db=self.db,
        )
        self.assertEqual(scoped_report["run_id"], listing_run.id)

    def test_router_automatic_run_once_returns_batch_summary(self):
        self.create_contact(name="Mia Chen", email="mia@example.com")
        message = self.sale_alert_message(subject="Toronto MLS Alert for Mia Chen")
        message.message_id = "router-auto-1"
        message.thread_id = "router-thread-1"

        with patch.object(
            listing_alert_recommendation_gmail,
            "fetch_gmail_candidates",
            return_value=agent_schemas.ListingAlertGmailFetchCandidatesResponse(
                gmail_user_id="me",
                query='from:"alerts@mls.example" subject:"Toronto MLS Alert"',
                matched_message_count=1,
                candidate_count=1,
                candidates=[
                    self.automatic_candidate(
                        message_id="router-auto-1",
                        thread_id="router-thread-1",
                        subject="Toronto MLS Alert for Mia Chen",
                    )
                ],
            ),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "_resolve_gmail_read_config_for_execution",
            return_value=self.automatic_resolved_gmail_config(),
        ), patch.object(
            listing_alert_recommendation_gmail,
            "fetch_normalized_gmail_message",
            return_value=message,
        ):
            result = agent_router.run_listing_alert_recommendation_automatic_once(
                self.build_automatic_request(),
                db=self.db,
            )

        self.assertEqual(result.processed_message_count, 1)
        self.assertEqual(result.waiting_approval_count, 1)
        self.assertEqual(result.outcomes[0].status, "waiting_approval")
        self.assertIsNotNone(result.outcomes[0].run_id)
        self.assertIsNotNone(result.outcomes[0].review_run_id)

    def test_router_automatic_latest_empty_and_run_read_routes(self):
        empty_latest = agent_router.get_latest_listing_alert_recommendation_automatic_result(
            db=self.db
        )
        self.assertEqual(
            empty_latest,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

        waiting_batch = self.run_automatic_waiting_approval_batch(
            message_id="auto-route-waiting-1",
            thread_id="auto-route-thread-waiting-1",
        )
        no_draft_batch = self.run_automatic_completed_no_draft_batch(
            message_id="auto-route-nodraft-1",
            thread_id="auto-route-thread-nodraft-1",
        )
        manual_run = agent_router.prepare_listing_alert_manual_packet(
            self.build_request(expected_contact_id=self.create_contact(
                name="Manual Buyer",
                email="manual@example.com",
            ).id),
            db=self.db,
        )

        automatic_runs = agent_router.list_listing_alert_recommendation_automatic_runs(
            db=self.db,
            limit=10,
        )
        automatic_run_ids = [run.id for run in automatic_runs]

        self.assertEqual(len(automatic_runs), 4)
        self.assertNotIn(manual_run.id, automatic_run_ids)
        self.assertTrue(
            all(
                json.loads(run.task.payload)["execution_mode"] == "automatic"
                for run in automatic_runs
            )
        )

        latest = agent_router.get_latest_listing_alert_recommendation_automatic_result(
            db=self.db
        )
        latest_review_run_id = no_draft_batch.outcomes[0].review_run_id
        self.assertEqual(latest["run_id"], latest_review_run_id)
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["result"]["workflow_mode"], "automatic")
        self.assertEqual(latest["result"]["review_outcome"], "completed_no_draft")

        report = agent_router.get_listing_alert_recommendation_automatic_run_report(
            latest_review_run_id,
            db=self.db,
        )
        self.assertEqual(report["run_id"], latest_review_run_id)
        self.assertEqual(report["result"]["workflow_mode"], "automatic")
        self.assertEqual(report["result"]["review_outcome"], "completed_no_draft")

        with self.assertRaises(HTTPException) as error:
            agent_router.get_listing_alert_recommendation_automatic_run_report(
                manual_run.id,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 404)

        waiting_packet_run_id = waiting_batch.outcomes[0].run_id
        waiting_packet_audits = (
            agent_router.list_listing_alert_recommendation_automatic_run_audit_logs(
                waiting_packet_run_id,
                db=self.db,
            )
        )
        self.assertIn(
            "listing_alert_automatic_packet_prepared",
            [log.action for log in waiting_packet_audits],
        )

        with self.assertRaises(HTTPException) as error:
            agent_router.list_listing_alert_recommendation_automatic_run_audit_logs(
                manual_run.id,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_router_automatic_approvals_and_history_are_scoped(self):
        automatic_batch = self.run_automatic_waiting_approval_batch(
            message_id="auto-approval-1",
            thread_id="auto-approval-thread-1",
        )
        manual_contact = self.create_contact(name="Manual Approval Buyer", email="manual-approval@example.com")
        manual_packet_run = agent_router.prepare_listing_alert_manual_packet(
            self.build_request(expected_contact_id=manual_contact.id),
            db=self.db,
        )
        manual_packet_result = json.loads(manual_packet_run.result)
        manual_submission_run = agent_router.submit_listing_alert_manual_review(
            agent_schemas.ListingAlertManualReviewSubmissionRequest(
                source_run_id=manual_packet_run.id,
                shortlisted_listings=[
                    agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                        listing_ref=manual_packet_result["extracted_listings"][0]["listing_ref"],
                        rank=1,
                        why_selected=["Manual review selected this listing."],
                    )
                ],
                tradeoff_notes=[],
                recommendation_reasoning="Manual review reasoning.",
                client_facing_drafts=[
                    agent_schemas.ListingAlertClientDraftSubmissionItem(
                        subject="Manual shortlist",
                        body="Manual mode draft.",
                    )
                ],
                operator_notes=[],
            ),
            db=self.db,
        )

        pending = agent_router.list_listing_alert_recommendation_automatic_pending_approvals(
            db=self.db
        )
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].run_id, automatic_batch.outcomes[0].review_run_id)
        self.assertNotEqual(pending[0].run_id, manual_submission_run.id)

        agent_router.approve_agent_action(pending[0].id, db=self.db)
        history = agent_router.list_listing_alert_recommendation_automatic_approval_history(
            db=self.db
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "approved")
        self.assertEqual(history[0].run_id, automatic_batch.outcomes[0].review_run_id)


class AutoGenerateReviewShortlistGateTests(unittest.TestCase):
    """Verify the hard-fit gate in ``_auto_generate_review``.

    These tests isolate the gate itself and do not go through the database.
    """

    def _make_association(self) -> agent_schemas.ListingAlertClientAssociationResponse:
        return agent_schemas.ListingAlertClientAssociationResponse(
            status="matched",
            method="expected_contact_id",
            contact_id=99,
            contact_name="Julia Tsai",
        )

    def _make_contact_context(self) -> dict:
        return {
            "contact_name": "Julia Tsai",
            "budget_min": 500000,
            "budget_max": 700000,
            "preferred_areas": ["Midtown", "Yonge-Eglinton"],
            "preferred_property_types": ["condo", "condo_apartment"],
        }

    def _make_listing(
        self,
        *,
        listing_ref: str,
        fit_strength: agent_schemas.ListingAlertFitStrength,
        criteria: list[tuple[str, agent_schemas.ListingAlertCriterionVerdict]],
        fit_score: float = 1.0,
    ) -> agent_schemas.ListingAlertNormalizedListing:
        return agent_schemas.ListingAlertNormalizedListing(
            listing_ref=listing_ref,
            address=f"{listing_ref} Test Lane",
            price=899000.0,
            market_type="sale",
            property_type="detached",
            source_excerpt="test",
            fit_analysis=agent_schemas.ListingAlertFitAnalysis(
                listing_ref=listing_ref,
                fit_score=fit_score,
                fit_strength=fit_strength,
                why_it_fits=["exceeds 1+ bedroom target with 2 beds"],
                tradeoffs=["over budget", "outside preferred area"],
                criteria_comparison=[
                    agent_schemas.ListingAlertFitCriterionComparison(
                        criterion=crit,
                        verdict=verdict,
                    )
                    for crit, verdict in criteria
                ],
            ),
        )

    def test_limited_fit_with_hard_mismatches_is_excluded(self):
        listing = self._make_listing(
            listing_ref="L1",
            fit_strength="limited",
            criteria=[
                ("budget", "over_budget"),
                ("area", "mismatch"),
                ("property_type", "mismatch"),
            ],
        )
        result = listing_alert_recommendation._auto_generate_review(
            [listing],
            self._make_association(),
            self._make_contact_context(),
        )
        self.assertEqual(result.shortlist, [])
        self.assertEqual(result.client_facing_drafts, [])
        reasoning_lower = result.recommendation_reasoning.lower()
        self.assertIn("declined to shortlist", reasoning_lower)
        self.assertIn("no client-facing draft", reasoning_lower)
        self.assertTrue(
            any("manual review" in note.lower() for note in result.operator_notes),
            result.operator_notes,
        )

    def test_limited_fit_with_over_budget_only_is_excluded(self):
        listing = self._make_listing(
            listing_ref="L2",
            fit_strength="limited",
            criteria=[
                ("budget", "over_budget"),
                ("area", "match"),
                ("property_type", "match"),
            ],
        )
        result = listing_alert_recommendation._auto_generate_review(
            [listing],
            self._make_association(),
            self._make_contact_context(),
        )
        self.assertEqual(result.shortlist, [])
        self.assertEqual(result.client_facing_drafts, [])

    def test_strong_fit_with_mismatch_still_shortlists(self):
        # Stronger fits are trusted; gate only applies to limited.
        listing = self._make_listing(
            listing_ref="L3",
            fit_strength="strong",
            fit_score=3.0,
            criteria=[
                ("budget", "match"),
                ("area", "mismatch"),
                ("property_type", "match"),
            ],
        )
        result = listing_alert_recommendation._auto_generate_review(
            [listing],
            self._make_association(),
            self._make_contact_context(),
        )
        self.assertEqual(len(result.shortlist), 1)
        self.assertEqual(result.shortlist[0].listing_ref, "L3")
        self.assertEqual(len(result.client_facing_drafts), 1)

    def test_qualifying_listing_passes_even_when_others_are_rejected(self):
        bad = self._make_listing(
            listing_ref="BAD",
            fit_strength="limited",
            fit_score=1.0,
            criteria=[
                ("budget", "over_budget"),
                ("area", "mismatch"),
                ("property_type", "mismatch"),
            ],
        )
        good = self._make_listing(
            listing_ref="GOOD",
            fit_strength="moderate",
            fit_score=2.5,
            criteria=[
                ("budget", "match"),
                ("area", "match"),
                ("property_type", "match"),
            ],
        )
        result = listing_alert_recommendation._auto_generate_review(
            [bad, good],
            self._make_association(),
            self._make_contact_context(),
        )
        self.assertEqual([item.listing_ref for item in result.shortlist], ["GOOD"])
        self.assertTrue(
            any("skipped candidates" in note.lower() for note in result.operator_notes),
            result.operator_notes,
        )


if __name__ == "__main__":
    unittest.main()
