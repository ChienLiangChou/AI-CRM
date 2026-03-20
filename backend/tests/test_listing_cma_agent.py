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
from app.agents import listing_cma
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import service as agent_service
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ListingCmaAgentTests(unittest.TestCase):
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
            "name": "Jane Seller",
            "email": "jane@example.com",
            "company": "Harbour Homes",
            "client_type": "seller",
            "lead_score": 72,
            "stage_id": self.stage.id,
            "status": "active",
            "notes": "Seller preparing for a downtown Toronto listing discussion.",
            "created_at": utcnow_naive() - timedelta(days=30),
            "last_contacted_at": utcnow_naive() - timedelta(days=3),
        }
        defaults.update(overrides)
        contact = crm_models.Contact(**defaults)
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def create_property(self, **overrides):
        defaults = {
            "street": "20 Stewart St",
            "unit": "706",
            "city": "Toronto",
            "province": "ON",
            "neighborhood": "King West",
            "property_type": "condo",
            "status": "off_market",
            "bedrooms": 2,
            "bathrooms": 2,
            "sqft": 800,
            "parking": 1,
            "listing_price": None,
            "notes": "South-facing suite with renovated kitchen.",
            "created_at": utcnow_naive() - timedelta(days=120),
        }
        defaults.update(overrides)
        property_record = crm_models.Property(**defaults)
        self.db.add(property_record)
        self.db.commit()
        self.db.refresh(property_record)
        return property_record

    def get_task(self, task_id: int):
        return (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == task_id)
            .first()
        )

    def create_agent_run(self, *, agent_type: str, status: str = "completed", result: str = "{}"):
        task = agent_service.create_task(self.db, agent_type=agent_type)
        run = agent_service.create_run(self.db, task=task, summary=agent_type)
        return agent_service.update_run_status(
            self.db,
            run,
            status=status,
            result=result,
            started_at=utcnow_naive(),
            finished_at=utcnow_naive(),
        )

    def get_audit_actions(self, run_id: int) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )
        return [log.action for log in logs]

    def build_request(self, contact_id: int, property_id: int | None, comparables=None):
        comparable_items = comparables if comparables is not None else [
            agent_schemas.ListingCmaComparableInput(
                address="123 King St W #1205",
                status="sold",
                price=845000,
                close_date="2026-02-12",
                property_type="condo",
                bedrooms=2,
                bathrooms=2,
                sqft=790,
                notes="Older finishes.",
            ),
            agent_schemas.ListingCmaComparableInput(
                address="88 Blue Jays Way #2108",
                status="active",
                price=879000,
                property_type="condo",
                bedrooms=2,
                bathrooms=2,
                sqft=805,
                notes="No parking.",
            ),
        ]
        return agent_schemas.ListingCmaRunRequest(
            contact_id=contact_id,
            property_id=property_id,
            meeting_goal="listing_appointment_prep",
            subject_property_notes="Renovated kitchen and south-facing exposure.",
            seller_context_notes="Seller wants pricing support before a listing appointment.",
            comparables=comparable_items,
        )

    @patch(
        "app.crud._send_push",
        side_effect=AssertionError("_send_push should not be called"),
    )
    @patch("app.agents.tools.call_llm_tool")
    def test_manual_trigger_creates_single_review_only_seller_draft(
        self,
        mock_call_llm_tool,
        mock_send_push,
    ):
        contact = self.create_contact()
        property_record = self.create_property(owner_client_id=contact.id)
        mock_call_llm_tool.return_value = json.dumps(
            {
                "subject": "Summary from today",
                "body": "Draft summary body",
            }
        )
        request = self.build_request(contact.id, property_record.id)

        run = listing_cma.run_listing_cma_once(self.db, request)
        approvals = self.db.query(agent_models.AgentApproval).all()
        interactions = self.db.query(crm_models.Interaction).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(result["seller_drafts"]), 1)
        self.assertEqual(
            result["seller_drafts"][0]["variant"],
            "post_meeting_summary",
        )
        self.assertIsNotNone(result["cma_support"]["internal_price_discussion_range"])
        self.assertEqual(
            result["cma_support"]["range_framing"],
            "Internal discussion support only. Not final list-price authority.",
        )
        self.assertEqual(interactions, [])
        self.assertFalse(mock_send_push.called)
        self.assertEqual(approvals[0].action_type, "send_listing_cma_summary")
        self.assertEqual(approvals[0].risk_level, "high")
        payload = json.loads(approvals[0].payload)
        self.assertEqual(payload["review_mode"], "manual_only")
        self.assertEqual(
            payload["pricing_framing"],
            "Internal discussion support only. Not final list-price authority.",
        )
        actions = self.get_audit_actions(run.id)
        self.assertIn("listing_cma_context_loaded", actions)
        self.assertIn("listing_cma_analysis_generated", actions)
        self.assertIn("generate_listing_cma_seller_draft", actions)
        self.assertIn("listing_cma_run_waiting_approval", actions)

    @patch("app.agents.tools.call_llm_tool")
    def test_missing_comparables_returns_internal_only_output(
        self,
        mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property(owner_client_id=contact.id)
        request = self.build_request(contact.id, property_record.id, comparables=[])

        run = listing_cma.run_listing_cma_once(self.db, request)
        approvals = self.db.query(agent_models.AgentApproval).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(result["seller_drafts"], [])
        self.assertIsNone(result["cma_support"]["internal_price_discussion_range"])
        self.assertIn(
            "manual_comparables_missing",
            result["cma_support"]["missing_data_flags"],
        )
        self.assertIn("insufficient_comparable_data", result["risk_flags"])
        self.assertIn("listing_cma_insufficient_comparables", self.get_audit_actions(run.id))
        mock_call_llm_tool.assert_not_called()

    def test_invalid_property_fails_safely(self):
        contact = self.create_contact()
        request = self.build_request(contact.id, 999)

        run = listing_cma.run_listing_cma_once(self.db, request)
        task = self.get_task(run.task_id)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(run.error, "property_not_found")
        self.assertIn("listing_cma_run_failed", self.get_audit_actions(run.id))

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_fallback_seller_draft_is_generated_when_llm_returns_empty(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property(owner_client_id=contact.id)
        request = self.build_request(contact.id, property_record.id)

        run = listing_cma.run_listing_cma_once(self.db, request)
        result = json.loads(run.result)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(result["seller_drafts"]), 1)
        self.assertTrue(result["seller_drafts"][0]["subject"])
        self.assertTrue(result["seller_drafts"][0]["body"])
        self.assertEqual(
            result["cma_support"]["range_framing"],
            "Internal discussion support only. Not final list-price authority.",
        )

    @patch("app.agents.tools.call_llm_tool")
    def test_router_endpoints_return_listing_cma_only_data(
        self,
        mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property(owner_client_id=contact.id)
        mock_call_llm_tool.return_value = json.dumps(
            {
                "subject": "Summary from today",
                "body": "Draft summary body",
            }
        )

        request = self.build_request(contact.id, property_record.id)
        run = agent_router.trigger_listing_cma_run_once(request, db=self.db)

        follow_up_run = self.create_agent_run(
            agent_type="follow_up",
            status="waiting_approval",
            result=json.dumps({"recommendations": [], "drafts": []}),
        )
        conversation_run = self.create_agent_run(
            agent_type="conversation_closer",
            status="waiting_approval",
            result=json.dumps(
                {
                    "summary": "Other agent",
                    "objection_analysis": {
                        "primary_type": "shopping_around",
                        "secondary_types": [],
                        "sentiment": "guarded",
                        "confidence": 0.8,
                        "urgency": "medium",
                        "requires_manual_escalation": False,
                    },
                    "strategy": {
                        "recommended_action": "review_and_send_reply",
                        "goal": "retain_client",
                        "tone": "measured",
                        "rationale": "test",
                        "do_not_say": [],
                    },
                    "talking_points": [],
                    "drafts": [],
                    "risk_flags": [],
                    "operator_notes": [],
                }
            ),
        )
        agent_service.create_approval(
            self.db,
            run=follow_up_run,
            action_type="send_email",
            payload=json.dumps({"review_mode": "manual_only"}),
        )
        agent_service.create_approval(
            self.db,
            run=conversation_run,
            action_type="send_client_reply",
            payload=json.dumps({"review_mode": "manual_only"}),
        )

        runs = agent_router.list_listing_cma_runs(db=self.db)
        latest = agent_router.get_latest_listing_cma_result(db=self.db)
        approvals = agent_router.list_listing_cma_pending_approvals(db=self.db)

        self.assertEqual([item.id for item in runs], [run.id])
        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "waiting_approval")
        self.assertIsNone(latest["error"])
        self.assertEqual(len(latest["result"]["seller_drafts"]), 1)
        self.assertEqual(
            latest["result"]["cma_support"]["range_framing"],
            "Internal discussion support only. Not final list-price authority.",
        )
        self.assertEqual({item.run_id for item in approvals}, {run.id})

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_history_and_audit_endpoints_stay_scoped_to_listing_cma(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property(owner_client_id=contact.id)
        request = self.build_request(contact.id, property_record.id)

        run = agent_router.trigger_listing_cma_run_once(request, db=self.db)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .order_by(agent_models.AgentApproval.created_at.asc())
            .all()
        )
        agent_router.approve_agent_action(approvals[0].id, db=self.db)

        other_run = self.create_agent_run(
            agent_type="conversation_closer",
            status="waiting_approval",
            result="{}",
        )
        other_approval = agent_service.create_approval(
            self.db,
            run=other_run,
            action_type="send_client_reply",
            payload=json.dumps({"review_mode": "manual_only"}),
        )
        agent_router.reject_agent_action(
            other_approval.id,
            reason="Not listing-cma",
            db=self.db,
        )

        history = agent_router.list_listing_cma_approval_history(db=self.db)
        logs = agent_router.list_listing_cma_run_audit_logs(run.id, db=self.db)
        actions = [log.action for log in logs]

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].run_id, run.id)
        self.assertEqual(history[0].status, "approved")
        self.assertIn("approve_agent_action", actions)
        self.assertIn("listing_cma_review_completed", actions)
        self.assertNotIn("follow_up_review_completed", actions)
        self.assertNotIn("conversation_closer_review_completed", actions)

        with self.assertRaises(HTTPException) as error:
            agent_router.list_listing_cma_run_audit_logs(other_run.id, db=self.db)
        self.assertEqual(error.exception.status_code, 404)

    def test_latest_endpoint_returns_safe_empty_or_invalid_contract(self):
        empty_payload = agent_router.get_latest_listing_cma_result(db=self.db)
        self.assertEqual(
            empty_payload,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

        task = agent_service.create_task(self.db, agent_type="listing_cma")
        run = agent_service.create_run(self.db, task=task, summary="bad result")
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        payload = agent_router.get_latest_listing_cma_result(db=self.db)
        self.assertEqual(payload["run_id"], run.id)
        self.assertEqual(payload["status"], "completed")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["result"])


if __name__ == "__main__":
    unittest.main()
