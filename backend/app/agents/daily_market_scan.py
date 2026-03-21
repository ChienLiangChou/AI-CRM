from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models as crm_models
from . import models, service
from . import market_scan_providers, schemas as agent_schemas


MAX_MARKET_SCAN_SUBJECTS = 25
INTERNAL_ONLY_OPERATOR_NOTE = (
    "Daily market scan findings remain internal logging only until explicitly"
    " approved for external use."
)
REVIEW_ONLY_OPERATOR_NOTE = (
    "This layer is manual or simulated only in v1. It does not auto-send,"
    " auto-contact, or autonomously publish outputs."
)
PROVIDER_ABSTRACTION_NOTE = (
    "Provider modeling is contract-only in this step. Real retrieval, browser"
    " automation, and scheduling are not enabled."
)
SCOPE_CONSTRAINED_RISK_FLAG = "scan_scope_constrained_to_v1_limit"
NO_PROVIDERS_AVAILABLE_RISK_FLAG = "no_providers_available"
PROVIDER_FAILURE_RECORDED_RISK_FLAG = "provider_failure_recorded"
PARTIAL_SCAN_RECORDED_RISK_FLAG = "partial_scan_recorded"
ZERO_FINDINGS_RECORDED_RISK_FLAG = "zero_findings_recorded"


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_model_dump(value), ensure_ascii=False)


def _safe_task_payload_json(request: Any) -> str:
    try:
        normalized = normalize_run_request(request)
        return _json_dumps(normalized)
    except Exception:
        if isinstance(request, dict):
            return json.dumps(request, ensure_ascii=False)
        return json.dumps({"invalid_request": True}, ensure_ascii=False)


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


def _priority_from_run_mode(
    run_mode: agent_schemas.DailyMarketScanRunMode,
) -> str:
    return "normal" if run_mode == "manual_preview" else "low"


def _contact_snapshot(contact: crm_models.Contact) -> dict[str, Any]:
    return {
        "contact_id": contact.id,
        "name": contact.name,
        "client_type": contact.client_type,
        "budget_min": contact.budget_min,
        "budget_max": contact.budget_max,
    }


def _property_snapshot(property_record: crm_models.Property) -> dict[str, Any]:
    address = " ".join(
        part
        for part in [
            property_record.unit,
            property_record.street,
            property_record.city,
        ]
        if part
    )
    return {
        "property_id": property_record.id,
        "address": address,
        "city": property_record.city,
        "property_type": property_record.property_type,
        "status": property_record.status,
        "listing_price": property_record.listing_price,
        "mls_number": property_record.mls_number,
    }


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


def resolve_subjects(
    db: Session,
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_run_request(request)

    contacts = (
        db.query(crm_models.Contact)
        .filter(crm_models.Contact.id.in_(normalized.contact_ids))
        .all()
        if normalized.contact_ids
        else []
    )
    properties = (
        db.query(crm_models.Property)
        .filter(crm_models.Property.id.in_(normalized.property_ids))
        .all()
        if normalized.property_ids
        else []
    )

    contact_map = {contact.id: contact for contact in contacts}
    property_map = {property_record.id: property_record for property_record in properties}

    found_contacts = [
        _contact_snapshot(contact_map[contact_id])
        for contact_id in normalized.contact_ids
        if contact_id in contact_map
    ]
    found_properties = [
        _property_snapshot(property_map[property_id])
        for property_id in normalized.property_ids
        if property_id in property_map
    ]

    listing_refs: list[dict[str, Any]] = []
    for listing in normalized.listing_refs:
        property_record = (
            property_map.get(listing.property_id) if listing.property_id is not None else None
        )
        listing_refs.append(
            {
                "listing_ref": listing.listing_ref,
                "property_id": listing.property_id,
                "label": listing.label,
                "property_type": property_record.property_type if property_record else None,
            }
        )

    return {
        "contacts": {
            "found": found_contacts,
            "missing_ids": [
                contact_id
                for contact_id in normalized.contact_ids
                if contact_id not in contact_map
            ],
        },
        "properties": {
            "found": found_properties,
            "missing_ids": [
                property_id
                for property_id in normalized.property_ids
                if property_id not in property_map
            ],
        },
        "listings": listing_refs,
        "counts": {
            "contacts_found": len(found_contacts),
            "properties_found": len(found_properties),
            "listings_linked": len(listing_refs),
        },
    }


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


def clamp_resolved_subjects(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_run_request(request)
    remaining = normalized.max_subjects

    selected_contacts = list(resolution.get("contacts", {}).get("found", []))
    selected_properties = list(resolution.get("properties", {}).get("found", []))
    selected_listings = list(resolution.get("listings", []))

    effective_contacts = selected_contacts[:remaining]
    remaining = max(remaining - len(effective_contacts), 0)
    effective_properties = selected_properties[:remaining]
    remaining = max(remaining - len(effective_properties), 0)
    effective_listings = selected_listings[:remaining]

    requested_total = (
        len(selected_contacts) + len(selected_properties) + len(selected_listings)
    )
    effective_total = (
        len(effective_contacts) + len(effective_properties) + len(effective_listings)
    )

    notes: list[str] = []
    if effective_total < requested_total:
        notes.append(
            "Effective subject selection was clamped to the v1 maximum before execution."
        )

    return {
        "contacts": effective_contacts,
        "properties": effective_properties,
        "listings": effective_listings,
        "counts": {
            "requested_total": requested_total,
            "effective_total": effective_total,
            "contacts_selected": len(effective_contacts),
            "properties_selected": len(effective_properties),
            "listings_selected": len(effective_listings),
        },
        "notes": notes,
    }


def build_provider_plan(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        market_scan_providers.BaseMarketScanProvider,
    ]
    | None = None,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> dict[str, Any]:
    normalized = normalize_run_request(request)
    registry = provider_registry or market_scan_providers.build_provider_registry(
        authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
        authenticated_mls_browser_availability=authenticated_mls_browser_availability,
        public_availability=public_availability,
    )
    ordered_items = market_scan_providers.ordered_registry_items(
        registry,
        source_preference=normalized.source_preference,
    )
    ordered_keys = [key for key, _provider in ordered_items]
    provider_catalog = market_scan_providers.build_provider_catalog_from_registry(
        registry,
        source_preference=normalized.source_preference,
    )
    return {
        "provider_order": ordered_keys,
        "provider_catalog": [_model_dump(item) for item in provider_catalog],
    }


def build_provider_catalog(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> list[agent_schemas.DailyMarketScanProviderDescriptor]:
    normalized = normalize_run_request(request)
    return market_scan_providers.build_provider_catalog(
        source_preference=normalized.source_preference,
        authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
        authenticated_mls_browser_availability=authenticated_mls_browser_availability,
        public_availability=public_availability,
    )


def _select_workflow_method(
    workflow: agent_schemas.DailyMarketScanWorkflowType,
    competitor_mode: agent_schemas.DailyMarketScanCompetitorMode | None = None,
) -> str:
    if workflow == "client_match":
        return "scan_client_matches"
    if competitor_mode == "condo_same_building":
        return "scan_condo_competitors"
    return "scan_area_competitors"


def _failure_metadata(
    *,
    code: str,
    provider_key: agent_schemas.DailyMarketScanProviderKey | None = None,
    message: str | None = None,
    retryable: bool = False,
    fallback_attempted: bool = False,
    fallback_used: bool = False,
) -> agent_schemas.DailyMarketScanFailureMetadata:
    return agent_schemas.DailyMarketScanFailureMetadata(
        provider_key=provider_key,
        code=code,
        message=message,
        retryable=retryable,
        fallback_attempted=fallback_attempted,
        fallback_used=fallback_used,
    )


def _execute_provider_chain(
    *,
    workflow: agent_schemas.DailyMarketScanWorkflowType,
    context: dict[str, Any],
    ordered_providers: list[
        tuple[
            agent_schemas.DailyMarketScanProviderKey,
            market_scan_providers.BaseMarketScanProvider,
        ]
    ],
) -> dict[str, Any]:
    source_attempts: list[agent_schemas.DailyMarketScanSourceAttempt] = []
    findings: list[agent_schemas.DailyMarketScanFinding] = []
    failure_metadata: list[agent_schemas.DailyMarketScanFailureMetadata] = []
    fallback_used = False
    had_execution_failure = False
    had_partial_result = False
    had_success_without_findings = False
    had_available_provider = False
    competitor_mode = context.get("competitor_mode")

    if not ordered_providers:
        failure = _failure_metadata(
            code="no_providers_available",
            message="No providers were available in the current provider plan.",
            retryable=True,
        )
        return {
            "status": "no_providers",
            "source_attempts": [],
            "findings": [],
            "fallback_used": False,
            "failure_metadata": [failure],
        }

    for index, (provider_key, provider) in enumerate(ordered_providers):
        fallback_attempted = index > 0
        if provider.availability == "unavailable":
            failure = _failure_metadata(
                code="provider_unavailable",
                provider_key=provider_key,
                message="Provider unavailable in the current plan.",
                retryable=True,
                fallback_attempted=fallback_attempted,
                fallback_used=False,
            )
            source_attempts.append(
                provider.build_source_attempt(
                    status="skipped",
                    fallback_used=False,
                    failure_metadata=[failure],
                    notes=["Provider unavailable in current plan."],
                )
            )
            failure_metadata.append(failure)
            continue

        had_available_provider = True

        try:
            method_name = _select_workflow_method(workflow, competitor_mode)
            provider_result = getattr(provider, method_name)(context)
        except Exception as exc:
            had_execution_failure = True
            failure = _failure_metadata(
                code="provider_execution_error",
                provider_key=provider_key,
                message=str(exc),
                retryable=True,
                fallback_attempted=fallback_attempted,
                fallback_used=False,
            )
            source_attempts.append(
                provider.build_source_attempt(
                    status="failed",
                    fallback_used=False,
                    failure_metadata=[failure],
                    notes=["Provider raised an exception during stub execution."],
                )
            )
            failure_metadata.append(failure)
            continue

        source_attempt = provider.build_source_attempt(
            status=provider_result.status,
            source_used=provider_result.source_used,
            fallback_used=provider_result.fallback_used or fallback_attempted,
            failure_metadata=provider_result.failure_metadata,
            notes=provider_result.notes,
            auth_state=provider_result.auth_state,
        )
        source_attempts.append(source_attempt)
        failure_metadata.extend(provider_result.failure_metadata)

        if provider_result.status == "partial":
            had_partial_result = True

        if provider_result.findings:
            findings.extend(provider_result.findings)
            fallback_used = fallback_used or fallback_attempted or provider_result.fallback_used
            if provider_result.status != "partial":
                break
        elif provider_result.status in {"completed", "partial"}:
            had_success_without_findings = True

    if findings:
        status: agent_schemas.DailyMarketScanWorkflowStatus = (
            "partial" if had_execution_failure or had_partial_result else "completed"
        )
    elif not had_available_provider:
        status = "no_providers"
    elif had_success_without_findings:
        status = "no_findings"
    elif had_execution_failure:
        status = "failed"
    else:
        status = "no_providers"

    if status == "no_providers" and not failure_metadata:
        failure_metadata.append(
            _failure_metadata(
                code="no_providers_available",
                message="No providers were available in the current provider plan.",
                retryable=True,
            )
        )

    return {
        "status": status,
        "source_attempts": source_attempts,
        "findings": findings,
        "fallback_used": fallback_used,
        "failure_metadata": failure_metadata,
    }


def _competitor_mode_for_property(
    property_snapshot: dict[str, Any],
) -> agent_schemas.DailyMarketScanCompetitorMode:
    if property_snapshot.get("property_type") == "condo":
        return "condo_same_building"
    return "area_nearby_non_condo"


def _build_client_match_scans(
    selected_subjects: dict[str, Any],
    ordered_providers: list[
        tuple[
            agent_schemas.DailyMarketScanProviderKey,
            market_scan_providers.BaseMarketScanProvider,
        ]
    ],
) -> list[agent_schemas.DailyMarketScanClientMatchScan]:
    scans: list[agent_schemas.DailyMarketScanClientMatchScan] = []
    for contact in selected_subjects.get("contacts", []):
        execution = _execute_provider_chain(
            workflow="client_match",
            context={"contact": contact},
            ordered_providers=ordered_providers,
        )
        scans.append(
            agent_schemas.DailyMarketScanClientMatchScan(
                status=execution["status"],
                contact_id=contact["contact_id"],
                criteria_summary=f"Manual/simulated client-match scan for contact {contact['contact_id']}.",
                source_attempts=execution["source_attempts"],
                findings=execution["findings"],
                fallback_used=execution["fallback_used"],
                failure_metadata=execution["failure_metadata"],
            )
        )
    return scans


def _build_competitor_watch_scans(
    selected_subjects: dict[str, Any],
    ordered_providers: list[
        tuple[
            agent_schemas.DailyMarketScanProviderKey,
            market_scan_providers.BaseMarketScanProvider,
        ]
    ],
) -> list[agent_schemas.DailyMarketScanCompetitorWatchScan]:
    scans: list[agent_schemas.DailyMarketScanCompetitorWatchScan] = []

    for property_snapshot in selected_subjects.get("properties", []):
        competitor_mode = _competitor_mode_for_property(property_snapshot)
        subject = agent_schemas.DailyMarketScanCompetitorSubject(
            property_id=property_snapshot["property_id"],
            competitor_mode=competitor_mode,
        )
        execution = _execute_provider_chain(
            workflow="competitor_watch",
            context={
                "subject": _model_dump(subject),
                "competitor_mode": competitor_mode,
                "property": property_snapshot,
            },
            ordered_providers=ordered_providers,
        )
        scans.append(
            agent_schemas.DailyMarketScanCompetitorWatchScan(
                status=execution["status"],
                subject=subject,
                source_attempts=execution["source_attempts"],
                findings=execution["findings"],
                fallback_used=execution["fallback_used"],
                failure_metadata=execution["failure_metadata"],
            )
        )

    for listing_snapshot in selected_subjects.get("listings", []):
        subject = agent_schemas.DailyMarketScanCompetitorSubject(
            property_id=listing_snapshot.get("property_id"),
            listing_ref=listing_snapshot["listing_ref"],
            competitor_mode="condo_same_building",
        )
        execution = _execute_provider_chain(
            workflow="competitor_watch",
            context={
                "subject": _model_dump(subject),
                "competitor_mode": "condo_same_building",
                "listing": listing_snapshot,
            },
            ordered_providers=ordered_providers,
        )
        scans.append(
            agent_schemas.DailyMarketScanCompetitorWatchScan(
                status=execution["status"],
                subject=subject,
                source_attempts=execution["source_attempts"],
                findings=execution["findings"],
                fallback_used=execution["fallback_used"],
                failure_metadata=execution["failure_metadata"],
            )
        )

    return scans


def _aggregate_scan_outcomes(
    *,
    base_result: agent_schemas.DailyMarketScanResultResponse,
    client_match_scans: list[agent_schemas.DailyMarketScanClientMatchScan],
    competitor_watch_scans: list[agent_schemas.DailyMarketScanCompetitorWatchScan],
) -> agent_schemas.DailyMarketScanResultResponse:
    risk_flags = list(base_result.risk_flags)
    operator_notes = list(base_result.operator_notes)
    failure_metadata = list(base_result.failure_metadata)

    workflow_statuses = [scan.status for scan in client_match_scans + competitor_watch_scans]
    workflow_failures = [
        failure
        for scan in client_match_scans + competitor_watch_scans
        for failure in scan.failure_metadata
    ]
    failure_metadata.extend(workflow_failures)

    if any(status == "no_providers" for status in workflow_statuses):
        risk_flags.append(NO_PROVIDERS_AVAILABLE_RISK_FLAG)
        operator_notes.append(
            "Some scan targets had no providers available and completed with fail-soft metadata only."
        )
    if any(status == "partial" for status in workflow_statuses):
        risk_flags.append(PARTIAL_SCAN_RECORDED_RISK_FLAG)
        operator_notes.append(
            "Some scan targets completed only partially; review failure metadata before acting on findings."
        )
    if any(status == "no_findings" for status in workflow_statuses):
        risk_flags.append(ZERO_FINDINGS_RECORDED_RISK_FLAG)
        operator_notes.append(
            "Some scan targets returned zero findings; absence of findings is not a business decision signal."
        )
    if any(failure.code == "provider_execution_error" for failure in workflow_failures):
        risk_flags.append(PROVIDER_FAILURE_RECORDED_RISK_FLAG)
        operator_notes.append(
            "At least one provider raised an execution error; fallback handling preserved the run."
        )

    return agent_schemas.DailyMarketScanResultResponse(
        scan_summary=base_result.scan_summary,
        execution_policy=base_result.execution_policy,
        provider_catalog=base_result.provider_catalog,
        client_match_scans=client_match_scans,
        competitor_watch_scans=competitor_watch_scans,
        risk_flags=list(dict.fromkeys(risk_flags)),
        failure_metadata=failure_metadata,
        operator_notes=list(dict.fromkeys(operator_notes)),
    )


def build_scan_result_contract(
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> agent_schemas.DailyMarketScanResultResponse:
    normalized = normalize_run_request(request)
    scope = build_scope_summary(normalized)
    provider_order = market_scan_providers.provider_order_for_preference(
        normalized.source_preference
    )
    provider_catalog = build_provider_catalog(
        normalized,
        authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
        authenticated_mls_browser_availability=authenticated_mls_browser_availability,
        public_availability=public_availability,
    )

    risk_flags = ["manual_or_simulated_only"]
    operator_notes = [
        INTERNAL_ONLY_OPERATOR_NOTE,
        REVIEW_ONLY_OPERATOR_NOTE,
        PROVIDER_ABSTRACTION_NOTE,
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


def plan_daily_market_scan_run(
    db: Session,
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        market_scan_providers.BaseMarketScanProvider,
    ]
    | None = None,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> dict[str, Any]:
    normalized_request = normalize_run_request(request)
    resolution = resolve_subjects(db, normalized_request)
    selected_subjects = clamp_resolved_subjects(normalized_request, resolution)
    provider_plan = build_provider_plan(
        normalized_request,
        provider_registry=provider_registry,
        authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
        authenticated_mls_browser_availability=authenticated_mls_browser_availability,
        public_availability=public_availability,
    )

    return {
        "request_snapshot": _model_dump(normalized_request),
        "scope": _model_dump(build_scope_summary(normalized_request)),
        "subject_resolution": resolution,
        "selected_subjects": selected_subjects,
        "provider_plan": provider_plan,
        "execution_policy": _model_dump(build_execution_policy()),
    }


def execute_daily_market_scan_run(
    db: Session,
    run: models.AgentRun,
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any],
    *,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        market_scan_providers.BaseMarketScanProvider,
    ]
    | None = None,
) -> dict[str, Any]:
    del db
    if not run.plan:
        raise ValueError("daily_market_scan_plan_missing")

    plan = json.loads(run.plan)
    normalized_request = normalize_run_request(request)
    persisted_provider_plan = plan.get("provider_plan", {})
    persisted_provider_catalog = persisted_provider_plan.get("provider_catalog", [])
    persisted_provider_order = persisted_provider_plan.get("provider_order", [])

    if provider_registry is not None:
        registry = provider_registry
        provider_catalog = market_scan_providers.build_provider_catalog_from_registry(
            registry,
            source_preference=normalized_request.source_preference,
        )
        ordered_providers = market_scan_providers.ordered_registry_items(
            registry,
            source_preference=normalized_request.source_preference,
        )
    else:
        registry = market_scan_providers.build_provider_registry_from_catalog(
            persisted_provider_catalog
        )
        provider_catalog = [
            (
                item
                if isinstance(item, agent_schemas.DailyMarketScanProviderDescriptor)
                else agent_schemas.DailyMarketScanProviderDescriptor.model_validate(item)
            )
            for item in persisted_provider_catalog
        ]
        ordered_providers = [
            (key, registry[key])
            for key in persisted_provider_order
            if key in registry
        ]
        if not ordered_providers:
            ordered_providers = market_scan_providers.ordered_registry_items(
                registry,
                source_preference=normalized_request.source_preference,
            )

    base_result = build_scan_result_contract(normalized_request)
    base_result = agent_schemas.DailyMarketScanResultResponse(
        scan_summary=base_result.scan_summary,
        execution_policy=base_result.execution_policy,
        provider_catalog=provider_catalog,
        client_match_scans=[],
        competitor_watch_scans=[],
        risk_flags=base_result.risk_flags,
        failure_metadata=base_result.failure_metadata,
        operator_notes=base_result.operator_notes,
    )

    selected_subjects = plan.get("selected_subjects", {})
    client_match_scans: list[agent_schemas.DailyMarketScanClientMatchScan] = []
    competitor_watch_scans: list[agent_schemas.DailyMarketScanCompetitorWatchScan] = []

    if normalized_request.scan_mode in {"client_match", "full_daily_scan"}:
        client_match_scans = _build_client_match_scans(
            selected_subjects,
            ordered_providers,
        )

    if normalized_request.scan_mode in {"competitor_watch", "full_daily_scan"}:
        competitor_watch_scans = _build_competitor_watch_scans(
            selected_subjects,
            ordered_providers,
        )

    result = _aggregate_scan_outcomes(
        base_result=base_result,
        client_match_scans=client_match_scans,
        competitor_watch_scans=competitor_watch_scans,
    )
    return _model_dump(result)


def run_daily_market_scan_once(
    db: Session,
    request: agent_schemas.DailyMarketScanRunRequest | dict[str, Any] | Any,
    *,
    provider_registry: dict[
        agent_schemas.DailyMarketScanProviderKey,
        market_scan_providers.BaseMarketScanProvider,
    ]
    | None = None,
    authenticated_mls_browser_auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated",
    authenticated_mls_browser_availability: agent_schemas.DailyMarketScanProviderAvailability = "limited",
    public_availability: agent_schemas.DailyMarketScanProviderAvailability = "available",
) -> models.AgentRun:
    payload_json = _safe_task_payload_json(request)
    try:
        normalized_request = normalize_run_request(request)
    except Exception:
        normalized_request = None

    task = service.create_task(
        db,
        agent_type="daily_market_scan",
        subject_type="scan_request",
        subject_id=None,
        payload=payload_json,
        priority=(
            _priority_from_run_mode(normalized_request.run_mode)
            if normalized_request is not None
            else "normal"
        ),
    )
    run = service.create_run(
        db,
        task=task,
        summary="Daily Market Scan run (MVP)",
    )

    now = datetime.utcnow()
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(db, run, status="planning", started_at=now)

    try:
        if normalized_request is None:
            normalized_request = normalize_run_request(request)

        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="daily_market_scan_request_normalized",
            details=payload_json,
        )

        plan_data = plan_daily_market_scan_run(
            db,
            normalized_request,
            provider_registry=provider_registry,
            authenticated_mls_browser_auth_state=authenticated_mls_browser_auth_state,
            authenticated_mls_browser_availability=authenticated_mls_browser_availability,
            public_availability=public_availability,
        )
        plan_json = _json_dumps(plan_data)
        run = service.update_run_status(
            db,
            run,
            status="executing",
            plan=plan_json,
        )

        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="daily_market_scan_subjects_resolved",
            details=_json_dumps(
                {
                    "subject_resolution": plan_data["subject_resolution"],
                    "selected_subjects": plan_data["selected_subjects"],
                    "scope": plan_data["scope"],
                }
            ),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="daily_market_scan_provider_plan_generated",
            details=_json_dumps(plan_data["provider_plan"]),
        )

        result = execute_daily_market_scan_run(
            db,
            run,
            normalized_request,
            provider_registry=provider_registry,
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="daily_market_scan_provider_execution_completed",
            details=_json_dumps(
                {
                    "client_match_scans": result["client_match_scans"],
                    "competitor_watch_scans": result["competitor_watch_scans"],
                    "risk_flags": result["risk_flags"],
                }
            ),
        )
        if any(
            failure.get("code") == "provider_execution_error"
            for failure in result["failure_metadata"]
        ):
            service.write_audit_log(
                db,
                run=run,
                task=task,
                actor_type="system",
                action="daily_market_scan_provider_failure_recorded",
                details=_json_dumps(
                    {
                        "failure_metadata": [
                            failure
                            for failure in result["failure_metadata"]
                            if failure.get("code") == "provider_execution_error"
                        ]
                    }
                ),
            )

        finished_at = datetime.utcnow()
        result_json = _json_dumps(result)
        run = service.update_run_status(
            db,
            run,
            status="completed",
            result=result_json,
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status="completed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="daily_market_scan_run_completed",
            details=result_json,
        )
        return run
    except Exception as exc:
        finished_at = datetime.utcnow()
        run = service.update_run_status(
            db,
            run,
            status="failed",
            error=str(exc),
            finished_at=finished_at,
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="daily_market_scan_run_failed",
            details=_json_dumps({"error": str(exc)}),
        )
        return run
