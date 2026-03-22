from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from ...agents import schemas as agent_schemas
from . import route_map
from .models import OpenClawReadonlyRoute


class OpenClawReadonlyTransport(Protocol):
    def get(self, path: str) -> Any:
        ...


def _validate_model(model_cls: Any, payload: Any):
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid_payload_for_{model_cls.__name__}") from exc


def _validate_model_list(model_cls: Any, payload: Any) -> list[Any]:
    if not isinstance(payload, list):
        raise ValueError("invalid_payload_for_list")
    return [_validate_model(model_cls, item) for item in payload]


class OpenClawReadonlyClient:
    def __init__(self, transport: OpenClawReadonlyTransport):
        self._transport = transport

    def _get_json(self, route: OpenClawReadonlyRoute) -> Any:
        if route.method != "GET":
            raise ValueError("read_only_client_requires_get")
        return self._transport.get(route.path)

    def get_control_room_snapshot(self) -> agent_schemas.OpenClawControlRoomResponse:
        payload = self._get_json(route_map.get_control_room_route())
        return _validate_model(agent_schemas.OpenClawControlRoomResponse, payload)

    def get_latest_payload(self, route: OpenClawReadonlyRoute) -> Any:
        return self._get_json(route)

    def get_report_payload(self, route: OpenClawReadonlyRoute) -> Any:
        return self._get_json(route)

    def get_audit_logs_payload(
        self,
        route: OpenClawReadonlyRoute,
    ) -> list[agent_schemas.AgentAuditLog]:
        payload = self._get_json(route)
        return _validate_model_list(agent_schemas.AgentAuditLog, payload)
