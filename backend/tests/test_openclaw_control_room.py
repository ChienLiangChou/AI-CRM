import json
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def dump_model(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class OpenClawControlRoomTests(unittest.TestCase):
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
        self.base_time = utcnow_naive() - timedelta(hours=2)

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
        result: str | None = None,
        error: str | None = None,
    ) -> tuple[agent_models.AgentTask, agent_models.AgentRun]:
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
        agent_service.update_task_status(self.db, task, status=status)

        task.created_at = created_at
        task.updated_at = created_at
        run.created_at = created_at
        if run.started_at is None:
            run.started_at = created_at
        self.db.commit()
        self.db.refresh(task)
        self.db.refresh(run)
        return task, run

    def create_approval(
        self,
        *,
        run: agent_models.AgentRun,
        action_type: str,
        payload: dict,
        created_offset_minutes: int,
    ) -> agent_models.AgentApproval:
        created_at = self.base_time + timedelta(minutes=created_offset_minutes)
        approval = agent_service.create_approval(
            self.db,
            run=run,
            action_type=action_type,
            risk_level="high",
            payload=json.dumps(payload, ensure_ascii=False),
        )
        approval.created_at = created_at
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def snapshot_counts(self) -> dict[str, int]:
        return {
            "tasks": self.db.query(agent_models.AgentTask).count(),
            "runs": self.db.query(agent_models.AgentRun).count(),
            "approvals": self.db.query(agent_models.AgentApproval).count(),
            "audit_logs": self.db.query(agent_models.AgentAuditLog).count(),
            "interactions": self.db.query(crm_models.Interaction).count(),
        }

    def build_strategy_result(self) -> dict:
        return dump_model(
            agent_schemas.StrategyCoordinationResultResponse(
                event_summary=agent_schemas.StrategyCoordinationEventSummary(
                    event_type="stalled_deal",
                    source_type="internal",
                    summary="A deal needs coordinated manual review.",
                    details="Review pending approvals before the next client update.",
                    urgency="high",
                ),
                importance_assessment=agent_schemas.StrategyCoordinationImportanceAssessment(
                    classification="strategy_review_required",
                    reason="A linked workflow is blocked.",
                    confidence=0.92,
                ),
                affected_entities=agent_schemas.StrategyCoordinationLinkedEntities(
                    contacts=[42],
                    runs=[101],
                    approvals=[202],
                ),
                execution_policy=agent_schemas.StrategyCoordinationExecutionPolicy(),
                perspective_blocks=agent_schemas.StrategyCoordinationPerspectiveBlocks(
                    follow_up=agent_schemas.StrategyCoordinationPerspectiveBlock(
                        relevance="high",
                        summary="Follow-up is blocked pending review.",
                    ),
                    conversation_retention=agent_schemas.StrategyCoordinationPerspectiveBlock(
                        relevance="low",
                        summary="No direct conversation risk.",
                    ),
                    listing_seller=agent_schemas.StrategyCoordinationPerspectiveBlock(
                        relevance="none",
                        summary="No listing impact.",
                    ),
                    operations_compliance=agent_schemas.StrategyCoordinationPerspectiveBlock(
                        relevance="high",
                        summary="Manual review is required before anything proceeds.",
                    ),
                ),
                strategy_synthesis=agent_schemas.StrategyCoordinationSynthesis(
                    summary="Review the blocked manual items before the operator acts.",
                    key_takeaways=["Blocked approvals are the immediate constraint."],
                ),
                recommended_next_actions=agent_schemas.StrategyCoordinationRecommendedActions(
                    internal_actions=["Inspect blocked review queue."],
                    human_review_actions=["Review the stalled deal approvals today."],
                ),
                risk_flags=["approval_backlog"],
                operator_notes=["Internal strategy support only. Non-executable output. No client delivery."],
            )
        )

    def build_daily_market_scan_result(self) -> dict:
        return dump_model(
            agent_schemas.DailyMarketScanResultResponse(
                scan_summary=agent_schemas.DailyMarketScanSummary(
                    scan_mode="full_daily_scan",
                    run_mode="manual_preview",
                    scope=agent_schemas.DailyMarketScanScopeSummary(
                        requested_subject_count=2,
                        effective_subject_count=2,
                        max_subjects=25,
                        decision="accepted",
                    ),
                    provider_order=["authenticated_mls_browser", "public_listing"],
                ),
                execution_policy=agent_schemas.DailyMarketScanExecutionPolicy(),
                provider_catalog=[
                    agent_schemas.DailyMarketScanProviderDescriptor(
                        provider_key="authenticated_mls_browser",
                        display_name="Authenticated MLS Browser",
                        authentication_required=True,
                        auth_state="unauthenticated",
                        availability="limited",
                        detail_level="high_detail",
                        confidence_level="high",
                        fallback_capable=False,
                        notes=["Unavailable in this run."],
                    ),
                    agent_schemas.DailyMarketScanProviderDescriptor(
                        provider_key="public_listing",
                        display_name="Public Listing",
                        authentication_required=False,
                        auth_state="not_required",
                        availability="available",
                        detail_level="lower_detail",
                        confidence_level="low",
                        fallback_capable=True,
                    ),
                ],
                client_match_scans=[
                    agent_schemas.DailyMarketScanClientMatchScan(
                        status="partial",
                        contact_id=7,
                        criteria_summary="Downtown condo search.",
                        source_attempts=[
                            agent_schemas.DailyMarketScanSourceAttempt(
                                provider_key="authenticated_mls_browser",
                                source_used="authenticated_mls_browser",
                                status="unauthenticated",
                                auth_state="unauthenticated",
                            ),
                            agent_schemas.DailyMarketScanSourceAttempt(
                                provider_key="public_listing",
                                source_used="public_listing:realtor_ca_public",
                                status="completed",
                                auth_state="not_required",
                                fallback_used=True,
                            ),
                        ],
                        findings=[
                            agent_schemas.DailyMarketScanFinding(
                                address="20 Stewart St #706",
                                source_used="public_listing:realtor_ca_public",
                                why_it_matches=["Budget fit"],
                            )
                        ],
                        fallback_used=True,
                    )
                ],
                competitor_watch_scans=[
                    agent_schemas.DailyMarketScanCompetitorWatchScan(
                        status="no_providers",
                        subject=agent_schemas.DailyMarketScanCompetitorSubject(
                            property_id=17,
                            competitor_mode="condo_same_building",
                        ),
                    )
                ],
                risk_flags=["partial_scan_recorded"],
                operator_notes=["Internal logging review only."],
            )
        )

    def build_conversation_result(self) -> dict:
        return dump_model(
            agent_schemas.ConversationCloserResultResponse(
                summary="The client needs a concise, lower-pressure follow-up.",
                objection_analysis=agent_schemas.ConversationCloserAnalysis(
                    primary_type="timing",
                    sentiment="neutral",
                    confidence=0.85,
                    urgency="medium",
                ),
                strategy=agent_schemas.ConversationCloserStrategy(
                    recommended_action="send_clarifying_follow_up",
                    goal="keep_conversation_alive",
                    tone="calm",
                    rationale="The client has not fully disengaged.",
                ),
                talking_points=["Acknowledge timing.", "Offer a lower-pressure next step."],
                drafts=[],
                risk_flags=[],
                operator_notes=["Manual review only."],
            )
        )

    def build_listing_result(self) -> dict:
        return dump_model(
            agent_schemas.ListingCmaResultResponse(
                listing_brief=agent_schemas.ListingCmaListingBrief(
                    summary="Seller prep is in good shape for the next meeting.",
                    property_highlights=["King West condo", "Parking included"],
                ),
                cma_support=agent_schemas.ListingCmaSupport(
                    range_framing="Use a tight, evidence-backed range discussion.",
                ),
                talking_points=["Focus on pricing confidence."],
                seller_drafts=[],
                risk_flags=[],
                operator_notes=["Internal review only."],
            )
        )

    @patch(
        "app.crud._send_push",
        side_effect=AssertionError("_send_push should not be called"),
    )
    @patch(
        "app.agents.tools.draft_email_tool",
        side_effect=AssertionError("draft_email_tool should not be called"),
    )
    def test_control_room_snapshot_is_read_only_and_composes_expected_sections(
        self,
        _mock_draft_email_tool,
        _mock_send_push,
    ):
        _, follow_up_run = self.create_run(
            agent_type="follow_up",
            status="waiting_approval",
            summary="Follow-up queue review",
            created_offset_minutes=10,
            result=json.dumps(
                {
                    "recommendations": [
                        {
                            "contact_id": 11,
                            "contact_name": "Alice Example",
                            "suggested_action": "Send follow-up email",
                        }
                    ],
                    "drafts": [
                        {
                            "contact_id": 11,
                            "approval_id": 1,
                            "subject": "Checking in",
                            "body": "Draft body",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        pending_approval = self.create_approval(
            run=follow_up_run,
            action_type="send_email",
            payload={
                "contact_id": 11,
                "subject": "Checking in",
                "body": "Draft body",
                "review_mode": "manual_only",
            },
            created_offset_minutes=11,
        )

        self.create_run(
            agent_type="conversation_closer",
            status="completed",
            summary="Conversation closer review",
            created_offset_minutes=20,
            result=json.dumps(self.build_conversation_result(), ensure_ascii=False),
        )
        self.create_run(
            agent_type="listing_cma",
            status="completed",
            summary="Listing prep review",
            created_offset_minutes=30,
            subject_type="property",
            subject_id=88,
            result=json.dumps(self.build_listing_result(), ensure_ascii=False),
        )
        self.create_run(
            agent_type="buyer_match",
            status="failed",
            summary="Buyer shortlist prep",
            created_offset_minutes=40,
            error="candidate scoring failed",
        )
        _, strategy_run = self.create_run(
            agent_type="strategy_coordination",
            status="completed",
            summary="Strategy Coordination run (MVP)",
            created_offset_minutes=50,
            subject_type="event",
            result=json.dumps(self.build_strategy_result(), ensure_ascii=False),
        )
        _, daily_run = self.create_run(
            agent_type="daily_market_scan",
            status="completed",
            summary="Daily Market Scan run (MVP)",
            created_offset_minutes=60,
            result=json.dumps(self.build_daily_market_scan_result(), ensure_ascii=False),
        )

        before_counts = self.snapshot_counts()
        snapshot = agent_router.get_openclaw_control_room(db=self.db)
        after_counts = self.snapshot_counts()

        self.assertEqual(before_counts, after_counts)
        self.assertTrue(snapshot.guardrails.read_only)
        self.assertTrue(snapshot.guardrails.approvals_truth_in_skc)
        self.assertTrue(snapshot.guardrails.audit_truth_in_skc)
        self.assertTrue(snapshot.guardrails.no_send)
        self.assertTrue(snapshot.guardrails.no_crm_mutation)

        self.assertEqual(len(snapshot.pending_approvals), 1)
        self.assertEqual(snapshot.pending_approvals[0].approval_id, pending_approval.id)
        self.assertEqual(len(snapshot.recent_failures), 1)
        self.assertEqual(snapshot.recent_failures[0].agent_type, "buyer_match")

        self.assertEqual(snapshot.latest_strategy_coordination.run_id, strategy_run.id)
        self.assertEqual(snapshot.latest_daily_market_scan.run_id, daily_run.id)
        self.assertIsNotNone(snapshot.latest_strategy_coordination.result)
        self.assertIsNotNone(snapshot.latest_daily_market_scan.result)

        module_cards = {item.agent_type: item for item in snapshot.module_cards}
        self.assertEqual(
            list(module_cards),
            [
                "follow_up",
                "conversation_closer",
                "listing_cma",
                "buyer_match",
                "strategy_coordination",
                "daily_market_scan",
            ],
        )
        self.assertEqual(
            module_cards["follow_up"].summary,
            "1 recommendation(s), 1 draft(s) generated.",
        )
        self.assertTrue(module_cards["follow_up"].has_pending_approvals)
        self.assertEqual(
            module_cards["strategy_coordination"].summary,
            "Review the blocked manual items before the operator acts.",
        )
        self.assertIn(
            "Provider order: authenticated_mls_browser -> public_listing",
            module_cards["daily_market_scan"].highlights,
        )

        needs_input = snapshot.needs_input_today
        self.assertEqual(
            {item.kind for item in needs_input},
            {
                "pending_approval",
                "failed_run",
                "strategy_human_review",
                "daily_market_scan_attention",
            },
        )
        self.assertTrue(
            any(
                item.kind == "pending_approval"
                and item.approval_id == pending_approval.id
                for item in needs_input
            )
        )
        self.assertTrue(
            any(
                item.kind == "failed_run"
                and item.run_id == module_cards["buyer_match"].latest_run_id
                for item in needs_input
            )
        )
        self.assertTrue(
            any(
                item.kind == "strategy_human_review"
                and item.run_id == strategy_run.id
                for item in needs_input
            )
        )
        self.assertTrue(
            any(
                item.kind == "daily_market_scan_attention"
                and item.run_id == daily_run.id
                for item in needs_input
            )
        )

    def test_control_room_snapshot_fail_softs_when_sources_are_empty(self):
        snapshot = agent_router.get_openclaw_control_room(db=self.db)

        self.assertEqual(snapshot.needs_input_today, [])
        self.assertEqual(snapshot.pending_approvals, [])
        self.assertEqual(snapshot.recent_failures, [])
        self.assertEqual(snapshot.recent_runs, [])
        self.assertIsNone(snapshot.latest_strategy_coordination.run_id)
        self.assertIsNone(snapshot.latest_daily_market_scan.run_id)
        self.assertEqual(len(snapshot.module_cards), 6)
        self.assertTrue(all(card.latest_run_id is None for card in snapshot.module_cards))

    def test_control_room_snapshot_handles_malformed_results_fail_soft(self):
        _, follow_up_run = self.create_run(
            agent_type="follow_up",
            status="completed",
            summary="Follow-up latest",
            created_offset_minutes=10,
            result="{not-json}",
        )
        _, strategy_run = self.create_run(
            agent_type="strategy_coordination",
            status="completed",
            summary="Strategy latest",
            created_offset_minutes=20,
            subject_type="event",
            result="{not-json}",
        )
        _, daily_run = self.create_run(
            agent_type="daily_market_scan",
            status="completed",
            summary="Daily latest",
            created_offset_minutes=30,
            result="{not-json}",
        )

        snapshot = agent_router.get_openclaw_control_room(db=self.db)
        module_cards = {item.agent_type: item for item in snapshot.module_cards}

        self.assertEqual(module_cards["follow_up"].latest_run_id, follow_up_run.id)
        self.assertIsNone(module_cards["follow_up"].summary)
        self.assertEqual(snapshot.latest_strategy_coordination.run_id, strategy_run.id)
        self.assertIsNone(snapshot.latest_strategy_coordination.result)
        self.assertEqual(snapshot.latest_daily_market_scan.run_id, daily_run.id)
        self.assertIsNone(snapshot.latest_daily_market_scan.result)
        self.assertEqual(snapshot.needs_input_today, [])


if __name__ == "__main__":
    unittest.main()
