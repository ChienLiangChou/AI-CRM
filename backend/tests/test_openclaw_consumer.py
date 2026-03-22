import sys
import types
import unittest
from datetime import UTC, datetime

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app.agents import schemas as agent_schemas
from app.integrations.openclaw_consumer.client import OpenClawReadonlyClient
from app.integrations.openclaw_consumer.route_map import (
    CONTROL_ROOM_PATH,
    get_allowed_get_paths,
)
from app.integrations.openclaw_consumer.service import (
    build_control_room_home_view,
    load_module_detail,
)


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class RecordingTransport:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls = []

    def get(self, path: str):
        self.calls.append(("GET", path))
        if path in self.errors:
            raise self.errors[path]
        if path not in self.responses:
            raise RuntimeError(f"missing_response:{path}")
        return self.responses[path]


class OpenClawConsumerTests(unittest.TestCase):
    def build_snapshot_payload(self):
        snapshot = agent_schemas.OpenClawControlRoomResponse(
            as_of=datetime.now(UTC).replace(tzinfo=None),
            module_cards=[
                agent_schemas.OpenClawModuleCard(
                    agent_type="follow_up",
                    label="Follow-up",
                    latest_run_id=11,
                    latest_run_status="waiting_approval",
                ),
                agent_schemas.OpenClawModuleCard(
                    agent_type="conversation_closer",
                    label="Client Conversation Closer",
                    latest_run_id=12,
                    latest_run_status="completed",
                ),
                agent_schemas.OpenClawModuleCard(
                    agent_type="listing_cma",
                    label="Listing / CMA",
                    latest_run_id=13,
                    latest_run_status="completed",
                ),
                agent_schemas.OpenClawModuleCard(
                    agent_type="buyer_match",
                    label="Buyer Match",
                    latest_run_id=14,
                    latest_run_status="failed",
                ),
                agent_schemas.OpenClawModuleCard(
                    agent_type="strategy_coordination",
                    label="Strategy Coordination",
                    latest_run_id=21,
                    latest_run_status="completed",
                ),
                agent_schemas.OpenClawModuleCard(
                    agent_type="daily_market_scan",
                    label="Daily Market Scan",
                    latest_run_id=31,
                    latest_run_status="completed",
                ),
            ],
        )
        return dump_model(snapshot)

    def test_build_control_room_home_view_parses_snapshot_and_attaches_route_support(self):
        transport = RecordingTransport(
            responses={
                CONTROL_ROOM_PATH: self.build_snapshot_payload(),
            }
        )
        client = OpenClawReadonlyClient(transport)

        home_view = build_control_room_home_view(client)

        self.assertEqual(transport.calls, [("GET", CONTROL_ROOM_PATH)])
        self.assertEqual(home_view.control_room_route.path, CONTROL_ROOM_PATH)
        self.assertEqual(len(home_view.modules), 6)

        by_agent = {
            item.card.agent_type: item.detail_support
            for item in home_view.modules
        }

        self.assertEqual(by_agent["follow_up"].depth, "shallow")
        self.assertEqual(
            by_agent["follow_up"].latest.path,
            "/api/agents/follow-up/recommendations",
        )
        self.assertIsNone(by_agent["follow_up"].report)
        self.assertEqual(
            by_agent["follow_up"].audit_logs.path,
            "/api/agents/runs/11/audit-logs",
        )

        self.assertEqual(by_agent["strategy_coordination"].depth, "deep")
        self.assertEqual(
            by_agent["strategy_coordination"].latest.path,
            "/api/agents/strategy-coordination/latest",
        )
        self.assertEqual(
            by_agent["strategy_coordination"].report.path,
            "/api/agents/strategy-coordination/runs/21/report",
        )
        self.assertEqual(
            by_agent["daily_market_scan"].audit_logs.path,
            "/api/agents/daily-market-scan/runs/31/audit-logs",
        )

    def test_load_module_detail_uses_only_get_routes_for_deep_module(self):
        transport = RecordingTransport(
            responses={
                "/api/agents/strategy-coordination/latest": {"run_id": 21},
                "/api/agents/strategy-coordination/runs/21/report": {
                    "event_summary": {"event_type": "policy_shift"}
                },
                "/api/agents/strategy-coordination/runs/21/audit-logs": [],
            }
        )
        client = OpenClawReadonlyClient(transport)

        result = load_module_detail(
            client,
            agent_type="strategy_coordination",
            run_id=21,
        )

        self.assertEqual(result.depth, "deep")
        self.assertEqual(result.status, "loaded")
        self.assertEqual(
            transport.calls,
            [
                ("GET", "/api/agents/strategy-coordination/latest"),
                ("GET", "/api/agents/strategy-coordination/runs/21/report"),
                ("GET", "/api/agents/strategy-coordination/runs/21/audit-logs"),
            ],
        )
        self.assertEqual(result.latest, {"run_id": 21})
        self.assertEqual(
            result.report,
            {"event_summary": {"event_type": "policy_shift"}},
        )
        self.assertEqual(result.audit_logs, [])

    def test_load_module_detail_fails_soft_when_detail_endpoint_is_unavailable(self):
        transport = RecordingTransport(
            responses={
                "/api/agents/daily-market-scan/latest": {"run_id": 31},
            },
            errors={
                "/api/agents/daily-market-scan/runs/31/report": RuntimeError("404"),
                "/api/agents/daily-market-scan/runs/31/audit-logs": RuntimeError("503"),
            },
        )
        client = OpenClawReadonlyClient(transport)

        result = load_module_detail(
            client,
            agent_type="daily_market_scan",
            run_id=31,
        )

        self.assertEqual(result.depth, "deep")
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.latest, {"run_id": 31})
        self.assertIsNone(result.report)
        self.assertEqual(result.audit_logs, [])
        self.assertEqual(len(result.errors), 2)
        self.assertTrue(any("report:/api/agents/daily-market-scan/runs/31/report:404" in err for err in result.errors))
        self.assertTrue(any("audit_logs:/api/agents/daily-market-scan/runs/31/audit-logs:503" in err for err in result.errors))

    def test_follow_up_stays_shallow_and_uses_existing_routes_only(self):
        transport = RecordingTransport(
            responses={
                "/api/agents/follow-up/recommendations": {
                    "recommendations": [],
                    "drafts": [],
                    "run_id": 11,
                },
                "/api/agents/runs/11/audit-logs": [],
            }
        )
        client = OpenClawReadonlyClient(transport)

        result = load_module_detail(
            client,
            agent_type="follow_up",
            run_id=11,
        )

        self.assertEqual(result.depth, "shallow")
        self.assertEqual(result.status, "loaded")
        self.assertIsNone(result.report)
        self.assertEqual(
            transport.calls,
            [
                ("GET", "/api/agents/follow-up/recommendations"),
                ("GET", "/api/agents/runs/11/audit-logs"),
            ],
        )

    def test_allowed_route_map_is_get_only_and_excludes_write_or_ops_routes(self):
        paths = get_allowed_get_paths()

        self.assertIn(CONTROL_ROOM_PATH, paths)
        self.assertTrue(all(path.startswith("/api/agents/") for path in paths))
        self.assertFalse(any("/approve" in path for path in paths))
        self.assertFalse(any("/reject" in path for path in paths))
        self.assertFalse(any("/run-once" in path for path in paths))
        self.assertFalse(any("/ops/" in path for path in paths))


if __name__ == "__main__":
    unittest.main()
