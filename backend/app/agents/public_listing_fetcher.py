from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


ALLOWED_PUBLIC_LISTING_HOSTS = frozenset({"www.realtor.ca", "realtor.ca"})
DEFAULT_FETCH_TIMEOUT_SECONDS = 8.0
MAX_FETCH_BYTES = 1_500_000
USER_AGENT = "SKC-Agent-OS/1.0 public listing retriever"


class PublicListingFetchError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class PublicListingFetchedPage:
    url: str
    host: str
    html: str
    status_code: int
    content_type: str | None = None


def normalize_public_listing_url(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = str(value).strip()
    if not stripped:
        return None

    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"}:
        return None

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_PUBLIC_LISTING_HOSTS:
        return None

    path = parsed.path or "/"
    return urlunparse(
        (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, "")
    )


def fetch_public_listing_page(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
) -> PublicListingFetchedPage:
    normalized_url = normalize_public_listing_url(url)
    if normalized_url is None:
        raise PublicListingFetchError(
            code="public_source_not_allowlisted",
            message="Public listing URL is not allowlisted for retrieval.",
            retryable=False,
        )

    request = Request(
        normalized_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = getattr(response, "status", 200)
            content_type = response.headers.get("Content-Type")
            body = response.read(MAX_FETCH_BYTES + 1)
    except HTTPError as exc:
        raise PublicListingFetchError(
            code="public_fetch_http_error",
            message=f"Public listing fetch failed with HTTP {exc.code}.",
            retryable=500 <= exc.code < 600,
        ) from exc
    except URLError as exc:
        raise PublicListingFetchError(
            code="public_fetch_network_error",
            message="Public listing fetch failed due to a network error.",
            retryable=True,
        ) from exc
    except TimeoutError as exc:
        raise PublicListingFetchError(
            code="public_fetch_timeout",
            message="Public listing fetch timed out.",
            retryable=True,
        ) from exc

    if len(body) > MAX_FETCH_BYTES:
        raise PublicListingFetchError(
            code="public_fetch_too_large",
            message="Public listing response exceeded the allowed size limit.",
            retryable=False,
        )

    if content_type and "html" not in content_type.lower():
        raise PublicListingFetchError(
            code="public_fetch_content_type_unsupported",
            message="Public listing response content type is not supported.",
            retryable=False,
        )

    return PublicListingFetchedPage(
        url=normalized_url,
        host=urlparse(normalized_url).hostname or "",
        html=body.decode("utf-8", errors="replace"),
        status_code=status_code,
        content_type=content_type,
    )
