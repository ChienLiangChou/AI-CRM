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

from app.agents import models as agent_models
from app.agents import ops as agent_ops
from app.agents import router as agent_router
from app.agents import service as agent_service
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AgentOpsVisibilityTests(unittest.TestCase):
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
        self.base_time = utcnow_naive() - timedelta(hours=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_run(
        self,
        *,
        agent_type: str,
        status: str,
        summary: str,
        created_offset_minutes: int,
        subject_type: str = "contact",
        subject_id: int = 1,
        result: str | None = "{}",
        error: str | None = None,
    ) -> agent_models.AgentRun:
        created_at = self.base_time + timedelta(minutes=created_offset_minutes)
        task = agent_service.create_task(
            self.db,
            agent_type=agent_type,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        run = agent_service.create_run(self.db, task=task, summary=summary)
        run = agent_service.update_run_status(
            self.db,
            run,
            status=status,
            result=result,
            error=error,
            started_at=created_at,
            finished_at=created_at if status in {"completed", "failed"} else None,
        )

        task.created_at = created_at
        task.updated_at = created_at
        run.created_at = created_at
        if run.started_at is None:
            run.started_at = created_at
        self.db.commit()
        self.db.refresh(task)
        self.db.refresh(run)
        return run

    def create_approval(
        self,
        *,
        run: agent_models.AgentRun,
        action_type: str,
        payload: str,
        status: str = "pending",
        created_offset_minutes: int,
        approved_by: str = "manual_review",
        rejection_reason: str | None = None,
    ) -> agent_models.AgentApproval:
        created_at = self.base_time + timedelta(minutes=created_offset_minutes)
        approval = agent_service.create_approval(
            self.db,
            run=run,
            action_type=action_type,
            risk_level="high",
            payload=payload,
        )
        approval.created_at = created_at
        approval.status = status
        if status == "approved":
            approval.approved_by = approved_by
            approval.approved_at = created_at + timedelta(minutes=1)
        elif status == "rejected":
            approval.rejection_reason = rejection_reason or "Needs rewrite"
            approval.rejected_at = created_at + timedelta(minutes=1)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def test_overview_and_recent_runs_cover_all_frozen_agents(self):
        follow_up_run = self.create_run(
            agent_type="follow_up",
            status="waiting_approval",
            summary="Follow-up queue review",
            created_offset_minutes=30,
            subject_id=101,
            result=json.dumps({"recommendations": [], "drafts": []}),
        )
        self.create_approval(
            run=follow_up_run,
            action_type="send_email",
            payload=json.dumps(
                {
                    "contact_id": 101,
                    "subject": "Follow Up",
                    "body": "Draft body",
                    "review_mode": "manual_only",
                }
            ),
            created_offset_minutes=31,
        )
        conversation_run = self.create_run(
            agent_type="conversation_closer",
            status="failed",
            summary="Conversation Closer run",
            created_offset_minutes=20,
            subject_id=202,
            result="{not-json}",
            error="llm boom",
        )
        listing_run = self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing / CMA internal-only run",
            created_offset_minutes=10,
            subject_type="property",
            subject_id=303,
            result="{bad-json}",
        )

        overview = agent_ops.get_ops_overview(self.db)
        recent_runs = agent_ops.list_ops_recent_runs(self.db)
        failed_runs = agent_ops.list_ops_failed_runs(self.db)

        by_agent = {item.agent_type: item for item in overview.agents}

        self.assertEqual(set(by_agent), {"follow_up", "conversation_closer", "listing_cma"})
        self.assertEqual(by_agent["follow_up"].latest_run_id, follow_up_run.id)
        self.assertEqual(by_agent["follow_up"].pending_approvals, 1)
        self.assertEqual(by_agent["conversation_closer"].failed_runs, 1)
        self.assertEqual(by_agent["listing_cma"].runs_tracked, 1)
        self.assertEqual(overview.totals.pending_approvals, 1)
        self.assertEqual(overview.totals.failed_runs, 1)
        self.assertEqual(overview.totals.runs_tracked, 3)
        self.assertEqual(overview.review_model.tracked_agent_types, list(agent_ops.TRACKED_AGENT_TYPES))
        self.assertTrue(overview.review_model.manual_only)
        self.assertTrue(overview.review_model.no_send)

        self.assertEqual([item.run_id for item in recent_runs], [follow_up_run.id, conversation_run.id, listing_run.id])
        listing_item = next(item for item in recent_runs if item.run_id == listing_run.id)
        self.assertTrue(listing_item.is_internal_only)
        self.assertFalse(listing_item.has_pending_approvals)
        self.assertEqual(listing_item.approval_count, 0)

        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].run_id, conversation_run.id)
        self.assertEqual(failed_runs[0].error, "llm boom")
        self.assertTrue(failed_runs[0].is_internal_only)

    def test_pending_and_decision_views_fail_soft_on_malformed_payloads(self):
        follow_up_run = self.create_run(
            agent_type="follow_up",
            status="waiting_approval",
            summary="Follow-up queue review",
            created_offset_minutes=20,
            subject_id=401,
            result=json.dumps({"recommendations": [], "drafts": []}),
        )
        malformed_pending = self.create_approval(
            run=follow_up_run,
            action_type="send_email",
            payload="{not-json}",
            created_offset_minutes=21,
        )

        listing_run = self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing summary",
            created_offset_minutes=10,
            subject_type="property",
            subject_id=402,
        )
        approved = self.create_approval(
            run=listing_run,
            action_type="send_listing_cma_summary",
            payload=json.dumps(
                {
                    "contact_id": 42,
                    "property_id": 402,
                    "variant": "post_meeting_summary",
                    "subject": "Summary from today",
                    "body": "Hi Jane, here is a concise recap for your review.",
                    "review_mode": "manual_only",
                }
            ),
            status="approved",
            created_offset_minutes=11,
        )

        pending = agent_ops.list_ops_pending_approvals(self.db)
        history = agent_ops.list_ops_recent_decisions(self.db)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].approval_id, malformed_pending.id)
        self.assertEqual(pending[0].preview.title, "follow-up email")
        self.assertIsNone(pending[0].preview.subject)
        self.assertIsNone(pending[0].preview.body_excerpt)
        self.assertIn("{not-json}", pending[0].preview.payload_text or "")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].approval_id, approved.id)
        self.assertEqual(history[0].decisioned_at, approved.approved_at)
        self.assertEqual(history[0].preview.title, "post_meeting_summary")
        self.assertEqual(history[0].preview.subject, "Summary from today")
        self.assertEqual(history[0].preview.contact_id, 42)
        self.assertEqual(history[0].preview.property_id, 402)
        self.assertEqual(history[0].preview.review_mode, "manual_only")

    def test_run_audit_inspection_parses_valid_json_and_falls_back_for_bad_text(self):
        listing_run = self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing / CMA run",
            created_offset_minutes=5,
            subject_type="property",
            subject_id=501,
        )
        agent_service.write_audit_log(
            self.db,
            run=listing_run,
            task=listing_run.task,
            actor_type="system",
            action="listing_cma_context_loaded",
            details=json.dumps({"contact_id": 7, "property_id": 501}),
        )
        agent_service.write_audit_log(
            self.db,
            run=listing_run,
            task=listing_run.task,
            actor_type="agent",
            action="listing_cma_run_failed",
            details="{not-json}",
        )

        audit_payload = agent_ops.get_ops_run_audit(self.db, run_id=listing_run.id)

        self.assertEqual(audit_payload.run.run_id, listing_run.id)
        self.assertEqual(audit_payload.run.agent_type, "listing_cma")
        self.assertEqual(audit_payload.run.subject_id, 501)
        self.assertEqual(len(audit_payload.audit_logs), 2)
        self.assertEqual(audit_payload.audit_logs[0].details_json, {"contact_id": 7, "property_id": 501})
        self.assertIsNone(audit_payload.audit_logs[0].details_text)
        self.assertIsNone(audit_payload.audit_logs[1].details_json)
        self.assertEqual(audit_payload.audit_logs[1].details_text, "{not-json}")

        other_run = self.create_run(
            agent_type="experimental",
            status="completed",
            summary="Ignored agent",
            created_offset_minutes=1,
        )
        with self.assertRaises(ValueError) as error:
            agent_ops.get_ops_run_audit(self.db, run_id=other_run.id)
        self.assertEqual(str(error.exception), "run_not_found")

    @patch("app.agents.router.list_runs", side_effect=AssertionError("follow-up route helper should not be called"))
    @patch(
        "app.agents.router.list_conversation_closer_runs",
        side_effect=AssertionError("conversation closer route helper should not be called"),
    )
    @patch(
        "app.agents.router.list_listing_cma_runs",
        side_effect=AssertionError("listing cma route helper should not be called"),
    )
    def test_ops_route_endpoints_return_read_only_cross_agent_contracts(
        self,
        _mock_listing_runs,
        _mock_conversation_runs,
        _mock_follow_up_runs,
    ):
        follow_up_run = self.create_run(
            agent_type="follow_up",
            status="waiting_approval",
            summary="Follow-up queue review",
            created_offset_minutes=40,
            subject_id=601,
            result=json.dumps({"recommendations": [], "drafts": []}),
        )
        pending_approval = self.create_approval(
            run=follow_up_run,
            action_type="send_email",
            payload="{not-json}",
            created_offset_minutes=41,
        )
        conversation_run = self.create_run(
            agent_type="conversation_closer",
            status="failed",
            summary="Conversation closer failed",
            created_offset_minutes=30,
            subject_id=602,
            error="bad llm output",
            result="{bad-json}",
        )
        listing_run = self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing approved run",
            created_offset_minutes=20,
            subject_type="property",
            subject_id=603,
        )
        internal_only_run = self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing internal-only run",
            created_offset_minutes=10,
            subject_type="property",
            subject_id=604,
        )
        decided_approval = self.create_approval(
            run=listing_run,
            action_type="send_listing_cma_summary",
            payload=json.dumps(
                {
                    "contact_id": 42,
                    "property_id": 603,
                    "variant": "post_meeting_summary",
                    "subject": "Summary from today",
                    "body": "A concise seller-facing draft",
                    "review_mode": "manual_only",
                }
            ),
            status="approved",
            created_offset_minutes=21,
        )
        agent_service.write_audit_log(
            self.db,
            run=listing_run,
            task=listing_run.task,
            actor_type="agent",
            action="listing_cma_context_loaded",
            details=json.dumps({"property_id": 603}),
        )
        agent_service.write_audit_log(
            self.db,
            run=listing_run,
            task=listing_run.task,
            actor_type="system",
            action="listing_cma_run_completed",
            details="{not-json}",
        )

        overview = agent_router.get_agent_ops_overview(db=self.db)
        pending = agent_router.list_agent_ops_pending_approvals(db=self.db)
        history = agent_router.list_agent_ops_approval_history(db=self.db)
        recent_runs = agent_router.list_agent_ops_recent_runs(db=self.db)
        failed_runs = agent_router.list_agent_ops_failed_runs(db=self.db)
        audit = agent_router.get_agent_ops_run_audit(listing_run.id, db=self.db)

        self.assertEqual(overview.totals.pending_approvals, 1)
        self.assertEqual(overview.totals.failed_runs, 1)
        self.assertEqual(overview.review_model.tracked_agent_types, list(agent_ops.TRACKED_AGENT_TYPES))

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].approval_id, pending_approval.id)
        self.assertEqual(pending[0].agent_type, "follow_up")
        self.assertEqual(pending[0].preview.payload_text, "{not-json}")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].approval_id, decided_approval.id)
        self.assertEqual(history[0].agent_type, "listing_cma")
        self.assertEqual(history[0].preview.subject, "Summary from today")

        self.assertEqual(
            [item.run_id for item in recent_runs],
            [follow_up_run.id, conversation_run.id, listing_run.id, internal_only_run.id],
        )
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].run_id, conversation_run.id)
        self.assertFalse(next(item for item in recent_runs if item.run_id == listing_run.id).is_internal_only)
        self.assertTrue(
            next(item for item in recent_runs if item.run_id == internal_only_run.id).is_internal_only
        )

        self.assertEqual(audit.run.run_id, listing_run.id)
        self.assertEqual(audit.run.agent_type, "listing_cma")
        self.assertEqual(len(audit.audit_logs), 2)
        self.assertEqual(audit.audit_logs[0].details_json, {"property_id": 603})
        self.assertEqual(audit.audit_logs[1].details_text, "{not-json}")

    def test_ops_run_audit_route_returns_404_for_non_tracked_run(self):
        other_run = self.create_run(
            agent_type="experimental",
            status="completed",
            summary="Ignored agent",
            created_offset_minutes=1,
        )

        with self.assertRaises(HTTPException) as error:
            agent_router.get_agent_ops_run_audit(other_run.id, db=self.db)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
