from __future__ import annotations

from abc import ABC
from typing import Any, Callable

from . import schemas as agent_schemas
from . import public_listing_fetcher, public_listing_normalizer


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
PUBLIC_RETRIEVAL_NOTE = (
    "Exact public URL retrieval only. Broad crawling, browser automation, and"
    " anti-bot workarounds are out of scope."
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
        fetch_page: Callable[
            [str], public_listing_fetcher.PublicListingFetchedPage
        ]
        | None = None,
    ):
        self.availability = availability
        self.notes = (PUBLIC_PROVIDER_NOTE, PUBLIC_RETRIEVAL_NOTE)
        self._fetch_page = fetch_page or public_listing_fetcher.fetch_public_listing_page

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

    def _failure(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        fallback_attempted: bool = False,
        fallback_used: bool = False,
    ) -> agent_schemas.DailyMarketScanFailureMetadata:
        return agent_schemas.DailyMarketScanFailureMetadata(
            provider_key=self.provider_key,
            code=code,
            message=message,
            retryable=retryable,
            fallback_attempted=fallback_attempted,
            fallback_used=fallback_used,
        )

    def _candidate_urls(self, context: Any) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        listing = context.get("listing") if isinstance(context, dict) else None
        property_snapshot = context.get("property") if isinstance(context, dict) else None

        for raw_value in [
            listing.get("listing_ref") if isinstance(listing, dict) else None,
            listing.get("listing_url") if isinstance(listing, dict) else None,
            property_snapshot.get("listing_url")
            if isinstance(property_snapshot, dict)
            else None,
        ]:
            normalized = public_listing_fetcher.normalize_public_listing_url(raw_value)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
        return urls

    def _fetch_records(
        self,
        context: Any,
    ) -> tuple[
        list[public_listing_normalizer.CanonicalPublicListingRecord],
        list[agent_schemas.DailyMarketScanFailureMetadata],
        list[str],
    ]:
        urls = self._candidate_urls(context)
        if not urls:
            return (
                [],
                [
                    self._failure(
                        code="public_reference_missing",
                        message="Public competitor retrieval requires an exact allowlisted public URL.",
                        retryable=False,
                    )
                ],
                ["No allowlisted public URL was available for this competitor-watch subject."],
            )

        failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata] = []
        notes: list[str] = [PUBLIC_RETRIEVAL_NOTE]
        records: list[public_listing_normalizer.CanonicalPublicListingRecord] = []

        for url in urls:
            try:
                page = self._fetch_page(url)
            except public_listing_fetcher.PublicListingFetchError as exc:
                failure_metadata.append(
                    self._failure(
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                    )
                )
                continue

            normalized = public_listing_normalizer.dedupe_public_listing_records(
                public_listing_normalizer.normalize_public_listing_records(page)
            )
            if not normalized:
                failure_metadata.append(
                    self._failure(
                        code="public_parse_no_records",
                        message="The public page did not expose usable structured listing records.",
                        retryable=False,
                    )
                )
                continue
            notes.append(f"Retrieved {len(normalized)} normalized public record(s) from {page.host}.")
            records.extend(normalized)

        if not records:
            return ([], failure_metadata, notes)

        return (
            public_listing_normalizer.dedupe_public_listing_records(records),
            failure_metadata,
            notes,
        )

    def _subject_building_key(self, context: Any) -> str | None:
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        listing = context.get("listing") if isinstance(context, dict) else None
        street = None
        city = None
        postal_code = None
        if isinstance(property_snapshot, dict):
            street = property_snapshot.get("street")
            city = property_snapshot.get("city")
            postal_code = property_snapshot.get("postal_code")
        elif isinstance(listing, dict):
            street = listing.get("street")
            city = listing.get("city")
            postal_code = listing.get("postal_code")

        record = public_listing_normalizer.CanonicalPublicListingRecord(
            source_family="subject",
            source_url="subject",
            external_listing_id=None,
            address=" ".join(part for part in [street, city] if part) or "subject",
            street=street,
            unit=None,
            city=city,
            postal_code=postal_code,
            neighborhood=None,
            property_type=None,
            list_price=None,
            listing_status=None,
            bedrooms=None,
            bathrooms=None,
            notes=(),
        )
        return public_listing_normalizer.building_key_for_record(record)

    def _subject_unit(self, context: Any) -> str | None:
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        listing = context.get("listing") if isinstance(context, dict) else None
        raw = None
        if isinstance(property_snapshot, dict):
            raw = property_snapshot.get("unit")
        elif isinstance(listing, dict):
            raw = listing.get("unit")
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def _subject_city(self, context: Any) -> str | None:
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        listing = context.get("listing") if isinstance(context, dict) else None
        if isinstance(property_snapshot, dict):
            return property_snapshot.get("city")
        if isinstance(listing, dict):
            return listing.get("city")
        return None

    def _subject_neighborhood(self, context: Any) -> str | None:
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        listing = context.get("listing") if isinstance(context, dict) else None
        if isinstance(property_snapshot, dict):
            return property_snapshot.get("neighborhood")
        if isinstance(listing, dict):
            return listing.get("neighborhood")
        return None

    def _subject_postal_prefix(self, context: Any) -> str | None:
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        listing = context.get("listing") if isinstance(context, dict) else None
        postal_code = None
        if isinstance(property_snapshot, dict):
            postal_code = property_snapshot.get("postal_code")
        elif isinstance(listing, dict):
            postal_code = listing.get("postal_code")
        return public_listing_normalizer.postal_prefix_for_record(
            public_listing_normalizer.CanonicalPublicListingRecord(
                source_family="subject",
                source_url="subject",
                external_listing_id=None,
                address="subject",
                street=None,
                unit=None,
                city=None,
                postal_code=postal_code,
                neighborhood=None,
                property_type=None,
                list_price=None,
                listing_status=None,
                bedrooms=None,
                bathrooms=None,
                notes=(),
            )
        )

    def _finding_from_record(
        self,
        record: public_listing_normalizer.CanonicalPublicListingRecord,
        *,
        competitor_mode: agent_schemas.DailyMarketScanCompetitorMode,
    ) -> agent_schemas.DailyMarketScanFinding:
        competitor_notes = list(record.notes)
        if competitor_mode == "condo_same_building":
            competitor_notes.append("Public same-building match only; confidence is lower than MLS-authenticated sources.")
        else:
            competitor_notes.append("Public nearby-area match only; location confidence is limited to public metadata.")

        why_relevant = []
        if competitor_mode == "condo_same_building":
            why_relevant.append("Structured public record matched the same building fingerprint.")
        else:
            why_relevant.append("Structured public record matched the same city and nearby-area confidence rules.")

        return agent_schemas.DailyMarketScanFinding(
            address=record.address,
            mls_number=record.external_listing_id,
            listing_ref=record.source_url,
            source_used="public_listing:realtor_ca_public",
            why_relevant=why_relevant,
            competitor_notes=competitor_notes,
            tradeoffs=(
                [f"Public listing price: {record.list_price:,.0f}"] if record.list_price else []
            ),
        )

    def _scan_competitors(
        self,
        context: Any,
        *,
        competitor_mode: agent_schemas.DailyMarketScanCompetitorMode,
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        if self.availability == "unavailable":
            return self.build_scan_result(
                status="failed",
                failure_metadata=[
                    self._failure(
                        code="provider_unavailable",
                        message="Public listing provider is unavailable.",
                        retryable=True,
                    )
                ],
                notes=[PUBLIC_RETRIEVAL_NOTE],
            )

        records, failure_metadata, notes = self._fetch_records(context)
        if not records:
            return self.build_scan_result(
                status="failed",
                source_used="public_listing:realtor_ca_public",
                failure_metadata=failure_metadata,
                notes=notes,
            )

        findings: list[agent_schemas.DailyMarketScanFinding] = []
        if competitor_mode == "condo_same_building":
            building_key = self._subject_building_key(context)
            if building_key is None:
                return self.build_scan_result(
                    status="completed",
                    source_used="public_listing:realtor_ca_public",
                    failure_metadata=failure_metadata
                    + [
                        self._failure(
                            code="same_building_confidence_low",
                            message="Subject building metadata was insufficient for same-building confidence.",
                            retryable=False,
                        )
                    ],
                    notes=notes,
                )

            subject_unit = self._subject_unit(context)
            for record in records:
                if public_listing_normalizer.building_key_for_record(record) != building_key:
                    continue
                if subject_unit and record.unit and record.unit == subject_unit:
                    continue
                findings.append(
                    self._finding_from_record(
                        record,
                        competitor_mode=competitor_mode,
                    )
                )
            if not findings:
                failure_metadata.append(
                    self._failure(
                        code="public_source_no_matches",
                        message="No same-building competitors were found on the retrieved public page.",
                        retryable=False,
                    )
                )
            return self.build_scan_result(
                status="completed",
                source_used="public_listing:realtor_ca_public",
                findings=findings,
                failure_metadata=failure_metadata,
                notes=notes,
            )

        subject_city = (self._subject_city(context) or "").strip().lower()
        subject_neighborhood = (self._subject_neighborhood(context) or "").strip().lower()
        subject_postal_prefix = self._subject_postal_prefix(context)
        low_confidence = False

        for record in records:
            record_city = (record.city or "").strip().lower()
            if subject_city and record_city and subject_city != record_city:
                continue
            record_neighborhood = (record.neighborhood or "").strip().lower()
            record_postal_prefix = public_listing_normalizer.postal_prefix_for_record(
                record
            )
            strong_location_match = False
            if subject_neighborhood and record_neighborhood:
                strong_location_match = subject_neighborhood == record_neighborhood
            elif subject_postal_prefix and record_postal_prefix:
                strong_location_match = subject_postal_prefix == record_postal_prefix

            if not strong_location_match:
                low_confidence = True
                continue

            findings.append(
                self._finding_from_record(
                    record,
                    competitor_mode=competitor_mode,
                )
            )

        if not findings:
            failure_metadata.append(
                self._failure(
                    code=(
                        "area_match_confidence_low"
                        if low_confidence
                        else "public_source_no_matches"
                    ),
                    message=(
                        "Nearby-area public matching confidence was too weak for a reliable result."
                        if low_confidence
                        else "No nearby-area competitors were found on the retrieved public page."
                    ),
                    retryable=False,
                )
            )

        return self.build_scan_result(
            status="completed",
            source_used="public_listing:realtor_ca_public",
            findings=findings,
            failure_metadata=failure_metadata,
            notes=notes,
        )

    def scan_client_matches(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._stub_scan_result("Client match scan")

    def scan_condo_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._scan_competitors(
            context,
            competitor_mode="condo_same_building",
        )

    def scan_area_competitors(
        self, context: Any
    ) -> agent_schemas.DailyMarketScanProviderScanResult:
        return self._scan_competitors(
            context,
            competitor_mode="area_nearby_non_condo",
        )


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
