from __future__ import annotations

from typing import Any

from . import schemas as agent_schemas


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
    "Step 1 preserves a controlled retrieval contract for manual_summary,"
    " manual_url_bundle, and curated_search_query without executing live web"
    " retrieval."
)
PACKAGING_EXPLICIT_STEP_NOTE = (
    "HTML packaging remains a separate explicit operator step and does not"
    " auto-run after report generation."
)
PERSPECTIVE_SKELETON_NOTE = (
    "Perspective blocks are fixed in v1 Step 1 and remain skeletonized until"
    " later runtime work is approved."
)


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

    items: list[agent_schemas.EventStrategyReviewUrlSourceInput] = []
    seen_urls: set[str] = set()
    for item in items_raw:
        if isinstance(item, agent_schemas.EventStrategyReviewUrlSourceInput):
            normalized = item
        elif isinstance(item, dict):
            url = _clean_text(item.get("url"))
            if url is None or url in seen_urls:
                continue
            normalized = agent_schemas.EventStrategyReviewUrlSourceInput(
                url=url,
                title=_clean_text(item.get("title")),
                publisher=_clean_text(item.get("publisher")),
                published_at=_clean_text(item.get("published_at")),
            )
        else:
            continue

        if normalized.url in seen_urls:
            continue
        seen_urls.add(normalized.url)
        items.append(normalized)

    if not items:
        raise ValueError("event_strategy_review_manual_url_bundle_required")

    return agent_schemas.EventStrategyReviewManualUrlBundleInput(items=items)


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
                    "no live retrieval executed in Step 1",
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
            " later controlled review. Step 1 does not fetch external content."
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
            "Event clears the Step 1 threshold for structured strategy review"
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
        f"This Step 1 report preserves a controlled {event_cluster.source_mode}"
        f" intake contract for '{event_cluster.canonical_event_title}' and"
        f" classifies it as {importance_assessment.classification}."
    )

    return agent_schemas.EventStrategyReviewReportResponse(
        report_title=report_title,
        retrieval_contract=normalized_request.retrieval_contract,
        event_cluster=event_cluster,
        score_breakdown=score_breakdown,
        importance_assessment=importance_assessment,
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
        selected_output_mode=package_request.selected_output_mode,
        status=status,
        artifacts=[],
        operator_notes=[
            PACKAGING_EXPLICIT_STEP_NOTE,
            "No packaging runtime is executed in Step 1.",
        ],
    )
