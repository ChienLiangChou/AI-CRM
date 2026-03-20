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
from app import schemas as crm_schemas
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import service as agent_service
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class FollowUpAgentBackendVerificationTests(unittest.TestCase):
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
            "name": "Alice Example",
            "email": "alice@example.com",
            "company": "Example Realty",
            "lead_score": 70,
            "stage_id": self.lead_stage.id,
            "status": "active",
            "created_at": utcnow_naive() - timedelta(days=40),
            "last_contacted_at": utcnow_naive() - timedelta(days=10),
        }
        defaults.update(overrides)
        contact = crm_models.Contact(**defaults)
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def get_run(self, run_id: int):
        return (
            self.db.query(agent_models.AgentRun)
            .filter(agent_models.AgentRun.id == run_id)
            .first()
        )

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

    @patch(
        "app.crud._send_push",
        side_effect=AssertionError("_send_push should not be called"),
    )
    @patch("app.agents.tools.draft_email_tool")
    def test_manual_trigger_creates_approval_and_no_send_side_effects(
        self,
        mock_draft_email_tool,
        mock_send_push,
    ):
        self.create_contact()
        mock_draft_email_tool.return_value = crm_schemas.EmailDraftResponse(
            subject="Follow Up",
            body="Draft body",
        )

        run = agent_router.trigger_follow_up_run_once(db=self.db)

        approvals = self.db.query(agent_models.AgentApproval).all()
        interactions = self.db.query(crm_models.Interaction).all()
        run_result = json.loads(run.result)

        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].status, "pending")
        self.assertEqual(approvals[0].action_type, "send_email")
        self.assertEqual(len(run_result["recommendations"]), 1)
        self.assertEqual(len(run_result["drafts"]), 1)
        self.assertEqual(interactions, [])
        self.assertFalse(mock_send_push.called)
        self.assertIn(
            "follow_up_recommendations_generated",
            self.get_audit_actions(run.id),
        )
        self.assertIn(
            "generate_followup_email_draft",
            self.get_audit_actions(run.id),
        )
        self.assertIn(
            "follow_up_run_waiting_approval",
            self.get_audit_actions(run.id),
        )

    @patch("app.agents.tools.draft_email_tool")
    def test_missing_email_completes_safely_without_approval(
        self,
        mock_draft_email_tool,
    ):
        self.create_contact(email=None)

        run = agent_router.trigger_follow_up_run_once(db=self.db)

        approvals = self.db.query(agent_models.AgentApproval).all()
        run_result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(len(run_result["recommendations"]), 1)
        self.assertEqual(len(run_result["drafts"]), 0)
        self.assertIn("skip_followup_email_draft", self.get_audit_actions(run.id))
        self.assertIn("follow_up_run_completed", self.get_audit_actions(run.id))
        mock_draft_email_tool.assert_not_called()

    @patch("app.agents.tools.draft_email_tool")
    def test_review_completion_after_approval(self, mock_draft_email_tool):
        self.create_contact()
        mock_draft_email_tool.return_value = crm_schemas.EmailDraftResponse(
            subject="Follow Up",
            body="Draft body",
        )

        run = agent_router.trigger_follow_up_run_once(db=self.db)
        approval = self.db.query(agent_models.AgentApproval).first()

        updated = agent_router.approve_agent_action(approval.id, db=self.db)
        run = self.get_run(run.id)
        task = self.get_task(run.task_id)

        self.assertEqual(updated.status, "approved")
        self.assertEqual(updated.approved_by, "manual_review")
        self.assertEqual(run.status, "completed")
        self.assertEqual(task.status, "completed")
        self.assertIn("approve_agent_action", self.get_audit_actions(run.id))
        self.assertIn("follow_up_review_completed", self.get_audit_actions(run.id))

        history = agent_router.list_recent_approval_decisions(db=self.db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].id, approval.id)
        self.assertEqual(history[0].status, "approved")

    @patch("app.agents.tools.draft_email_tool")
    def test_review_completion_after_rejection(self, mock_draft_email_tool):
        self.create_contact()
        mock_draft_email_tool.return_value = crm_schemas.EmailDraftResponse(
            subject="Follow Up",
            body="Draft body",
        )

        run = agent_router.trigger_follow_up_run_once(db=self.db)
        approval = self.db.query(agent_models.AgentApproval).first()

        updated = agent_router.reject_agent_action(
            approval.id,
            reason="Needs rewrite",
            db=self.db,
        )
        run = self.get_run(run.id)
        task = self.get_task(run.task_id)

        self.assertEqual(updated.status, "rejected")
        self.assertEqual(updated.rejection_reason, "Needs rewrite")
        self.assertEqual(run.status, "completed")
        self.assertEqual(task.status, "completed")
        self.assertIn("reject_agent_action", self.get_audit_actions(run.id))
        self.assertIn("follow_up_review_completed", self.get_audit_actions(run.id))

        history = agent_router.list_recent_approval_decisions(db=self.db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].id, approval.id)
        self.assertEqual(history[0].status, "rejected")

    @patch("app.agents.tools.draft_email_tool")
    def test_approval_fails_safely_when_run_is_not_in_review(
        self,
        mock_draft_email_tool,
    ):
        self.create_contact()
        mock_draft_email_tool.return_value = crm_schemas.EmailDraftResponse(
            subject="Follow Up",
            body="Draft body",
        )

        run = agent_router.trigger_follow_up_run_once(db=self.db)
        approval = self.db.query(agent_models.AgentApproval).first()

        run.status = "completed"
        self.db.commit()

        with self.assertRaises(HTTPException) as approve_error:
            agent_router.approve_agent_action(approval.id, db=self.db)
        self.assertEqual(approve_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as reject_error:
            agent_router.reject_agent_action(approval.id, reason="late", db=self.db)
        self.assertEqual(reject_error.exception.status_code, 409)

    @patch("app.agents.tools.draft_email_tool", side_effect=RuntimeError("draft boom"))
    def test_draft_generation_failure_marks_run_failed_safely(
        self,
        _mock_draft_email_tool,
    ):
        self.create_contact()

        run = agent_router.trigger_follow_up_run_once(db=self.db)
        task = self.get_task(run.task_id)
        approvals = self.db.query(agent_models.AgentApproval).all()

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertEqual(run.error, "draft boom")
        self.assertIn("follow_up_run_failed", self.get_audit_actions(run.id))

    def test_recommendations_endpoint_returns_safe_empty_contract_for_invalid_result(
        self,
    ):
        task = agent_service.create_task(self.db, agent_type="follow_up")
        run = agent_service.create_run(self.db, task=task, summary="bad result")
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        payload = agent_router.get_follow_up_recommendations(db=self.db)

        self.assertEqual(payload["run_id"], run.id)
        self.assertEqual(payload["recommendations"], [])
        self.assertEqual(payload["drafts"], [])

    @patch("app.agents.tools.draft_email_tool")
    def test_run_audit_logs_endpoint_returns_chronological_history(
        self,
        mock_draft_email_tool,
    ):
        self.create_contact()
        mock_draft_email_tool.return_value = crm_schemas.EmailDraftResponse(
            subject="Follow Up",
            body="Draft body",
        )

        run = agent_router.trigger_follow_up_run_once(db=self.db)
        logs = agent_router.list_run_audit_logs(run.id, db=self.db)
        actions = [log.action for log in logs]

        self.assertGreaterEqual(len(logs), 3)
        self.assertEqual(actions[0], "follow_up_recommendations_generated")
        self.assertIn("generate_followup_email_draft", actions)
        self.assertEqual(actions[-1], "follow_up_run_waiting_approval")

    def test_run_audit_logs_endpoint_404s_for_missing_run(self):
        with self.assertRaises(HTTPException) as error:
            agent_router.list_run_audit_logs(999, db=self.db)

        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
