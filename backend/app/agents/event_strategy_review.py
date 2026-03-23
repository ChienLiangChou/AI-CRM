from __future__ import annotations

import json
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from . import models, schemas as agent_schemas, service


AGENT_TYPE: agent_schemas.AgentType = "event_strategy_review"
FIXED_PERSPECTIVE_KEYS: tuple[str, ...] = (
    "follow_up",
    "conversation_retention",
    "listing_seller",
    "cma_market",
    "ops_compliance",
    "buyer_renter",
)
INTERNAL_ONLY_OPERATOR_NOTE = (
    "Internal event strategy review only. No client delivery, no auto-send,"
    " no hidden automation, and no autonomous execution."
)
RETRIEVAL_CONTRACT_NOTE = (
    "v1 preserves a controlled retrieval contract for manual_summary,"
    " manual_url_bundle, and curated_search_query without enabling live web"
    " retrieval in this backend slice."
)
PACKAGING_EXPLICIT_STEP_NOTE = (
    "HTML packaging remains a separate explicit operator step and does not"
    " auto-run after report generation."
)
PERSPECTIVE_SKELETON_NOTE = (
    "Perspective blocks remain fixed and skeletonized until later department"
    " runtime work is explicitly approved."
)
CURATED_QUERY_NOT_ACTIVE_NOTE = (
    "curated_search_query is accepted by the contract in v1, but live retrieval"
    " remains disabled in this step."
)
URL_DEDUPE_NOTE = (
    "Manual URL bundle entries are deduplicated conservatively by normalized URL"
    " before clustering."
)
HTML_PACKAGE_NOTE = (
    "HTML report packaging is internal-only and manual-deploy only in v1. No"
    " publish or deploy action occurs here."
)
PACKAGE_SOURCE_MISSING_NOTE = (
    "Packaging is blocked because the source analysis run does not have a"
    " structured stored report result."
)
PACKAGE_SOURCE_NOT_ACTIVE_NOTE = (
    "Packaging is blocked because the source analysis run is not active for"
    " report packaging yet."
)
PACKAGE_MODE_NOT_IMPLEMENTED_NOTE = (
    "Only html_report_package is implemented in this step. Other output modes"
    " remain planned and package-blocked."
)
PACKAGE_SUBJECT_TYPE = "event_strategy_review_package"
ANALYSIS_SUBJECT_TYPE = "event"


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


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _json_default(value: Any) -> Any:
    dumped = _model_dump(value)
    if dumped is value:
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )
    return dumped


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _sha256_for_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8192)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _lower_text(value: str | None) -> str:
    return value.lower() if value else ""


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _request_to_dict(raw: Any) -> dict[str, Any]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()
    if not isinstance(raw, dict):
        raise TypeError("event_strategy_review_request_must_be_dict")
    return raw


def _safe_task_payload_json(request: Any) -> str:
    try:
        normalized = normalize_run_request(request)
        return _json_dumps(normalized)
    except Exception:
        if isinstance(request, dict):
            return json.dumps(request, ensure_ascii=False)
        return json.dumps({"invalid_request": True}, ensure_ascii=False)


def _safe_package_payload_json(source_run_id: int, request: Any) -> str:
    try:
        if isinstance(request, agent_schemas.EventStrategyReviewPackageRequest):
            package_request = request
        else:
            package_request = agent_schemas.EventStrategyReviewPackageRequest(
                **_request_to_dict(request)
            )
        payload = package_request.model_dump() if hasattr(package_request, "model_dump") else package_request.dict()
        payload["source_run_id"] = source_run_id
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        if isinstance(request, dict):
            payload = dict(request)
            payload["source_run_id"] = source_run_id
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps(
            {"invalid_package_request": True, "source_run_id": source_run_id},
            ensure_ascii=False,
        )


def _normalize_url_dedupe_key(url: str) -> str:
    try:
        split = urlsplit(url)
    except Exception:
        return url.strip()

    scheme = split.scheme.lower() or "https"
    netloc = split.netloc.lower()
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]

    path = split.path or "/"
    if path != "/":
        path = path.rstrip("/")
        if not path:
            path = "/"

    filtered_query_pairs = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    ]
    normalized_query = urlencode(filtered_query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, normalized_query, ""))


def normalize_manual_summary_input(
    raw: Any,
) -> agent_schemas.EventStrategyReviewManualSummaryInput:
    if isinstance(raw, agent_schemas.EventStrategyReviewManualSummaryInput):
        raw = raw.model_dump()

    if not isinstance(raw, dict):
        raise ValueError("event_strategy_review_manual_summary_required")

    headline = _clean_text(raw.get("headline"))
    summary = _clean_text(raw.get("summary"))
    if headline is None or summary is None:
        raise ValueError("event_strategy_review_manual_summary_required")

    return agent_schemas.EventStrategyReviewManualSummaryInput(
        headline=headline,
        summary=summary,
        source_label=_clean_text(raw.get("source_label")),
        event_date=_clean_text(raw.get("event_date")),
    )


def normalize_manual_url_bundle_input(
    raw: Any,
) -> agent_schemas.EventStrategyReviewManualUrlBundleInput:
    if isinstance(raw, agent_schemas.EventStrategyReviewManualUrlBundleInput):
        raw = raw.model_dump()

    if not isinstance(raw, dict):
        raise ValueError("event_strategy_review_manual_url_bundle_required")

    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise ValueError("event_strategy_review_manual_url_bundle_required")
    submitted_item_count = _coerce_positive_int(raw.get("submitted_item_count")) or len(
        items_raw
    )

    items: list[agent_schemas.EventStrategyReviewUrlSourceInput] = []
    seen_urls: set[str] = set()
    for item in items_raw:
        if isinstance(item, agent_schemas.EventStrategyReviewUrlSourceInput):
            normalized = item
        elif isinstance(item, dict):
            url = _clean_text(item.get("url"))
            if url is None:
                continue
            normalized = agent_schemas.EventStrategyReviewUrlSourceInput(
                url=url,
                title=_clean_text(item.get("title")),
                publisher=_clean_text(item.get("publisher")),
                published_at=_clean_text(item.get("published_at")),
            )
        else:
            continue

        dedupe_key = _normalize_url_dedupe_key(normalized.url)
        if dedupe_key in seen_urls:
            continue
        seen_urls.add(dedupe_key)
        items.append(normalized)

    if not items:
        raise ValueError("event_strategy_review_manual_url_bundle_required")

    return agent_schemas.EventStrategyReviewManualUrlBundleInput(
        items=items,
        submitted_item_count=max(submitted_item_count, len(items)),
    )


def normalize_curated_search_query_input(
    raw: Any,
) -> agent_schemas.EventStrategyReviewCuratedSearchQueryInput:
    if isinstance(raw, agent_schemas.EventStrategyReviewCuratedSearchQueryInput):
        raw = raw.model_dump()

    if not isinstance(raw, dict):
        raise ValueError("event_strategy_review_curated_search_query_required")

    query = _clean_text(raw.get("query"))
    if query is None:
        raise ValueError("event_strategy_review_curated_search_query_required")

    requested_max_results = _coerce_positive_int(raw.get("max_results"))

    return agent_schemas.EventStrategyReviewCuratedSearchQueryInput(
        query=query,
        geography_hint=_clean_text(raw.get("geography_hint")),
        topic_hints=_dedupe_str_list(raw.get("topic_hints")),
        allowed_domains=_dedupe_str_list(raw.get("allowed_domains")),
        max_results=requested_max_results or 10,
    )


def normalize_retrieval_contract(
    raw: Any,
) -> agent_schemas.EventStrategyReviewRetrievalContract:
    if isinstance(raw, agent_schemas.EventStrategyReviewRetrievalContract):
        raw = raw.model_dump()

    if not isinstance(raw, dict):
        raise TypeError("event_strategy_review_retrieval_contract_must_be_dict")

    source_mode = raw.get("source_mode")
    if source_mode not in {
        "manual_summary",
        "manual_url_bundle",
        "curated_search_query",
    }:
        raise ValueError("event_strategy_review_invalid_source_mode")

    manual_summary_input = None
    manual_url_bundle_input = None
    curated_search_query_input = None

    if source_mode == "manual_summary":
        manual_summary_input = normalize_manual_summary_input(
            raw.get("manual_summary_input")
        )
    elif source_mode == "manual_url_bundle":
        manual_url_bundle_input = normalize_manual_url_bundle_input(
            raw.get("manual_url_bundle_input")
        )
    else:
        curated_search_query_input = normalize_curated_search_query_input(
            raw.get("curated_search_query_input")
        )

    return agent_schemas.EventStrategyReviewRetrievalContract(
        source_mode=source_mode,
        manual_summary_input=manual_summary_input,
        manual_url_bundle_input=manual_url_bundle_input,
        curated_search_query_input=curated_search_query_input,
        live_retrieval_enabled=False,
    )


def normalize_run_request(
    raw: Any,
) -> agent_schemas.EventStrategyReviewRunRequest:
    if isinstance(raw, agent_schemas.EventStrategyReviewRunRequest):
        raw = raw.model_dump()

    raw_dict = _request_to_dict(raw)

    return agent_schemas.EventStrategyReviewRunRequest(
        retrieval_contract=normalize_retrieval_contract(
            raw_dict.get("retrieval_contract")
        ),
        operator_notes=_clean_text(raw_dict.get("operator_notes")),
        topic_hints=_dedupe_str_list(raw_dict.get("topic_hints")),
        geo_focus=_dedupe_str_list(raw_dict.get("geo_focus")),
    )


def _text_corpus(
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> str:
    contract = request.retrieval_contract
    parts: list[str] = []

    if contract.manual_summary_input is not None:
        parts.extend(
            [
                contract.manual_summary_input.headline,
                contract.manual_summary_input.summary,
                contract.manual_summary_input.source_label or "",
            ]
        )
    if contract.manual_url_bundle_input is not None:
        for item in contract.manual_url_bundle_input.items:
            parts.extend([item.title or "", item.publisher or "", item.url])
    if contract.curated_search_query_input is not None:
        parts.extend(
            [
                contract.curated_search_query_input.query,
                contract.curated_search_query_input.geography_hint or "",
                " ".join(contract.curated_search_query_input.topic_hints),
            ]
        )

    parts.extend(normalized_hint for normalized_hint in request.topic_hints)
    parts.extend(request.geo_focus)
    if request.operator_notes:
        parts.append(request.operator_notes)

    return " ".join(part for part in parts if part).lower()


def _derive_taxonomy_tags(
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> list[str]:
    text = _text_corpus(request)
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    for hint in request.topic_hints:
        hint_text = hint.strip().lower()
        if hint_text:
            add(hint_text.replace(" ", "_"))

    query_input = request.retrieval_contract.curated_search_query_input
    if query_input is not None:
        for hint in query_input.topic_hints:
            hint_text = hint.strip().lower()
            if hint_text:
                add(hint_text.replace(" ", "_"))

    if _contains_any(text, ("bank of canada", "federal reserve", "rate decision")):
        add("central_bank_decision")
    if _contains_any(text, ("mortgage", "interest rate", "rate path", "rates")):
        add("mortgage_rate_shift")
    if _contains_any(text, ("inflation", "macro", "economic", "economy")):
        add("macro_housing_signal")
    if _contains_any(text, ("policy", "regulation", "tax", "compliance")):
        add("policy_regulation_change")
    if _contains_any(text, ("inventory", "pricing", "price", "demand", "supply")):
        add("inventory_pricing_shift")
    if _contains_any(text, ("condo", "condominium")):
        add("condo_market_change")
    if _contains_any(text, ("rental", "rent", "lease", "tenant", "landlord")):
        add("rental_market_change")
    if _contains_any(text, ("neighborhood", "neighbourhood", "building")):
        add("neighborhood_building_trend")

    return tags


def _derive_geography_tags(
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> list[str]:
    text = _text_corpus(request)
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    for geo_focus in request.geo_focus:
        add(geo_focus)

    query_input = request.retrieval_contract.curated_search_query_input
    if query_input is not None and query_input.geography_hint:
        add(query_input.geography_hint)

    if "toronto" in text:
        add("Toronto")
    if "gta" in text or "greater toronto" in text:
        add("GTA")
    if "ontario" in text:
        add("Ontario")
    if "canada" in text:
        add("Canada")

    return tags


def _build_clustered_sources(
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> list[agent_schemas.EventStrategyReviewClusteredSource]:
    contract = request.retrieval_contract
    sources: list[agent_schemas.EventStrategyReviewClusteredSource] = []

    if contract.manual_summary_input is not None:
        manual_summary = contract.manual_summary_input
        sources.append(
            agent_schemas.EventStrategyReviewClusteredSource(
                source_kind="manual_summary",
                title=manual_summary.headline,
                source_label=manual_summary.source_label,
                published_at=manual_summary.event_date,
                notes=["manual summary preserved without live retrieval"],
            )
        )
        return sources

    if contract.manual_url_bundle_input is not None:
        for item in contract.manual_url_bundle_input.items:
            sources.append(
                agent_schemas.EventStrategyReviewClusteredSource(
                    source_kind="manual_url_bundle",
                    title=item.title,
                    url=item.url,
                    publisher=item.publisher,
                    published_at=item.published_at,
                    notes=[
                        "manual URL bundle item preserved for later controlled"
                        " retrieval"
                    ],
                )
            )
        return sources

    query_input = contract.curated_search_query_input
    if query_input is not None:
        sources.append(
            agent_schemas.EventStrategyReviewClusteredSource(
                source_kind="curated_search_query",
                source_label="curated_search_query",
                notes=[
                    f"query preserved: {query_input.query}",
                    "no live retrieval executed in this step",
                ],
            )
        )

    return sources


def build_event_cluster(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
) -> agent_schemas.EventStrategyReviewEventCluster:
    normalized_request = normalize_run_request(request)
    contract = normalized_request.retrieval_contract
    sources = _build_clustered_sources(normalized_request)

    if contract.manual_summary_input is not None:
        canonical_title = contract.manual_summary_input.headline
        canonical_summary = contract.manual_summary_input.summary
        retrieval_notes = [
            "Manual summary input preserved as the canonical event summary.",
            RETRIEVAL_CONTRACT_NOTE,
        ]
    elif contract.manual_url_bundle_input is not None:
        primary_title = contract.manual_url_bundle_input.items[0].title
        canonical_title = (
            primary_title
            or f"Manual URL bundle submitted with {len(sources)} source item(s)"
        )
        canonical_summary = (
            f"Manual URL bundle preserved with {len(sources)} source item(s) for"
            " later controlled review. This step does not fetch external content."
        )
        retrieval_notes = [
            "Manual URL bundle accepted without uncontrolled crawling.",
            RETRIEVAL_CONTRACT_NOTE,
        ]
    else:
        curated_query = contract.curated_search_query_input
        assert curated_query is not None
        canonical_title = f"Curated search query: {curated_query.query}"
        canonical_summary = (
            "Curated search query preserved for later controlled retrieval. Step"
            " 1 records the retrieval contract but does not execute live search."
        )
        retrieval_notes = [
            "Curated search query contract accepted with no live retrieval executed.",
            RETRIEVAL_CONTRACT_NOTE,
        ]

    source_count = len(sources)
    duplicate_count = 0
    if contract.manual_url_bundle_input is not None:
        duplicate_count = max(
            contract.manual_url_bundle_input.submitted_item_count - source_count,
            0,
        )
    cluster_strength = source_count
    if contract.source_mode == "curated_search_query":
        cluster_strength = 0

    return agent_schemas.EventStrategyReviewEventCluster(
        source_mode=contract.source_mode,
        canonical_event_title=canonical_title,
        canonical_summary=canonical_summary,
        taxonomy_tags=_derive_taxonomy_tags(normalized_request),
        geography_tags=_derive_geography_tags(normalized_request),
        source_count=source_count,
        cluster_strength=cluster_strength,
        duplicate_count=duplicate_count,
        sources=sources,
        retrieval_notes=retrieval_notes,
    )


def build_score_breakdown(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
    event_cluster: agent_schemas.EventStrategyReviewEventCluster | None = None,
) -> agent_schemas.EventStrategyReviewScoreBreakdown:
    normalized_request = normalize_run_request(request)
    cluster = event_cluster or build_event_cluster(normalized_request)
    text = _text_corpus(normalized_request)
    selection_notes: list[str] = []

    relevance_score = min(30.0, float(len(cluster.taxonomy_tags) * 7))
    if relevance_score:
        selection_notes.append("real_estate_relevance_detected")

    geography_score = min(20.0, float(len(cluster.geography_tags) * 5))
    if geography_score:
        selection_notes.append("geography_relevance_detected")

    recency_score = 0.0
    if any(source.published_at for source in cluster.sources):
        recency_score = 5.0
        selection_notes.append("dated_source_metadata_present")

    source_credibility_score = 0.0
    if normalized_request.retrieval_contract.source_mode == "manual_url_bundle":
        source_credibility_score = min(
            10.0,
            float(
                sum(1 for source in cluster.sources if source.publisher or source.title)
                * 2
            ),
        )
    elif normalized_request.retrieval_contract.source_mode == "manual_summary":
        source_credibility_score = 2.0

    cluster_strength_score = min(10.0, float(cluster.cluster_strength * 3))
    if cluster_strength_score:
        selection_notes.append("source_cluster_strength_recorded")

    operator_usefulness_score = 0.0
    if _contains_any(
        text,
        (
            "buyer",
            "seller",
            "listing",
            "mortgage",
            "rental",
            "tenant",
            "landlord",
            "inventory",
            "condo",
            "policy",
            "compliance",
        ),
    ):
        operator_usefulness_score += 15.0
    if _contains_any(
        text,
        (
            "bank of canada",
            "federal reserve",
            "rate",
            "housing",
            "tax",
            "affordability",
        ),
    ):
        operator_usefulness_score += 10.0
    operator_usefulness_score = min(25.0, operator_usefulness_score)
    if operator_usefulness_score:
        selection_notes.append("operator_usefulness_detected")

    total_score = round(
        relevance_score
        + geography_score
        + recency_score
        + source_credibility_score
        + cluster_strength_score
        + operator_usefulness_score,
        2,
    )

    return agent_schemas.EventStrategyReviewScoreBreakdown(
        relevance_score=relevance_score,
        geography_score=geography_score,
        recency_score=recency_score,
        source_credibility_score=source_credibility_score,
        cluster_strength_score=cluster_strength_score,
        operator_usefulness_score=operator_usefulness_score,
        total_score=total_score,
        selection_notes=selection_notes,
    )


def conservative_importance_assessment(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
    event_cluster: agent_schemas.EventStrategyReviewEventCluster | None = None,
    score_breakdown: agent_schemas.EventStrategyReviewScoreBreakdown | None = None,
) -> agent_schemas.EventStrategyReviewImportanceAssessment:
    normalized_request = normalize_run_request(request)
    cluster = event_cluster or build_event_cluster(normalized_request)
    scores = score_breakdown or build_score_breakdown(normalized_request, cluster)

    if scores.total_score >= 70:
        classification: agent_schemas.EventStrategyReviewImportance = (
            "strategy_review_required"
        )
        reason = (
            "Event clears the v1 threshold for structured strategy review"
            " based on relevance, operator usefulness, and available source"
            " signal."
        )
    elif scores.total_score >= 50:
        classification = "watchlist"
        reason = (
            "Event shows meaningful signal but still needs stronger confirmation"
            " or clearer operator impact before it becomes a required strategy"
            " review."
        )
    else:
        classification = "noise"
        reason = (
            "Event remains below the threshold for structured strategy review and"
            " should stay out of active packaging or execution flows."
        )

    confidence = 0.58
    if cluster.source_mode == "manual_url_bundle":
        confidence += 0.08
    if cluster.source_count >= 2:
        confidence += 0.08
    if scores.total_score >= 70:
        confidence += 0.12
    elif scores.total_score >= 50:
        confidence += 0.06

    return agent_schemas.EventStrategyReviewImportanceAssessment(
        classification=classification,
        reason=reason,
        confidence=min(round(confidence, 2), 0.9),
    )


def _placeholder_perspective_block(
    perspective_key: str,
    event_cluster: agent_schemas.EventStrategyReviewEventCluster,
    importance_assessment: agent_schemas.EventStrategyReviewImportanceAssessment,
) -> agent_schemas.EventStrategyReviewPerspectiveBlock:
    summaries = {
        "follow_up": "Follow-up / CRM perspective placeholder retained for later pipeline-aware review.",
        "conversation_retention": "Conversation / retention perspective placeholder retained for later messaging review.",
        "listing_seller": "Listing / seller perspective placeholder retained for later seller-strategy review.",
        "cma_market": "CMA / market perspective placeholder retained for later market-comparison review.",
        "ops_compliance": "Operations / compliance perspective placeholder retained for later policy/compliance review.",
        "buyer_renter": "Buyer / renter perspective placeholder retained for later buyer and rental impact review.",
    }
    why_it_matters = {
        "follow_up": "Active CRM follow-up framing may need review if the event changes market expectations.",
        "conversation_retention": "Live client conversations may need updated framing once the event is validated.",
        "listing_seller": "Seller-side positioning may shift if the event materially affects pricing or timing sentiment.",
        "cma_market": "Market-comparison assumptions may need review if the event changes local demand or supply expectations.",
        "ops_compliance": "Policy and process implications may need review before any external use of this analysis.",
        "buyer_renter": "Buyer and renter positioning may shift if affordability, rates, or rental conditions move materially.",
    }

    return agent_schemas.EventStrategyReviewPerspectiveBlock(
        status="placeholder",
        summary=summaries[perspective_key],
        why_it_matters=[why_it_matters[perspective_key]],
        business_implications=[
            (
                f"Current event classification is"
                f" {importance_assessment.classification} for"
                f" '{event_cluster.canonical_event_title}'."
            )
        ],
        recommended_internal_actions=[
            "Keep this perspective block fixed and ready for deeper implementation"
            " in a later approved step."
        ],
        cautions=[PERSPECTIVE_SKELETON_NOTE],
    )


def build_fixed_perspective_blocks(
    event_cluster: agent_schemas.EventStrategyReviewEventCluster,
    importance_assessment: agent_schemas.EventStrategyReviewImportanceAssessment,
) -> agent_schemas.EventStrategyReviewPerspectiveBlocks:
    return agent_schemas.EventStrategyReviewPerspectiveBlocks(
        follow_up=_placeholder_perspective_block(
            "follow_up",
            event_cluster,
            importance_assessment,
        ),
        conversation_retention=_placeholder_perspective_block(
            "conversation_retention",
            event_cluster,
            importance_assessment,
        ),
        listing_seller=_placeholder_perspective_block(
            "listing_seller",
            event_cluster,
            importance_assessment,
        ),
        cma_market=_placeholder_perspective_block(
            "cma_market",
            event_cluster,
            importance_assessment,
        ),
        ops_compliance=_placeholder_perspective_block(
            "ops_compliance",
            event_cluster,
            importance_assessment,
        ),
        buyer_renter=_placeholder_perspective_block(
            "buyer_renter",
            event_cluster,
            importance_assessment,
        ),
    )


def build_affected_entities(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
    event_cluster: agent_schemas.EventStrategyReviewEventCluster | None = None,
    importance_assessment: agent_schemas.EventStrategyReviewImportanceAssessment | None = None,
) -> agent_schemas.EventStrategyReviewAffectedEntities:
    normalized_request = normalize_run_request(request)
    cluster = event_cluster or build_event_cluster(normalized_request)
    importance = importance_assessment or conservative_importance_assessment(
        normalized_request,
        cluster,
        None,
    )
    text = _text_corpus(normalized_request)

    geographies = list(cluster.geography_tags)
    market_segments: list[str] = []
    business_functions: list[str] = []

    def add_unique(target: list[str], value: str) -> None:
        if value not in target:
            target.append(value)

    if _contains_any(text, ("buyer", "mortgage", "affordability", "purchase")):
        add_unique(market_segments, "buyer")
    if _contains_any(text, ("seller", "listing", "inventory", "pricing", "price")):
        add_unique(market_segments, "seller")
    if _contains_any(text, ("tenant", "renter", "rent", "lease", "rental")):
        add_unique(market_segments, "renter")
    if _contains_any(text, ("landlord", "rent", "lease", "rental")):
        add_unique(market_segments, "landlord")
    if _contains_any(text, ("investor", "investment", "investor policy")):
        add_unique(market_segments, "investor")
    if _contains_any(text, ("condo", "condominium")):
        add_unique(market_segments, "condo")

    if importance.classification != "noise":
        add_unique(business_functions, "follow_up")
        add_unique(business_functions, "conversation_retention")
    if _contains_any(text, ("seller", "listing", "inventory", "pricing", "price", "condo")):
        add_unique(business_functions, "listing_seller")
    if cluster.taxonomy_tags or cluster.geography_tags:
        add_unique(business_functions, "cma_market")
    if _contains_any(text, ("policy", "regulation", "compliance", "tax")):
        add_unique(business_functions, "ops_compliance")
    if _contains_any(text, ("buyer", "tenant", "renter", "rent", "lease", "mortgage")):
        add_unique(business_functions, "buyer_renter")

    notes = [
        "Affected entities are inferred conservatively from event content only; no CRM-linked contact or property targeting is attempted in v1."
    ]

    return agent_schemas.EventStrategyReviewAffectedEntities(
        geographies=geographies,
        market_segments=market_segments,
        business_functions=business_functions,
        notes=notes,
    )


def build_execution_plan(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
) -> agent_schemas.EventStrategyReviewExecutionPlan:
    normalized_request = normalize_run_request(request)
    contract = normalized_request.retrieval_contract

    deduped_source_count = 0
    duplicate_source_count = 0
    operator_notes: list[str] = [RETRIEVAL_CONTRACT_NOTE]

    if contract.manual_summary_input is not None:
        deduped_source_count = 1
        operator_notes.append(
            "manual_summary is active for internal report generation in this step."
        )
        return agent_schemas.EventStrategyReviewExecutionPlan(
            source_mode="manual_summary",
            execution_path="manual_summary_internal_report",
            accepted_for_execution=True,
            live_retrieval_enabled=False,
            deduped_source_count=deduped_source_count,
            duplicate_source_count=duplicate_source_count,
            operator_notes=operator_notes,
        )

    if contract.manual_url_bundle_input is not None:
        deduped_source_count = len(contract.manual_url_bundle_input.items)
        duplicate_source_count = max(
            contract.manual_url_bundle_input.submitted_item_count
            - deduped_source_count,
            0,
        )
        operator_notes.append(
            "manual_url_bundle is active for internal clustering and report generation in this step."
        )
        if duplicate_source_count > 0:
            operator_notes.append(URL_DEDUPE_NOTE)
        return agent_schemas.EventStrategyReviewExecutionPlan(
            source_mode="manual_url_bundle",
            execution_path="manual_url_bundle_internal_report",
            accepted_for_execution=True,
            live_retrieval_enabled=False,
            deduped_source_count=deduped_source_count,
            duplicate_source_count=duplicate_source_count,
            operator_notes=operator_notes,
        )

    operator_notes.append(CURATED_QUERY_NOT_ACTIVE_NOTE)
    query_input = contract.curated_search_query_input
    if query_input is not None:
        deduped_source_count = len(query_input.allowed_domains)

    return agent_schemas.EventStrategyReviewExecutionPlan(
        source_mode="curated_search_query",
        execution_path="curated_search_query_not_active_yet",
        accepted_for_execution=False,
        live_retrieval_enabled=False,
        deduped_source_count=deduped_source_count,
        duplicate_source_count=0,
        operator_notes=operator_notes,
    )


def build_output_mode_options() -> list[agent_schemas.EventStrategyReviewOutputModeOption]:
    return [
        agent_schemas.EventStrategyReviewOutputModeOption(
            mode="internal_report_only",
            status="first_class_v1",
            reason="Available immediately as the default internal operator report.",
        ),
        agent_schemas.EventStrategyReviewOutputModeOption(
            mode="html_report_package",
            status="first_class_v1",
            reason=(
                "Supported as a separate explicit packaging step after Kevin"
                " reviews the analysis."
            ),
        ),
        agent_schemas.EventStrategyReviewOutputModeOption(
            mode="social_post_draft_pack",
            status="planned_later",
            reason="Planned only as a later draft-only expansion.",
        ),
        agent_schemas.EventStrategyReviewOutputModeOption(
            mode="email_newsletter_draft_pack",
            status="planned_later",
            reason="Planned only as a later draft-only expansion.",
        ),
        agent_schemas.EventStrategyReviewOutputModeOption(
            mode="client_summary_draft_pack",
            status="planned_later",
            reason="Planned only as a later draft-only expansion.",
        ),
    ]


def _build_recommended_actions(
    importance_assessment: agent_schemas.EventStrategyReviewImportanceAssessment,
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> agent_schemas.EventStrategyReviewRecommendedActions:
    internal_actions: list[str] = []
    human_review_actions: list[str] = [
        "Kevin should decide whether this event stays internal-only or merits a later packaging step."
    ]

    if request.retrieval_contract.source_mode == "curated_search_query":
        human_review_actions.append(
            "Kevin should confirm whether the curated query should proceed to a later controlled retrieval step."
        )

    if importance_assessment.classification == "noise":
        internal_actions.append(
            "Keep this event out of active packaging and treat it as background noise unless stronger signal appears."
        )
    elif importance_assessment.classification == "watchlist":
        internal_actions.extend(
            [
                "Keep this event on a watchlist until stronger source clustering or business impact is confirmed.",
                "Preserve the retrieval contract for later controlled follow-up if Kevin requests it.",
            ]
        )
    else:
        internal_actions.extend(
            [
                "Prepare this event for a deeper structured strategy review in a later approved runtime step.",
                "Review which fixed perspective blocks will need active implementation once controlled retrieval is enabled.",
            ]
        )
        human_review_actions.append(
            "Kevin should decide whether an HTML report package should be requested after the analysis is reviewed."
        )

    return agent_schemas.EventStrategyReviewRecommendedActions(
        internal_actions=internal_actions,
        human_review_actions=human_review_actions,
    )


def execute_event_strategy_review_request(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
) -> agent_schemas.EventStrategyReviewExecutionResult:
    normalized_request = normalize_run_request(request)
    execution_plan = build_execution_plan(normalized_request)

    if not execution_plan.accepted_for_execution:
        return agent_schemas.EventStrategyReviewExecutionResult(
            source_mode=normalized_request.retrieval_contract.source_mode,
            execution_status="not_active_yet",
            execution_plan=execution_plan,
            report=None,
            inactive_reason=CURATED_QUERY_NOT_ACTIVE_NOTE,
            operator_notes=[
                INTERNAL_ONLY_OPERATOR_NOTE,
                CURATED_QUERY_NOT_ACTIVE_NOTE,
            ],
        )

    report = build_internal_report(normalized_request)
    operator_notes = [INTERNAL_ONLY_OPERATOR_NOTE]
    operator_notes.extend(note for note in execution_plan.operator_notes if note)

    return agent_schemas.EventStrategyReviewExecutionResult(
        source_mode=normalized_request.retrieval_contract.source_mode,
        execution_status="report_generated",
        execution_plan=execution_plan,
        report=report,
        inactive_reason=None,
        operator_notes=operator_notes,
    )


def _parse_execution_result(
    raw_result: str | None,
) -> agent_schemas.EventStrategyReviewExecutionResult | None:
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    if hasattr(agent_schemas.EventStrategyReviewExecutionResult, "model_validate"):
        try:
            return agent_schemas.EventStrategyReviewExecutionResult.model_validate(parsed)
        except Exception:
            return None

    try:
        return agent_schemas.EventStrategyReviewExecutionResult.parse_obj(parsed)
    except Exception:
        return None


def _parse_package_result(
    raw_result: str | None,
) -> agent_schemas.EventStrategyReviewPackageResult | None:
    if not raw_result:
        return None

    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return None

    if hasattr(agent_schemas.EventStrategyReviewPackageResult, "model_validate"):
        try:
            return agent_schemas.EventStrategyReviewPackageResult.model_validate(parsed)
        except Exception:
            return None

    try:
        return agent_schemas.EventStrategyReviewPackageResult.parse_obj(parsed)
    except Exception:
        return None


def build_internal_report(
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any],
) -> agent_schemas.EventStrategyReviewReportResponse:
    normalized_request = normalize_run_request(request)
    event_cluster = build_event_cluster(normalized_request)
    score_breakdown = build_score_breakdown(normalized_request, event_cluster)
    importance_assessment = conservative_importance_assessment(
        normalized_request,
        event_cluster,
        score_breakdown,
    )
    affected_entities = build_affected_entities(
        normalized_request,
        event_cluster,
        importance_assessment,
    )
    perspective_blocks = build_fixed_perspective_blocks(
        event_cluster,
        importance_assessment,
    )
    recommended_actions = _build_recommended_actions(
        importance_assessment,
        normalized_request,
    )

    report_title = f"Event strategy review: {event_cluster.canonical_event_title}"
    synthesis_summary = (
        f"This internal report preserves a controlled {event_cluster.source_mode}"
        f" intake contract for '{event_cluster.canonical_event_title}' and"
        f" classifies it as {importance_assessment.classification}."
    )

    return agent_schemas.EventStrategyReviewReportResponse(
        report_title=report_title,
        retrieval_contract=normalized_request.retrieval_contract,
        event_cluster=event_cluster,
        score_breakdown=score_breakdown,
        importance_assessment=importance_assessment,
        affected_entities=affected_entities,
        execution_policy=agent_schemas.EventStrategyReviewExecutionPolicy(),
        perspective_blocks=perspective_blocks,
        strategy_synthesis=agent_schemas.EventStrategyReviewSynthesis(
            summary=synthesis_summary,
            key_takeaways=[
                RETRIEVAL_CONTRACT_NOTE,
                PACKAGING_EXPLICIT_STEP_NOTE,
                PERSPECTIVE_SKELETON_NOTE,
            ],
        ),
        recommended_next_actions=recommended_actions,
        output_mode_options=build_output_mode_options(),
        operator_notes=[
            INTERNAL_ONLY_OPERATOR_NOTE,
            RETRIEVAL_CONTRACT_NOTE,
            PACKAGING_EXPLICIT_STEP_NOTE,
        ],
    )


def _event_strategy_source_title(
    report: agent_schemas.EventStrategyReviewReportResponse,
    package_request: agent_schemas.EventStrategyReviewPackageRequest,
) -> str:
    title_override = _clean_text(package_request.title_override)
    if title_override:
        return title_override
    return report.report_title


def _render_html_report_document(
    *,
    report: agent_schemas.EventStrategyReviewReportResponse,
    execution_result: agent_schemas.EventStrategyReviewExecutionResult,
    package_request: agent_schemas.EventStrategyReviewPackageRequest,
) -> str:
    title = escape(_event_strategy_source_title(report, package_request))
    perspective_html = []
    for key in FIXED_PERSPECTIVE_KEYS:
        block = getattr(report.perspective_blocks, key)
        perspective_html.append(
            "\n".join(
                [
                    f"<section class=\"perspective-block\"><h3>{escape(key.replace('_', ' ').title())}</h3>",
                    f"<p><strong>Status:</strong> {escape(block.status)}</p>",
                    f"<p>{escape(block.summary)}</p>",
                    "<h4>Why It Matters</h4><ul>"
                    + "".join(f"<li>{escape(item)}</li>" for item in block.why_it_matters)
                    + "</ul>",
                    "<h4>Business Implications</h4><ul>"
                    + "".join(
                        f"<li>{escape(item)}</li>" for item in block.business_implications
                    )
                    + "</ul>",
                    "<h4>Recommended Internal Actions</h4><ul>"
                    + "".join(
                        f"<li>{escape(item)}</li>"
                        for item in block.recommended_internal_actions
                    )
                    + "</ul>",
                    "<h4>Cautions</h4><ul>"
                    + "".join(f"<li>{escape(item)}</li>" for item in block.cautions)
                    + "</ul>",
                    "</section>",
                ]
            )
        )

    internal_actions_html = "".join(
        f"<li>{escape(item)}</li>"
        for item in report.recommended_next_actions.internal_actions
    )
    human_actions_html = "".join(
        f"<li>{escape(item)}</li>"
        for item in report.recommended_next_actions.human_review_actions
    )
    source_items_html = "".join(
        "<li>"
        + escape(source.title or source.source_label or source.url or "source")
        + (
            f" ({escape(source.publisher)})"
            if source.publisher
            else ""
        )
        + "</li>"
        for source in report.event_cluster.sources
    )

    return "\n".join(
        [
            "<!DOCTYPE html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\" />",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
            f"<title>{title}</title>",
            "<style>",
            "body{font-family:Georgia,serif;margin:40px auto;max-width:960px;padding:0 20px;color:#14213d;background:#f7f4ed;line-height:1.55;}",
            "header,section{background:#fff;padding:24px;border:1px solid #d8d2c4;margin-bottom:18px;}",
            "h1,h2,h3,h4{color:#111827;margin-top:0;}",
            ".meta{color:#5b6470;font-size:0.95rem;}",
            ".pill{display:inline-block;padding:4px 10px;border:1px solid #c6b89e;border-radius:999px;margin-right:8px;margin-bottom:8px;background:#f3ead7;}",
            "ul{padding-left:22px;}",
            "code{background:#f2f2f2;padding:2px 5px;}",
            "</style>",
            "</head>",
            "<body>",
            "<header>",
            f"<h1>{title}</h1>",
            f"<p class=\"meta\">Internal-only HTML package. Source mode: {escape(execution_result.source_mode)}. Classification: {escape(report.importance_assessment.classification)}.</p>",
            f"<p>{escape(report.event_cluster.canonical_summary)}</p>",
            "</header>",
            "<section>",
            "<h2>Score Breakdown</h2>",
            f"<p><span class=\"pill\">Total {report.score_breakdown.total_score}</span>"
            f"<span class=\"pill\">Relevance {report.score_breakdown.relevance_score}</span>"
            f"<span class=\"pill\">Geography {report.score_breakdown.geography_score}</span>"
            f"<span class=\"pill\">Recency {report.score_breakdown.recency_score}</span>"
            f"<span class=\"pill\">Source Credibility {report.score_breakdown.source_credibility_score}</span>"
            f"<span class=\"pill\">Cluster Strength {report.score_breakdown.cluster_strength_score}</span>"
            f"<span class=\"pill\">Operator Usefulness {report.score_breakdown.operator_usefulness_score}</span></p>",
            "</section>",
            "<section>",
            "<h2>Affected Entities</h2>",
            "<h3>Geographies</h3>",
            "<ul>"
            + "".join(
                f"<li>{escape(item)}</li>"
                for item in report.affected_entities.geographies
            )
            + "</ul>",
            "<h3>Market Segments</h3>",
            "<ul>"
            + "".join(
                f"<li>{escape(item)}</li>"
                for item in report.affected_entities.market_segments
            )
            + "</ul>",
            "<h3>Business Functions</h3>",
            "<ul>"
            + "".join(
                f"<li>{escape(item)}</li>"
                for item in report.affected_entities.business_functions
            )
            + "</ul>",
            "<h3>Notes</h3>",
            "<ul>"
            + "".join(
                f"<li>{escape(item)}</li>"
                for item in report.affected_entities.notes
            )
            + "</ul>",
            "</section>",
            "<section>",
            "<h2>Recommended Next Actions</h2>",
            "<h3>Internal Actions</h3>",
            f"<ul>{internal_actions_html}</ul>",
            "<h3>Human Review Actions</h3>",
            f"<ul>{human_actions_html}</ul>",
            "</section>",
            "<section>",
            "<h2>Sources</h2>",
            f"<ul>{source_items_html}</ul>",
            "</section>",
            "<section>",
            "<h2>Perspective Blocks</h2>",
            *perspective_html,
            "</section>",
            "<section>",
            "<h2>Notes</h2>",
            "<ul>"
            + "".join(f"<li>{escape(note)}</li>" for note in report.operator_notes)
            + "</ul>",
            "</section>",
            "</body>",
            "</html>",
        ]
    )


def _write_text_artifact(
    *,
    directory: Path,
    file_name: str,
    content: str,
    artifact_type: agent_schemas.EventStrategyReviewArtifactType,
    label: str,
    content_type: str,
    is_entrypoint: bool = False,
) -> agent_schemas.EventStrategyReviewPackageArtifact:
    path = directory / file_name
    path.write_text(content, encoding="utf-8")
    return agent_schemas.EventStrategyReviewPackageArtifact(
        artifact_type=artifact_type,
        file_name=file_name,
        path=str(path),
        content_type=content_type,
        file_size_bytes=path.stat().st_size,
        checksum_sha256=_sha256_for_file(path),
        is_entrypoint=is_entrypoint,
        label=label,
    )


def _blocked_package_result(
    *,
    source_run_id: int,
    package_request: agent_schemas.EventStrategyReviewPackageRequest,
    notes: list[str],
) -> agent_schemas.EventStrategyReviewPackageResult:
    return agent_schemas.EventStrategyReviewPackageResult(
        source_run_id=source_run_id,
        selected_output_mode=package_request.selected_output_mode,
        status="blocked",
        requires_explicit_operator_step=True,
        package_directory_path=None,
        artifacts=[],
        operator_notes=notes,
    )


def build_event_strategy_review_html_package(
    *,
    source_run_id: int,
    execution_result: agent_schemas.EventStrategyReviewExecutionResult,
    package_request: agent_schemas.EventStrategyReviewPackageRequest,
) -> agent_schemas.EventStrategyReviewPackageResult:
    report = execution_result.report
    if report is None:
        return _blocked_package_result(
            source_run_id=source_run_id,
            package_request=package_request,
            notes=[PACKAGE_SOURCE_MISSING_NOTE],
        )

    package_dir = Path(
        tempfile.mkdtemp(prefix=f"event_strategy_review_package_{source_run_id}_")
    )

    report_payload = (
        execution_result.model_dump()
        if hasattr(execution_result, "model_dump")
        else execution_result.dict()
    )
    sources_payload = [source.model_dump() if hasattr(source, "model_dump") else source.dict() for source in report.event_cluster.sources]
    html = _render_html_report_document(
        report=report,
        execution_result=execution_result,
        package_request=package_request,
    )

    artifacts = [
        _write_text_artifact(
            directory=package_dir,
            file_name="index.html",
            content=html,
            artifact_type="static_html_bundle",
            label="HTML entrypoint",
            content_type="text/html; charset=utf-8",
            is_entrypoint=True,
        ),
        _write_text_artifact(
            directory=package_dir,
            file_name="report.json",
            content=json.dumps(report_payload, ensure_ascii=False, indent=2),
            artifact_type="json_report",
            label="Structured execution result",
            content_type="application/json",
        ),
    ]

    if sources_payload:
        artifacts.append(
            _write_text_artifact(
                directory=package_dir,
                file_name="sources.json",
                content=json.dumps(sources_payload, ensure_ascii=False, indent=2),
                artifact_type="json_report",
                label="Clustered sources",
                content_type="application/json",
            )
        )

    return agent_schemas.EventStrategyReviewPackageResult(
        source_run_id=source_run_id,
        selected_output_mode="html_report_package",
        status="draft_ready",
        requires_explicit_operator_step=True,
        package_directory_path=str(package_dir),
        artifacts=artifacts,
        operator_notes=[
            HTML_PACKAGE_NOTE,
            PACKAGING_EXPLICIT_STEP_NOTE,
        ],
    )

def run_event_strategy_review_once(
    db: Session,
    request: agent_schemas.EventStrategyReviewRunRequest | dict[str, Any] | Any,
) -> models.AgentRun:
    payload_json = _safe_task_payload_json(request)
    try:
        normalized_request = normalize_run_request(request)
    except Exception:
        normalized_request = None

    task = service.create_task(
        db,
        agent_type=AGENT_TYPE,
        subject_type=ANALYSIS_SUBJECT_TYPE,
        subject_id=None,
        payload=payload_json,
        priority="normal",
    )
    run = service.create_run(
        db,
        task=task,
        summary="Event Strategy Review run (MVP)",
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
            action="event_strategy_review_intake_received",
            details=payload_json,
        )

        execution_plan = build_execution_plan(normalized_request)
        run = service.update_run_status(
            db,
            run,
            status="executing",
            plan=_json_dumps(execution_plan),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="event_strategy_review_execution_planned",
            details=_json_dumps(execution_plan),
        )

        if execution_plan.duplicate_source_count > 0:
            service.write_audit_log(
                db,
                run=run,
                task=task,
                actor_type="system",
                action="event_strategy_review_duplicates_collapsed",
                details=_json_dumps(
                    {
                        "duplicate_source_count": execution_plan.duplicate_source_count,
                        "deduped_source_count": execution_plan.deduped_source_count,
                    }
                ),
            )

        execution_result = execute_event_strategy_review_request(normalized_request)

        if execution_result.execution_status == "not_active_yet":
            result_json = _json_dumps(execution_result)
            service.write_audit_log(
                db,
                run=run,
                task=task,
                actor_type="system",
                action="event_strategy_review_source_mode_not_active",
                details=result_json,
            )
            finished_at = datetime.utcnow()
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
                action="event_strategy_review_run_completed",
                details=result_json,
            )
            return run

        report = execution_result.report
        if report is None:
            raise RuntimeError("event_strategy_review_report_missing")

        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="event_strategy_review_sources_clustered",
            details=_json_dumps(report.event_cluster),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="event_strategy_review_importance_classified",
            details=_json_dumps(
                {
                    "score_breakdown": report.score_breakdown,
                    "importance_assessment": report.importance_assessment,
                }
            ),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="event_strategy_review_perspectives_built",
            details=_json_dumps(report.perspective_blocks),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="agent",
            action="event_strategy_review_report_generated",
            details=_json_dumps(
                {
                    "report_title": report.report_title,
                    "recommended_next_actions": report.recommended_next_actions,
                    "strategy_synthesis": report.strategy_synthesis,
                }
            ),
        )

        result_json = _json_dumps(execution_result)
        finished_at = datetime.utcnow()
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
            action="event_strategy_review_run_completed",
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
            action="event_strategy_review_run_failed",
            details=_json_dumps({"error": str(exc)}),
        )
        return run


def run_event_strategy_review_package_once(
    db: Session,
    *,
    source_run: models.AgentRun,
    package_request: agent_schemas.EventStrategyReviewPackageRequest,
) -> models.AgentRun:
    payload_json = _safe_package_payload_json(source_run.id, package_request)
    task = service.create_task(
        db,
        agent_type=AGENT_TYPE,
        subject_type=PACKAGE_SUBJECT_TYPE,
        subject_id=source_run.id,
        payload=payload_json,
        priority="normal",
    )
    run = service.create_run(
        db,
        task=task,
        summary="Event Strategy Review package run (MVP)",
    )

    now = datetime.utcnow()
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(db, run, status="planning", started_at=now)

    try:
        source_execution_result = _parse_execution_result(source_run.result)
        plan = {
            "source_run_id": source_run.id,
            "selected_output_mode": package_request.selected_output_mode,
            "requires_explicit_operator_step": True,
            "source_execution_status": (
                source_execution_result.execution_status
                if source_execution_result is not None
                else None
            ),
        }
        run = service.update_run_status(
            db,
            run,
            status="executing",
            plan=_json_dumps(plan),
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            actor_type="system",
            action="event_strategy_review_packaging_requested",
            details=payload_json,
        )

        if (
            source_execution_result is not None
            and source_execution_result.execution_status == "not_active_yet"
        ):
            package_result = _blocked_package_result(
                source_run_id=source_run.id,
                package_request=package_request,
                notes=[PACKAGE_SOURCE_NOT_ACTIVE_NOTE, PACKAGING_EXPLICIT_STEP_NOTE],
            )
        elif source_execution_result is None or source_execution_result.report is None:
            package_result = _blocked_package_result(
                source_run_id=source_run.id,
                package_request=package_request,
                notes=[PACKAGE_SOURCE_MISSING_NOTE, PACKAGING_EXPLICIT_STEP_NOTE],
            )
        elif package_request.selected_output_mode != "html_report_package":
            package_result = _blocked_package_result(
                source_run_id=source_run.id,
                package_request=package_request,
                notes=[PACKAGE_MODE_NOT_IMPLEMENTED_NOTE, PACKAGING_EXPLICIT_STEP_NOTE],
            )
        else:
            package_result = build_event_strategy_review_html_package(
                source_run_id=source_run.id,
                execution_result=source_execution_result,
                package_request=package_request,
            )

        result_json = _json_dumps(package_result)
        finished_at = datetime.utcnow()
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
            action="event_strategy_review_packaging_completed",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "status": package_result.status,
                    "selected_output_mode": package_result.selected_output_mode,
                    "artifacts": package_result.artifacts,
                }
            ),
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
            action="event_strategy_review_packaging_failed",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "error": str(exc),
                }
            ),
        )
        return run


def build_package_result_placeholder(
    request: agent_schemas.EventStrategyReviewPackageRequest | dict[str, Any],
) -> agent_schemas.EventStrategyReviewPackageResult:
    if isinstance(request, agent_schemas.EventStrategyReviewPackageRequest):
        package_request = request
    else:
        package_request = agent_schemas.EventStrategyReviewPackageRequest(**_request_to_dict(request))

    if package_request.selected_output_mode in {
        "internal_report_only",
        "html_report_package",
    }:
        status: agent_schemas.EventStrategyReviewPackageStatus = "not_generated"
    else:
        status = "blocked"

    return agent_schemas.EventStrategyReviewPackageResult(
        source_run_id=package_request.source_run_id,
        selected_output_mode=package_request.selected_output_mode,
        status=status,
        package_directory_path=None,
        artifacts=[],
        operator_notes=[
            PACKAGING_EXPLICIT_STEP_NOTE,
            "No packaging runtime is executed in this step.",
        ],
    )
