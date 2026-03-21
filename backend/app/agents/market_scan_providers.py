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

    def _candidate_reference_values(self, context: Any) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        listing = context.get("listing") if isinstance(context, dict) else None
        property_snapshot = context.get("property") if isinstance(context, dict) else None
        candidate_listings = (
            context.get("candidate_listings") if isinstance(context, dict) else None
        )
        candidate_properties = (
            context.get("candidate_properties") if isinstance(context, dict) else None
        )

        candidates: list[Any] = [
            listing.get("listing_ref") if isinstance(listing, dict) else None,
            listing.get("listing_url") if isinstance(listing, dict) else None,
            property_snapshot.get("listing_url")
            if isinstance(property_snapshot, dict)
            else None,
        ]
        if isinstance(candidate_listings, list):
            for item in candidate_listings:
                if isinstance(item, dict):
                    candidates.append(item.get("listing_ref"))
                    candidates.append(item.get("listing_url"))
        if isinstance(candidate_properties, list):
            for item in candidate_properties:
                if isinstance(item, dict):
                    candidates.append(item.get("listing_url"))

        for raw_value in candidates:
            if raw_value is None:
                continue
            text = str(raw_value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            values.append(text)
        return values

    def _fetch_records(
        self,
        context: Any,
    ) -> tuple[
        list[public_listing_normalizer.CanonicalPublicListingRecord],
        list[agent_schemas.DailyMarketScanFailureMetadata],
        list[str],
    ]:
        raw_references = self._candidate_reference_values(context)
        if not raw_references:
            return (
                [],
                [
                    self._failure(
                        code="public_reference_missing",
                        message="Public retrieval requires an exact allowlisted public URL.",
                        retryable=False,
                    )
                ],
                ["No exact public URL was available in the current constrained context."],
            )

        urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_value in raw_references:
            normalized = public_listing_fetcher.normalize_public_listing_url(raw_value)
            if normalized is None or normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            urls.append(normalized)
        if not urls:
            return (
                [],
                [
                    self._failure(
                        code="public_source_not_allowlisted",
                        message="The provided public URL is not allowlisted for retrieval.",
                        retryable=False,
                    )
                ],
                ["Only exact allowlisted public URLs are permitted in this step."],
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

    def _contact_area_tokens(self, context: Any) -> set[str]:
        contact = context.get("contact") if isinstance(context, dict) else None
        if not isinstance(contact, dict):
            return set()
        tokens: set[str] = set()
        for item in contact.get("preferred_areas", []):
            text = str(item).strip().lower()
            if text:
                tokens.add(text)
        return tokens

    def _contact_property_type(self, context: Any) -> str | None:
        contact = context.get("contact") if isinstance(context, dict) else None
        if not isinstance(contact, dict):
            return None
        property_preferences = contact.get("property_preferences")
        if not isinstance(property_preferences, dict):
            return None
        property_type = property_preferences.get("property_type")
        if isinstance(property_type, str) and property_type.strip():
            return property_type.strip().lower()
        types = property_preferences.get("types")
        if isinstance(types, list) and types:
            first = str(types[0]).strip().lower()
            return first or None
        return None

    def _evaluate_client_match(
        self,
        *,
        record: public_listing_normalizer.CanonicalPublicListingRecord,
        context: Any,
    ) -> tuple[bool, bool, list[str], list[str]]:
        contact = context.get("contact") if isinstance(context, dict) else None
        if not isinstance(contact, dict):
            return (False, True, [], ["Missing contact context for public client-match evaluation."])

        score = 0.0
        criteria_used = False
        hard_conflict = False
        why_it_matches: list[str] = []
        tradeoffs: list[str] = []

        budget_min = contact.get("budget_min")
        budget_max = contact.get("budget_max")
        if isinstance(budget_min, (int, float)) or isinstance(budget_max, (int, float)):
            criteria_used = True
            if record.list_price is None:
                tradeoffs.append("Public listing price was unavailable for budget comparison.")
            elif isinstance(budget_min, (int, float)) and isinstance(budget_max, (int, float)):
                if budget_min <= record.list_price <= budget_max:
                    score += 2.0
                    why_it_matches.append("Public list price fits the current buyer budget range.")
                elif record.list_price > budget_max:
                    hard_conflict = True
                    tradeoffs.append("Public list price is above the current buyer budget range.")
                else:
                    hard_conflict = True
                    tradeoffs.append("Public list price sits below the stated range and needs manual review.")
            elif isinstance(budget_max, (int, float)):
                if record.list_price <= budget_max:
                    score += 1.5
                    why_it_matches.append("Public list price is within the buyer's stated ceiling.")
                else:
                    hard_conflict = True
                    tradeoffs.append("Public list price is above the buyer's stated ceiling.")
            elif isinstance(budget_min, (int, float)):
                if record.list_price >= budget_min:
                    score += 1.0
                    why_it_matches.append("Public list price is at or above the buyer's stated floor.")
                else:
                    hard_conflict = True
                    tradeoffs.append("Public list price is below the buyer's stated floor.")

        preferred_type = self._contact_property_type(context)
        if preferred_type:
            criteria_used = True
            if record.property_type and record.property_type.lower() == preferred_type:
                score += 1.5
                why_it_matches.append("Public property type matches the buyer's stated preference.")
            elif record.property_type:
                tradeoffs.append("Public property type differs from the buyer's stated preference.")

        area_tokens = self._contact_area_tokens(context)
        if area_tokens:
            criteria_used = True
            haystack = " ".join(
                part
                for part in [
                    record.city,
                    record.neighborhood,
                    record.address,
                ]
                if part
            ).lower()
            if any(token in haystack for token in area_tokens):
                score += 1.0
                why_it_matches.append("Public location aligns with the buyer's preferred area.")
            else:
                tradeoffs.append("Public location sits outside the buyer's current preferred areas.")

        return (score >= 2.0 and not hard_conflict, criteria_used, why_it_matches, tradeoffs)

    def _scan_client_matches_real(
        self,
        context: Any,
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
        weak_confidence = False
        criteria_used = False

        for record in records:
            matched, used_criteria, why_it_matches, tradeoffs = self._evaluate_client_match(
                record=record,
                context=context,
            )
            criteria_used = criteria_used or used_criteria
            if not matched:
                weak_confidence = weak_confidence or used_criteria
                continue
            findings.append(
                agent_schemas.DailyMarketScanFinding(
                    address=record.address,
                    mls_number=record.external_listing_id,
                    listing_ref=record.source_url,
                    source_used="public_listing:realtor_ca_public",
                    why_it_matches=why_it_matches,
                    tradeoffs=tradeoffs + list(record.notes),
                )
            )

        if not findings:
            failure_metadata.append(
                self._failure(
                    code=(
                        "public_client_match_confidence_low"
                        if criteria_used and weak_confidence
                        else "public_client_match_no_matches"
                    ),
                    message=(
                        "Public client-match confidence was too weak for a reliable candidate match."
                        if criteria_used and weak_confidence
                        else "No constrained public listings matched the current client criteria."
                    ),
                    retryable=False,
                )
            )

        status: agent_schemas.DailyMarketScanProviderAttemptStatus = (
            "partial" if findings and failure_metadata else "completed"
        )
        return self.build_scan_result(
            status=status,
            source_used="public_listing:realtor_ca_public",
            findings=findings,
            failure_metadata=failure_metadata,
            notes=notes,
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
        if not isinstance(context, dict) or "contact" not in context:
            return self._stub_scan_result("Client match scan")
        return self._scan_client_matches_real(context)

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
