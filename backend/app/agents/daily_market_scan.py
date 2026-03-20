from __future__ import annotations

from typing import Any

from . import market_scan_providers, schemas as agent_schemas


MAX_MARKET_SCAN_SUBJECTS = 25
INTERNAL_ONLY_OPERATOR_NOTE = (
    "Daily market scan findings remain internal logging only until explicitly"
    " approved for external use."
)
REVIEW_ONLY_DRAFT_NOTE = (
    "Any external-facing draft from this layer remains review-only and is never"
    " auto-sent."
)
SIMULATED_RUN_NOTE = (
    "V1 supports manual or simulated runs only. Real scheduling is not enabled."
)
SCOPE_CONSTRAINED_RISK_FLAG = "scan_scope_constrained_to_v1_limit"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value) if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _dedupe_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []

    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _coerce_positive_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        deduped.append(parsed)
    return deduped


def _normalize_listing_refs(
    raw: Any,
) -> list[agent_schemas.DailyMarketScanListingReference]:
    if not isinstance(raw, list):
        return []

    listings: list[agent_schemas.DailyMarketScanListingReference] = []
    seen: set[str] = set()

    for item in raw:
        if isinstance(item, agent_schemas.DailyMarketScanListingReference):
            listing = item
        elif isinstance(item, dict):
            property_id = _coerce_positive_int(item.get("property_id"))
            listing_ref = _clean_text(item.get("listing_ref"))
            if listing_ref is None and property_id is not None:
                listing_ref = f"manual:property:{property_id}"
            if listing_ref is None:
                continue
            listing = agent_schemas.DailyMarketScanListingReference(
                listing_ref=listing_ref,
                property_id=property_id,
                label=_clean_text(item.get("label")),
            )
        else:
            continue

        if listing.listing_ref in seen:
            continue
        seen.add(listing.listing_ref)
        listings.append(listing)

    return listings


def normalize_run_request(
    raw: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
) -> agent_schemas.DailyMarketScanRunRequest:
    if isinstance(raw, agent_schemas.DailyMarketScanRunRequest):
        raw = raw.model_dump()

    if not isinstance(raw, dict):
        raise TypeError("daily_market_scan_request_must_be_dict")

    requested_max_subjects = _coerce_positive_int(raw.get("max_subjects"))
    max_subjects = min(
        requested_max_subjects or MAX_MARKET_SCAN_SUBJECTS,
        MAX_MARKET_SCAN_SUBJECTS,
    )

    return agent_schemas.DailyMarketScanRunRequest(
        scan_mode=raw.get("scan_mode") or "full_daily_scan",
        run_mode=raw.get("run_mode") or "manual_preview",
        source_preference=raw.get("source_preference") or "auto",
        contact_ids=_dedupe_int_list(raw.get("contact_ids")),
        property_ids=_dedupe_int_list(raw.get("property_ids")),
        listing_refs=_normalize_listing_refs(raw.get("listing_refs")),
        max_subjects=max_subjects,
    )


def requested_subject_count(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
) -> int:
    normalized = normalize_run_request(request)
    return (
        len(normalized.contact_ids)
        + len(normalized.property_ids)
        + len(normalized.listing_refs)
    )


def build_scope_summary(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
) -> agent_schemas.DailyMarketScanScopeSummary:
    normalized = normalize_run_request(request)
    requested_count = requested_subject_count(normalized)
    effective_count = min(requested_count, normalized.max_subjects)

    notes: list[str] = []
    decision: agent_schemas.DailyMarketScanScopeDecision = "accepted"
    if requested_count > effective_count:
        decision = "constrained"
        notes.append(
            "Requested subject scope exceeds the v1 daily scan limit and must be"
            " constrained before execution."
        )

    return agent_schemas.DailyMarketScanScopeSummary(
        requested_subject_count=requested_count,
        effective_subject_count=effective_count,
        max_subjects=normalized.max_subjects,
        decision=decision,
        notes=notes,
    )


def build_execution_policy() -> agent_schemas.DailyMarketScanExecutionPolicy:
    return agent_schemas.DailyMarketScanExecutionPolicy(
        mode="internal_logging_review_only",
        can_auto_send=False,
        can_auto_contact_clients=False,
        can_create_client_outputs_without_approval=False,
    )


def build_provider_catalog(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    stratus_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    stratus_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> list[agent_schemas.DailyMarketScanProviderDescriptor]:
    normalized = normalize_run_request(request)
    return market_scan_providers.build_provider_catalog(
        source_preference=normalized.source_preference,
        stratus_auth_state=stratus_auth_state,
        stratus_availability=stratus_availability,
        public_availability=public_availability,
    )


def build_scan_result_contract(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    stratus_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    stratus_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> agent_schemas.DailyMarketScanResultResponse:
    normalized = normalize_run_request(request)
    scope = build_scope_summary(normalized)
    provider_order = market_scan_providers.provider_order_for_preference(
        normalized.source_preference
    )
    provider_catalog = build_provider_catalog(
        normalized,
        stratus_auth_state=stratus_auth_state,
        stratus_availability=stratus_availability,
        public_availability=public_availability,
    )

    risk_flags = ["manual_or_simulated_only"]
    operator_notes = [
        INTERNAL_ONLY_OPERATOR_NOTE,
        REVIEW_ONLY_DRAFT_NOTE,
        SIMULATED_RUN_NOTE,
    ]

    failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata] = []
    if scope.decision == "constrained":
        risk_flags.append(SCOPE_CONSTRAINED_RISK_FLAG)
        failure_metadata.append(
            agent_schemas.DailyMarketScanFailureMetadata(
                code="scan_scope_exceeds_v1_limit",
                message=(
                    "Requested scan scope exceeds the v1 limit and must be"
                    " constrained before execution."
                ),
                retryable=False,
                fallback_attempted=False,
                fallback_used=False,
            )
        )

    return agent_schemas.DailyMarketScanResultResponse(
        scan_summary=agent_schemas.DailyMarketScanSummary(
            scan_mode=normalized.scan_mode,
            run_mode=normalized.run_mode,
            scope=scope,
            provider_order=provider_order,
        ),
        execution_policy=build_execution_policy(),
        provider_catalog=provider_catalog,
        client_match_scans=[],
        competitor_watch_scans=[],
        risk_flags=risk_flags,
        failure_metadata=failure_metadata,
        operator_notes=operator_notes,
    )
