from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ...agents import schemas as agent_schemas


OpenClawDetailDepth = Literal["deep", "shallow"]
OpenClawDetailLoadStatus = Literal["loaded", "partial", "unavailable"]
OpenClawRouteKind = Literal["control_room", "latest", "report", "audit_logs"]


class OpenClawReadonlyRoute(BaseModel):
    kind: OpenClawRouteKind
    path: str
    method: Literal["GET"] = "GET"


class OpenClawModuleDetailSupport(BaseModel):
    agent_type: agent_schemas.AgentType
    label: str
    depth: OpenClawDetailDepth
    latest: Optional[OpenClawReadonlyRoute] = None
    report: Optional[OpenClawReadonlyRoute] = None
    audit_logs: Optional[OpenClawReadonlyRoute] = None
    notes: list[str] = Field(default_factory=list)


class OpenClawModuleHomeItem(BaseModel):
    card: agent_schemas.OpenClawModuleCard
    detail_support: OpenClawModuleDetailSupport


class OpenClawControlRoomHomeView(BaseModel):
    control_room_route: OpenClawReadonlyRoute
    snapshot: agent_schemas.OpenClawControlRoomResponse
    modules: list[OpenClawModuleHomeItem] = Field(default_factory=list)


class OpenClawModuleDetailResult(BaseModel):
    agent_type: agent_schemas.AgentType
    label: str
    depth: OpenClawDetailDepth
    status: OpenClawDetailLoadStatus
    latest: Optional[Any] = None
    report: Optional[Any] = None
    audit_logs: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    routes_used: list[OpenClawReadonlyRoute] = Field(default_factory=list)
