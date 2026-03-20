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
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import service as agent_service
from app.agents import strategy_coordination
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StrategyCoordinationLayerTests(unittest.TestCase):
    def test_normalize_run_request_filters_sparse_and_malformed_linked_context(self):
        request = strategy_coordination.normalize_run_request(
            {
                "event_type": "bank_of_canada_decision",
                "source_type": "external",
                "summary": "Rates held.",
                "urgency": "high",
                "linked_entities": {
                    "contacts": [42, "51", None, "bad", -1, 42],
                    "properties": [17, "18", 0, False, "bad"],
                    "listings": [
                        {
                            "listing_ref": "manual:downtown-condo",
                            "property_id": "17",
                            "label": "20 Stewart St #706",
                        },
                        {
                            "property_id": "19",
                            "label": "Auto-derived listing ref",
                        },
                        {"listing_ref": "", "property_id": None},
                        "bad",
                    ],
                    "runs": [103, "104", "bad"],
                    "approvals": [88, "89", None, "bad"],
                },
            }
        )

        self.assertEqual(request.source_type, "external")
        self.assertEqual(request.urgency, "high")
        self.assertEqual(request.linked_entities.contacts, [42, 51])
        self.assertEqual(request.linked_entities.properties, [17, 18])
        self.assertEqual(request.linked_entities.runs, [103, 104])
        self.assertEqual(request.linked_entities.approvals, [88, 89])
        self.assertEqual(len(request.linked_entities.listings), 2)
        self.assertEqual(
            request.linked_entities.listings[0].listing_ref,
            "manual:downtown-condo",
        )
        self.assertEqual(
            request.linked_entities.listings[1].listing_ref,
            "manual:property:19",
        )

    def test_conservative_importance_filter_is_not_over_eager(self):
        noise_request = agent_schemas.StrategyCoordinationRunRequest(
            event_type="macro_headline",
            source_type="external",
            summary="Generic market headline",
            urgency="low",
            linked_entities=agent_schemas.StrategyCoordinationLinkedEntities(),
        )
        watchlist_request = agent_schemas.StrategyCoordinationRunRequest(
            event_type="policy_shift",
            source_type="external",
            summary="Potential policy impact",
            urgency="high",
            linked_entities=agent_schemas.StrategyCoordinationLinkedEntities(),
        )

        noise_assessment = strategy_coordination.conservative_importance_assessment(
            noise_request
        )
        watchlist_assessment = strategy_coordination.conservative_importance_assessment(
            watchlist_request
        )

        self.assertEqual(noise_assessment.classification, "noise")
        self.assertEqual(watchlist_assessment.classification, "watchlist")

    def test_conservative_importance_filter_requires_review_for_high_impact_linked_event(self):
        request = agent_schemas.StrategyCoordinationRunRequest(
            event_type="stalled_deal",
            source_type="internal",
            summary="Active buyer deal has stalled and two approvals are blocked.",
            urgency="high",
            linked_entities=agent_schemas.StrategyCoordinationLinkedEntities(
                contacts=[42],
                properties=[17],
                runs=[103],
                approvals=[88],
            ),
        )

        assessment = strategy_coordination.conservative_importance_assessment(request)

        self.assertEqual(assessment.classification, "strategy_review_required")
        self.assertGreaterEqual(assessment.confidence, 0.8)

    def test_build_internal_report_is_non_executable_and_uses_fixed_perspective_schema(self):
        report = strategy_coordination.build_internal_report(
            {
                "event_type": "upcoming_listing_appointment",
                "source_type": "internal",
                "summary": "Listing appointment is coming up for a linked property.",
                "urgency": "medium",
                "linked_entities": {
                    "contacts": [42],
                    "properties": [17],
                    "listings": [{"property_id": 17, "label": "20 Stewart St #706"}],
                    "runs": [103],
                },
            }
        )

        self.assertEqual(
            report.execution_policy.mode,
            "internal_only_non_executable",
        )
        self.assertFalse(report.execution_policy.can_execute_actions)
        self.assertFalse(report.execution_policy.can_trigger_agents)
        self.assertFalse(report.execution_policy.can_create_client_outputs)
        self.assertIn(
            "Internal strategy support only. Non-executable output. No client delivery.",
            report.operator_notes,
        )
        perspective_payload = (
            report.perspective_blocks.model_dump()
            if hasattr(report.perspective_blocks, "model_dump")
            else report.perspective_blocks.dict()
        )
        self.assertEqual(
            set(perspective_payload.keys()),
            {
                "follow_up",
                "conversation_retention",
                "listing_seller",
                "operations_compliance",
            },
        )
        for field_name in (
            "follow_up",
            "conversation_retention",
            "listing_seller",
            "operations_compliance",
        ):
            block = getattr(report.perspective_blocks, field_name)
            self.assertTrue(hasattr(block, "relevance"))
            self.assertTrue(hasattr(block, "summary"))
            self.assertTrue(hasattr(block, "supporting_signals"))
            self.assertTrue(hasattr(block, "risk_flags"))

    def test_sparse_linked_context_stays_safe_and_internal_only(self):
        report = strategy_coordination.build_internal_report(
            {
                "event_type": "generic_market_noise",
                "source_type": "external",
                "summary": "Broad market commentary",
                "urgency": "low",
                "linked_entities": "not-a-dict",
            }
        )

        self.assertEqual(report.importance_assessment.classification, "noise")
        self.assertEqual(report.affected_entities.contacts, [])
        self.assertEqual(report.affected_entities.properties, [])
        self.assertEqual(report.recommended_next_actions.human_review_actions, [])
        self.assertIn("linked_context_sparse", report.risk_flags)

class StrategyCoordinationRunLifecycleTests(unittest.TestCase):
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
            "name": "Seller Contact",
            "email": "seller@example.com",
            "company": "SKC",
            "client_type": "seller",
            "lead_score": 70,
            "stage_id": self.stage.id,
            "status": "active",
            "notes": "Important seller account.",
            "created_at": utcnow_naive() - timedelta(days=10),
            "last_contacted_at": utcnow_naive() - timedelta(days=1),
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
            "created_at": utcnow_naive() - timedelta(days=20),
        }
        defaults.update(overrides)
        property_record = crm_models.Property(**defaults)
        self.db.add(property_record)
        self.db.commit()
        self.db.refresh(property_record)
        return property_record

    def create_agent_run_with_approval(self, *, agent_type: str = "buyer_match"):
        task = agent_service.create_task(
            self.db,
            agent_type=agent_type,
            subject_type="contact",
            subject_id=1,
            payload=json.dumps({"source": "test"}, ensure_ascii=False),
        )
        run = agent_service.create_run(self.db, task=task, summary=f"{agent_type} run")
        run = agent_service.update_run_status(
            self.db,
            run,
            status="waiting_approval",
            result=json.dumps({"ok": True}, ensure_ascii=False),
            started_at=utcnow_naive(),
            finished_at=utcnow_naive(),
        )
        agent_service.update_task_status(self.db, task, status="waiting_approval")
        approval = agent_service.create_approval(
            self.db,
            run=run,
            action_type="send_email",
            risk_level="high",
            payload=json.dumps(
                {
                    "subject": "Test approval",
                    "body": "Review this item.",
                    "contact_id": 1,
                    "review_mode": "manual_only",
                },
                ensure_ascii=False,
            ),
        )
        return task, run, approval

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

    def create_completed_strategy_run(
        self,
        *,
        result_payload: dict | None = None,
        raw_result: str | None = None,
    ):
        task = agent_service.create_task(
            self.db,
            agent_type="strategy_coordination",
            subject_type="event",
            payload=json.dumps(
                {
                    "event_type": "internal_event",
                    "source_type": "internal",
                    "summary": "Test strategy event",
                },
                ensure_ascii=False,
            ),
        )
        run = agent_service.create_run(
            self.db,
            task=task,
            summary="Strategy Coordination run (MVP)",
        )
        result_value = raw_result
        if result_value is None:
            report = result_payload or strategy_coordination.build_internal_report(
                {
                    "event_type": "internal_event",
                    "source_type": "internal",
                    "summary": "Test strategy event",
                    "urgency": "medium",
                    "linked_entities": {},
                }
            )
            result_value = json.dumps(
                report.model_dump() if hasattr(report, "model_dump") else report.dict(),
                ensure_ascii=False,
            )
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            plan=json.dumps(
                {"event_snapshot": {"event_type": "internal_event"}},
                ensure_ascii=False,
            ),
            result=result_value,
            started_at=utcnow_naive(),
            finished_at=utcnow_naive(),
        )
        agent_service.update_task_status(self.db, task, status="completed")
        return task, run

    def test_db_backed_run_creation_stores_payload_plan_result_and_zero_approvals(self):
        contact = self.create_contact()
        property_record = self.create_property()
        _, linked_run, linked_approval = self.create_agent_run_with_approval()
        request = agent_schemas.StrategyCoordinationRunRequest(
            event_type="bank_of_canada_decision",
            source_type="external",
            summary="BoC held rates and the operator wants pipeline impact review.",
            urgency="high",
            operator_goal="assess_pipeline_impact",
            linked_entities=agent_schemas.StrategyCoordinationLinkedEntities(
                contacts=[contact.id],
                properties=[property_record.id],
                listings=[
                    agent_schemas.StrategyCoordinationListingReference(
                        listing_ref="manual:downtown-condo-listing",
                        property_id=property_record.id,
                        label="20 Stewart St #706",
                    )
                ],
                runs=[linked_run.id],
                approvals=[linked_approval.id],
            ),
        )

        run = strategy_coordination.run_strategy_coordination_once(self.db, request)
        task = self.get_task(run.task_id)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .all()
        )
        payload = json.loads(task.payload)
        plan = json.loads(run.plan)
        result = json.loads(run.result)

        self.assertEqual(task.agent_type, "strategy_coordination")
        self.assertEqual(task.subject_type, "event")
        self.assertEqual(task.status, "completed")
        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(payload["event_type"], "bank_of_canada_decision")
        self.assertEqual(plan["execution_policy"]["mode"], "internal_only_non_executable")
        self.assertEqual(plan["importance_assessment"]["classification"], "strategy_review_required")
        self.assertEqual(plan["linked_context"]["counts"]["contacts_found"], 1)
        self.assertEqual(plan["linked_context"]["counts"]["properties_found"], 1)
        self.assertEqual(plan["linked_context"]["counts"]["runs_found"], 1)
        self.assertEqual(plan["linked_context"]["counts"]["approvals_found"], 1)
        self.assertEqual(
            result["execution_policy"]["mode"],
            "internal_only_non_executable",
        )
        self.assertFalse(result["execution_policy"]["can_execute_actions"])
        self.assertFalse(result["execution_policy"]["can_trigger_agents"])
        self.assertFalse(result["execution_policy"]["can_create_client_outputs"])
        self.assertTrue(result["recommended_next_actions"]["internal_actions"])
        self.assertTrue(result["recommended_next_actions"]["human_review_actions"])
        self.assertIn(
            "Internal strategy support only. Non-executable output. No client delivery.",
            result["operator_notes"],
        )
        self.assertEqual(
            self.get_audit_actions(run.id),
            [
                "strategy_coordination_event_intake",
                "strategy_coordination_classification_generated",
                "strategy_coordination_entities_mapped",
                "strategy_coordination_perspectives_generated",
                "strategy_coordination_strategy_synthesized",
                "strategy_coordination_run_completed",
            ],
        )

    def test_sparse_or_malformed_linked_context_completes_safely_without_approvals(self):
        run = strategy_coordination.run_strategy_coordination_once(
            self.db,
            {
                "event_type": "macro_headline",
                "source_type": "external",
                "summary": "Generic macro event with no verified linked context.",
                "urgency": "high",
                "linked_entities": "not-a-dict",
            },
        )
        task = self.get_task(run.task_id)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .all()
        )
        payload = json.loads(task.payload)
        plan = json.loads(run.plan)
        result = json.loads(run.result)

        self.assertEqual(run.status, "completed")
        self.assertEqual(task.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(payload["linked_entities"]["contacts"], [])
        self.assertEqual(plan["linked_context"]["counts"]["contacts_found"], 0)
        self.assertEqual(
            result["importance_assessment"]["classification"],
            "watchlist",
        )
        self.assertIn("linked_context_sparse", result["risk_flags"])
        self.assertTrue(result["recommended_next_actions"]["human_review_actions"])

    def test_invalid_input_fails_and_writes_failure_audit(self):
        run = strategy_coordination.run_strategy_coordination_once(self.db, 12345)
        task = self.get_task(run.task_id)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .all()
        )

        self.assertEqual(run.status, "failed")
        self.assertEqual(task.status, "failed")
        self.assertEqual(approvals, [])
        self.assertIn("strategy_coordination_run_failed", self.get_audit_actions(run.id))

    def test_strategy_coordination_route_surface_is_scoped_and_safe(self):
        contact = self.create_contact()
        property_record = self.create_property()
        request = agent_schemas.StrategyCoordinationRunRequest(
            event_type="listing_appointment_upcoming",
            source_type="internal",
            summary="Upcoming listing appointment with linked seller context.",
            urgency="medium",
            linked_entities=agent_schemas.StrategyCoordinationLinkedEntities(
                contacts=[contact.id],
                properties=[property_record.id],
            ),
        )
        strategy_run = agent_router.trigger_strategy_coordination_run_once(
            request,
            self.db,
        )
        _, non_strategy_run, _ = self.create_agent_run_with_approval(agent_type="buyer_match")

        runs = agent_router.list_strategy_coordination_runs(db=self.db)
        latest = agent_router.get_latest_strategy_coordination_result(db=self.db)
        report = agent_router.get_strategy_coordination_run_report(
            strategy_run.id,
            db=self.db,
        )
        audit_logs = agent_router.list_strategy_coordination_run_audit_logs(
            strategy_run.id,
            db=self.db,
        )

        self.assertEqual([run.id for run in runs], [strategy_run.id])
        self.assertEqual(latest["run_id"], strategy_run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertIsNotNone(latest["result"])
        self.assertEqual(report["execution_policy"]["mode"], "internal_only_non_executable")
        self.assertIn("event_summary", report)
        self.assertTrue(audit_logs)
        self.assertEqual(audit_logs[0].action, "strategy_coordination_event_intake")

        with self.assertRaises(HTTPException) as report_error:
            agent_router.get_strategy_coordination_run_report(non_strategy_run.id, db=self.db)
        self.assertEqual(report_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as audit_error:
            agent_router.list_strategy_coordination_run_audit_logs(
                non_strategy_run.id,
                db=self.db,
            )
        self.assertEqual(audit_error.exception.status_code, 404)

    def test_strategy_coordination_latest_returns_safe_empty_contract(self):
        latest = agent_router.get_latest_strategy_coordination_result(db=self.db)

        self.assertEqual(
            latest,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

    def test_strategy_coordination_latest_fails_soft_for_malformed_result(self):
        _, run = self.create_completed_strategy_run(raw_result="{not-json}")

        latest = agent_router.get_latest_strategy_coordination_result(db=self.db)

        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertIsNone(latest["result"])

    def test_strategy_coordination_report_returns_404_for_missing_structured_report(self):
        _, run = self.create_completed_strategy_run(raw_result="{not-json}")

        with self.assertRaises(HTTPException) as report_error:
            agent_router.get_strategy_coordination_run_report(run.id, db=self.db)

        self.assertEqual(report_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
