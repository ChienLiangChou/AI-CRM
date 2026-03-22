from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from .public_listing_fetcher import PublicListingFetchedPage


JSON_LD_SCRIPT_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class CanonicalPublicListingRecord:
    source_family: str
    source_url: str
    external_listing_id: str | None
    address: str
    street: str | None
    unit: str | None
    city: str | None
    postal_code: str | None
    neighborhood: str | None
    property_type: str | None
    list_price: float | None
    listing_status: str | None
    bedrooms: int | None
    bathrooms: float | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicListingParseHealth:
    json_ld_script_count: int
    json_ld_object_count: int
    candidate_node_count: int
    usable_record_count: int
    structured_data_present: bool
    completeness_min: int = 0
    completeness_max: int = 0
    completeness_average: float = 0.0
    failure_code: str | None = None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_token(value: str | None) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return normalized or None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _coerce_unit(value: str | None) -> str | None:
    text = _normalize_token(value)
    if text is None:
        return None
    match = re.search(r"^(?:unit|apt|suite|ste|#)\s*([a-z0-9-]+)\b", text)
    if match:
        return match.group(1)
    parts = text.split()
    if (
        len(parts) >= 2
        and len(parts[0]) <= 6
        and any(char.isdigit() for char in parts[0])
        and len(parts[1]) <= 6
        and any(char.isdigit() for char in parts[1])
    ):
        return parts[0]
    return None


def _postal_prefix(value: str | None) -> str | None:
    text = _normalize_token(value)
    if text is None:
        return None
    compact = text.replace(" ", "")
    return compact[:3] if len(compact) >= 3 else compact


def _building_street(value: str | None) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    parts = text.split()
    if (
        len(parts) >= 2
        and len(parts[0]) <= 8
        and any(char.isdigit() for char in parts[0])
        and len(parts[1]) <= 8
        and any(char.isdigit() for char in parts[1])
    ):
        return " ".join(parts[1:])
    return text


def _extract_json_ld_objects(html: str) -> list[Any]:
    objects: list[Any] = []
    for match in JSON_LD_SCRIPT_PATTERN.finditer(html):
        body = match.group("body").strip()
        if not body:
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            objects.extend(parsed)
        else:
            objects.append(parsed)
    return objects


def _iter_candidate_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack: list[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        nodes.append(current)

        for key in ("@graph", "itemListElement"):
            value = current.get(key)
            if isinstance(value, list):
                stack.extend(value)

        item = current.get("item")
        if isinstance(item, dict):
            stack.append(item)
    return nodes


def _extract_identifier(node: dict[str, Any]) -> str | None:
    for key in ("identifier", "sku", "listingId", "mls_number", "mlsNumber"):
        value = node.get(key)
        if isinstance(value, dict):
            candidate = value.get("value") or value.get("@value") or value.get("name")
        else:
            candidate = value
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned
    return None


def _extract_offer(node: dict[str, Any]) -> dict[str, Any] | None:
    offers = node.get("offers")
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
    return None


def _extract_address_parts(node: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    address = node.get("address")
    if isinstance(address, dict):
        street = _clean_text(address.get("streetAddress"))
        city = _clean_text(address.get("addressLocality"))
        postal_code = _clean_text(address.get("postalCode"))
        return street, city, postal_code
    if isinstance(address, str):
        return _clean_text(address), None, None
    return None, None, None


def _extract_source_url(node: dict[str, Any], page_url: str) -> str:
    url_value = _clean_text(node.get("url"))
    if url_value is None:
        return page_url
    return urljoin(page_url, url_value)


def _extract_notes(node: dict[str, Any], page: PublicListingFetchedPage) -> tuple[str, ...]:
    notes = [f"Retrieved from {page.host} public page."]
    if node.get("@type"):
        node_type = node.get("@type")
        if isinstance(node_type, list):
            notes.append(f"Structured types: {', '.join(str(item) for item in node_type)}.")
        else:
            notes.append(f"Structured type: {node_type}.")
    return tuple(notes)


def _extract_property_type(node: dict[str, Any]) -> str | None:
    raw_type = node.get("@type")
    if isinstance(raw_type, list):
        candidates = [str(item).lower() for item in raw_type]
    elif raw_type is None:
        candidates = []
    else:
        candidates = [str(raw_type).lower()]

    text = " ".join(candidates)
    if "apartment" in text or "condo" in text:
        return "condo"
    if "singlefamily" in text or "house" in text:
        return "detached"
    if "townhouse" in text:
        return "townhouse"
    return _clean_text(node.get("propertyType"))


def record_completeness_score(record: CanonicalPublicListingRecord) -> int:
    return sum(
        1
        for present in [
            bool(record.address),
            record.list_price is not None,
            bool(record.property_type),
            bool(record.external_listing_id or record.source_url),
        ]
        if present
    )


def parse_public_listing_page(
    page: PublicListingFetchedPage,
) -> tuple[list[CanonicalPublicListingRecord], PublicListingParseHealth]:
    script_count = len(list(JSON_LD_SCRIPT_PATTERN.finditer(page.html)))
    payloads = _extract_json_ld_objects(page.html)
    records: list[CanonicalPublicListingRecord] = []
    candidate_node_count = 0

    for payload in payloads:
        nodes = _iter_candidate_nodes(payload)
        candidate_node_count += len(nodes)
        for node in nodes:
            source_url = _extract_source_url(node, page.url)
            identifier = _extract_identifier(node)
            street, city, postal_code = _extract_address_parts(node)
            address = _clean_text(" ".join(part for part in [street, city] if part))
            if address is None:
                address = _clean_text(node.get("name")) or _clean_text(node.get("description"))
            if address is None:
                continue

            offer = _extract_offer(node) or {}
            records.append(
                CanonicalPublicListingRecord(
                    source_family="realtor_ca_public",
                    source_url=source_url,
                    external_listing_id=identifier,
                    address=address,
                    street=street,
                    unit=_coerce_unit(street),
                    city=city,
                    postal_code=postal_code,
                    neighborhood=_clean_text(node.get("areaServed"))
                    or _clean_text(node.get("neighborhood")),
                    property_type=_extract_property_type(node),
                    list_price=_coerce_float(offer.get("price") or node.get("price")),
                    listing_status=_clean_text(offer.get("availability") or node.get("availability")),
                    bedrooms=_coerce_int(node.get("numberOfBedrooms") or node.get("bedrooms")),
                    bathrooms=_coerce_float(
                        node.get("numberOfBathroomsTotal") or node.get("bathrooms")
                    ),
                    notes=_extract_notes(node, page),
                )
            )

    completeness_scores = [record_completeness_score(item) for item in records]
    failure_code = None
    if script_count == 0:
        failure_code = "public_structured_data_missing"
    elif not payloads or candidate_node_count == 0:
        failure_code = "public_structured_payload_empty"
    elif not records:
        failure_code = "public_parse_drift"

    parse_health = PublicListingParseHealth(
        json_ld_script_count=script_count,
        json_ld_object_count=len(payloads),
        candidate_node_count=candidate_node_count,
        usable_record_count=len(records),
        structured_data_present=script_count > 0,
        completeness_min=min(completeness_scores) if completeness_scores else 0,
        completeness_max=max(completeness_scores) if completeness_scores else 0,
        completeness_average=(
            sum(completeness_scores) / len(completeness_scores)
            if completeness_scores
            else 0.0
        ),
        failure_code=failure_code,
    )
    return records, parse_health


def parse_health_notes(parse_health: PublicListingParseHealth) -> list[str]:
    notes = [
        "Parser health: "
        f"JSON-LD scripts={parse_health.json_ld_script_count}, "
        f"objects={parse_health.json_ld_object_count}, "
        f"candidate nodes={parse_health.candidate_node_count}, "
        f"usable records={parse_health.usable_record_count}.",
    ]
    if parse_health.usable_record_count > 0:
        notes.append(
            "Parser completeness: "
            f"{parse_health.completeness_min}-{parse_health.completeness_max}/4 "
            f"(avg {parse_health.completeness_average:.1f}/4)."
        )
    elif parse_health.failure_code:
        notes.append(f"Parser health classified failure as {parse_health.failure_code}.")
    return notes


def normalize_public_listing_records(
    page: PublicListingFetchedPage,
) -> list[CanonicalPublicListingRecord]:
    records, _ = parse_public_listing_page(page)
    return records


def fingerprint_public_listing_record(record: CanonicalPublicListingRecord) -> str:
    if record.external_listing_id:
        return f"external:{record.external_listing_id.lower()}"

    street = _normalize_token(record.street or record.address)
    city = _normalize_token(record.city)
    unit = _normalize_token(record.unit)
    property_type = _normalize_token(record.property_type)
    if street and city:
        return f"address:{street}|{city}|{unit or '-'}|{property_type or '-'}"

    parsed = urlparse(record.source_url)
    return f"url:{parsed.netloc.lower()}{parsed.path}"


def dedupe_public_listing_records(
    records: list[CanonicalPublicListingRecord],
) -> list[CanonicalPublicListingRecord]:
    def richness(item: CanonicalPublicListingRecord) -> int:
        return sum(
            value is not None and value != ""
            for value in [
                item.external_listing_id,
                item.street,
                item.unit,
                item.city,
                item.postal_code,
                item.neighborhood,
                item.property_type,
                item.list_price,
                item.listing_status,
                item.bedrooms,
                item.bathrooms,
            ]
        )

    deduped: dict[str, CanonicalPublicListingRecord] = {}
    for record in records:
        fingerprint = fingerprint_public_listing_record(record)
        existing = deduped.get(fingerprint)
        if existing is None or richness(record) > richness(existing):
            merged_notes = tuple(
                dict.fromkeys((existing.notes if existing else ()) + record.notes)
            )
            deduped[fingerprint] = CanonicalPublicListingRecord(
                source_family=record.source_family,
                source_url=record.source_url,
                external_listing_id=record.external_listing_id or (existing.external_listing_id if existing else None),
                address=record.address,
                street=record.street or (existing.street if existing else None),
                unit=record.unit or (existing.unit if existing else None),
                city=record.city or (existing.city if existing else None),
                postal_code=record.postal_code or (existing.postal_code if existing else None),
                neighborhood=record.neighborhood or (existing.neighborhood if existing else None),
                property_type=record.property_type or (existing.property_type if existing else None),
                list_price=record.list_price or (existing.list_price if existing else None),
                listing_status=record.listing_status or (existing.listing_status if existing else None),
                bedrooms=record.bedrooms or (existing.bedrooms if existing else None),
                bathrooms=record.bathrooms or (existing.bathrooms if existing else None),
                notes=merged_notes,
            )
    return list(deduped.values())


def building_key_for_record(record: CanonicalPublicListingRecord) -> str | None:
    street = _normalize_token(_building_street(record.street) or record.address)
    city = _normalize_token(record.city)
    if street is None or city is None:
        return None
    return f"{street}|{city}"


def postal_prefix_for_record(record: CanonicalPublicListingRecord) -> str | None:
    return _postal_prefix(record.postal_code)
