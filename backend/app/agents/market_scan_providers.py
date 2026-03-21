from __future__ import annotations

from abc import ABC
from typing import Any

from . import schemas as agent_schemas


AUTHENTICATED_BROWSER_PROVIDER_NOTE = (
    "Authenticated MLS browser is a future-facing provider path that can later"
    " consume auth availability without depending on browser runtime internals"
    " in this layer."
)
PUBLIC_PROVIDER_NOTE = (
    "Public listing provider is fallback-capable but lower-confidence and"
    " lower-detail than authenticated MLS sources."
)
STUB_EXECUTION_NOTE = (
    "Stub provider execution only. Real source retrieval is not enabled in this"
    " step."
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

    def scan_client_matches(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("client_match_scan_not_implemented")

    def scan_condo_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("condo_competitor_scan_not_implemented")

    def scan_area_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        raise NotImplementedError("area_competitor_scan_not_implemented")


class AuthenticatedMlsBrowserProvider(BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "authenticated_mls_browser"
    display_name = "Authenticated MLS Browser"
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
        self.notes = (AUTHENTICATED_BROWSER_PROVIDER_NOTE,)

    def _stub_scan_result(
        self, workflow_label: str
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata] = []
        notes = [STUB_EXECUTION_NOTE, f"{workflow_label} via authenticated browser remains stub-only."]

        if self.availability == "unavailable":
            failure_metadata.append(
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="provider_unavailable",
                    message="Authenticated MLS browser provider is unavailable.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            )
            return self.build_scan_result(
                status="failed",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        if self.auth_state == "expired":
            failure_metadata.append(
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="auth_expired",
                    message="Authenticated MLS browser requires renewed auth before use.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            )
            return self.build_scan_result(
                status="expired",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        if self.auth_state == "failed":
            failure_metadata.append(
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="auth_failed",
                    message="Authenticated MLS browser auth is currently failed.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            )
            return self.build_scan_result(
                status="failed",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        if self.auth_state != "authenticated":
            failure_metadata.append(
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="auth_unavailable",
                    message="Authenticated MLS browser is not currently authenticated.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            )
            return self.build_scan_result(
                status="unauthenticated",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        return self.build_scan_result(
            status="completed",
            notes=notes,
        )

    def scan_client_matches(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Client match scan")

    def scan_condo_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Condo competitor scan")

    def scan_area_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Area competitor scan")


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

    def _stub_scan_result(
        self, workflow_label: str
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata] = []
        notes = [STUB_EXECUTION_NOTE, f"{workflow_label} via public listing source remains stub-only."]

        if self.availability == "unavailable":
            failure_metadata.append(
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="provider_unavailable",
                    message="Public listing provider is unavailable.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            )
            return self.build_scan_result(
                status="failed",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        return self.build_scan_result(
            status="completed",
            notes=notes,
        )

    def scan_client_matches(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Client match scan")

    def scan_condo_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Condo competitor scan")

    def scan_area_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Area competitor scan")


def build_provider_registry(
    *,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider]:
    return {
        "authenticated_mls_browser": AuthenticatedMlsBrowserProvider(
            auth_state=authenticated_mls_browser_auth_state,
            availability=authenticated_mls_browser_availability,
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
    return ["authenticated_mls_browser", "public_listing"]


def build_provider_catalog(
    *,
    source_preference: agent_schemas.DailyMarketScanSourcePreference = "auto",
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> list[agent_schemas.DailyMarketScanProviderDescriptor]:
    registry = build_provider_registry(
        authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
        authenticated_mls_browser_availability=authenticated_mls_browser_availability,
        public_availability=public_availability,
    )
    ordered_keys = provider_order_for_preference(source_preference)
    return [registry[key].describe() for key in ordered_keys]


def build_provider_catalog_from_registry(
    registry: dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider],
    *,
    source_preference: agent_schemas.DailyMarketScanSourcePreference = "auto",
) -> list[agent_schemas.DailyMarketScanProviderDescriptor]:
    ordered_keys = provider_order_for_preference(source_preference)
    return [
        registry[key].describe()
        for key in ordered_keys
        if key in registry
    ]


def build_provider_registry_from_catalog(
    provider_catalog: list[
        agent_schemas.DailyMarketScanProviderDescriptor | dict[str, Any]
    ],
) -> dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider]:
    registry: dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider] = {}
    for item in provider_catalog:
        descriptor = (
            item
            if isinstance(item, agent_schemas.DailyMarketScanProviderDescriptor)
            else agent_schemas.DailyMarketScanProviderDescriptor.model_validate(item)
        )
        if descriptor.provider_key == "authenticated_mls_browser":
            registry[descriptor.provider_key] = AuthenticatedMlsBrowserProvider(
                auth_state=descriptor.auth_state,
                availability=descriptor.availability,
            )
        elif descriptor.provider_key == "public_listing":
            registry[descriptor.provider_key] = PublicListingProvider(
                availability=descriptor.availability,
            )
    return registry


def ordered_registry_items(
    registry: dict[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider],
    *,
    source_preference: agent_schemas.DailyMarketScanSourcePreference = "auto",
) -> list[tuple[agent_schemas.DailyMarketScanProviderKey, BaseMarketScanProvider]]:
    ordered_keys = provider_order_for_preference(source_preference)
    return [(key, registry[key]) for key in ordered_keys if key in registry]
