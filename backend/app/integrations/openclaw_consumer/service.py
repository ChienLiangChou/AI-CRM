from __future__ import annotations

from typing import Any

from ...agents import schemas as agent_schemas
from .client import OpenClawReadonlyClient
from .models import (
    OpenClawControlRoomHomeView,
    OpenClawModuleDetailResult,
    OpenClawModuleHomeItem,
)
from .route_map import get_control_room_route, get_module_detail_support


def build_control_room_home_view(
    client: OpenClawReadonlyClient,
) -> OpenClawControlRoomHomeView:
    snapshot = client.get_control_room_snapshot()
    modules = [
        OpenClawModuleHomeItem(
            card=card,
            detail_support=get_module_detail_support(
                card.agent_type,
                run_id=card.latest_run_id,
            ),
        )
        for card in snapshot.module_cards
    ]
    return OpenClawControlRoomHomeView(
        control_room_route=get_control_room_route(),
        snapshot=snapshot,
        modules=modules,
    )


def _error_message(
    *,
    route_kind: str,
    path: str,
    exc: Exception,
) -> str:
    return f"{route_kind}:{path}:{exc}"


def _derive_status(
    *,
    latest_loaded: bool,
    report_loaded: bool,
    audit_loaded: bool,
    attempted_count: int,
    errors: list[str],
) -> str:
    loaded_count = sum((latest_loaded, report_loaded, audit_loaded))
    if loaded_count == 0:
        return "unavailable"
    if errors or loaded_count < attempted_count:
        return "partial"
    return "loaded"


def load_module_detail(
    client: OpenClawReadonlyClient,
    *,
    agent_type: agent_schemas.AgentType,
    run_id: int | None = None,
) -> OpenClawModuleDetailResult:
    support = get_module_detail_support(agent_type, run_id=run_id)
    latest: Any = None
    report: Any = None
    audit_logs: list[Any] = []
    errors: list[str] = []
    routes_used = []

    latest_loaded = False
    report_loaded = False
    audit_loaded = False
    attempted_count = 0

    if support.latest is not None:
        attempted_count += 1
        routes_used.append(support.latest)
        try:
            latest = client.get_latest_payload(support.latest)
            latest_loaded = True
        except Exception as exc:  # fail-soft bridge by design
            errors.append(
                _error_message(
                    route_kind="latest",
                    path=support.latest.path,
                    exc=exc,
                )
            )

    if support.report is not None:
        attempted_count += 1
        routes_used.append(support.report)
        try:
            report = client.get_report_payload(support.report)
            report_loaded = True
        except Exception as exc:  # fail-soft bridge by design
            errors.append(
                _error_message(
                    route_kind="report",
                    path=support.report.path,
                    exc=exc,
                )
            )

    if support.audit_logs is not None:
        attempted_count += 1
        routes_used.append(support.audit_logs)
        try:
            audit_logs = client.get_audit_logs_payload(support.audit_logs)
            audit_loaded = True
        except Exception as exc:  # fail-soft bridge by design
            errors.append(
                _error_message(
                    route_kind="audit_logs",
                    path=support.audit_logs.path,
                    exc=exc,
                )
            )

    return OpenClawModuleDetailResult(
        agent_type=agent_type,
        label=support.label,
        depth=support.depth,
        status=_derive_status(
            latest_loaded=latest_loaded,
            report_loaded=report_loaded,
            audit_loaded=audit_loaded,
            attempted_count=attempted_count,
            errors=errors,
        ),
        latest=latest,
        report=report,
        audit_logs=audit_logs,
        errors=errors,
        routes_used=routes_used,
    )
