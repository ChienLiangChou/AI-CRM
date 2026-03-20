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
from app.agents import buyer_match
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import service as agent_service
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BuyerMatchAgentTests(unittest.TestCase):
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
            "company": "Skyline Buyer",
            "client_type": "buyer",
            "lead_score": 68,
            "stage_id": self.stage.id,
            "status": "active",
            "notes": "Buyer wants a practical downtown shortlist.",
            "budget_min": 700000,
            "budget_max": 900000,
            "preferred_areas": json.dumps(["King West", "CityPlace"]),
            "property_preferences": json.dumps(
                {
                    "types": ["condo"],
                    "bedrooms_min": 2,
                    "bathrooms_min": 2,
                    "parking_required": True,
                    "must_haves": ["good transit"],
                }
            ),
            "created_at": utcnow_naive() - timedelta(days=20),
            "last_contacted_at": utcnow_naive() - timedelta(days=2),
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
            "status": "listed_for_sale",
            "bedrooms": 2,
            "bathrooms": 2,
            "sqft": 800,
            "parking": 1,
            "listing_price": 859000,
            "notes": "South-facing layout near transit.",
            "created_at": utcnow_naive() - timedelta(days=60),
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

    def get_audit_actions(self, run_id: int) -> list[str]:
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )
        return [log.action for log in logs]

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

    def build_request(
        self,
        contact_id: int,
        property_id: int | None = None,
        candidates: list[agent_schemas.BuyerMatchCandidateInput] | None = None,
    ):
        candidate_items = candidates if candidates is not None else [
            agent_schemas.BuyerMatchCandidateInput(
                property_id=property_id,
                notes="Parking included and close to transit.",
            ),
            agent_schemas.BuyerMatchCandidateInput(
                address="87 Fort York Blvd #1908",
                list_price=889000,
                property_type="condo",
                bedrooms=2,
                bathrooms=2,
                sqft=760,
                area="CityPlace",
                parking=0,
                notes="Good area fit but no parking.",
            ),
        ]
        return agent_schemas.BuyerMatchRunRequest(
            contact_id=contact_id,
            goal="shortlist_prep",
            criteria=agent_schemas.BuyerMatchCriteriaInput(
                budget_min=700000,
                budget_max=900000,
                areas=["King West", "CityPlace"],
                property_type="condo",
                bedrooms_min=2,
                bathrooms_min=2,
                parking_required=True,
                must_haves=["transit access"],
            ),
            buyer_context_notes="Buyer wants the best 2 practical options, not a long list.",
            candidates=candidate_items,
        )

    @patch(
        "app.crud._send_push",
        side_effect=AssertionError("_send_push should not be called"),
    )
    @patch("app.agents.tools.call_llm_tool")
    def test_manual_trigger_creates_single_review_only_buyer_draft(
        self,
        mock_call_llm_tool,
        mock_send_push,
    ):
        contact = self.create_contact()
        property_record = self.create_property()
        mock_call_llm_tool.return_value = json.dumps(
            {
                "subject": "Shortlist to review",
                "body": "Here are the top options to review together.",
            }
        )
        request = self.build_request(contact.id, property_record.id)

        run = buyer_match.run_buyer_match_once(self.db, request)
        approvals = self.db.query(agent_models.AgentApproval).all()
        interactions = self.db.query(crm_models.Interaction).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(result["buyer_drafts"]), 1)
        self.assertEqual(result["buyer_drafts"][0]["variant"], "shortlist_summary")
        self.assertEqual(
            result["shortlist_framing"],
            "Internal shortlist support only. Not final purchase or offer advice.",
        )
        self.assertTrue(result["shortlist"])
        self.assertFalse(mock_send_push.called)
        self.assertEqual(interactions, [])
        self.assertEqual(approvals[0].action_type, "send_buyer_shortlist_summary")
        self.assertEqual(approvals[0].risk_level, "high")
        payload = json.loads(approvals[0].payload)
        self.assertEqual(payload["review_mode"], "manual_only")
        self.assertEqual(
            payload["shortlist_framing"],
            "Internal shortlist support only. Not final purchase or offer advice.",
        )
        self.assertEqual(len(payload["shortlist_titles"]), 2)
        self.assertNotIn("offer", result["recommended_next_manual_action"].lower())
        self.assertNotIn("negotiat", result["recommended_next_manual_action"].lower())
        actions = self.get_audit_actions(run.id)
        self.assertIn("buyer_match_context_loaded", actions)
        self.assertIn("buyer_match_analysis_generated", actions)
        self.assertIn("generate_buyer_match_draft", actions)
        self.assertIn("buyer_match_run_waiting_approval", actions)

    @patch("app.agents.tools.call_llm_tool")
    def test_no_candidates_returns_internal_only_output(
        self,
        mock_call_llm_tool,
    ):
        contact = self.create_contact()
        request = self.build_request(contact.id, None, candidates=[])

        run = buyer_match.run_buyer_match_once(self.db, request)
        approvals = self.db.query(agent_models.AgentApproval).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(result["shortlist"], [])
        self.assertEqual(result["buyer_drafts"], [])
        self.assertIn("manual_candidates_missing", result["missing_data_flags"])
        self.assertIn("insufficient_candidate_data", result["risk_flags"])
        self.assertIn("buyer_match_candidate_set_missing", self.get_audit_actions(run.id))
        mock_call_llm_tool.assert_not_called()

    def test_candidate_count_over_cap_fails_safely(self):
        contact = self.create_contact()
        candidates = [
            agent_schemas.BuyerMatchCandidateInput(address=f"{index} Example St", list_price=800000)
            for index in range(6)
        ]
        request = self.build_request(contact.id, None, candidates=candidates)

        run = buyer_match.run_buyer_match_once(self.db, request)
        task = self.get_task(run.task_id)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(run.error, "candidate_limit_exceeded")
        self.assertIn("buyer_match_run_failed", self.get_audit_actions(run.id))

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_fallback_buyer_draft_is_generated_when_llm_returns_empty(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property()
        request = self.build_request(contact.id, property_record.id)

        run = buyer_match.run_buyer_match_once(self.db, request)
        result = json.loads(run.result)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(result["buyer_drafts"]), 1)
        self.assertTrue(result["buyer_drafts"][0]["subject"])
        self.assertTrue(result["buyer_drafts"][0]["body"])
        self.assertEqual(
            result["shortlist_framing"],
            "Internal shortlist support only. Not final purchase or offer advice.",
        )

    def test_invalid_candidate_property_fails_safely(self):
        contact = self.create_contact()
        request = self.build_request(
            contact.id,
            None,
            candidates=[
                agent_schemas.BuyerMatchCandidateInput(
                    property_id=999,
                )
            ],
        )

        run = buyer_match.run_buyer_match_once(self.db, request)
        task = self.get_task(run.task_id)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(run.error, "candidate_property_not_found")
        self.assertIn("buyer_match_run_failed", self.get_audit_actions(run.id))

    @patch("app.agents.tools.call_llm_tool")
    def test_router_endpoints_return_buyer_match_only_data(
        self,
        mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property()
        mock_call_llm_tool.return_value = json.dumps(
            {
                "subject": "Shortlist to review",
                "body": "Here are the top options to review together.",
            }
        )
        request = self.build_request(contact.id, property_record.id)

        run = agent_router.trigger_buyer_match_run_once(request, db=self.db)

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
        listing_run = self.create_agent_run(
            agent_type="listing_cma",
            status="waiting_approval",
            result=json.dumps(
                {
                    "listing_brief": {
                        "summary": "test",
                        "property_highlights": [],
                        "seller_context": [],
                    },
                    "cma_support": {
                        "internal_price_discussion_range": None,
                        "range_framing": "Internal discussion support only. Not final list-price authority.",
                        "comparable_narrative": [],
                        "missing_data_flags": [],
                    },
                    "talking_points": [],
                    "seller_drafts": [],
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
        agent_service.create_approval(
            self.db,
            run=listing_run,
            action_type="send_listing_cma_summary",
            payload=json.dumps({"review_mode": "manual_only"}),
        )

        runs = agent_router.list_buyer_match_runs(db=self.db)
        latest = agent_router.get_latest_buyer_match_result(db=self.db)
        approvals = agent_router.list_buyer_match_pending_approvals(db=self.db)

        self.assertEqual([item.id for item in runs], [run.id])
        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "waiting_approval")
        self.assertIsNone(latest["error"])
        self.assertEqual(len(latest["result"]["buyer_drafts"]), 1)
        self.assertEqual(
            latest["result"]["shortlist_framing"],
            "Internal shortlist support only. Not final purchase or offer advice.",
        )
        self.assertEqual({item.run_id for item in approvals}, {run.id})

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_history_and_audit_endpoints_stay_scoped_to_buyer_match(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        property_record = self.create_property()
        request = self.build_request(contact.id, property_record.id)

        run = agent_router.trigger_buyer_match_run_once(request, db=self.db)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .order_by(agent_models.AgentApproval.created_at.asc())
            .all()
        )

        agent_router.approve_agent_action(approvals[0].id, db=self.db)

        history = agent_router.list_buyer_match_approval_history(db=self.db)
        logs = agent_router.list_buyer_match_run_audit_logs(run.id, db=self.db)
        actions = [log.action for log in logs]

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "approved")
        self.assertIn("approve_agent_action", actions)
        self.assertIn("buyer_match_review_completed", actions)
        self.assertNotIn("follow_up_review_completed", actions)

        follow_up_run = self.create_agent_run(agent_type="follow_up")
        with self.assertRaises(HTTPException) as error:
            agent_router.list_buyer_match_run_audit_logs(
                follow_up_run.id,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_latest_endpoint_returns_safe_empty_or_invalid_contract(self):
        empty_payload = agent_router.get_latest_buyer_match_result(db=self.db)
        self.assertEqual(
            empty_payload,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

        task = agent_service.create_task(self.db, agent_type="buyer_match")
        run = agent_service.create_run(self.db, task=task, summary="bad result")
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        payload = agent_router.get_latest_buyer_match_result(db=self.db)
        self.assertEqual(payload["run_id"], run.id)
        self.assertEqual(payload["status"], "completed")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["result"])


if __name__ == "__main__":
    unittest.main()
