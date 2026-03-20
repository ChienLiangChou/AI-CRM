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
from app.agents import conversation_closer
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import service as agent_service
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ConversationCloserAgentTests(unittest.TestCase):
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

        self.lead_stage = crm_models.PipelineStage(name="Lead", order=1)
        self.db.add(self.lead_stage)
        self.db.commit()
        self.db.refresh(self.lead_stage)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_contact(self, **overrides):
        defaults = {
            "name": "Jane Seller",
            "email": "jane@example.com",
            "company": "Example Realty",
            "client_type": "seller",
            "lead_score": 75,
            "stage_id": self.lead_stage.id,
            "status": "active",
            "notes": "Preparing to list a downtown condo.",
            "created_at": utcnow_naive() - timedelta(days=35),
            "last_contacted_at": utcnow_naive() - timedelta(days=4),
        }
        defaults.update(overrides)
        contact = crm_models.Contact(**defaults)
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def get_task(self, task_id: int):
        return (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == task_id)
            .first()
        )

    def create_follow_up_run(self, *, status: str = "completed", result: str = "{}"):
        task = agent_service.create_task(self.db, agent_type="follow_up")
        run = agent_service.create_run(self.db, task=task, summary="follow-up")
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

    @patch(
        "app.crud._send_push",
        side_effect=AssertionError("_send_push should not be called"),
    )
    @patch("app.agents.tools.call_llm_tool")
    def test_manual_trigger_creates_at_most_two_reply_approvals(
        self,
        mock_call_llm_tool,
        mock_send_push,
    ):
        contact = self.create_contact()
        mock_call_llm_tool.return_value = json.dumps(
            {
                "variants": [
                    {
                        "variant": "direct_practical",
                        "subject": "Quick follow-up",
                        "body": "Direct response",
                    },
                    {
                        "variant": "relationship_first",
                        "subject": "Appreciate your honesty",
                        "body": "Relationship-first response",
                    },
                    {
                        "variant": "extra_variant",
                        "subject": "Ignore me",
                        "body": "Should not be used",
                    },
                ]
            }
        )
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="We are interviewing other agents and the commission feels high.",
            channel="email",
            operator_goal="retain_seller",
        )

        run = conversation_closer.run_conversation_closer_once(self.db, request)

        approvals = self.db.query(agent_models.AgentApproval).all()
        interactions = self.db.query(crm_models.Interaction).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 2)
        self.assertEqual(len(result["drafts"]), 2)
        self.assertEqual(
            [draft["variant"] for draft in result["drafts"]],
            ["direct_practical", "relationship_first"],
        )
        self.assertEqual(interactions, [])
        self.assertFalse(mock_send_push.called)
        for approval in approvals:
            self.assertEqual(approval.action_type, "send_client_reply")
            self.assertEqual(approval.risk_level, "high")
            payload = json.loads(approval.payload)
            self.assertEqual(payload["review_mode"], "manual_only")
        actions = self.get_audit_actions(run.id)
        self.assertIn("conversation_closer_context_loaded", actions)
        self.assertIn("conversation_closer_analysis_generated", actions)
        self.assertIn("generate_conversation_closer_draft", actions)
        self.assertIn("conversation_closer_run_waiting_approval", actions)

    @patch("app.agents.tools.call_llm_tool")
    def test_legal_risk_completes_without_drafts_or_approvals(
        self,
        mock_call_llm_tool,
    ):
        contact = self.create_contact(client_type="buyer")
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="My lawyer says the contract clause might not be binding. What should I say back?",
            channel="email",
        )

        run = conversation_closer.run_conversation_closer_once(self.db, request)

        approvals = self.db.query(agent_models.AgentApproval).all()
        result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(result["strategy"]["recommended_action"], "manual_escalation_only")
        self.assertTrue(result["objection_analysis"]["requires_manual_escalation"])
        self.assertIn("legal_or_compliance_risk", result["risk_flags"])
        self.assertIn(
            "conversation_closer_manual_escalation_required",
            self.get_audit_actions(run.id),
        )
        mock_call_llm_tool.assert_not_called()

    def test_invalid_interaction_for_contact_fails_safely(self):
        contact = self.create_contact()
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="We need to think about it.",
            interaction_id=999,
        )

        run = conversation_closer.run_conversation_closer_once(self.db, request)
        task = self.get_task(run.task_id)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(run.error, "interaction_not_found_for_contact")
        self.assertIn("conversation_closer_run_failed", self.get_audit_actions(run.id))

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_fallback_drafts_are_generated_when_llm_returns_empty(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="We are still comparing and the fee feels high.",
            channel="email",
        )

        run = conversation_closer.run_conversation_closer_once(self.db, request)
        result = json.loads(run.result)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 2)
        self.assertEqual(len(result["drafts"]), 2)
        self.assertEqual(
            {draft["variant"] for draft in result["drafts"]},
            {"direct_practical", "relationship_first"},
        )
        for draft in result["drafts"]:
            self.assertTrue(draft["body"])

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_router_endpoints_return_conversation_closer_only_data(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="We are still comparing and the fee feels high.",
            channel="email",
        )

        run = agent_router.trigger_conversation_closer_run_once(request, db=self.db)
        follow_up_run = self.create_follow_up_run(
            status="waiting_approval",
            result=json.dumps({"recommendations": [], "drafts": []}),
        )
        agent_service.create_approval(
            self.db,
            run=follow_up_run,
            action_type="send_email",
            payload=json.dumps({"review_mode": "manual_only"}),
        )

        runs = agent_router.list_conversation_closer_runs(db=self.db)
        latest = agent_router.get_latest_conversation_closer_result(db=self.db)
        approvals = agent_router.list_conversation_closer_pending_approvals(db=self.db)

        self.assertEqual([item.id for item in runs], [run.id])
        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "waiting_approval")
        self.assertIsNone(latest["error"])
        self.assertEqual(len(latest["result"]["drafts"]), 2)
        self.assertEqual({item.run_id for item in approvals}, {run.id})

    @patch("app.agents.tools.call_llm_tool", return_value="{}")
    def test_history_and_audit_endpoints_stay_scoped_to_conversation_closer(
        self,
        _mock_call_llm_tool,
    ):
        contact = self.create_contact()
        request = agent_schemas.ConversationCloserRunRequest(
            contact_id=contact.id,
            message="We are interviewing other agents and the commission feels high.",
            channel="email",
        )

        run = agent_router.trigger_conversation_closer_run_once(request, db=self.db)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .order_by(agent_models.AgentApproval.created_at.asc())
            .all()
        )

        agent_router.approve_agent_action(approvals[0].id, db=self.db)
        agent_router.reject_agent_action(
            approvals[1].id,
            reason="Needs a different tone",
            db=self.db,
        )

        history = agent_router.list_conversation_closer_approval_history(db=self.db)
        logs = agent_router.list_conversation_closer_run_audit_logs(run.id, db=self.db)
        actions = [log.action for log in logs]

        self.assertEqual(len(history), 2)
        self.assertEqual({item.status for item in history}, {"approved", "rejected"})
        self.assertIn("approve_agent_action", actions)
        self.assertIn("reject_agent_action", actions)
        self.assertIn("conversation_closer_review_completed", actions)
        self.assertNotIn("follow_up_review_completed", actions)

        follow_up_run = self.create_follow_up_run()
        with self.assertRaises(HTTPException) as error:
            agent_router.list_conversation_closer_run_audit_logs(
                follow_up_run.id,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_latest_endpoint_returns_safe_empty_or_invalid_contract(self):
        empty_payload = agent_router.get_latest_conversation_closer_result(db=self.db)
        self.assertEqual(
            empty_payload,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

        task = agent_service.create_task(self.db, agent_type="conversation_closer")
        run = agent_service.create_run(self.db, task=task, summary="bad result")
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        payload = agent_router.get_latest_conversation_closer_result(db=self.db)
        self.assertEqual(payload["run_id"], run.id)
        self.assertEqual(payload["status"], "completed")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["result"])


if __name__ == "__main__":
    unittest.main()
