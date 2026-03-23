from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import schemas as agent_schemas


RAW_CANDIDATE_CAP = 8
FETCHED_SOURCE_CAP = 3
INFERENCE_SH_API_URL = "https://api.inference.sh/apps/run"
INFERENCE_SH_CURATED_SEARCH_APP = "tavily/search-assistant"
SAFE_DEFAULT_TRUSTED_DOMAINS: dict[str, agent_schemas.EventStrategyReviewSourceTrustTier] = {
    "bankofcanada.ca": "tier_1_primary",
    "federalreserve.gov": "tier_1_primary",
    "canada.ca": "tier_1_primary",
    "ontario.ca": "tier_1_primary",
    "toronto.ca": "tier_1_primary",
    "cmhc-schl.gc.ca": "tier_1_primary",
    "statcan.gc.ca": "tier_1_primary",
    "reuters.com": "tier_2_reputable",
    "cbc.ca": "tier_2_reputable",
    "bnnbloomberg.ca": "tier_2_reputable",
    "theglobeandmail.com": "tier_2_reputable",
    "financialpost.com": "tier_2_reputable",
    "storeys.com": "tier_3_trade",
}
TRUST_TIER_WEIGHTS: dict[agent_schemas.EventStrategyReviewSourceTrustTier, float] = {
    "tier_1_primary": 30.0,
    "tier_2_reputable": 24.0,
    "tier_3_trade": 15.0,
    "untrusted": 0.0,
}


@dataclass(frozen=True)
class CuratedSearchCandidate:
    url: str
    title: str | None = None
    snippet: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class CuratedSearchAdapterResponse:
    status: str
    candidates: tuple[CuratedSearchCandidate, ...] = ()
    notes: tuple[str, ...] = ()


class BaseCuratedSearchAdapter(ABC):
    adapter_key = "unconfigured"

    @abstractmethod
    def search(
        self,
        *,
        query: str,
        max_results: int,
        allowed_domains: Sequence[str],
    ) -> CuratedSearchAdapterResponse:
        raise NotImplementedError("event_strategy_review_curated_search_not_implemented")


class UnavailableCuratedSearchAdapter(BaseCuratedSearchAdapter):
    adapter_key = "unavailable"

    def __init__(self, *, reason: str | None = None):
        self._reason = reason

    def search(
        self,
        *,
        query: str,
        max_results: int,
        allowed_domains: Sequence[str],
    ) -> CuratedSearchAdapterResponse:
        return CuratedSearchAdapterResponse(
            status="unavailable",
            candidates=(),
            notes=tuple(
                note
                for note in [
                    "Controlled curated-search retrieval is not configured in this environment yet.",
                    self._reason,
                ]
                if note
            ),
        )


class InferenceShTavilyCuratedSearchAdapter(BaseCuratedSearchAdapter):
    adapter_key = "inference_sh_tavily_search_assistant"

    def __init__(
        self,
        *,
        api_key: str,
        urlopen=urllib_request.urlopen,
        api_url: str = INFERENCE_SH_API_URL,
        app_id: str = INFERENCE_SH_CURATED_SEARCH_APP,
        timeout_seconds: int = 30,
    ):
        self._api_key = api_key
        self._urlopen = urlopen
        self._api_url = api_url
        self._app_id = app_id
        self._timeout_seconds = timeout_seconds

    def _build_payload(
        self,
        *,
        query: str,
        max_results: int,
    ) -> dict[str, object]:
        return {
            "app": self._app_id,
            "input": {
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
        }

    def search(
        self,
        *,
        query: str,
        max_results: int,
        allowed_domains: Sequence[str],
    ) -> CuratedSearchAdapterResponse:
        payload = self._build_payload(query=query, max_results=max_results)
        body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            self._api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            message = ""
            try:
                if exc.fp is not None:
                    message = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                message = ""
            lowered = message.lower()
            if exc.code == 429 or "rate limit" in lowered:
                return CuratedSearchAdapterResponse(
                    status="rate_limited",
                    notes=(
                        "inference.sh Tavily search adapter returned a rate-limited response.",
                    ),
                )
            return CuratedSearchAdapterResponse(
                status="unavailable",
                notes=(
                    "inference.sh Tavily search adapter rejected the request.",
                    _clean_text(message) or f"http_status={exc.code}",
                ),
            )
        except urllib_error.URLError as exc:
            return CuratedSearchAdapterResponse(
                status="unavailable",
                notes=(
                    "inference.sh Tavily search adapter could not reach the provider.",
                    str(exc.reason),
                ),
            )
        except TimeoutError:
            return CuratedSearchAdapterResponse(
                status="rate_limited",
                notes=("inference.sh Tavily search adapter timed out during retrieval.",),
            )
        except Exception as exc:
            return CuratedSearchAdapterResponse(
                status="unavailable",
                notes=(
                    "inference.sh Tavily search adapter raised an unexpected error.",
                    str(exc),
                ),
            )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return CuratedSearchAdapterResponse(
                status="unavailable",
                notes=(
                    "inference.sh Tavily search adapter returned non-JSON output.",
                ),
            )

        output_payload = parsed.get("output") if isinstance(parsed, dict) else parsed
        candidates = tuple(_extract_candidates_from_output(output_payload))
        notes = [
            "inference.sh Tavily search adapter completed a constrained search request.",
        ]
        if allowed_domains:
            notes.append(
                f"Allowed-domain constraint preserved {len(allowed_domains)} domain(s) for downstream filtering."
            )
        return CuratedSearchAdapterResponse(
            status="success",
            candidates=candidates,
            notes=tuple(notes),
        )


@dataclass
class RankedCandidate:
    candidate: CuratedSearchCandidate
    url: str
    domain: str
    trust_tier: agent_schemas.EventStrategyReviewSourceTrustTier
    score: float
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CuratedRetrievalOutcome:
    execution_status: agent_schemas.EventStrategyReviewExecutionStatus
    retrieval_metadata: agent_schemas.EventStrategyReviewRetrievalMetadata
    sources: tuple[agent_schemas.EventStrategyReviewClusteredSource, ...] = ()
    canonical_event_title: str | None = None
    canonical_summary: str | None = None
    retrieval_notes: tuple[str, ...] = ()
    inactive_reason: str | None = None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_domain(value: str | None) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    if "://" not in text:
        text = f"https://{text}"
    try:
        split = urlsplit(text)
    except Exception:
        return None
    host = split.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":443"):
        host = host[:-4]
    if host.endswith(":80"):
        host = host[:-3]
    return host or None


def _normalize_url(url: str) -> str:
    try:
        split = urlsplit(url)
    except Exception:
        return url.strip()

    scheme = split.scheme.lower() or "https"
    netloc = split.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]

    path = split.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    filtered_query_pairs = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.lower()
        not in {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "gclid",
            "fbclid",
        }
    ]
    normalized_query = urlencode(filtered_query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, normalized_query, ""))


def _domain_matches_constraint(domain: str, allowed_domains: Sequence[str]) -> bool:
    normalized_domain = _normalize_domain(domain)
    if normalized_domain is None:
        return False

    for allowed in allowed_domains:
        normalized_allowed = _normalize_domain(allowed)
        if normalized_allowed is None:
            continue
        if normalized_domain == normalized_allowed:
            return True
        if normalized_domain.endswith(f".{normalized_allowed}"):
            return True
    return False


def resolve_trust_tier(
    domain: str | None,
) -> agent_schemas.EventStrategyReviewSourceTrustTier:
    normalized_domain = _normalize_domain(domain)
    if normalized_domain is None:
        return "untrusted"
    for trusted_domain, tier in SAFE_DEFAULT_TRUSTED_DOMAINS.items():
        if normalized_domain == trusted_domain or normalized_domain.endswith(
            f".{trusted_domain}"
        ):
            return tier
    return "untrusted"


def _tokenize(value: str | None) -> set[str]:
    text = _clean_text(value)
    if text is None:
        return set()
    tokens = {
        token.strip(" ,.:;()[]{}\"'").lower()
        for token in text.split()
    }
    return {token for token in tokens if token}


def _extract_candidates_from_output(output: object) -> list[CuratedSearchCandidate]:
    candidates: list[CuratedSearchCandidate] = []
    seen_urls: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        candidate = _candidate_from_dict(value)
        if candidate is not None and candidate.url not in seen_urls:
            seen_urls.add(candidate.url)
            candidates.append(candidate)

        for nested in value.values():
            if isinstance(nested, (list, dict)):
                visit(nested)

    visit(output)
    return candidates


def _candidate_from_dict(value: dict[str, object]) -> CuratedSearchCandidate | None:
    url = _clean_text(
        value.get("url")
        if isinstance(value.get("url"), str)
        else value.get("link")
    )
    if url is None:
        return None

    title_value = value.get("title")
    if not isinstance(title_value, str):
        title_value = value.get("name") if isinstance(value.get("name"), str) else None
    snippet_value = value.get("content")
    if not isinstance(snippet_value, str):
        snippet_value = value.get("snippet") if isinstance(value.get("snippet"), str) else None
    if not isinstance(snippet_value, str):
        snippet_value = value.get("text") if isinstance(value.get("text"), str) else None
    publisher_value = value.get("publisher")
    if not isinstance(publisher_value, str):
        publisher_value = value.get("source") if isinstance(value.get("source"), str) else None
    published_value = value.get("published_at")
    if not isinstance(published_value, str):
        published_value = (
            value.get("published_date")
            if isinstance(value.get("published_date"), str)
            else None
        )
    if not isinstance(published_value, str):
        published_value = value.get("date") if isinstance(value.get("date"), str) else None

    return CuratedSearchCandidate(
        url=url,
        title=_clean_text(title_value),
        snippet=_clean_text(snippet_value),
        publisher=_clean_text(publisher_value),
        published_at=_clean_text(published_value),
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


def resolve_curated_search_adapter() -> BaseCuratedSearchAdapter:
    api_key = _clean_text(os.getenv("INFERENCE_API_KEY"))
    if api_key is None:
        return UnavailableCuratedSearchAdapter(
            reason="INFERENCE_API_KEY is not set, so the approved inference.sh search path stays unavailable.",
        )

    return InferenceShTavilyCuratedSearchAdapter(api_key=api_key)


def _candidate_score(
    *,
    candidate: CuratedSearchCandidate,
    domain: str,
    trust_tier: agent_schemas.EventStrategyReviewSourceTrustTier,
    request: agent_schemas.EventStrategyReviewRunRequest,
) -> float:
    title = _clean_text(candidate.title) or ""
    snippet = _clean_text(candidate.snippet) or ""
    publisher = _clean_text(candidate.publisher) or ""
    corpus = " ".join([title, snippet, publisher, domain]).lower()

    query_input = request.retrieval_contract.curated_search_query_input
    assert query_input is not None

    query_text = query_input.query.lower()
    query_tokens = _tokenize(query_input.query)
    topic_tokens = set(request.topic_hints)
    topic_tokens.update(query_input.topic_hints)
    topic_tokens = {token.lower() for token in topic_tokens if token}
    geo_tokens = {token.lower() for token in request.geo_focus if token}
    if query_input.geography_hint:
        geo_tokens.add(query_input.geography_hint.lower())

    score = TRUST_TIER_WEIGHTS[trust_tier]
    if query_text and query_text in corpus:
        score += 18.0
    score += min(18.0, float(len(query_tokens & _tokenize(corpus)) * 3))
    score += min(10.0, float(len(topic_tokens & _tokenize(corpus)) * 2))
    score += min(8.0, float(len(geo_tokens & _tokenize(corpus)) * 2))
    if candidate.published_at:
        score += 4.0
    elif candidate.observed_at:
        score += 2.0
    if title:
        score += 2.0
    return round(score, 2)


def _selected_candidates(
    *,
    ranked_candidates: Sequence[RankedCandidate],
) -> list[RankedCandidate]:
    selected: list[RankedCandidate] = []
    seen_domains: set[str] = set()

    for ranked in ranked_candidates:
        if ranked.domain in seen_domains:
            continue
        selected.append(ranked)
        seen_domains.add(ranked.domain)
        if len(selected) >= FETCHED_SOURCE_CAP:
            break

    if len(selected) >= 2:
        return selected

    for ranked in ranked_candidates:
        if ranked in selected:
            continue
        selected.append(ranked)
        if len(selected) >= FETCHED_SOURCE_CAP:
            break
    return selected


def _clustered_source_from_ranked(
    ranked: RankedCandidate,
) -> agent_schemas.EventStrategyReviewClusteredSource:
    candidate = ranked.candidate
    observed_at = candidate.observed_at or datetime.now(timezone.utc).isoformat()
    return agent_schemas.EventStrategyReviewClusteredSource(
        source_kind="curated_search_query",
        title=_clean_text(candidate.title),
        url=ranked.url,
        source_domain=ranked.domain,
        publisher=_clean_text(candidate.publisher),
        published_at=_clean_text(candidate.published_at),
        observed_at=observed_at,
        trust_tier=ranked.trust_tier,
        source_label="curated_search_query",
        notes=ranked.notes,
    )


def _blocked_outcome(
    *,
    execution_status: agent_schemas.EventStrategyReviewExecutionStatus,
    adapter_key: str,
    allowed_domains_applied: Sequence[str],
    default_trusted_domain_policy_applied: bool,
    raw_candidate_count: int,
    notes: Sequence[str],
    inactive_reason: str,
) -> CuratedRetrievalOutcome:
    return CuratedRetrievalOutcome(
        execution_status=execution_status,
        retrieval_metadata=agent_schemas.EventStrategyReviewRetrievalMetadata(
            retrieval_state=execution_status,
            adapter_key=adapter_key,
            raw_candidate_cap=RAW_CANDIDATE_CAP,
            raw_candidate_count=raw_candidate_count,
            fetched_source_cap=FETCHED_SOURCE_CAP,
            fetched_source_count=0,
            independent_source_count=0,
            allowed_domains_applied=list(allowed_domains_applied),
            default_trusted_domain_policy_applied=default_trusted_domain_policy_applied,
            has_tier_one_or_two_support=False,
            notes=list(notes),
        ),
        sources=(),
        canonical_event_title=None,
        canonical_summary=None,
        retrieval_notes=tuple(notes),
        inactive_reason=inactive_reason,
    )


def run_curated_search_query(
    request: agent_schemas.EventStrategyReviewRunRequest,
    *,
    adapter: BaseCuratedSearchAdapter | None = None,
) -> CuratedRetrievalOutcome:
    query_input = request.retrieval_contract.curated_search_query_input
    if query_input is None:
        raise ValueError("event_strategy_review_curated_search_query_required")

    retrieval_adapter = adapter or resolve_curated_search_adapter()
    requested_allowed_domains = [
        normalized
        for normalized in (
            _normalize_domain(domain) for domain in query_input.allowed_domains
        )
        if normalized is not None
    ]
    requested_allowed_domains = list(dict.fromkeys(requested_allowed_domains))
    default_policy_applied = not requested_allowed_domains
    allowed_domains_applied = (
        requested_allowed_domains
        if requested_allowed_domains
        else list(SAFE_DEFAULT_TRUSTED_DOMAINS.keys())
    )

    adapter_response = retrieval_adapter.search(
        query=query_input.query,
        max_results=min(query_input.max_results, RAW_CANDIDATE_CAP),
        allowed_domains=allowed_domains_applied,
    )

    adapter_notes = list(adapter_response.notes)
    if adapter_response.status == "unavailable":
        return _blocked_outcome(
            execution_status="retrieval_unavailable",
            adapter_key=retrieval_adapter.adapter_key,
            allowed_domains_applied=allowed_domains_applied,
            default_trusted_domain_policy_applied=default_policy_applied,
            raw_candidate_count=0,
            notes=adapter_notes
            + [
                "Curated query retrieval was requested, but no constrained retrieval adapter is available for this run.",
            ],
            inactive_reason="Controlled curated-query retrieval is unavailable for this run.",
        )
    if adapter_response.status == "rate_limited":
        return _blocked_outcome(
            execution_status="rate_limited",
            adapter_key=retrieval_adapter.adapter_key,
            allowed_domains_applied=allowed_domains_applied,
            default_trusted_domain_policy_applied=default_policy_applied,
            raw_candidate_count=0,
            notes=adapter_notes
            + [
                "Curated query retrieval hit a rate limit before a clean source cluster could be built.",
            ],
            inactive_reason="Controlled curated-query retrieval is temporarily rate limited.",
        )

    raw_candidates = list(adapter_response.candidates[:RAW_CANDIDATE_CAP])
    notes: list[str] = list(adapter_notes)
    if len(adapter_response.candidates) > RAW_CANDIDATE_CAP:
        notes.append(
            f"Raw candidate list was capped at {RAW_CANDIDATE_CAP} items for controlled review."
        )

    ranked_candidates: list[RankedCandidate] = []
    seen_urls: set[str] = set()
    for candidate in raw_candidates:
        normalized_url = _normalize_url(candidate.url)
        normalized_domain = _normalize_domain(candidate.url)
        if normalized_domain is None:
            continue
        if not _domain_matches_constraint(normalized_domain, allowed_domains_applied):
            continue
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        trust_tier = resolve_trust_tier(normalized_domain)
        if trust_tier == "untrusted":
            continue
        score = _candidate_score(
            candidate=candidate,
            domain=normalized_domain,
            trust_tier=trust_tier,
            request=request,
        )
        ranked_candidates.append(
            RankedCandidate(
                candidate=candidate,
                url=normalized_url,
                domain=normalized_domain,
                trust_tier=trust_tier,
                score=score,
                notes=[
                    f"rank_score={score}",
                    f"trust_tier={trust_tier}",
                ],
            )
        )

    if not ranked_candidates:
        return _blocked_outcome(
            execution_status="no_credible_sources",
            adapter_key=retrieval_adapter.adapter_key,
            allowed_domains_applied=allowed_domains_applied,
            default_trusted_domain_policy_applied=default_policy_applied,
            raw_candidate_count=len(raw_candidates),
            notes=notes
            + [
                "No Tier 1, Tier 2, or Tier 3 sources survived the trust and domain filters.",
            ],
            inactive_reason="Controlled curated-query retrieval found no credible sources after filtering.",
        )

    ranked_candidates.sort(key=lambda item: item.score, reverse=True)
    selected = _selected_candidates(ranked_candidates=ranked_candidates)
    sources = tuple(_clustered_source_from_ranked(item) for item in selected)
    selected_domains = {source.source_domain for source in sources if source.source_domain}
    has_tier_one_or_two_support = any(
        source.trust_tier in {"tier_1_primary", "tier_2_reputable"}
        for source in sources
    )

    if has_tier_one_or_two_support:
        retrieval_state: agent_schemas.EventStrategyReviewRetrievalState = (
            "successful_retrieval"
        )
        notes.append(
            "Controlled curated-query retrieval found Tier 1 or Tier 2 support for report generation."
        )
    else:
        retrieval_state = "low_confidence_watchlist"
        notes.append(
            "Retrieved sources remain below Tier 1/Tier 2 confidence, so this cluster should stay at watchlist level."
        )

    lead_source = sources[0]
    canonical_title = (
        lead_source.title
        or f"Curated query retrieval: {query_input.query}"
    )
    canonical_summary = (
        f"Controlled curated-query retrieval gathered {len(sources)} source(s)"
        f" across {len(selected_domains)} independent domain(s) for"
        f" '{query_input.query}'."
    )

    return CuratedRetrievalOutcome(
        execution_status="report_generated",
        retrieval_metadata=agent_schemas.EventStrategyReviewRetrievalMetadata(
            retrieval_state=retrieval_state,
            adapter_key=retrieval_adapter.adapter_key,
            raw_candidate_cap=RAW_CANDIDATE_CAP,
            raw_candidate_count=len(raw_candidates),
            fetched_source_cap=FETCHED_SOURCE_CAP,
            fetched_source_count=len(sources),
            independent_source_count=len(selected_domains),
            allowed_domains_applied=allowed_domains_applied,
            default_trusted_domain_policy_applied=default_policy_applied,
            has_tier_one_or_two_support=has_tier_one_or_two_support,
            notes=notes,
        ),
        sources=sources,
        canonical_event_title=canonical_title,
        canonical_summary=canonical_summary,
        retrieval_notes=tuple(notes),
        inactive_reason=None,
    )
