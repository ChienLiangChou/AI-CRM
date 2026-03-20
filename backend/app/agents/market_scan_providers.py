from __future__ import annotations

from abc import ABC
from typing import Any

from . import schemas as agent_schemas


STRATUS_PROVIDER_NOTE = (
    "TorontoMLS / Stratus is an authenticated provider and may be unavailable,"
    " unauthenticated, or expired."
)
PUBLIC_PROVIDER_NOTE = (
    "Public listing provider is fallback-capable but lower-confidence and"
    " lower-detail than authenticated MLS sources."
)


class BaseMarketScanProvider(ABC):
    provider_key: agent_schemas.DailyMarketScanProviderKey
    display_name: str
    authentication_required: bool = False
    auth_state: agent_schemas.DailyMarketScanProviderAuthState = "not_required"
    availability: agent_schemas.DailyMarketScanProviderAvailability = "available"
    detail_level: str = "standard_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "medium"
    fallback_capable: bool = False
    notes: tuple[str, ...] = ()

    def describe(self) -> agent_schemas.DailyMarketScanProviderDescriptor:
        return agent_schemas.DailyMarketScanProviderDescriptor(
            provider_key=self.provider_key,
            display_name=self.display_name,
            authentication_required=self.authentication_required,
            auth_state=self.auth_state,
            availability=self.availability,
            detail_level=self.detail_level,
            confidence_level=self.confidence_level,
            fallback_capable=self.fallback_capable,
            notes=list(self.notes),
        )

    def build_source_attempt(
        self,
        *,
        status: agent_schemas.DailyMarketScanProviderAttemptStatus,
        source_used: str | None = None,
        fallback_used: bool = False,
        failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata]
        | None = None,
        notes: list[str] | None = None,
        auth_state: agent_schemas.DailyMarketScanProviderAuthState | None = None,
    ) -> agent_schemas.DailyMarketScanSourceAttempt:
        return agent_schemas.DailyMarketScanSourceAttempt(
            provider_key=self.provider_key,
            source_used=source_used or self.provider_key,
            status=status,
            auth_state=auth_state or self.auth_state,
            fallback_used=fallback_used,
            failure_metadata=failure_metadata or [],
            notes=notes or [],
        )

    def build_scan_result(
        self,
        *,
        status: agent_schemas.DailyMarketScanProviderAttemptStatus,
        source_used: str | None = None,
        fallback_used: bool = False,
        findings: list[agent_schemas.DailyMarketScanFinding] | None = None,
        failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata]
        | None = None,
        notes: list[str] | None = None,
        auth_state: agent_schemas.DailyMarketScanProviderAuthState | None = None,
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return agent_schemas.DailyMarketScanProviderScanResult(
            provider_key=self.provider_key,
            source_used=source_used or self.provider_key,
            status=status,
            auth_state=auth_state or self.auth_state,
            fallback_used=fallback_used,
            findings=findings or [],
            failure_metadata=failure_metadata or [],
            notes=notes or [],
        )

    # Stub-friendly provider methods. Step 1 defines the abstraction only;
    # concrete scanning logic is added later.
    def scan_client_matches(self, context: Any) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("client_match_scan_not_implemented")

    def scan_condo_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("condo_competitor_scan_not_implemented")

    def scan_area_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("area_competitor_scan_not_implemented")


class StratusAuthenticatedProvider(BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "stratus_authenticated"
    display_name = "TorontoMLS / Stratus"
    authentication_required = True
    detail_level = "high_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "high"
    fallback_capable = False

    def __init__(
        self,
        *,
        auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
        availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    ):
        self.auth_state = auth_state
        self.availability = availability
        self.notes = (STRATUS_PROVIDER_NOTE,)


class PublicListingProvider(BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "public_listing"
    display_name = "Public Listing Source"
    authentication_required = False
    auth_state: agent_schemas.DailyMarketScanProviderAuthState = "not_required"
    detail_level = "lower_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "low"
    fallback_capable = True

    def __init__(
        self,
        *,
        availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
    ):
        self.availability = availability
        self.notes = (PUBLIC_PROVIDER_NOTE,)


def build_provider_registry(
    *,
    stratus_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    stratus_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider]:
    return {
        "stratus_authenticated": StratusAuthenticatedProvider(
            auth_state=stratus_auth_state,
            availability=stratus_availability,
        ),
        "public_listing": PublicListingProvider(
            availability=public_availability,
        ),
    }


def provider_order_for_preference(
    source_preference: agent_schemas.DailyMarketScanSourcePreference,
) -> list[agent_schemas.DailyMarketScanProviderKey]:
    if source_preference == "public_only":
        return ["public_listing"]
    return ["stratus_authenticated", "public_listing"]


def build_provider_catalog(
    *,
    source_preference: agent_schemas.DailyMarketScanSourcePreference = "auto",
    stratus_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    stratus_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> list[agent_schemas.DailyMarketScanProviderDescriptor]:
    registry = build_provider_registry(
        stratus_auth_state=stratus_auth_state,
        stratus_availability=stratus_availability,
        public_availability=public_availability,
    )
    ordered_keys = provider_order_for_preference(source_preference)
    return [registry[key].describe() for key in ordered_keys]
