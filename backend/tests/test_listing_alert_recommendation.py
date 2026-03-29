import json
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app import models as crm_models
from app.agents import listing_alert_recommendation
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

    def get_audit_actions(self, run_id: int) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
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


if __name__ == "__main__":
    unittest.main()
