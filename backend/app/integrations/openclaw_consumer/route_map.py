from __future__ import annotations

from typing import Optional

from ...agents import schemas as agent_schemas
from .models import OpenClawModuleDetailSupport, OpenClawReadonlyRoute


CONTROL_ROOM_PATH = "/api/agents/openclaw/control-room"

_MODULE_CONFIG: dict[agent_schemas.AgentType, dict[str, object]] = {
    "follow_up": {
        "label": "Follow-up",
        "depth": "shallow",
        "latest_path": "/api/agents/follow-up/recommendations",
        "audit_path_template": "/api/agents/runs/{run_id}/audit-logs",
        "notes": (
            "Follow-up stays shallow in Phase 1.",
            "No per-run report route is required for this step.",
        ),
    },
    "conversation_closer": {
        "label": "Client Conversation Closer",
        "depth": "shallow",
        "latest_path": "/api/agents/conversation-closer/latest",
        "audit_path_template": "/api/agents/conversation-closer/runs/{run_id}/audit-logs",
    },
    "listing_cma": {
        "label": "Listing / CMA",
        "depth": "shallow",
        "latest_path": "/api/agents/listing-cma/latest",
        "audit_path_template": "/api/agents/listing-cma/runs/{run_id}/audit-logs",
    },
    "buyer_match": {
        "label": "Buyer Match",
        "depth": "shallow",
        "latest_path": "/api/agents/buyer-match/latest",
        "audit_path_template": "/api/agents/buyer-match/runs/{run_id}/audit-logs",
    },
    "strategy_coordination": {
        "label": "Strategy Coordination",
        "depth": "deep",
        "latest_path": "/api/agents/strategy-coordination/latest",
        "report_path_template": "/api/agents/strategy-coordination/runs/{run_id}/report",
        "audit_path_template": "/api/agents/strategy-coordination/runs/{run_id}/audit-logs",
    },
    "daily_market_scan": {
        "label": "Daily Market Scan",
        "depth": "deep",
        "latest_path": "/api/agents/daily-market-scan/latest",
        "report_path_template": "/api/agents/daily-market-scan/runs/{run_id}/report",
        "audit_path_template": "/api/agents/daily-market-scan/runs/{run_id}/audit-logs",
    },
}


def _resolve_path(
    template: str | None,
    *,
    run_id: int | None,
) -> str | None:
    if template is None:
        return None
    if "{run_id}" not in template:
        return template
    if run_id is None:
        return None
    return template.format(run_id=run_id)


def get_control_room_route() -> OpenClawReadonlyRoute:
    return OpenClawReadonlyRoute(
        kind="control_room",
        path=CONTROL_ROOM_PATH,
    )


def get_module_detail_support(
    agent_type: agent_schemas.AgentType,
    *,
    run_id: int | None = None,
) -> OpenClawModuleDetailSupport:
    config = _MODULE_CONFIG[agent_type]
    latest_path = _resolve_path(
        config.get("latest_path"),  # type: ignore[arg-type]
        run_id=run_id,
    )
    report_path = _resolve_path(
        config.get("report_path_template"),  # type: ignore[arg-type]
        run_id=run_id,
    )
    audit_path = _resolve_path(
        config.get("audit_path_template"),  # type: ignore[arg-type]
        run_id=run_id,
    )

    return OpenClawModuleDetailSupport(
        agent_type=agent_type,
        label=config["label"],  # type: ignore[index]
        depth=config["depth"],  # type: ignore[index]
        latest=(
            OpenClawReadonlyRoute(kind="latest", path=latest_path)
            if latest_path
            else None
        ),
        report=(
            OpenClawReadonlyRoute(kind="report", path=report_path)
            if report_path
            else None
        ),
        audit_logs=(
            OpenClawReadonlyRoute(kind="audit_logs", path=audit_path)
            if audit_path
            else None
        ),
        notes=list(config.get("notes", ())),  # type: ignore[arg-type]
    )


def supports_deep_detail(agent_type: agent_schemas.AgentType) -> bool:
    return _MODULE_CONFIG[agent_type]["depth"] == "deep"


def get_allowed_get_paths() -> set[str]:
    paths = {CONTROL_ROOM_PATH}
    for agent_type in _MODULE_CONFIG:
        support = get_module_detail_support(agent_type, run_id=999)
        for route in (support.latest, support.report, support.audit_logs):
            if route is not None:
                paths.add(route.path)
    return paths
