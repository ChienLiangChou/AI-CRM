from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from .. import models as crm_models
from . import models, schemas as agent_schemas, service


AGENT_TYPE: agent_schemas.AgentType = "listing_alert_recommendation"
MANUAL_PACKET_VERSION = "listing_alert_manual_review_v1"
AUTOMATIC_BATCH_MESSAGE_CAP = 3
MAX_EXTRACTED_CANDIDATES = 10
MAX_SHORTLIST = 3
MAX_DRAFT_OUTPUTS = 1
LISTING_ALERT_DRAFT_APPROVAL_ACTION = "send_listing_alert_recommendation_draft"
ACTIVE_CONTACT_STATUSES = {"active"}
SALE_HINTS = (
    "for sale",
    "sale",
    "listed for sale",
    "list price",
    "purchase",
)
RENT_HINTS = (
    "for lease",
    "lease",
    "rent",
    "rental",
    "/mo",
    "/month",
    "monthly",
)
PROPERTY_TYPE_KEYWORDS = (
    "condo",
    "apartment",
    "townhouse",
    "semi",
    "semi-detached",
    "detached",
    "loft",
    "house",
    "studio",
)
STREET_SUFFIXES = (
    "st",
    "street",
    "ave",
    "avenue",
    "blvd",
    "boulevard",
    "rd",
    "road",
    "dr",
    "drive",
    "cres",
    "crescent",
    "crt",
    "court",
    "terr",
    "terrace",
    "lane",
    "ln",
    "way",
    "trail",
    "trl",
    "place",
    "pl",
    "parkway",
    "pkwy",
)
CLIENT_TYPE_ALIASES = {
    "buyer": "buyer",
    "buyers": "buyer",
    "tenant": "tenant",
    "tenants": "tenant",
    "renter": "tenant",
    "renters": "tenant",
    "seller": "seller",
    "sellers": "seller",
    "investor": "investor",
    "investors": "investor",
    "landlord": "landlord",
    "landlords": "landlord",
}
PROPERTY_TYPE_ALIASES = {
    "condos": "condo",
    "apts": "apartment",
    "apartments": "apartment",
    "townhome": "townhouse",
    "townhomes": "townhouse",
    "town house": "townhouse",
    "semi detached": "semi-detached",
    "semi detached house": "semi-detached",
    "houses": "house",
}


def _model_dump(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
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


def _request_to_dict(raw: Any) -> dict[str, Any]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()
    if not isinstance(raw, dict):
        raise TypeError("listing_alert_request_must_be_dict")
    return raw


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_email(value: Any) -> str | None:
    text = _clean_text(value)
    return text.lower() if text else None


def _normalize_space(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_multiline_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_match_text(value: str | None) -> str:
    text = _normalize_space(value).lower()
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _dedupe_clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    cleaned: list[str] = []
    for item in parsed:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _safe_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _split_loose_text_values(raw: Any) -> list[str]:
    text = _clean_text(raw)
    if text is None:
        return []
    return [part for part in re.split(r"[,;/|\n]+", text) if _clean_text(part)]


def _normalized_string_list(raw: Any) -> list[str]:
    values: list[str]
    if isinstance(raw, list):
        values = [str(item) for item in raw if _clean_text(item)]
    else:
        values = _split_loose_text_values(raw)
    return _dedupe_clean_list(values)


def _normalize_client_type_token(value: str | None) -> str | None:
    token = _normalize_match_text(value)
    if not token:
        return None
    return CLIENT_TYPE_ALIASES.get(token, token)


def _normalize_property_type_token(value: str | None) -> str | None:
    token = _normalize_match_text(value)
    if not token:
        return None
    return PROPERTY_TYPE_ALIASES.get(token, token)


def _contact_preferred_area_tokens(contact: crm_models.Contact) -> set[str]:
    raw = getattr(contact, "preferred_areas", None)
    values = _safe_json_list(raw)
    if not values:
        text = _clean_text(raw)
        if text and not text.startswith(("[", "{")):
            values = _normalized_string_list(text)
    return {
        _normalize_match_text(value)
        for value in values
        if _normalize_match_text(value)
    }


def _contact_property_preferences(
    contact: crm_models.Contact,
) -> dict[str, list[str]]:
    raw = getattr(contact, "property_preferences", None)
    parsed = _safe_json_dict(raw)
    types: set[str] = set()
    for value in _normalized_string_list(parsed.get("types")):
        normalized = _normalize_property_type_token(value)
        if normalized:
            types.add(normalized)
    property_type_value = _clean_text(parsed.get("property_type"))
    if property_type_value:
        normalized = _normalize_property_type_token(property_type_value)
        if normalized:
            types.add(normalized)
    if not types:
        text = _clean_text(raw)
        if text and not text.startswith("{"):
            for value in _normalized_string_list(text):
                normalized = _normalize_property_type_token(value)
                if normalized:
                    types.add(normalized)

    return {
        "types": sorted(types),
        "must_haves": _normalized_string_list(parsed.get("must_haves")),
        "deal_breakers": _normalized_string_list(parsed.get("deal_breakers")),
    }


def _contact_missing_criteria(contact: crm_models.Contact) -> list[str]:
    missing: list[str] = []
    if not _client_type_tokens(contact):
        missing.append("client_type")
    if not _contact_preferred_area_tokens(contact):
        missing.append("preferred_areas")
    if not _contact_property_preferences(contact)["types"]:
        missing.append("property_preferences.types")
    if (
        getattr(contact, "budget_min", None) is None
        and getattr(contact, "budget_max", None) is None
    ):
        missing.append("budget_range")
    return missing


def _dedupe_text_list(values: list[str]) -> list[str]:
    return _dedupe_clean_list(values)


def _build_candidate_contact_diagnostic(
    *,
    contact: crm_models.Contact,
    stage: str,
    score: float | None = None,
    matched_on: list[str] | None = None,
    missing_criteria: list[str] | None = None,
    failed_checks: list[str] | None = None,
    representation_intent: agent_schemas.ListingAlertRepresentationIntent | None = None,
) -> agent_schemas.ListingAlertCandidateContactDiagnostic:
    return agent_schemas.ListingAlertCandidateContactDiagnostic(
        contact_id=contact.id,
        contact_name=contact.name,
        stage=stage,
        score=score,
        matched_on=_dedupe_text_list(matched_on or []),
        missing_criteria=_dedupe_text_list(missing_criteria or []),
        failed_checks=_dedupe_text_list(failed_checks or []),
        representation_intent=representation_intent,
    )


def _aggregate_candidate_contact_ids(
    candidate_contacts: list[agent_schemas.ListingAlertCandidateContactDiagnostic],
) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for candidate in candidate_contacts:
        if candidate.contact_id in seen:
            continue
        seen.add(candidate.contact_id)
        ids.append(candidate.contact_id)
    return ids


def _aggregate_candidate_missing_criteria(
    candidate_contacts: list[agent_schemas.ListingAlertCandidateContactDiagnostic],
) -> list[str]:
    values: list[str] = []
    for candidate in candidate_contacts:
        values.extend(candidate.missing_criteria)
    return _dedupe_text_list(values)


def _aggregate_candidate_failed_checks(
    candidate_contacts: list[agent_schemas.ListingAlertCandidateContactDiagnostic],
) -> list[str]:
    values: list[str] = []
    for candidate in candidate_contacts:
        values.extend(candidate.failed_checks)
    return _dedupe_text_list(values)


def _parse_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kKmM]?)", value)
    if not match:
        return None
    number = match.group(1).replace(",", "")
    try:
        parsed = float(number)
    except ValueError:
        return None
    suffix = match.group(2).lower()
    if suffix == "k":
        parsed *= 1_000
    elif suffix == "m":
        parsed *= 1_000_000
    return round(parsed, 2)


def _parse_optional_float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = re.sub(r"(?s)<\s*style[^>]*>.*?</\s*style\s*>", " ", html)
    text = re.sub(
        r"(?i)<\s*(br|/p|/div|/li|/tr|/table|/h\d)\s*/?\s*>",
        "\n",
        text,
    )
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)<\s*td[^>]*>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _get_message_text(message: agent_schemas.ListingAlertGmailMessageInput) -> str:
    if _clean_text(message.plain_text_body):
        return _normalize_multiline_text(message.plain_text_body)
    stripped_html = _strip_html(message.html_body)
    if stripped_html:
        return stripped_html
    return _normalize_space(message.snippet)


def _extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>()]+", text)


def _candidate_blocks(text: str) -> list[str]:
    if not text:
        return []

    blocks: list[str] = []
    seen: set[str] = set()
    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.strip()
        if not block:
            continue
        key = _normalize_match_text(block)
        if not key or key in seen:
            continue
        seen.add(key)
        blocks.append(block)

    if any(_block_has_listing_signal(b) for b in blocks):
        return blocks

    merged = _merge_sparse_listing_blocks(blocks)
    result_blocks: list[str] = []
    merged_seen: set[str] = set()
    for block in merged:
        key = _normalize_match_text(block)
        if key and key not in merged_seen:
            merged_seen.add(key)
            result_blocks.append(block)
    return result_blocks


def _merge_sparse_listing_blocks(blocks: list[str]) -> list[str]:
    """Merge small adjacent blocks that together describe a single listing.

    REALM HTML emails produce address, beds/baths, price, and MLS ref as
    separate tiny paragraphs.  This walks the block list and greedily
    attaches non-address blocks that follow an address block until the next
    address or large non-listing block appears.
    """
    if not blocks:
        return []

    _LISTING_FRAGMENT_RE = re.compile(
        r"(?i)"
        r"(?:\d+\s*(?:bed|bath|br)\b)"
        r"|(?:\$[\d,]+)"
        r"|(?:#[A-Z]\d{5,})"
        r"|(?:\bmls\b)"
        r"|(?:\bdom\b)"
        r"|(?:\bnew\b)"
        r"|(?:\bdetached|semi|condo|townhouse|loft|house|apartment\b)"
        r"|(?:\bbaczsplit|bungalow|storey\b)"
    )

    merged: list[str] = []
    accumulator: list[str] = []

    def flush():
        if accumulator:
            merged.append("\n".join(accumulator))
            accumulator.clear()

    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        if _extract_address(stripped):
            flush()
            accumulator.append(stripped)
        elif accumulator and (
            _LISTING_FRAGMENT_RE.search(stripped)
            or len(stripped) < 80
        ):
            accumulator.append(stripped)
        else:
            flush()
            merged.append(stripped)

    flush()
    return merged


def _looks_like_address_line(value: str) -> bool:
    line = _normalize_space(value)
    if not line:
        return False
    lowered = line.lower()
    if lowered.startswith("address:"):
        return True
    if not re.search(r"\d", line):
        return False
    if not any(
        re.search(rf"\b{re.escape(suffix)}\b", lowered) for suffix in STREET_SUFFIXES
    ):
        return False
    return bool(
        re.match(r"^(?:#?\d+\s*[-–]\s*)?\d{1,5}[a-zA-Z]?\s+.+", line)
    )


def _extract_address(block: str) -> str | None:
    explicit_match = re.search(
        r"(?im)^address\s*:\s*(?P<address>.+)$",
        block,
    )
    if explicit_match:
        return _normalize_space(explicit_match.group("address"))

    for line in block.splitlines():
        if _looks_like_address_line(line):
            return _normalize_space(line)
    return None


def _extract_listing_ref(block: str, listing_url: str | None, index: int) -> str:
    mls_match = re.search(
        r"(?i)\bmls(?:®)?\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Za-z0-9-]+)",
        block,
    )
    if mls_match:
        return mls_match.group(1)
    realm_ref_match = _REALM_LISTING_REF_RE.search(block)
    if realm_ref_match:
        return realm_ref_match.group(0).lstrip("#")
    if listing_url:
        path = urlsplit(listing_url).path.strip("/")
        if path:
            return path.split("/")[-1][:80]
    address = _extract_address(block)
    if address:
        return re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")[:80]
    return f"candidate-{index}"


def _detect_market_type(text: str) -> agent_schemas.ListingAlertMarketType:
    lowered = text.lower()
    has_rent_hint = any(hint in lowered for hint in RENT_HINTS)
    has_sale_hint = any(hint in lowered for hint in SALE_HINTS)
    if has_rent_hint and not has_sale_hint:
        return "rent"
    if has_sale_hint and not has_rent_hint:
        return "sale"
    if "/mo" in lowered or "for lease" in lowered:
        return "rent"
    return "unknown"


def _extract_property_type(block: str) -> str | None:
    lowered = block.lower()
    for property_type in PROPERTY_TYPE_KEYWORDS:
        if re.search(rf"\b{re.escape(property_type)}\b", lowered):
            return property_type
    return None


def _extract_neighborhood(block: str) -> str | None:
    explicit_match = re.search(
        r"(?im)^(?:area|neighbou?rhood)\s*:\s*(?P<value>.+)$",
        block,
    )
    if explicit_match:
        return _normalize_space(explicit_match.group("value"))
    return None


_REALM_LISTING_REF_RE = re.compile(r"#[A-Z]\d{5,}")
_PRICE_SIGNAL_RE = re.compile(r"\$\s*[\d,]+(?:\.\d+)?\s*[kKmM]?")
_BEDS_BATHS_RE = re.compile(r"(?i)\b\d+\s*(?:bed|beds|br|bath|baths)\b")


def _block_has_listing_signal(block: str) -> bool:
    if not _extract_address(block):
        return False
    return bool(
        _extract_urls(block)
        or _PRICE_SIGNAL_RE.search(block)
        or re.search(r"(?i)\bmls(?:®)?\b", block)
        or _REALM_LISTING_REF_RE.search(block)
        or _BEDS_BATHS_RE.search(block)
    )


def _normalize_listing_block(
    block: str,
    index: int,
) -> agent_schemas.ListingAlertNormalizedListing | None:
    if not _block_has_listing_signal(block):
        return None

    listing_url = _extract_urls(block)[0] if _extract_urls(block) else None
    address = _extract_address(block)
    if not address:
        return None

    price_match = re.search(r"\$\s*[\d,]+(?:\.\d+)?\s*[kKmM]?", block)
    market_type = _detect_market_type(block)
    match_notes: list[str] = []
    if market_type == "unknown":
        match_notes.append("market_type_unclear_from_alert")
    if price_match is None:
        match_notes.append("price_missing_in_alert_block")
    neighborhood = _extract_neighborhood(block)
    if neighborhood is None:
        match_notes.append("neighborhood_missing_in_alert_block")

    listing = agent_schemas.ListingAlertNormalizedListing(
        listing_ref=_extract_listing_ref(block, listing_url, index),
        address=address,
        price=_parse_price(price_match.group(0) if price_match else None),
        market_type=market_type,
        property_type=_extract_property_type(block),
        bedrooms=_parse_optional_float(
            re.search(r"(?i)(\d+(?:\.\d+)?)\s*(?:bed|beds|br)\b", block).group(1)
            if re.search(r"(?i)(\d+(?:\.\d+)?)\s*(?:bed|beds|br)\b", block)
            else None
        ),
        bathrooms=_parse_optional_float(
            re.search(r"(?i)(\d+(?:\.\d+)?)\s*(?:bath|baths)\b", block).group(1)
            if re.search(r"(?i)(\d+(?:\.\d+)?)\s*(?:bath|baths)\b", block)
            else None
        ),
        neighborhood=neighborhood,
        listing_url=listing_url,
        source_excerpt=block[:500],
        match_notes=match_notes,
    )
    return listing


def extract_normalized_listings(
    message: agent_schemas.ListingAlertGmailMessageInput,
) -> list[agent_schemas.ListingAlertNormalizedListing]:
    text = _get_message_text(message)
    listings: list[agent_schemas.ListingAlertNormalizedListing] = []
    seen_keys: set[str] = set()
    for index, block in enumerate(_candidate_blocks(text), start=1):
        listing = _normalize_listing_block(block, index)
        if listing is None:
            continue
        dedupe_key = "|".join(
            [
                _normalize_match_text(listing.address),
                _normalize_match_text(listing.listing_url),
                str(listing.price or ""),
            ]
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        listings.append(listing)
        if len(listings) >= MAX_EXTRACTED_CANDIDATES:
            break
    return listings


def _listing_market_type(
    listings: list[agent_schemas.ListingAlertNormalizedListing],
) -> agent_schemas.ListingAlertMarketType:
    market_types = {listing.market_type for listing in listings if listing.market_type != "unknown"}
    if len(market_types) == 1:
        return next(iter(market_types))
    return "unknown"


def _client_type_tokens(contact: crm_models.Contact) -> set[str]:
    tokens: set[str] = set()
    raw = _clean_text(getattr(contact, "client_type", None))
    if raw is None:
        return tokens
    for token in _split_loose_text_values(raw):
        cleaned = _normalize_client_type_token(token)
        if cleaned:
            tokens.add(cleaned)
    return tokens


def _resolve_contact_intent(
    contact: crm_models.Contact,
    market_type: agent_schemas.ListingAlertMarketType,
    *,
    override_intent: agent_schemas.ListingAlertRepresentationIntent | None = None,
) -> tuple[agent_schemas.ListingAlertRepresentationIntent | None, str | None]:
    if override_intent is not None:
        tokens = _client_type_tokens(contact)
        if override_intent == "buyer_purchase" and "buyer" not in tokens:
            return None, "contact_not_configured_as_buyer"
        if override_intent == "renter_representation" and not (
            "tenant" in tokens or "renter" in tokens
        ):
            return None, "contact_not_configured_as_renter"
        if market_type == "sale" and override_intent != "buyer_purchase":
            return None, "market_type_conflicts_with_contact_intent"
        if market_type == "rent" and override_intent != "renter_representation":
            return None, "market_type_conflicts_with_contact_intent"
        return override_intent, None

    tokens = _client_type_tokens(contact)
    buyer_capable = "buyer" in tokens
    renter_capable = "tenant" in tokens or "renter" in tokens

    if market_type == "sale":
        if buyer_capable:
            return "buyer_purchase", None
        return None, "contact_not_configured_for_sale_alerts"
    if market_type == "rent":
        if renter_capable:
            return "renter_representation", None
        return None, "contact_not_configured_for_rental_alerts"

    if buyer_capable and renter_capable:
        return None, "buyer_vs_renter_intent_ambiguous"
    if buyer_capable:
        return "buyer_purchase", None
    if renter_capable:
        return "renter_representation", None
    return None, "contact_not_configured_for_buyer_or_renter_representation"


def _association_response_for_contact(
    *,
    contact: crm_models.Contact,
    method: agent_schemas.ListingAlertAssociationMethod,
    matched_on: list[str],
    market_type: agent_schemas.ListingAlertMarketType,
    confidence: float,
    override_intent: agent_schemas.ListingAlertRepresentationIntent | None = None,
    failed_checks: list[str] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> agent_schemas.ListingAlertClientAssociationResponse:
    missing_criteria = _contact_missing_criteria(contact)
    diagnostic_payload = {
        "market_type": market_type,
        "match_stage": method,
        **(diagnostics or {}),
    }
    intent, error = _resolve_contact_intent(
        contact,
        market_type,
        override_intent=override_intent,
    )
    if error == "buyer_vs_renter_intent_ambiguous":
        failed = _dedupe_text_list([*(failed_checks or []), error])
        candidate = _build_candidate_contact_diagnostic(
            contact=contact,
            stage=method,
            score=confidence,
            matched_on=matched_on,
            missing_criteria=missing_criteria,
            failed_checks=failed,
        )
        return agent_schemas.ListingAlertClientAssociationResponse(
            status="blocked_ambiguous_intent",
            method="blocked",
            contact_id=contact.id,
            contact_name=contact.name,
            matched_on=matched_on,
            blocked_reason=error,
            candidate_contact_ids=[contact.id],
            diagnostics=diagnostic_payload,
            candidate_contacts=[candidate],
            missing_criteria=missing_criteria,
            failed_checks=failed,
        )
    if error is not None:
        failed = _dedupe_text_list([*(failed_checks or []), error])
        candidate = _build_candidate_contact_diagnostic(
            contact=contact,
            stage=method,
            score=confidence,
            matched_on=matched_on,
            missing_criteria=missing_criteria,
            failed_checks=failed,
        )
        return agent_schemas.ListingAlertClientAssociationResponse(
            status="blocked_intent_mismatch",
            method="blocked",
            contact_id=contact.id,
            contact_name=contact.name,
            matched_on=matched_on,
            blocked_reason=error,
            candidate_contact_ids=[contact.id],
            diagnostics=diagnostic_payload,
            candidate_contacts=[candidate],
            missing_criteria=missing_criteria,
            failed_checks=failed,
        )
    return agent_schemas.ListingAlertClientAssociationResponse(
        status="matched",
        method=method,
        contact_id=contact.id,
        contact_name=contact.name,
        representation_intent=intent,
        confidence=confidence,
        matched_on=matched_on,
        diagnostics=diagnostic_payload,
        missing_criteria=missing_criteria,
        failed_checks=_dedupe_text_list(failed_checks or []),
    )


def _blocked_association(
    status: agent_schemas.ListingAlertAssociationStatus,
    reason: str,
    *,
    candidate_contact_ids: list[int] | None = None,
    diagnostics: dict[str, Any] | None = None,
    candidate_contacts: list[
        agent_schemas.ListingAlertCandidateContactDiagnostic
    ] | None = None,
    missing_criteria: list[str] | None = None,
    failed_checks: list[str] | None = None,
) -> agent_schemas.ListingAlertClientAssociationResponse:
    resolved_candidate_contacts = candidate_contacts or []
    return agent_schemas.ListingAlertClientAssociationResponse(
        status=status,
        method="blocked",
        blocked_reason=reason,
        candidate_contact_ids=(
            candidate_contact_ids
            if candidate_contact_ids is not None
            else _aggregate_candidate_contact_ids(resolved_candidate_contacts)
        ),
        diagnostics=diagnostics or {},
        candidate_contacts=resolved_candidate_contacts,
        missing_criteria=(
            missing_criteria
            if missing_criteria is not None
            else _aggregate_candidate_missing_criteria(resolved_candidate_contacts)
        ),
        failed_checks=(
            failed_checks
            if failed_checks is not None
            else _aggregate_candidate_failed_checks(resolved_candidate_contacts)
        ),
    )


def _active_contacts(db: Session) -> list[crm_models.Contact]:
    return (
        db.query(crm_models.Contact)
        .filter(crm_models.Contact.status.in_(ACTIVE_CONTACT_STATUSES))
        .order_by(crm_models.Contact.id.asc())
        .all()
    )


def _message_recipients(
    message: agent_schemas.ListingAlertGmailMessageInput,
) -> set[str]:
    recipients = {
        normalized
        for normalized in (
            _normalize_email(address)
            for address in [*message.to_addresses, *message.cc_addresses]
        )
        if normalized
    }
    return recipients


def _match_explicit_mapping(
    message: agent_schemas.ListingAlertGmailMessageInput,
    mapping: agent_schemas.ListingAlertExplicitContactMappingInput,
) -> bool:
    recipients = _message_recipients(message)
    if mapping.recipient_address:
        recipient = _normalize_email(mapping.recipient_address)
        if recipient is None or recipient not in recipients:
            return False
    if mapping.sender_address:
        sender = _normalize_email(mapping.sender_address)
        if sender is None or sender != _normalize_email(message.from_address):
            return False
    if mapping.subject_contains:
        subject_contains = _normalize_match_text(mapping.subject_contains)
        subject = _normalize_match_text(message.subject)
        if subject_contains not in subject:
            return False
    if mapping.label_id:
        if mapping.label_id not in message.label_ids:
            return False
    return True


def _find_contact_by_id(
    db: Session,
    contact_id: int,
) -> crm_models.Contact | None:
    return (
        db.query(crm_models.Contact)
        .filter(crm_models.Contact.id == contact_id)
        .first()
    )


def _deterministic_metadata_matches(
    db: Session,
    message: agent_schemas.ListingAlertGmailMessageInput,
) -> list[
    tuple[
        crm_models.Contact,
        list[str],
        agent_schemas.ListingAlertCandidateContactDiagnostic,
    ]
]:
    searchable_fields = [
        message.subject,
        message.snippet,
        message.plain_text_body,
        _strip_html(message.html_body),
    ]
    searchable_text = " ".join(field for field in searchable_fields if field)
    normalized_search = f" {_normalize_match_text(searchable_text)} "
    lower_search_text = searchable_text.lower()
    matches: list[
        tuple[
            crm_models.Contact,
            list[str],
            agent_schemas.ListingAlertCandidateContactDiagnostic,
        ]
    ] = []

    for contact in _active_contacts(db):
        reasons: list[str] = []
        if contact.email:
            email_token = _normalize_email(contact.email)
            addresses = {
                *_message_recipients(message),
                _normalize_email(message.from_address),
            }
            if email_token in addresses:
                reasons.append(f"contact_email:{email_token}")
            elif email_token and email_token in lower_search_text:
                reasons.append(f"contact_email_text:{email_token}")
        for name_value in (contact.name, getattr(contact, "name_zh", None)):
            name_token = _normalize_match_text(name_value)
            if name_token and f" {name_token} " in normalized_search:
                reasons.append(f"contact_name:{name_token}")
        if reasons:
            matches.append(
                (
                    contact,
                    reasons,
                    _build_candidate_contact_diagnostic(
                        contact=contact,
                        stage="deterministic_metadata",
                        score=0.95,
                        matched_on=reasons,
                        missing_criteria=_contact_missing_criteria(contact),
                    ),
                )
            )

    return matches


def _listing_summary(
    listings: list[agent_schemas.ListingAlertNormalizedListing],
) -> dict[str, Any]:
    neighborhoods = [
        listing.neighborhood for listing in listings if _clean_text(listing.neighborhood)
    ]
    property_types = [
        listing.property_type for listing in listings if _clean_text(listing.property_type)
    ]
    prices = [listing.price for listing in listings if listing.price is not None]
    return {
        "market_type": _listing_market_type(listings),
        "neighborhoods": neighborhoods,
        "property_types": property_types,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
    }


def _heuristic_candidate_score(
    contact: crm_models.Contact,
    listings: list[agent_schemas.ListingAlertNormalizedListing],
) -> dict[str, Any]:
    summary = _listing_summary(listings)
    market_type = summary["market_type"]
    missing_criteria = _contact_missing_criteria(contact)
    failed_checks: list[str] = []
    intent, intent_error = _resolve_contact_intent(contact, market_type)
    if intent_error is not None:
        failed_checks.append(intent_error)
        return {
            "contact": contact,
            "score": 0.0,
            "matched_on": [],
            "representation_intent": None,
            "intent_error": intent_error,
            "missing_criteria": missing_criteria,
            "failed_checks": failed_checks,
        }

    score = 0.0
    reasons: list[str] = []

    preferred_areas = _contact_preferred_area_tokens(contact)
    listing_area_matches = sorted(
        {
            area
            for area in (
                _normalize_match_text(neighborhood)
                for neighborhood in summary["neighborhoods"]
            )
            if area and area in preferred_areas
        }
    )
    if listing_area_matches:
        score += 2.0 + min(len(listing_area_matches) - 1, 1) * 0.5
        reasons.append(f"preferred_areas:{', '.join(listing_area_matches[:2])}")
    elif preferred_areas and summary["neighborhoods"]:
        failed_checks.append("preferred_areas_no_overlap")

    property_preferences = _contact_property_preferences(contact)
    preferred_types = set(property_preferences["types"])
    listing_types = {
        _normalize_property_type_token(property_type)
        for property_type in summary["property_types"]
        if _normalize_property_type_token(property_type)
    }
    type_matches = sorted(preferred_types & listing_types)
    if type_matches:
        score += 1.0
        reasons.append(f"property_type:{', '.join(type_matches[:2])}")
    elif preferred_types and listing_types:
        failed_checks.append("property_type_no_overlap")

    budget_min = getattr(contact, "budget_min", None)
    budget_max = getattr(contact, "budget_max", None)
    min_price = summary["min_price"]
    max_price = summary["max_price"]
    if min_price is not None and max_price is not None:
        if (
            budget_min is not None
            and budget_max is not None
            and max_price >= budget_min
            and min_price <= budget_max
        ):
            score += 1.5
            reasons.append("budget_overlap")
        elif budget_min is None and budget_max is not None and min_price <= budget_max:
            score += 1.0
            reasons.append("budget_ceiling_fit")
        elif budget_min is not None and budget_max is None and max_price >= budget_min:
            score += 1.0
            reasons.append("budget_floor_fit")
        elif budget_min is not None or budget_max is not None:
            failed_checks.append("budget_out_of_range")

    return {
        "contact": contact,
        "score": score,
        "matched_on": reasons,
        "representation_intent": intent,
        "intent_error": None,
        "missing_criteria": missing_criteria,
        "failed_checks": failed_checks,
    }


def _heuristic_fallback_match(
    db: Session,
    listings: list[agent_schemas.ListingAlertNormalizedListing],
) -> agent_schemas.ListingAlertClientAssociationResponse:
    scored: list[dict[str, Any]] = []
    candidate_diagnostics: list[agent_schemas.ListingAlertCandidateContactDiagnostic] = []
    ambiguous_intent_diagnostics: list[
        agent_schemas.ListingAlertCandidateContactDiagnostic
    ] = []
    for contact in _active_contacts(db):
        evaluation = _heuristic_candidate_score(contact, listings)
        score = float(evaluation["score"])
        reasons = list(evaluation["matched_on"])
        intent = evaluation["representation_intent"]
        error = evaluation["intent_error"]
        missing_criteria = list(evaluation["missing_criteria"])
        failed_checks = list(evaluation["failed_checks"])
        candidate_diagnostic = _build_candidate_contact_diagnostic(
            contact=contact,
            stage="heuristic_fallback",
            score=round(score, 2),
            matched_on=reasons,
            missing_criteria=missing_criteria,
            failed_checks=failed_checks,
            representation_intent=intent,
        )
        candidate_diagnostics.append(candidate_diagnostic)
        if error == "buyer_vs_renter_intent_ambiguous":
            ambiguous_intent_diagnostics.append(candidate_diagnostic)
            continue
        if score <= 0.0 or not reasons or intent is None:
            continue
        scored.append(
            {
                "score": score,
                "contact": contact,
                "matched_on": reasons,
                "representation_intent": intent,
                "candidate_diagnostic": candidate_diagnostic,
            }
        )

    if not scored:
        if ambiguous_intent_diagnostics:
            return _blocked_association(
                "blocked_ambiguous_intent",
                "buyer_vs_renter_intent_ambiguous",
                diagnostics={
                    "match_stage": "heuristic_fallback",
                    "market_type": _listing_summary(listings)["market_type"],
                    "evaluated_contact_count": len(candidate_diagnostics),
                },
                candidate_contacts=ambiguous_intent_diagnostics,
            )
        return _blocked_association(
            "blocked_no_match",
            "no_safe_contact_match",
            diagnostics={
                "match_stage": "heuristic_fallback",
                "market_type": _listing_summary(listings)["market_type"],
                "evaluated_contact_count": len(candidate_diagnostics),
            },
            candidate_contacts=sorted(
                candidate_diagnostics,
                key=lambda candidate: (-(candidate.score or 0.0), candidate.contact_id),
            )[:3],
        )

    scored.sort(key=lambda item: (-item["score"], item["contact"].id))
    top_score = float(scored[0]["score"])
    top_contact = scored[0]["contact"]
    top_reasons = scored[0]["matched_on"]
    top_intent = scored[0]["representation_intent"]
    close_competitors = [
        candidate["contact"].id
        for candidate in scored
        if candidate["contact"].id != top_contact.id
        and (top_score - float(candidate["score"])) < 1.5
    ]
    if top_score < 3.0:
        return _blocked_association(
            "blocked_no_match",
            "no_safe_contact_match",
            diagnostics={
                "match_stage": "heuristic_fallback",
                "market_type": _listing_summary(listings)["market_type"],
                "evaluated_contact_count": len(candidate_diagnostics),
                "top_score": round(top_score, 2),
            },
            candidate_contacts=[
                candidate["candidate_diagnostic"] for candidate in scored[:3]
            ],
        )
    if close_competitors:
        return _blocked_association(
            "blocked_ambiguous",
            "multiple_contacts_match_same_listing_profile",
            diagnostics={
                "match_stage": "heuristic_fallback",
                "market_type": _listing_summary(listings)["market_type"],
                "evaluated_contact_count": len(candidate_diagnostics),
                "top_score": round(top_score, 2),
            },
            candidate_contacts=[
                candidate["candidate_diagnostic"]
                for candidate in scored
                if candidate["contact"].id in [top_contact.id, *close_competitors]
            ],
        )

    return agent_schemas.ListingAlertClientAssociationResponse(
        status="matched",
        method="heuristic_fallback",
        contact_id=top_contact.id,
        contact_name=top_contact.name,
        representation_intent=top_intent,
        confidence=round(min(top_score / 5.0, 0.89), 2),
        matched_on=top_reasons,
        diagnostics={
            "market_type": _listing_summary(listings)["market_type"],
            "match_stage": "heuristic_fallback",
            "top_score": round(top_score, 2),
        },
        missing_criteria=_contact_missing_criteria(top_contact),
    )


def resolve_client_association(
    db: Session,
    request: agent_schemas.ListingAlertRunRequest,
    listings: list[agent_schemas.ListingAlertNormalizedListing],
) -> agent_schemas.ListingAlertClientAssociationResponse:
    market_type = _listing_market_type(listings)
    message = request.gmail_alert

    if request.expected_contact_id is not None:
        contact = _find_contact_by_id(db, request.expected_contact_id)
        if contact is None:
            return _blocked_association(
                "blocked_no_match",
                "expected_contact_id_not_found",
                diagnostics={
                    "market_type": market_type,
                    "match_stage": "expected_contact_id",
                    "operator_override": True,
                },
                failed_checks=["expected_contact_id_not_found"],
            )
        return _association_response_for_contact(
            contact=contact,
            method="expected_contact_id",
            matched_on=["expected_contact_id_override"],
            market_type=market_type,
            confidence=1.0,
            diagnostics={"operator_override": True},
        )

    explicit_matches: list[
        tuple[crm_models.Contact, agent_schemas.ListingAlertExplicitContactMappingInput]
    ] = []
    for mapping in request.explicit_contact_mappings:
        if not _match_explicit_mapping(message, mapping):
            continue
        contact = _find_contact_by_id(db, mapping.contact_id)
        if contact is None:
            continue
        explicit_matches.append((contact, mapping))

    if explicit_matches:
        unique_contact_ids = sorted({contact.id for contact, _ in explicit_matches})
        if len(unique_contact_ids) > 1:
            return _blocked_association(
                "blocked_ambiguous",
                "multiple_explicit_mappings_matched",
                diagnostics={
                    "market_type": market_type,
                    "match_stage": "explicit_mapping",
                    "operator_override": True,
                },
                candidate_contacts=[
                    _build_candidate_contact_diagnostic(
                        contact=contact,
                        stage="explicit_mapping",
                        score=0.99,
                        matched_on=["explicit_mapping"],
                        missing_criteria=_contact_missing_criteria(contact),
                    )
                    for contact, _ in explicit_matches
                ],
            )
        contact, mapping = explicit_matches[0]
        matched_on: list[str] = ["explicit_mapping"]
        if mapping.recipient_address:
            matched_on.append(f"recipient:{_normalize_email(mapping.recipient_address)}")
        if mapping.sender_address:
            matched_on.append(f"sender:{_normalize_email(mapping.sender_address)}")
        if mapping.subject_contains:
            matched_on.append(
                f"subject_contains:{_normalize_space(mapping.subject_contains)}"
            )
        if mapping.label_id:
            matched_on.append(f"label_id:{mapping.label_id}")
        return _association_response_for_contact(
            contact=contact,
            method="explicit_mapping",
            matched_on=matched_on,
            market_type=market_type,
            confidence=0.99,
            override_intent=mapping.representation_intent,
            diagnostics={"operator_override": True},
        )

    deterministic_matches = _deterministic_metadata_matches(db, message)
    if deterministic_matches:
        unique_contact_ids = sorted(
            {contact.id for contact, _, _ in deterministic_matches}
        )
        if len(unique_contact_ids) > 1:
            return _blocked_association(
                "blocked_ambiguous",
                "multiple_contacts_matched_alert_metadata",
                diagnostics={
                    "market_type": market_type,
                    "match_stage": "deterministic_metadata",
                },
                candidate_contacts=[
                    diagnostic for _, _, diagnostic in deterministic_matches
                ],
            )
        contact, reasons, _ = deterministic_matches[0]
        return _association_response_for_contact(
            contact=contact,
            method="deterministic_metadata",
            matched_on=reasons,
            market_type=market_type,
            confidence=0.95,
        )

    return _heuristic_fallback_match(db, listings)


def _recent_interaction_summaries(
    db: Session,
    contact_id: int,
) -> list[str]:
    interactions = (
        db.query(crm_models.Interaction)
        .filter(crm_models.Interaction.contact_id == contact_id)
        .order_by(crm_models.Interaction.date.desc())
        .limit(3)
        .all()
    )
    summaries: list[str] = []
    for interaction in interactions:
        note = _clean_text(getattr(interaction, "ai_auto_summary", None)) or _clean_text(
            getattr(interaction, "notes", None)
        )
        if note:
            summaries.append(note[:180])
    return summaries


def _contact_context(
    db: Session,
    association: agent_schemas.ListingAlertClientAssociationResponse,
) -> dict[str, Any]:
    if association.contact_id is None or association.status != "matched":
        return {}
    contact = _find_contact_by_id(db, association.contact_id)
    if contact is None:
        return {}

    return {
        "contact_id": contact.id,
        "contact_name": contact.name,
        "preferred_language": getattr(contact, "preferred_language", None),
        "client_type": getattr(contact, "client_type", None),
        "representation_intent": association.representation_intent,
        "budget_min": getattr(contact, "budget_min", None),
        "budget_max": getattr(contact, "budget_max", None),
        "preferred_areas": _safe_json_list(getattr(contact, "preferred_areas", None)),
        "property_preferences": _safe_json_dict(
            getattr(contact, "property_preferences", None)
        ),
        "recent_interaction_summaries": _recent_interaction_summaries(db, contact.id),
    }


def _format_price_label(value: Any) -> str | None:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return f"${amount:,.0f}"


def _budget_label(budget_min: Any, budget_max: Any) -> str | None:
    min_label = _format_price_label(budget_min)
    max_label = _format_price_label(budget_max)
    if min_label and max_label:
        return f"{min_label}-{max_label}"
    return min_label or max_label


def _normalize_area_token(value: Any) -> str:
    text = _clean_text(value)
    return text.lower() if text else ""


def _extract_property_type_preferences(prefs: dict[str, Any]) -> tuple[str | None, list[str]]:
    primary = _clean_text(prefs.get("property_type"))
    type_list_raw = prefs.get("types")
    types: list[str] = []
    if isinstance(type_list_raw, list):
        for item in type_list_raw:
            text = _clean_text(item)
            if text:
                types.append(text)
    if primary is None and types:
        primary = types[0]
    return primary, types


def _analyze_listing_fit(
    listing: agent_schemas.ListingAlertNormalizedListing,
    contact_context: dict[str, Any],
) -> agent_schemas.ListingAlertFitAnalysis:
    """Deterministic per-listing fit scoring against stored client criteria.

    Mirrors the weight scheme from buyer_match._score_candidate so the
    surfaces produce consistent match-strength labels for operators.
    """
    score = 0.0
    why_it_fits: list[str] = []
    tradeoffs: list[str] = []
    comparisons: list[agent_schemas.ListingAlertFitCriterionComparison] = []

    budget_min = contact_context.get("budget_min")
    budget_max = contact_context.get("budget_max")
    budget_label = _budget_label(budget_min, budget_max)
    listing_price_label = _format_price_label(listing.price)

    if listing.price is not None and (budget_min is not None or budget_max is not None):
        in_range_low = budget_min is None or listing.price >= float(budget_min)
        in_range_high = budget_max is None or listing.price <= float(budget_max)
        if in_range_low and in_range_high:
            score += 2.0
            why_it_fits.append("Priced within the client's stated budget range.")
            verdict: agent_schemas.ListingAlertCriterionVerdict = "match"
        elif budget_max is not None and listing.price > float(budget_max):
            tradeoffs.append("Priced above the stated budget range.")
            verdict = "over_budget"
        else:
            tradeoffs.append("Priced below the stated range, so fit depends on flexibility.")
            verdict = "under_budget"
        comparisons.append(
            agent_schemas.ListingAlertFitCriterionComparison(
                criterion="budget",
                client=budget_label,
                listing=listing_price_label,
                verdict=verdict,
            )
        )
    elif listing.price is None and (budget_min is not None or budget_max is not None):
        tradeoffs.append("Listing price was not extracted, so a budget check is incomplete.")
        comparisons.append(
            agent_schemas.ListingAlertFitCriterionComparison(
                criterion="budget",
                client=budget_label,
                listing=None,
                verdict="unknown",
            )
        )

    preferred_areas_raw = contact_context.get("preferred_areas") or []
    preferred_areas: list[str] = []
    if isinstance(preferred_areas_raw, list):
        for item in preferred_areas_raw:
            cleaned = _clean_text(item)
            if cleaned:
                preferred_areas.append(cleaned)
    preferred_area_tokens = {
        _normalize_area_token(area) for area in preferred_areas if _normalize_area_token(area)
    }
    listing_area_sources = [listing.neighborhood, listing.address]
    listing_area_tokens = {
        _normalize_area_token(src) for src in listing_area_sources if _normalize_area_token(src)
    }
    if preferred_area_tokens:
        match_found = False
        for preferred in preferred_area_tokens:
            if any(preferred in token or token in preferred for token in listing_area_tokens):
                match_found = True
                break
        listing_area_label = _clean_text(listing.neighborhood) or _clean_text(listing.address)
        if match_found:
            score += 1.5
            why_it_fits.append("Matches the client's preferred area list.")
            verdict = "match"
        else:
            tradeoffs.append("Location is outside the stated preferred areas.")
            verdict = "mismatch"
        comparisons.append(
            agent_schemas.ListingAlertFitCriterionComparison(
                criterion="area",
                client=", ".join(preferred_areas) if preferred_areas else None,
                listing=listing_area_label,
                verdict=verdict,
            )
        )

    property_prefs = contact_context.get("property_preferences") or {}
    if not isinstance(property_prefs, dict):
        property_prefs = {}
    preferred_primary_type, preferred_types = _extract_property_type_preferences(property_prefs)
    listing_type = _clean_text(listing.property_type)
    if preferred_primary_type:
        preferred_lower = {t.lower() for t in preferred_types or [preferred_primary_type]}
        if listing_type and listing_type.lower() in preferred_lower:
            score += 1.0
            why_it_fits.append("Matches the preferred property type.")
            verdict = "match"
        elif listing_type:
            tradeoffs.append(
                f"Property type is {listing_type}, not the preferred {preferred_primary_type}."
            )
            verdict = "mismatch"
        else:
            tradeoffs.append("Property type was not extracted, so a type check is incomplete.")
            verdict = "unknown"
        comparisons.append(
            agent_schemas.ListingAlertFitCriterionComparison(
                criterion="property_type",
                client=", ".join(preferred_types) if preferred_types else preferred_primary_type,
                listing=listing_type,
                verdict=verdict,
            )
        )

    bedrooms_min = property_prefs.get("bedrooms_min")
    if bedrooms_min is not None:
        try:
            min_beds = float(bedrooms_min)
        except (TypeError, ValueError):
            min_beds = None
        if min_beds is not None:
            if listing.bedrooms is None:
                tradeoffs.append("Bedroom count was not extracted.")
                verdict = "unknown"
            elif listing.bedrooms >= min_beds:
                score += 1.0
                if listing.bedrooms > min_beds:
                    why_it_fits.append(
                        f"Exceeds the {int(min_beds)}+ bedroom target with {int(listing.bedrooms)} beds."
                    )
                    verdict = "exceeds"
                else:
                    why_it_fits.append(f"Meets the {int(min_beds)}+ bedroom target.")
                    verdict = "match"
            else:
                tradeoffs.append(
                    f"Has {int(listing.bedrooms)} beds, fewer than the {int(min_beds)}+ target."
                )
                verdict = "mismatch"
            comparisons.append(
                agent_schemas.ListingAlertFitCriterionComparison(
                    criterion="bedrooms",
                    client=f"{int(min_beds)}+",
                    listing=(
                        None if listing.bedrooms is None else f"{int(listing.bedrooms)}"
                    ),
                    verdict=verdict,
                )
            )

    bathrooms_min = property_prefs.get("bathrooms_min")
    if bathrooms_min is not None:
        try:
            min_baths = float(bathrooms_min)
        except (TypeError, ValueError):
            min_baths = None
        if min_baths is not None:
            if listing.bathrooms is None:
                tradeoffs.append("Bathroom count was not extracted.")
                verdict = "unknown"
            elif listing.bathrooms >= min_baths:
                score += 0.75
                why_it_fits.append(f"Meets the {int(min_baths)}+ bathroom target.")
                verdict = "match" if listing.bathrooms == min_baths else "exceeds"
            else:
                tradeoffs.append(
                    f"Has {int(listing.bathrooms)} baths, fewer than the {int(min_baths)}+ target."
                )
                verdict = "mismatch"
            comparisons.append(
                agent_schemas.ListingAlertFitCriterionComparison(
                    criterion="bathrooms",
                    client=f"{int(min_baths)}+",
                    listing=(
                        None if listing.bathrooms is None else f"{int(listing.bathrooms)}"
                    ),
                    verdict=verdict,
                )
            )

    if not why_it_fits:
        why_it_fits.append("Review required to decide fit from available context.")

    fit_strength: agent_schemas.ListingAlertFitStrength
    if score >= 4.5:
        fit_strength = "strong"
    elif score >= 2.5:
        fit_strength = "moderate"
    else:
        fit_strength = "limited"

    return agent_schemas.ListingAlertFitAnalysis(
        listing_ref=listing.listing_ref,
        fit_score=round(score, 2),
        fit_strength=fit_strength,
        why_it_fits=why_it_fits[:3],
        tradeoffs=tradeoffs[:3],
        criteria_comparison=comparisons,
    )


def _attach_fit_analysis(
    listings: list[agent_schemas.ListingAlertNormalizedListing],
    contact_context: dict[str, Any],
) -> list[agent_schemas.ListingAlertNormalizedListing]:
    if not contact_context:
        return listings
    updated: list[agent_schemas.ListingAlertNormalizedListing] = []
    for listing in listings:
        analysis = _analyze_listing_fit(listing, contact_context)
        updated.append(listing.model_copy(update={"fit_analysis": analysis}))
    return updated


def _auto_draft_from_analysis(
    contact_context: dict[str, Any],
    shortlist: list[agent_schemas.ListingAlertNormalizedListing],
) -> agent_schemas.ListingAlertAutoReviewDraft | None:
    if not shortlist:
        return None
    contact_name = _clean_text(contact_context.get("contact_name")) or "there"
    top = shortlist[0]
    analysis = top.fit_analysis
    lines: list[str] = [f"Hi {contact_name},", ""]
    if len(shortlist) == 1:
        lines.append(
            "I came across a newly listed property that looked worth flagging for you:"
        )
    else:
        lines.append(
            f"I came across {len(shortlist)} newly listed properties that looked worth flagging for you:"
        )
    lines.append("")
    for idx, listing in enumerate(shortlist, start=1):
        price_text = _format_price_label(listing.price) or "Price TBC"
        type_text = _clean_text(listing.property_type) or "Residential"
        beds = (
            f"{int(listing.bedrooms)} bed" if listing.bedrooms is not None else "beds TBC"
        )
        baths = (
            f"{int(listing.bathrooms)} bath"
            if listing.bathrooms is not None
            else "baths TBC"
        )
        ref_text = listing.listing_ref
        header = f"{idx}. {listing.address}"
        meta = f"   * {price_text} - {type_text} - {beds}, {baths} - MLS#{ref_text}"
        lines.append(header)
        lines.append(meta)
        if listing.fit_analysis and listing.fit_analysis.why_it_fits:
            lines.append(
                f"   * Why it fits: {listing.fit_analysis.why_it_fits[0]}"
            )
        if listing.fit_analysis and listing.fit_analysis.tradeoffs:
            lines.append(
                f"   * Tradeoff to note: {listing.fit_analysis.tradeoffs[0]}"
            )
        lines.append("")
    lines.append("Let me know which ones you'd like to look at more closely, or whether I should keep searching for different fits.")
    lines.append("")
    lines.append("Best regards,")
    lines.append("Kevin Chou")
    lines.append("SKC Realty Team")
    body = "\n".join(lines)
    subject_suffix = (
        top.address if len(shortlist) == 1 else f"{len(shortlist)} properties to review"
    )
    strength = analysis.fit_strength if analysis else "limited"
    prefix = "New Listing Alert" if strength != "limited" else "Worth a Look"
    subject = f"{prefix}: {subject_suffix}"
    return agent_schemas.ListingAlertAutoReviewDraft(
        variant="shortlist_summary",
        subject=subject,
        body=body,
    )


# Criteria whose mismatch is considered a hard disqualifier for auto-shortlist.
# A limited-fit listing with a verdict in this set on a critical criterion should
# never auto-advance to a client-facing draft; operator must review manually.
_HARD_MISMATCH_CRITERIA = {"area", "property_type"}
_HARD_MISMATCH_VERDICTS = {"mismatch", "over_budget"}


def _listing_auto_shortlist_rejection_reason(
    listing: agent_schemas.ListingAlertNormalizedListing,
) -> str | None:
    """Return a reason string if the listing must not be auto-shortlisted.

    The gate only fires when fit is ``limited``. Stronger fits always pass —
    the operator still gets the full tradeoff list per listing.
    """
    analysis = listing.fit_analysis
    if analysis is None:
        return "no_fit_analysis"
    if analysis.fit_strength != "limited":
        return None

    disqualifiers: list[str] = []
    budget_overrun = any(
        cc.criterion == "budget" and cc.verdict == "over_budget"
        for cc in analysis.criteria_comparison
    )
    if budget_overrun:
        disqualifiers.append("over_budget")
    for cc in analysis.criteria_comparison:
        if cc.criterion in _HARD_MISMATCH_CRITERIA and cc.verdict in _HARD_MISMATCH_VERDICTS:
            disqualifiers.append(f"{cc.criterion}_{cc.verdict}")
    if disqualifiers:
        return ",".join(disqualifiers)
    return None


def _auto_generate_review(
    listings: list[agent_schemas.ListingAlertNormalizedListing],
    association: agent_schemas.ListingAlertClientAssociationResponse,
    contact_context: dict[str, Any],
) -> agent_schemas.ListingAlertAutoReviewResult:
    if not listings or not contact_context or association.status != "matched":
        return agent_schemas.ListingAlertAutoReviewResult(
            recommendation_reasoning=(
                "Auto-analysis skipped: contact context or association was incomplete."
            ),
            operator_notes=[
                "Revise the shortlist manually before sending any client-facing content.",
            ],
        )

    contact_name = _clean_text(contact_context.get("contact_name")) or "the client"
    budget_label = _budget_label(
        contact_context.get("budget_min"), contact_context.get("budget_max")
    )
    preferred_areas = contact_context.get("preferred_areas") or []
    area_label = (
        ", ".join(preferred_areas)
        if isinstance(preferred_areas, list) and preferred_areas
        else "their stated areas"
    )

    scored = [listing for listing in listings if listing.fit_analysis is not None]
    scored.sort(
        key=lambda item: item.fit_analysis.fit_score if item.fit_analysis else 0.0,
        reverse=True,
    )

    qualified: list[agent_schemas.ListingAlertNormalizedListing] = []
    rejection_notes: list[str] = []
    for listing in scored:
        reason = _listing_auto_shortlist_rejection_reason(listing)
        if reason is None:
            qualified.append(listing)
        else:
            rejection_notes.append(
                f"Skipped {listing.listing_ref} ({listing.address}): {reason.replace(',', ', ')}"
            )
        if len(qualified) >= MAX_SHORTLIST:
            break

    if not qualified:
        skipped_count = len(scored)
        reasoning_parts = [
            f"Auto-analysis declined to shortlist any of the {skipped_count} extracted listing(s) "
            f"for {contact_name}.",
            f"Client criteria: budget {budget_label or 'not set'}, areas: {area_label}.",
            "Every candidate failed the hard-fit gate (over-budget, wrong area, or wrong property type "
            "on a limited-fit listing), so no client-facing draft was generated.",
        ]
        operator_notes = [
            "Auto-analysis found no qualified listings; manual review required before any client outreach.",
        ]
        if rejection_notes:
            operator_notes.extend(rejection_notes[:MAX_SHORTLIST])
        return agent_schemas.ListingAlertAutoReviewResult(
            shortlist=[],
            tradeoff_notes=[],
            recommendation_reasoning=" ".join(reasoning_parts),
            client_facing_drafts=[],
            operator_notes=operator_notes,
        )

    top_shortlist = qualified
    shortlist_items: list[agent_schemas.ListingAlertAutoReviewShortlistItem] = []
    tradeoff_notes: list[str] = []
    for rank, listing in enumerate(top_shortlist, start=1):
        analysis = listing.fit_analysis
        why = list(analysis.why_it_fits) if analysis else []
        shortlist_items.append(
            agent_schemas.ListingAlertAutoReviewShortlistItem(
                listing_ref=listing.listing_ref,
                rank=rank,
                why_selected=why[:3],
            )
        )
        if analysis:
            for tradeoff in analysis.tradeoffs:
                if tradeoff not in tradeoff_notes:
                    tradeoff_notes.append(tradeoff)

    strengths = [
        s.fit_analysis.fit_strength for s in top_shortlist if s.fit_analysis is not None
    ]
    top_strength = strengths[0] if strengths else "limited"
    reasoning = (
        f"Auto-analysis ranked {len(shortlist_items)} listing(s) against {contact_name}'s stored criteria "
        f"(budget {budget_label or 'not set'}, areas: {area_label}). "
        f"Top match fit-strength: {top_strength}. "
        "Kevin should verify the reasoning and tradeoffs before approving the client-facing draft."
    )

    draft = _auto_draft_from_analysis(contact_context, top_shortlist)
    drafts = [draft] if draft else []

    operator_notes: list[str] = [
        "Auto-analysis pre-filled the shortlist and draft; Kevin approval still required.",
    ]
    if any(
        s.fit_analysis and s.fit_analysis.fit_strength == "limited"
        for s in top_shortlist
    ):
        operator_notes.append(
            "At least one shortlisted listing has limited fit strength; revise or reject if it does not hold up."
        )
    if rejection_notes:
        operator_notes.append(
            "Skipped candidates with hard mismatches:"
        )
        operator_notes.extend(rejection_notes[:MAX_SHORTLIST])

    return agent_schemas.ListingAlertAutoReviewResult(
        shortlist=shortlist_items,
        tradeoff_notes=tradeoff_notes[:5],
        recommendation_reasoning=reasoning,
        client_facing_drafts=drafts,
        operator_notes=operator_notes,
    )


def _comparison_frame(
    listings: list[agent_schemas.ListingAlertNormalizedListing],
    association: agent_schemas.ListingAlertClientAssociationResponse,
) -> dict[str, Any]:
    summary = _listing_summary(listings)
    per_listing_fit: list[dict[str, Any]] = []
    for listing in listings:
        if listing.fit_analysis is None:
            continue
        per_listing_fit.append(
            {
                "listing_ref": listing.listing_ref,
                "address": listing.address,
                "fit_score": listing.fit_analysis.fit_score,
                "fit_strength": listing.fit_analysis.fit_strength,
                "why_it_fits": listing.fit_analysis.why_it_fits,
                "tradeoffs": listing.fit_analysis.tradeoffs,
            }
        )
    return {
        "workflow_goal": "manual_review_packet_preparation",
        "representation_intent": association.representation_intent,
        "market_type_detected": summary["market_type"],
        "candidate_count": len(listings),
        "shortlist_cap": MAX_SHORTLIST,
        "draft_output_cap": MAX_DRAFT_OUTPUTS,
        "per_listing_fit": per_listing_fit,
        "review_questions": [
            "Does the auto-generated shortlist correctly rank the best-fit listings?",
            "Are the auto-extracted tradeoffs accurate and sufficient for client context?",
            "Is the drafted subject and body tone appropriate, or does it need revision?",
        ],
    }


def _draft_constraints() -> list[str]:
    return [
        "Review-only support. Do not auto-send email or create a draft from this packet.",
        "Return at most 3 shortlisted listings.",
        "Return at most 1 buyer/renter-facing draft.",
        "Do not give pricing, offer, negotiation, legal, or compliance advice.",
        "If fit is weak or the alert is ambiguous, recommend no shortlist instead of forcing a draft.",
    ]


def _recommended_prompt_context(
    association: agent_schemas.ListingAlertClientAssociationResponse,
) -> list[str]:
    intent_label = association.representation_intent or "undetermined"
    return [
        "Use this packet inside ChatGPT Pro / GPT-5.4 Pro as an external manual reasoning step.",
        f"Treat the client intent as {intent_label} unless you conclude the packet is too ambiguous to proceed.",
        "Compare the normalized listings against the contact context before selecting any shortlist.",
        "Keep the result review-first and suitable for Kevin approval inside SKC Agent OS later.",
    ]


def _return_contract() -> dict[str, Any]:
    return {
        "reviewed_result_fields": [
            "selected_listing_refs",
            "selection_reasoning_summary",
            "client_facing_subject",
            "client_facing_body",
            "operator_notes",
        ],
        "caps": {
            "selected_listing_refs_max": MAX_SHORTLIST,
            "client_facing_drafts_max": MAX_DRAFT_OUTPUTS,
        },
        "required_guards": [
            "no_auto_send",
            "no_hidden_automation",
            "manual_review_required",
        ],
    }


def build_manual_review_packet_result(
    db: Session,
    request: agent_schemas.ListingAlertRunRequest,
) -> agent_schemas.ListingAlertManualPacketResultResponse:
    listings = extract_normalized_listings(request.gmail_alert)
    if not listings:
        return agent_schemas.ListingAlertManualPacketResultResponse(
            execution_status="blocked_no_candidates",
            association=_blocked_association(
                "blocked_no_match",
                "association_skipped_no_candidate_listings",
            ),
            extracted_listings=[],
            risk_flags=["no_candidate_listings_extracted"],
            operator_notes=[
                "No review packet was prepared because the alert did not yield any safe normalized listing candidates.",
            ],
        )

    association = resolve_client_association(db, request, listings)
    if association.status != "matched":
        execution_status: agent_schemas.ListingAlertExecutionStatus
        if association.status == "blocked_ambiguous":
            execution_status = "blocked_ambiguous_client_match"
        elif association.status == "blocked_ambiguous_intent":
            execution_status = "blocked_ambiguous_intent"
        elif association.status == "blocked_intent_mismatch":
            execution_status = "blocked_intent_mismatch"
        else:
            execution_status = "blocked_no_client_match"
        return agent_schemas.ListingAlertManualPacketResultResponse(
            execution_status=execution_status,
            association=association,
            extracted_listings=listings,
            risk_flags=["manual_client_resolution_required"],
            operator_notes=[
                "No manual review packet was prepared because the client association step did not resolve safely.",
            ],
        )

    contact_context = _contact_context(db, association)
    listings_with_analysis = _attach_fit_analysis(listings, contact_context)
    auto_review = _auto_generate_review(listings_with_analysis, association, contact_context)
    packet = agent_schemas.ListingAlertManualReviewPacket(
        packet_version=MANUAL_PACKET_VERSION,
        manual_reasoning_surface=request.manual_reasoning_surface
        or "chatgpt_pro_gpt_5_4",
        source_message=request.gmail_alert,
        association=association,
        contact_context=contact_context,
        comparison_frame=_comparison_frame(listings_with_analysis, association),
        extracted_listing_count=len(listings_with_analysis),
        extracted_listings=listings_with_analysis,
        shortlist_cap=MAX_SHORTLIST,
        draft_output_cap=MAX_DRAFT_OUTPUTS,
        draft_constraints=_draft_constraints(),
        recommended_prompt_context=_recommended_prompt_context(association),
        return_contract=_return_contract(),
        auto_review=auto_review,
    )
    risk_flags = ["manual_review_required"]
    operator_notes = [
        "Auto-analysis pre-filled a shortlist and draft; Kevin approval still gates any client delivery.",
    ]
    if auto_review is not None and not auto_review.shortlist:
        risk_flags.append("auto_review_no_qualified_matches")
        operator_notes.append(
            "Auto-analysis found no listings that cleared the hard-fit gate; no client-facing draft was auto-generated."
        )
    return agent_schemas.ListingAlertManualPacketResultResponse(
        execution_status="packet_ready",
        association=association,
        extracted_listings=listings_with_analysis,
        manual_review_packet=packet,
        risk_flags=risk_flags,
        operator_notes=operator_notes,
    )


def normalize_run_request(raw: Any) -> agent_schemas.ListingAlertRunRequest:
    if isinstance(raw, agent_schemas.ListingAlertRunRequest):
        return raw
    return agent_schemas.ListingAlertRunRequest(**_request_to_dict(raw))


def normalize_manual_review_submission_request(
    raw: Any,
) -> agent_schemas.ListingAlertManualReviewSubmissionRequest:
    if isinstance(raw, agent_schemas.ListingAlertManualReviewSubmissionRequest):
        return raw
    return agent_schemas.ListingAlertManualReviewSubmissionRequest(**_request_to_dict(raw))


def _extract_source_run_id(raw: Any) -> int:
    if isinstance(raw, agent_schemas.ListingAlertManualReviewSubmissionRequest):
        return raw.source_run_id
    payload = _request_to_dict(raw)
    source_run_id = payload.get("source_run_id")
    if not isinstance(source_run_id, int):
        raise ValueError("source_run_id_required")
    return source_run_id


def _load_manual_packet_result(
    run: models.AgentRun,
) -> agent_schemas.ListingAlertManualPacketResultResponse:
    if not run.result:
        raise ValueError("source_packet_result_missing")
    try:
        parsed = json.loads(run.result)
    except json.JSONDecodeError as exc:
        raise ValueError("source_packet_result_invalid") from exc
    return agent_schemas.ListingAlertManualPacketResultResponse(**parsed)


def _load_source_packet_run(
    db: Session,
    source_run_id: int,
) -> models.AgentRun:
    source_run = (
        db.query(models.AgentRun)
        .join(models.AgentTask)
        .filter(
            models.AgentRun.id == source_run_id,
            models.AgentTask.agent_type == AGENT_TYPE,
        )
        .first()
    )
    if source_run is None:
        raise ValueError("source_packet_run_not_found")
    return source_run


def _validated_shortlist_result(
    packet: agent_schemas.ListingAlertManualReviewPacket,
    submission: agent_schemas.ListingAlertManualReviewSubmissionRequest,
) -> list[agent_schemas.ListingAlertReviewedShortlistResultItem]:
    if len(submission.shortlisted_listings) > MAX_SHORTLIST:
        raise ValueError("shortlist_limit_exceeded")

    listing_lookup = {
        listing.listing_ref: listing for listing in packet.extracted_listings
    }
    seen_refs: set[str] = set()
    seen_ranks: set[int] = set()
    shortlist: list[agent_schemas.ListingAlertReviewedShortlistResultItem] = []

    for item in submission.shortlisted_listings:
        if item.rank <= 0:
            raise ValueError("shortlist_rank_invalid")
        if item.rank in seen_ranks:
            raise ValueError("shortlist_rank_duplicate")
        seen_ranks.add(item.rank)

        listing_ref = _clean_text(item.listing_ref)
        if listing_ref is None:
            raise ValueError("shortlist_listing_ref_missing")
        if listing_ref in seen_refs:
            raise ValueError("shortlist_listing_ref_duplicate")
        seen_refs.add(listing_ref)

        listing = listing_lookup.get(listing_ref)
        if listing is None:
            raise ValueError("shortlist_listing_not_in_packet")

        why_selected = _dedupe_clean_list(item.why_selected)
        if not why_selected:
            raise ValueError("shortlist_why_selected_missing")

        shortlist.append(
            agent_schemas.ListingAlertReviewedShortlistResultItem(
                listing_ref=listing_ref,
                address=listing.address,
                rank=item.rank,
                why_selected=why_selected[:3],
            )
        )

    shortlist.sort(key=lambda item: item.rank)
    return shortlist


def _validated_reviewed_drafts(
    submission: agent_schemas.ListingAlertManualReviewSubmissionRequest,
) -> list[agent_schemas.ListingAlertClientDraftResultItem]:
    if len(submission.client_facing_drafts) > MAX_DRAFT_OUTPUTS:
        raise ValueError("draft_limit_exceeded")

    drafts: list[agent_schemas.ListingAlertClientDraftResultItem] = []
    for draft in submission.client_facing_drafts:
        subject = _clean_text(draft.subject)
        body = _clean_text(draft.body)
        if subject is None:
            raise ValueError("draft_subject_missing")
        if body is None:
            raise ValueError("draft_body_missing")
        drafts.append(
            agent_schemas.ListingAlertClientDraftResultItem(
                variant=_clean_text(draft.variant) or "shortlist_summary",
                subject=subject,
                body=body,
            )
        )
    return drafts


def _build_reviewed_submission_result(
    packet_result: agent_schemas.ListingAlertManualPacketResultResponse,
    submission: agent_schemas.ListingAlertManualReviewSubmissionRequest,
) -> agent_schemas.ListingAlertReviewedSubmissionResultResponse:
    packet = packet_result.manual_review_packet
    if packet is None or packet_result.execution_status != "packet_ready":
        raise ValueError("source_packet_not_reviewable")
    if packet_result.association.status != "matched":
        raise ValueError("source_packet_association_blocked")

    recommendation_reasoning = _clean_text(submission.recommendation_reasoning)
    if recommendation_reasoning is None:
        raise ValueError("recommendation_reasoning_missing")

    shortlisted_listings = _validated_shortlist_result(packet, submission)
    client_facing_drafts = _validated_reviewed_drafts(submission)
    if client_facing_drafts and not shortlisted_listings:
        raise ValueError("draft_requires_shortlist")

    tradeoff_notes = _dedupe_clean_list(submission.tradeoff_notes)
    operator_notes = _dedupe_clean_list(submission.operator_notes)
    review_outcome: agent_schemas.ListingAlertReviewOutcome = (
        "waiting_approval" if client_facing_drafts else "completed_no_draft"
    )

    risk_flags = ["manual_review_submission_recorded"]
    if client_facing_drafts:
        risk_flags.append("client_facing_draft_requires_review")
    else:
        risk_flags.append("no_client_facing_draft_submitted")

    return agent_schemas.ListingAlertReviewedSubmissionResultResponse(
        source_run_id=submission.source_run_id,
        source_task_id=0,
        packet_version=packet.packet_version,
        association=packet_result.association,
        review_outcome=review_outcome,
        shortlisted_listings=shortlisted_listings,
        tradeoff_notes=tradeoff_notes[:5],
        recommendation_reasoning=recommendation_reasoning,
        client_facing_drafts=client_facing_drafts,
        risk_flags=risk_flags,
        operator_notes=operator_notes,
    )


def _build_listing_alert_review_approval_payload(
    result: agent_schemas.ListingAlertReviewedSubmissionResultResponse
    | agent_schemas.ListingAlertAutomaticReviewedResultResponse,
    *,
    review_mode: str,
) -> dict[str, Any]:
    draft = result.client_facing_drafts[0]
    return {
        "contact_id": result.association.contact_id,
        "source_run_id": result.source_run_id,
        "source_task_id": result.source_task_id,
        "representation_intent": result.association.representation_intent,
        "variant": draft.variant,
        "subject": draft.subject,
        "body": draft.body,
        "shortlist_listing_refs": [
            item.listing_ref for item in result.shortlisted_listings
        ],
        "shortlist_addresses": [
            item.address for item in result.shortlisted_listings
        ],
        "tradeoff_notes": result.tradeoff_notes,
        "recommendation_reasoning": result.recommendation_reasoning,
        "review_mode": review_mode,
    }


def _safe_task_payload_json(request: Any) -> str:
    try:
        normalized = normalize_run_request(request)
        return _json_dumps(normalized)
    except Exception:
        if isinstance(request, dict):
            return json.dumps(request, ensure_ascii=False)
        return json.dumps({"invalid_request": True}, ensure_ascii=False)


def _update_task_subject_from_association(
    db: Session,
    task: models.AgentTask,
    association: agent_schemas.ListingAlertClientAssociationResponse,
) -> None:
    if association.contact_id is None:
        return
    task.subject_type = "contact"
    task.subject_id = association.contact_id
    db.commit()
    db.refresh(task)


def _run_listing_alert_packet_once(
    db: Session,
    normalized_request: agent_schemas.ListingAlertRunRequest,
    *,
    run_summary: str,
    planning_action: str,
    extracted_action: str,
    association_resolved_action: str,
    association_blocked_action: str,
    packet_ready_action: str,
    packet_blocked_action: str,
    failure_action: str,
    expected_execution_mode: agent_schemas.ListingAlertExecutionMode | None = None,
    mode_mismatch_error: str = "automatic_mode_not_implemented",
) -> models.AgentRun:
    task = service.create_task(
        db,
        agent_type=AGENT_TYPE,
        payload=_safe_task_payload_json(normalized_request),
    )
    run = service.create_run(
        db,
        task=task,
        summary=run_summary,
    )
    now = datetime.utcnow()
    run = service.update_run_status(db, run, status="planning", started_at=now)
    service.write_audit_log(
        db,
        run=run,
        task=task,
        action=planning_action,
        details=_json_dumps(
            {
                "execution_mode": normalized_request.execution_mode,
                "message_id": normalized_request.gmail_alert.message_id,
                "thread_id": normalized_request.gmail_alert.thread_id,
            }
        ),
    )

    try:
        if (
            expected_execution_mode is not None
            and normalized_request.execution_mode != expected_execution_mode
        ):
            raise ValueError(mode_mismatch_error)

        extracted_listings = extract_normalized_listings(normalized_request.gmail_alert)
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action=extracted_action,
            details=_json_dumps(
                {
                    "message_id": normalized_request.gmail_alert.message_id,
                    "extracted_listing_count": len(extracted_listings),
                    "cap": MAX_EXTRACTED_CANDIDATES,
                }
            ),
        )

        result = build_manual_review_packet_result(db, normalized_request)
        _update_task_subject_from_association(db, task, result.association)

        association_action = association_blocked_action
        if result.association.status == "matched":
            association_action = association_resolved_action
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action=association_action,
            details=_json_dumps(
                {
                    "status": result.association.status,
                    "method": result.association.method,
                    "contact_id": result.association.contact_id,
                    "representation_intent": result.association.representation_intent,
                    "blocked_reason": result.association.blocked_reason,
                    "candidate_contact_ids": result.association.candidate_contact_ids,
                }
            ),
        )

        completion_action = packet_blocked_action
        if result.execution_status == "packet_ready":
            completion_action = packet_ready_action

        run = service.update_run_status(
            db,
            run,
            status="completed",
            result=_json_dumps(result),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="completed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action=completion_action,
            details=_json_dumps(
                {
                    "execution_status": result.execution_status,
                    "manual_packet_ready": result.manual_review_packet is not None,
                }
            ),
        )
        return run
    except Exception as exc:
        run = service.update_run_status(
            db,
            run,
            status="failed",
            error=str(exc),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action=failure_action,
            details=_json_dumps({"error": str(exc)}),
        )
        return run


def run_listing_alert_manual_packet_once(
    db: Session,
    request: Any,
) -> models.AgentRun:
    normalized_request = normalize_run_request(request)
    return _run_listing_alert_packet_once(
        db,
        normalized_request,
        run_summary="Listing alert manual review packet preparation",
        planning_action="listing_alert_manual_packet_planning_started",
        extracted_action="listing_alert_candidates_extracted",
        association_resolved_action="listing_alert_client_association_resolved",
        association_blocked_action="listing_alert_client_association_blocked",
        packet_ready_action="listing_alert_manual_packet_prepared",
        packet_blocked_action="listing_alert_manual_packet_blocked",
        failure_action="listing_alert_manual_packet_failed",
        expected_execution_mode="manual",
        mode_mismatch_error="automatic_mode_not_implemented",
    )


def normalize_automatic_run_request(
    raw: Any,
) -> agent_schemas.ListingAlertAutomaticRunRequest:
    if isinstance(raw, agent_schemas.ListingAlertAutomaticRunRequest):
        normalized = raw
    else:
        normalized = agent_schemas.ListingAlertAutomaticRunRequest(
            **_request_to_dict(raw)
        )
    normalized.max_messages = max(
        1,
        min(normalized.max_messages or AUTOMATIC_BATCH_MESSAGE_CAP, AUTOMATIC_BATCH_MESSAGE_CAP),
    )
    return normalized


def run_listing_alert_automatic_packet_once(
    db: Session,
    request: Any,
) -> models.AgentRun:
    normalized_request = normalize_run_request(request)
    return _run_listing_alert_packet_once(
        db,
        normalized_request,
        run_summary="Listing alert automatic packet preparation",
        planning_action="listing_alert_automatic_packet_planning_started",
        extracted_action="listing_alert_automatic_candidates_extracted",
        association_resolved_action="listing_alert_automatic_client_association_resolved",
        association_blocked_action="listing_alert_automatic_client_association_blocked",
        packet_ready_action="listing_alert_automatic_packet_prepared",
        packet_blocked_action="listing_alert_automatic_packet_blocked",
        failure_action="listing_alert_automatic_packet_failed",
        expected_execution_mode="automatic",
        mode_mismatch_error="automatic_execution_mode_required",
    )


def _automatic_operator_notes(value: str | None) -> str:
    return (
        _clean_text(value)
        or "Automatic Mode v1 bounded batch packet preparation."
    )


def _automatic_review_operator_notes() -> list[str]:
    return [
        "Generated automatically by Listing Alert Recommendation Automatic Mode v1.",
        "Stopped before any client delivery and requires review-first handling.",
    ]


def _automatic_listing_selection_reasons(
    packet: agent_schemas.ListingAlertManualReviewPacket,
    listing: agent_schemas.ListingAlertNormalizedListing,
) -> list[str]:
    reasons: list[str] = []
    neighborhood = _clean_text(listing.neighborhood)
    property_type = _clean_text(listing.property_type)
    if neighborhood:
        reasons.append(f"Matches the current area signal around {neighborhood}.")
    if property_type:
        reasons.append(f"Fits the current {property_type} search profile.")

    budget_min = packet.contact_context.get("budget_min")
    budget_max = packet.contact_context.get("budget_max")
    price = listing.price
    if price is not None:
        if (
            budget_min is not None
            and budget_max is not None
            and budget_min <= price <= budget_max
        ):
            reasons.append("Falls inside the stated budget range.")
        elif budget_max is not None and price <= budget_max:
            reasons.append("Fits under the current budget ceiling.")
        elif budget_min is not None and price >= budget_min:
            reasons.append("Meets the current budget floor.")

    if not reasons:
        reasons.append("Appears worth a closer manual review against the current criteria.")
    return reasons[:3]


def _automatic_shortlist_submission_items(
    packet: agent_schemas.ListingAlertManualReviewPacket,
) -> list[agent_schemas.ListingAlertReviewedShortlistSubmissionItem]:
    shortlisted: list[agent_schemas.ListingAlertReviewedShortlistSubmissionItem] = []
    for rank, listing in enumerate(packet.extracted_listings[:MAX_SHORTLIST], start=1):
        shortlisted.append(
            agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                listing_ref=listing.listing_ref,
                rank=rank,
                why_selected=_automatic_listing_selection_reasons(packet, listing),
            )
        )
    return shortlisted


def _automatic_tradeoff_notes(
    packet: agent_schemas.ListingAlertManualReviewPacket,
) -> list[str]:
    notes: list[str] = []
    if packet.extracted_listing_count > MAX_SHORTLIST:
        notes.append(
            "More matching listings were extracted than the shortlist cap, so only the top review set was carried forward."
        )
    if packet.comparison_frame.get("market_type_detected") == "unknown":
        notes.append(
            "Market type remained ambiguous, so no client-facing draft should be generated automatically."
        )
    return notes[:5]


def _automatic_recommendation_reasoning(
    packet: agent_schemas.ListingAlertManualReviewPacket,
    shortlist_count: int,
) -> str:
    contact_name = _clean_text(packet.contact_context.get("contact_name")) or "the client"
    intent = packet.association.representation_intent or "undetermined_intent"
    market_type = packet.comparison_frame.get("market_type_detected") or "unknown"
    return (
        f"Automatic Mode v1 shortlisted {shortlist_count} listing(s) for {contact_name} "
        f"after a matched {intent} association on a {market_type} alert. "
        "The shortlist stays within the existing review caps and remains approval-gated before any client-facing use."
    )


def _automatic_should_generate_client_draft(
    packet: agent_schemas.ListingAlertManualReviewPacket,
    shortlist_count: int,
) -> bool:
    market_type = packet.comparison_frame.get("market_type_detected")
    return shortlist_count >= 2 and market_type in {"sale", "rent"}


def _automatic_client_draft_submissions(
    packet: agent_schemas.ListingAlertManualReviewPacket,
    shortlist: list[agent_schemas.ListingAlertReviewedShortlistSubmissionItem],
) -> list[agent_schemas.ListingAlertClientDraftSubmissionItem]:
    if not _automatic_should_generate_client_draft(packet, len(shortlist)):
        return []

    contact_name = _clean_text(packet.contact_context.get("contact_name")) or "there"
    shortlist_addresses = [
        listing.address
        for listing in packet.extracted_listings
        if any(item.listing_ref == listing.listing_ref for item in shortlist)
    ]
    body_lines = [
        f"Hi {contact_name},",
        "",
        f"I pulled together {len(shortlist)} listings that look worth reviewing together based on your current criteria.",
    ]
    for address in shortlist_addresses[:MAX_SHORTLIST]:
        body_lines.append(f"- {address}")
    body_lines.extend(
        [
            "",
            "If these are directionally right, Kevin can help compare the tradeoffs and confirm the next best options to review more closely.",
        ]
    )
    return [
        agent_schemas.ListingAlertClientDraftSubmissionItem(
            variant="shortlist_summary",
            subject="Listings worth reviewing together",
            body="\n".join(body_lines).strip(),
        )
    ]


def _build_automatic_reviewed_result(
    *,
    source_run: models.AgentRun,
    source_task: models.AgentTask,
    packet_result: agent_schemas.ListingAlertManualPacketResultResponse,
) -> agent_schemas.ListingAlertAutomaticReviewedResultResponse:
    packet = packet_result.manual_review_packet
    if packet is None or packet_result.execution_status != "packet_ready":
        raise ValueError("source_packet_not_reviewable")
    if packet_result.association.status != "matched":
        raise ValueError("source_packet_association_blocked")

    shortlist_submission = _automatic_shortlist_submission_items(packet)
    draft_submissions = _automatic_client_draft_submissions(packet, shortlist_submission)
    submission = agent_schemas.ListingAlertManualReviewSubmissionRequest(
        source_run_id=source_run.id,
        shortlisted_listings=shortlist_submission,
        tradeoff_notes=_automatic_tradeoff_notes(packet),
        recommendation_reasoning=_automatic_recommendation_reasoning(
            packet,
            len(shortlist_submission),
        ),
        client_facing_drafts=draft_submissions,
        operator_notes=_automatic_review_operator_notes(),
    )
    shortlisted_listings = _validated_shortlist_result(packet, submission)
    client_facing_drafts = _validated_reviewed_drafts(submission)
    review_outcome: agent_schemas.ListingAlertReviewOutcome = (
        "waiting_approval" if client_facing_drafts else "completed_no_draft"
    )
    risk_flags = ["automatic_review_generated"]
    if client_facing_drafts:
        risk_flags.append("client_facing_draft_requires_review")
    else:
        risk_flags.append("no_client_facing_draft_generated")

    return agent_schemas.ListingAlertAutomaticReviewedResultResponse(
        source_run_id=source_run.id,
        source_task_id=source_task.id,
        packet_version=packet.packet_version,
        association=packet_result.association,
        review_outcome=review_outcome,
        shortlisted_listings=shortlisted_listings,
        tradeoff_notes=_dedupe_clean_list(submission.tradeoff_notes)[:5],
        recommendation_reasoning=_clean_text(submission.recommendation_reasoning) or "",
        client_facing_drafts=client_facing_drafts,
        risk_flags=risk_flags,
        operator_notes=_dedupe_clean_list(submission.operator_notes),
        workflow_mode="automatic",
    )


def _persist_listing_alert_review_run(
    db: Session,
    *,
    run: models.AgentRun,
    task: models.AgentTask,
    source_run: models.AgentRun,
    result: agent_schemas.ListingAlertReviewedSubmissionResultResponse
    | agent_schemas.ListingAlertAutomaticReviewedResultResponse,
    approval_created_action: str,
    completed_no_draft_action: str,
    review_mode: str,
) -> models.AgentRun:
    if result.client_facing_drafts:
        approval_payload = _build_listing_alert_review_approval_payload(
            result,
            review_mode=review_mode,
        )
        approval = service.create_approval(
            db,
            run=run,
            action_type=LISTING_ALERT_DRAFT_APPROVAL_ACTION,
            risk_level="high",
            payload=_json_dumps(approval_payload),
        )
        result.client_facing_drafts[0].approval_id = approval.id
        run = service.update_run_status(
            db,
            run,
            status="waiting_approval",
            result=_json_dumps(result),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="waiting_approval")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action=approval_created_action,
            details=_json_dumps(
                {
                    "approval_id": approval.id,
                    "action_type": LISTING_ALERT_DRAFT_APPROVAL_ACTION,
                    "source_run_id": source_run.id,
                }
            ),
        )
        return run

    run = service.update_run_status(
        db,
        run,
        status="completed",
        result=_json_dumps(result),
        finished_at=datetime.utcnow(),
    )
    service.update_task_status(db, task, status="completed")
    service.write_audit_log(
        db,
        run=run,
        task=task,
        action=completed_no_draft_action,
        details=_json_dumps(
            {
                "source_run_id": source_run.id,
                "shortlisted_listing_count": len(result.shortlisted_listings),
            }
        ),
    )
    return run


def _automatic_packet_outcome_from_run(
    *,
    candidate: agent_schemas.ListingAlertGmailCandidateMessage,
    run: models.AgentRun,
) -> agent_schemas.ListingAlertAutomaticMessageOutcomeSummary:
    if not run.result:
        raise ValueError("listing_alert_automatic_packet_result_missing")
    try:
        parsed = json.loads(run.result)
    except json.JSONDecodeError as exc:
        raise ValueError("listing_alert_automatic_packet_result_invalid") from exc
    result = agent_schemas.ListingAlertManualPacketResultResponse(**parsed)
    return agent_schemas.ListingAlertAutomaticMessageOutcomeSummary(
        message_id=candidate.message_id,
        thread_id=candidate.thread_id,
        subject=candidate.subject,
        received_at=candidate.received_at,
        status="blocked",
        reason=result.association.blocked_reason,
        task_id=run.task_id,
        run_id=run.id,
        execution_status=result.execution_status,
        association_status=result.association.status,
        packet_ready=False,
    )


def _automatic_review_outcome_from_runs(
    *,
    candidate: agent_schemas.ListingAlertGmailCandidateMessage,
    packet_run: models.AgentRun,
    review_run: models.AgentRun,
) -> agent_schemas.ListingAlertAutomaticMessageOutcomeSummary:
    if not review_run.result:
        raise ValueError("listing_alert_automatic_review_result_missing")
    try:
        parsed_review = json.loads(review_run.result)
    except json.JSONDecodeError as exc:
        raise ValueError("listing_alert_automatic_review_result_invalid") from exc
    result = agent_schemas.ListingAlertAutomaticReviewedResultResponse(**parsed_review)
    approval_id = None
    if result.client_facing_drafts:
        approval_id = result.client_facing_drafts[0].approval_id
    return agent_schemas.ListingAlertAutomaticMessageOutcomeSummary(
        message_id=candidate.message_id,
        thread_id=candidate.thread_id,
        subject=candidate.subject,
        received_at=candidate.received_at,
        status=result.review_outcome,
        reason=None,
        task_id=packet_run.task_id,
        run_id=packet_run.id,
        review_run_id=review_run.id,
        execution_status="packet_ready",
        association_status=result.association.status,
        review_outcome=result.review_outcome,
        approval_id=approval_id,
        packet_ready=True,
    )


def run_listing_alert_automatic_review_once(
    db: Session,
    *,
    source_run: models.AgentRun,
) -> models.AgentRun:
    task = source_run.task
    if task is None:
        raise ValueError("source_task_missing")

    run = service.create_run(
        db,
        task=task,
        summary="Listing alert automatic review generation",
    )
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(
        db,
        run,
        status="planning",
        plan=_json_dumps(
            {
                "source_run_id": source_run.id,
                "source_task_id": task.id,
                "submission_type": "automatic_review_generation",
            }
        ),
        started_at=datetime.utcnow(),
    )

    try:
        packet_result = _load_manual_packet_result(source_run)
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action="listing_alert_automatic_review_started",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "source_task_id": task.id,
                    "execution_status": packet_result.execution_status,
                }
            ),
        )

        reviewed_result = _build_automatic_reviewed_result(
            source_run=source_run,
            source_task=task,
            packet_result=packet_result,
        )
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action="listing_alert_automatic_shortlist_generated",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "shortlisted_listing_count": len(reviewed_result.shortlisted_listings),
                }
            ),
        )
        if reviewed_result.client_facing_drafts:
            service.write_audit_log(
                db,
                run=run,
                task=task,
                action="listing_alert_automatic_draft_generated",
                details=_json_dumps(
                    {
                        "source_run_id": source_run.id,
                        "draft_count": len(reviewed_result.client_facing_drafts),
                    }
                ),
            )

        return _persist_listing_alert_review_run(
            db,
            run=run,
            task=task,
            source_run=source_run,
            result=reviewed_result,
            approval_created_action="listing_alert_automatic_review_approval_created",
            completed_no_draft_action="listing_alert_automatic_review_completed_no_draft",
            review_mode="automatic_only",
        )
    except Exception as exc:
        run = service.update_run_status(
            db,
            run,
            status="failed",
            error=str(exc),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action="listing_alert_automatic_review_failed",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "error": str(exc),
                }
            ),
        )
        return run


def run_listing_alert_automatic_batch_once(
    db: Session,
    request: Any,
) -> agent_schemas.ListingAlertAutomaticBatchResult:
    from . import listing_alert_recommendation_gmail

    normalized_request = normalize_automatic_run_request(request)
    service.write_audit_log(
        db,
        actor_type="system",
        action="listing_alert_automatic_batch_started",
        details=_json_dumps(
            {
                "max_messages_requested": normalized_request.max_messages,
                "message_cap": AUTOMATIC_BATCH_MESSAGE_CAP,
            }
        ),
    )

    candidate_response = listing_alert_recommendation_gmail.fetch_gmail_candidates(
        db,
        normalized_request.gmail_read_config,
    )
    candidates_to_process = candidate_response.candidates[: normalized_request.max_messages]
    resolved_config = None
    outcomes: list[agent_schemas.ListingAlertAutomaticMessageOutcomeSummary] = []

    for candidate in candidates_to_process:
        if candidate.existing_task_id is not None:
            outcome = agent_schemas.ListingAlertAutomaticMessageOutcomeSummary(
                message_id=candidate.message_id,
                thread_id=candidate.thread_id,
                subject=candidate.subject,
                received_at=candidate.received_at,
                status="duplicate_skipped",
                reason="message_id_already_imported",
                task_id=candidate.existing_task_id,
                run_id=candidate.existing_run_id,
                packet_ready=False,
            )
            outcomes.append(outcome)
            details = _json_dumps(outcome)
            service.write_audit_log(
                db,
                actor_type="system",
                action="listing_alert_automatic_message_outcome_recorded",
                details=details,
            )
            service.write_audit_log(
                db,
                actor_type="system",
                action="listing_alert_automatic_message_duplicate_skipped",
                details=details,
            )
            continue

        if resolved_config is None:
            resolved_config = (
                listing_alert_recommendation_gmail._resolve_gmail_read_config_for_execution(
                    db,
                    normalized_request.gmail_read_config,
                )
            )

        normalized_message = listing_alert_recommendation_gmail.fetch_normalized_gmail_message(
            resolved_config,
            agent_schemas.ListingAlertGmailMessageReference(
                message_id=candidate.message_id,
                thread_id=candidate.thread_id,
            ),
            db=db,
        )
        run = run_listing_alert_automatic_packet_once(
            db,
            agent_schemas.ListingAlertRunRequest(
                execution_mode="automatic",
                gmail_alert=normalized_message,
                expected_contact_id=None,
                explicit_contact_mappings=[],
                operator_notes=_automatic_operator_notes(
                    normalized_request.operator_notes
                ),
            ),
        )
        if run.status == "failed":
            raise ValueError("listing_alert_automatic_packet_run_failed")

        packet_result = _load_manual_packet_result(run)
        if packet_result.execution_status != "packet_ready":
            outcome = _automatic_packet_outcome_from_run(candidate=candidate, run=run)
            outcomes.append(outcome)
            details = _json_dumps(outcome)
            service.write_audit_log(
                db,
                actor_type="system",
                action="listing_alert_automatic_message_outcome_recorded",
                details=details,
            )
            service.write_audit_log(
                db,
                actor_type="system",
                action="listing_alert_automatic_message_blocked",
                details=details,
            )
            continue

        review_run = run_listing_alert_automatic_review_once(db, source_run=run)
        if review_run.status == "failed":
            raise ValueError("listing_alert_automatic_review_run_failed")

        outcome = _automatic_review_outcome_from_runs(
            candidate=candidate,
            packet_run=run,
            review_run=review_run,
        )
        outcomes.append(outcome)
        details = _json_dumps(outcome)
        service.write_audit_log(
            db,
            actor_type="system",
            action="listing_alert_automatic_message_outcome_recorded",
            details=details,
        )
        specific_action = "listing_alert_automatic_message_completed_no_draft"
        if outcome.status == "waiting_approval":
            specific_action = "listing_alert_automatic_message_waiting_approval"
        service.write_audit_log(
            db,
            actor_type="system",
            action=specific_action,
            details=details,
        )

    duplicate_skipped_count = sum(
        1 for item in outcomes if item.status == "duplicate_skipped"
    )
    blocked_count = sum(1 for item in outcomes if item.status == "blocked")
    completed_no_draft_count = sum(
        1 for item in outcomes if item.status == "completed_no_draft"
    )
    waiting_approval_count = sum(
        1 for item in outcomes if item.status == "waiting_approval"
    )

    result = agent_schemas.ListingAlertAutomaticBatchResult(
        gmail_user_id=candidate_response.gmail_user_id,
        query=candidate_response.query,
        matched_message_count=candidate_response.matched_message_count,
        candidate_count=candidate_response.candidate_count,
        message_cap=normalized_request.max_messages,
        processed_message_count=len(outcomes),
        duplicate_skipped_count=duplicate_skipped_count,
        blocked_count=blocked_count,
        completed_no_draft_count=completed_no_draft_count,
        waiting_approval_count=waiting_approval_count,
        outcomes=outcomes,
    )
    service.write_audit_log(
        db,
        actor_type="system",
        action="listing_alert_automatic_batch_completed",
        details=_json_dumps(result),
    )
    return result


def submit_listing_alert_manual_review(
    db: Session,
    request: Any,
) -> models.AgentRun:
    source_run_id = _extract_source_run_id(request)
    source_run = _load_source_packet_run(db, source_run_id)
    task = source_run.task
    if task is None:
        raise ValueError("source_task_missing")

    run = service.create_run(
        db,
        task=task,
        summary="Listing alert manual review submission",
    )
    service.update_task_status(db, task, status="executing")
    run = service.update_run_status(
        db,
        run,
        status="planning",
        plan=_json_dumps(
            {
                "source_run_id": source_run.id,
                "source_task_id": task.id,
                "submission_type": "manual_review_submission",
            }
        ),
        started_at=datetime.utcnow(),
    )

    try:
        submission = normalize_manual_review_submission_request(request)
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action="listing_alert_manual_review_submitted",
            details=_json_dumps(
                {
                    "source_run_id": submission.source_run_id,
                    "shortlisted_listing_count": len(submission.shortlisted_listings),
                    "draft_count": len(submission.client_facing_drafts),
                }
            ),
        )

        packet_result = _load_manual_packet_result(source_run)
        reviewed_result = _build_reviewed_submission_result(packet_result, submission)
        reviewed_result.source_task_id = task.id

        return _persist_listing_alert_review_run(
            db,
            run=run,
            task=task,
            source_run=source_run,
            result=reviewed_result,
            approval_created_action="listing_alert_manual_review_approval_created",
            completed_no_draft_action="listing_alert_manual_review_completed_no_draft",
            review_mode="manual_only",
        )
    except Exception as exc:
        run = service.update_run_status(
            db,
            run,
            status="failed",
            error=str(exc),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=run,
            task=task,
            action="listing_alert_manual_review_validation_failed",
            details=_json_dumps(
                {
                    "source_run_id": source_run.id,
                    "error": str(exc),
                }
            ),
        )
        return run


def normalize_revise_review_request(
    raw: Any,
) -> agent_schemas.ListingAlertReviseReviewRequest:
    if isinstance(raw, agent_schemas.ListingAlertReviseReviewRequest):
        return raw
    return agent_schemas.ListingAlertReviseReviewRequest(**_request_to_dict(raw))


def _load_previous_review_result(
    run: models.AgentRun,
) -> agent_schemas.ListingAlertReviewedSubmissionResultResponse:
    if not run.result:
        raise ValueError("previous_review_result_missing")
    try:
        parsed = json.loads(run.result)
    except json.JSONDecodeError as exc:
        raise ValueError("previous_review_result_invalid") from exc
    return agent_schemas.ListingAlertReviewedSubmissionResultResponse(**parsed)


def _find_source_packet_run_for_review(
    db: Session,
    previous_review: agent_schemas.ListingAlertReviewedSubmissionResultResponse,
) -> models.AgentRun:
    return _load_source_packet_run(db, previous_review.source_run_id)


def revise_listing_alert_review(
    db: Session,
    request: Any,
) -> models.AgentRun:
    """Create a fresh review run by revising a previously rejected submission.

    The rejected approval must belong to a listing alert review run whose
    status is waiting_approval (the run has not yet been finalized). We
    synthesize a new submission using provided overrides or re-apply the
    previous structured data with the operator's revision instructions.
    """
    revision = normalize_revise_review_request(request)
    revision_notes = _clean_text(revision.revision_instructions)
    if revision_notes is None:
        raise ValueError("revision_instructions_missing")

    approval = (
        db.query(models.AgentApproval)
        .filter(models.AgentApproval.id == revision.source_approval_id)
        .first()
    )
    if approval is None:
        raise ValueError("revision_source_approval_not_found")
    if approval.status != "rejected":
        raise ValueError("revision_source_approval_not_rejected")
    previous_run = approval.run
    if previous_run is None:
        raise ValueError("revision_source_run_missing")
    if previous_run.task is None:
        raise ValueError("source_task_missing")
    if previous_run.task.agent_type != AGENT_TYPE:
        raise ValueError("revision_source_run_wrong_agent")

    previous_review_result = _load_previous_review_result(previous_run)
    packet_run = _find_source_packet_run_for_review(db, previous_review_result)
    packet_result = _load_manual_packet_result(packet_run)
    packet = packet_result.manual_review_packet
    if packet is None or packet_result.execution_status != "packet_ready":
        raise ValueError("source_packet_not_reviewable")

    task = previous_run.task

    new_run = service.create_run(
        db,
        task=task,
        summary="Listing alert manual review revision",
    )
    service.update_task_status(db, task, status="executing")
    new_run = service.update_run_status(
        db,
        new_run,
        status="planning",
        plan=_json_dumps(
            {
                "source_run_id": packet_run.id,
                "source_task_id": task.id,
                "rejected_approval_id": approval.id,
                "rejected_run_id": previous_run.id,
                "submission_type": "manual_review_revision",
            }
        ),
        started_at=datetime.utcnow(),
    )

    try:
        shortlist_items: list[agent_schemas.ListingAlertReviewedShortlistSubmissionItem]
        if revision.override_shortlist is not None:
            shortlist_items = list(revision.override_shortlist)
        else:
            shortlist_items = [
                agent_schemas.ListingAlertReviewedShortlistSubmissionItem(
                    listing_ref=item.listing_ref,
                    rank=item.rank,
                    why_selected=list(item.why_selected),
                )
                for item in previous_review_result.shortlisted_listings
            ]

        tradeoff_notes = (
            list(revision.override_tradeoff_notes)
            if revision.override_tradeoff_notes is not None
            else list(previous_review_result.tradeoff_notes)
        )

        recommendation_reasoning_base = (
            _clean_text(revision.override_recommendation_reasoning)
            if revision.override_recommendation_reasoning is not None
            else _clean_text(previous_review_result.recommendation_reasoning)
        ) or ""
        recommendation_reasoning = (
            f"{recommendation_reasoning_base}\n\n[Revision instructions]: {revision_notes}"
            if recommendation_reasoning_base
            else f"[Revision instructions]: {revision_notes}"
        )

        previous_drafts = previous_review_result.client_facing_drafts
        previous_draft = previous_drafts[0] if previous_drafts else None
        draft_subject = (
            _clean_text(revision.override_draft_subject)
            if revision.override_draft_subject is not None
            else (_clean_text(previous_draft.subject) if previous_draft else None)
        )
        draft_body = (
            revision.override_draft_body
            if revision.override_draft_body is not None
            else (previous_draft.body if previous_draft else None)
        )

        client_drafts: list[agent_schemas.ListingAlertClientDraftSubmissionItem] = []
        if draft_subject and draft_body and shortlist_items:
            client_drafts.append(
                agent_schemas.ListingAlertClientDraftSubmissionItem(
                    variant=previous_draft.variant if previous_draft else "shortlist_summary",
                    subject=draft_subject,
                    body=draft_body,
                )
            )

        operator_notes = (
            list(revision.override_operator_notes)
            if revision.override_operator_notes is not None
            else list(previous_review_result.operator_notes)
        )
        operator_notes.insert(
            0,
            f"Revision applied from rejected approval #{approval.id}: {revision_notes}",
        )

        submission = agent_schemas.ListingAlertManualReviewSubmissionRequest(
            source_run_id=packet_run.id,
            shortlisted_listings=shortlist_items,
            tradeoff_notes=tradeoff_notes,
            recommendation_reasoning=recommendation_reasoning,
            client_facing_drafts=client_drafts,
            operator_notes=operator_notes,
        )

        service.write_audit_log(
            db,
            run=new_run,
            task=task,
            action="listing_alert_manual_review_revision_submitted",
            details=_json_dumps(
                {
                    "rejected_approval_id": approval.id,
                    "rejected_run_id": previous_run.id,
                    "source_run_id": packet_run.id,
                    "revision_instructions": revision_notes[:500],
                    "shortlisted_listing_count": len(submission.shortlisted_listings),
                    "draft_count": len(submission.client_facing_drafts),
                }
            ),
        )

        reviewed_result = _build_reviewed_submission_result(packet_result, submission)
        reviewed_result.source_task_id = task.id

        return _persist_listing_alert_review_run(
            db,
            run=new_run,
            task=task,
            source_run=packet_run,
            result=reviewed_result,
            approval_created_action="listing_alert_manual_review_revision_approval_created",
            completed_no_draft_action="listing_alert_manual_review_revision_completed_no_draft",
            review_mode="manual_revision",
        )
    except Exception as exc:
        new_run = service.update_run_status(
            db,
            new_run,
            status="failed",
            error=str(exc),
            finished_at=datetime.utcnow(),
        )
        service.update_task_status(db, task, status="failed")
        service.write_audit_log(
            db,
            run=new_run,
            task=task,
            action="listing_alert_manual_review_revision_failed",
            details=_json_dumps(
                {
                    "rejected_approval_id": approval.id,
                    "error": str(exc),
                }
            ),
        )
        return new_run
