import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import event_strategy_review
from app.agents import models as agent_models
from app.agents import schemas as agent_schemas
from app.database import Base


class EventStrategyReviewContractTests(unittest.TestCase):
    def test_manual_summary_contract_requires_summary_fields_and_disables_live_retrieval(self):
        request = event_strategy_review.normalize_run_request(
            {
                "retrieval_contract": {
                    "source_mode": "manual_summary",
                    "manual_summary_input": {
                        "headline": "Bank of Canada holds rates",
                        "summary": "Housing demand may stay uneven across Toronto.",
                        "source_label": "operator_note",
                        "event_date": "2026-03-23",
                    },
                },
                "geo_focus": ["Toronto", "GTA"],
            }
        )

        self.assertEqual(request.retrieval_contract.source_mode, "manual_summary")
        self.assertFalse(request.retrieval_contract.live_retrieval_enabled)
        self.assertEqual(
            request.retrieval_contract.manual_summary_input.headline,
            "Bank of Canada holds rates",
        )
        self.assertEqual(request.geo_focus, ["Toronto", "GTA"])

    def test_manual_url_bundle_contract_filters_invalid_and_duplicate_urls(self):
        request = event_strategy_review.normalize_run_request(
            {
                "retrieval_contract": {
                    "source_mode": "manual_url_bundle",
                    "manual_url_bundle_input": {
                        "items": [
                            {
                                "url": "https://example.com/a",
                                "title": "Toronto housing policy update",
                                "publisher": "Example News",
                            },
                            {
                                "url": "https://example.com/a",
                                "title": "Duplicate should be removed",
                            },
                            {
                                "url": "https://example.com/a/?utm_source=newsletter",
                                "title": "Tracked duplicate should be removed",
                            },
                            {"url": "   "},
                            "bad-item",
                            {
                                "url": "https://example.com/b",
                                "title": "GTA inventory shift",
                            },
                        ]
                    },
                }
            }
        )

        items = request.retrieval_contract.manual_url_bundle_input.items
        self.assertEqual(len(items), 2)
        self.assertEqual(
            request.retrieval_contract.manual_url_bundle_input.submitted_item_count,
            6,
        )
        self.assertEqual(items[0].url, "https://example.com/a")
        self.assertEqual(items[1].url, "https://example.com/b")

    def test_curated_search_query_contract_is_preserved_without_live_retrieval(self):
        report = event_strategy_review.build_internal_report(
            {
                "retrieval_contract": {
                    "source_mode": "curated_search_query",
                    "curated_search_query_input": {
                        "query": "Bank of Canada Toronto housing rates",
                        "geography_hint": "Toronto",
                        "topic_hints": ["mortgage", "policy"],
                        "allowed_domains": ["bankofcanada.ca", "betterdwelling.com"],
                        "max_results": 7,
                    },
                },
                "operator_notes": "Prioritize high-signal events only.",
                "geo_focus": ["Toronto", "Ontario"],
            }
        )

        self.assertEqual(report.retrieval_contract.source_mode, "curated_search_query")
        self.assertFalse(report.retrieval_contract.live_retrieval_enabled)
        self.assertIn(
            "v1 preserves a controlled retrieval contract",
            report.operator_notes[1],
        )
        self.assertIn("no live retrieval", report.event_cluster.retrieval_notes[0].lower())

    def test_build_internal_report_uses_fixed_perspective_blocks_and_action_split(self):
        report = event_strategy_review.build_internal_report(
            {
                "retrieval_contract": {
                    "source_mode": "manual_summary",
                    "manual_summary_input": {
                        "headline": "GTA condo market update",
                        "summary": "Inventory is rising and buyer caution is increasing.",
                    },
                },
                "geo_focus": ["GTA"],
            }
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
                "cma_market",
                "ops_compliance",
                "buyer_renter",
            },
        )
        for key in event_strategy_review.FIXED_PERSPECTIVE_KEYS:
            block = getattr(report.perspective_blocks, key)
            self.assertEqual(block.status, "placeholder")
            self.assertTrue(block.why_it_matters)
            self.assertTrue(block.business_implications)
            self.assertTrue(block.cautions)

        self.assertIsInstance(report.recommended_next_actions.internal_actions, list)
        self.assertIsInstance(
            report.recommended_next_actions.human_review_actions,
            list,
        )
        self.assertNotEqual(
            report.recommended_next_actions.internal_actions,
            report.recommended_next_actions.human_review_actions,
        )
        self.assertEqual(
            report.execution_policy.mode,
            "internal_review_only_non_executable",
        )
        self.assertFalse(report.execution_policy.can_auto_send)
        self.assertFalse(report.execution_policy.can_auto_publish)
        self.assertFalse(report.execution_policy.can_auto_execute)
        self.assertFalse(report.execution_policy.can_auto_deploy)

    def test_high_signal_manual_summary_can_reach_strategy_review_required(self):
        report = event_strategy_review.build_internal_report(
            {
                "retrieval_contract": {
                    "source_mode": "manual_summary",
                    "manual_summary_input": {
                        "headline": "Bank of Canada policy decision hits Toronto condo and rental market",
                        "summary": (
                            "Mortgage rates, inventory, condo pricing, rental"
                            " conditions, and housing policy may shift buyer,"
                            " seller, landlord, tenant, and compliance decisions"
                            " across Toronto, the GTA, Ontario, and Canada."
                        ),
                        "event_date": "2026-03-23",
                    },
                },
                "geo_focus": ["Toronto", "GTA", "Ontario", "Canada"],
            }
        )

        self.assertEqual(
            report.importance_assessment.classification,
            "strategy_review_required",
        )
        self.assertGreaterEqual(report.score_breakdown.total_score, 70.0)
        output_modes = {option.mode: option for option in report.output_mode_options}
        self.assertEqual(output_modes["html_report_package"].status, "first_class_v1")
        self.assertIn(
            "separate explicit packaging step",
            output_modes["html_report_package"].reason.lower(),
        )

    def test_package_result_placeholder_keeps_packaging_as_a_second_explicit_step(self):
        result = event_strategy_review.build_package_result_placeholder(
            {
                "source_run_id": 17,
                "selected_output_mode": "html_report_package",
                "title_override": "Toronto housing strategy report",
            }
        )

        self.assertEqual(result.selected_output_mode, "html_report_package")
        self.assertEqual(result.status, "not_generated")
        self.assertTrue(result.requires_explicit_operator_step)
        self.assertEqual(result.artifacts, [])
        self.assertIn("separate explicit operator step", result.operator_notes[0].lower())


class EventStrategyReviewErrorHandlingTests(unittest.TestCase):
    def test_invalid_source_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            event_strategy_review.normalize_run_request(
                {
                    "retrieval_contract": {
                        "source_mode": "crawl_the_entire_web",
                    }
                }
            )

    def test_missing_manual_summary_payload_raises_value_error(self):
        with self.assertRaises(ValueError):
            event_strategy_review.normalize_run_request(
                {
                    "retrieval_contract": {
                        "source_mode": "manual_summary",
                        "manual_summary_input": {"headline": "Missing summary"},
                    }
                }
            )

    def test_empty_manual_url_bundle_raises_value_error(self):
        with self.assertRaises(ValueError):
            event_strategy_review.normalize_run_request(
                {
                    "retrieval_contract": {
                        "source_mode": "manual_url_bundle",
                        "manual_url_bundle_input": {"items": []},
                    }
                }
            )


class EventStrategyReviewPersistenceTests(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def parse_result(
        self,
        run: agent_models.AgentRun,
    ) -> agent_schemas.EventStrategyReviewExecutionResult:
        self.assertIsNotNone(run.result)
        payload = json.loads(run.result)
        return agent_schemas.EventStrategyReviewExecutionResult(**payload)

    def test_manual_summary_run_persists_task_run_report_and_audit(self):
        run = event_strategy_review.run_event_strategy_review_once(
            self.db,
            {
                "retrieval_contract": {
                    "source_mode": "manual_summary",
                    "manual_summary_input": {
                        "headline": "Toronto policy update",
                        "summary": "Housing and rental policy changes may affect buyer and seller conversations.",
                        "source_label": "manual_note",
                    },
                },
                "geo_focus": ["Toronto", "Ontario"],
            },
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.task.agent_type, "event_strategy_review")
        self.assertEqual(run.task.status, "completed")
        self.assertEqual(run.approvals, [])

        result = self.parse_result(run)
        self.assertEqual(result.execution_status, "report_generated")
        self.assertIsNotNone(result.report)
        self.assertEqual(
            result.report.retrieval_contract.source_mode,
            "manual_summary",
        )

        audit_actions = [log.action for log in run.audit_logs]
        self.assertEqual(
            audit_actions,
            [
                "event_strategy_review_intake_received",
                "event_strategy_review_execution_planned",
                "event_strategy_review_sources_clustered",
                "event_strategy_review_importance_classified",
                "event_strategy_review_perspectives_built",
                "event_strategy_review_report_generated",
                "event_strategy_review_run_completed",
            ],
        )

    def test_manual_url_bundle_run_dedupes_obvious_duplicates_before_persistence(self):
        run = event_strategy_review.run_event_strategy_review_once(
            self.db,
            {
                "retrieval_contract": {
                    "source_mode": "manual_url_bundle",
                    "manual_url_bundle_input": {
                        "items": [
                            {
                                "url": "https://example.com/story",
                                "title": "Rate story",
                                "publisher": "Example",
                            },
                            {
                                "url": "https://example.com/story/",
                                "title": "Duplicate rate story",
                            },
                            {
                                "url": "https://example.com/story?utm_source=x",
                                "title": "Tracked duplicate rate story",
                            },
                            {
                                "url": "https://example.com/second",
                                "title": "Second story",
                            },
                        ]
                    },
                }
            },
        )

        result = self.parse_result(run)
        self.assertEqual(result.execution_status, "report_generated")
        self.assertIsNotNone(result.report)
        self.assertEqual(result.execution_plan.deduped_source_count, 2)
        self.assertEqual(result.execution_plan.duplicate_source_count, 2)
        self.assertEqual(result.report.event_cluster.source_count, 2)
        self.assertEqual(result.report.event_cluster.duplicate_count, 2)
        self.assertTrue(
            any(log.action == "event_strategy_review_duplicates_collapsed" for log in run.audit_logs)
        )

    def test_curated_search_query_is_persisted_as_not_active_yet_without_crashing(self):
        run = event_strategy_review.run_event_strategy_review_once(
            self.db,
            {
                "retrieval_contract": {
                    "source_mode": "curated_search_query",
                    "curated_search_query_input": {
                        "query": "Toronto housing policy change",
                        "allowed_domains": ["toronto.ca"],
                    },
                }
            },
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.task.status, "completed")
        self.assertEqual(run.approvals, [])

        result = self.parse_result(run)
        self.assertEqual(result.execution_status, "not_active_yet")
        self.assertIsNone(result.report)
        self.assertEqual(
            result.execution_plan.execution_path,
            "curated_search_query_not_active_yet",
        )
        self.assertEqual(
            result.inactive_reason,
            event_strategy_review.CURATED_QUERY_NOT_ACTIVE_NOTE,
        )

        audit_actions = [log.action for log in run.audit_logs]
        self.assertIn("event_strategy_review_source_mode_not_active", audit_actions)
        self.assertIn("event_strategy_review_run_completed", audit_actions)

    def test_malformed_input_fails_safe_without_approvals(self):
        run = event_strategy_review.run_event_strategy_review_once(
            self.db,
            {
                "retrieval_contract": {
                    "source_mode": "manual_summary",
                    "manual_summary_input": {"headline": "Missing summary"},
                }
            },
        )

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.task.status, "failed")
        self.assertEqual(run.approvals, [])
        self.assertIn("event_strategy_review_manual_summary_required", run.error)
        self.assertTrue(
            any(log.action == "event_strategy_review_run_failed" for log in run.audit_logs)
        )


if __name__ == "__main__":
    unittest.main()
