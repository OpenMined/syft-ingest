"""URL router: detect platform from creator URLs and dispatch to the right source.

Given a raw URL pasted by a creator, this module:
1. Validates it's a real HTTP(S) URL
2. Identifies which social platform it belongs to
3. Returns routing metadata (platform, acquisition method, normalized URL)
4. Rejects unsupported platforms with a clear error
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class Platform(str, Enum):
    """Social platforms we can ingest content from."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"


class AcquisitionMethod(str, Enum):
    """How content is fetched for a given platform."""

    YT_DLP = "yt-dlp"
    BRIGHT_DATA = "bright_data"


# Maps each platform to its acquisition method.
_PLATFORM_ACQUISITION: dict[Platform, AcquisitionMethod] = {
    Platform.FACEBOOK: AcquisitionMethod.BRIGHT_DATA,
    Platform.INSTAGRAM: AcquisitionMethod.BRIGHT_DATA,
    Platform.YOUTUBE: AcquisitionMethod.YT_DLP,
    Platform.TIKTOK: AcquisitionMethod.BRIGHT_DATA,
}


class RouteResult(BaseModel):
    """Result of resolving a creator URL."""

    platform: Platform
    acquisition_method: AcquisitionMethod
    normalized_url: str = Field(description="Cleaned URL without tracking params")
    original_url: str


class UnsupportedPlatformError(Exception):
    """Raised when a URL belongs to an unsupported platform."""

    def __init__(self, url: str, host: str) -> None:
        self.url = url
        self.host = host
        super().__init__(
            f"Unsupported platform: {host!r}. "
            f"Supported: {', '.join(p.value for p in Platform)}"
        )


class InvalidURLError(Exception):
    """Raised when the input is not a valid HTTP(S) URL."""

    def __init__(self, url: str, reason: str = "not a valid HTTP(S) URL") -> None:
        self.url = url
        super().__init__(f"Invalid URL: {url!r} — {reason}")


# ---------------------------------------------------------------------------
# Host → Platform mapping
# ---------------------------------------------------------------------------

# Each tuple: (compiled regex matching the netloc, Platform)
_HOST_PATTERNS: list[tuple[re.Pattern[str], Platform]] = [
    # Facebook
    (
        re.compile(
            r"^(www\.)?(facebook\.com|fb\.com|fb\.watch|m\.facebook\.com)$", re.I
        ),
        Platform.FACEBOOK,
    ),
    # Instagram
    (re.compile(r"^(www\.)?(instagram\.com|instagr\.am)$", re.I), Platform.INSTAGRAM),
    # YouTube
    (
        re.compile(
            r"^(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com|music\.youtube\.com)$",
            re.I,
        ),
        Platform.YOUTUBE,
    ),
    # TikTok
    (
        re.compile(r"^(www\.)?(tiktok\.com|vm\.tiktok\.com|m\.tiktok\.com)$", re.I),
        Platform.TIKTOK,
    ),
]

# Tracking query params to strip when normalizing.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "igshid",
        "si",
        "feature",
        "ref",
        "ref_src",
        "ref_url",
        "tt_from",
        "is_from_webapp",
        "sender_device",
    }
)


def _normalize_url(url: str, parsed: urlparse) -> str:  # type: ignore[override]
    """Strip tracking parameters and fragments, lowercase the host."""
    from urllib.parse import parse_qs, urlencode, urlunparse

    clean_params = {
        k: v for k, v in parse_qs(parsed.query).items() if k not in _TRACKING_PARAMS
    }
    clean_query = urlencode(clean_params, doseq=True)
    # Strip trailing slashes from path for consistency
    clean_path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            clean_path,
            "",  # params
            clean_query,
            "",  # fragment
        )
    )


def _detect_platform(host: str) -> Platform | None:
    """Match a hostname to a supported platform."""
    for pattern, platform in _HOST_PATTERNS:
        if pattern.match(host):
            return platform
    return None


def resolve_url(url: str) -> RouteResult:
    """Resolve a creator URL to a platform and acquisition method.

    Args:
        url: Raw URL pasted by the creator (e.g. "https://www.youtube.com/@mkbhd")

    Returns:
        RouteResult with platform, method, and normalized URL.

    Raises:
        InvalidURLError: If the input is not a valid HTTP(S) URL.
        UnsupportedPlatformError: If the platform is not supported.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidURLError(
            url if isinstance(url, str) else str(url), "empty or not a string"
        )

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(url, f"scheme {parsed.scheme!r} is not http/https")

    if not parsed.netloc:
        raise InvalidURLError(url, "no host found")

    platform = _detect_platform(parsed.netloc)
    if platform is None:
        raise UnsupportedPlatformError(url, parsed.netloc)

    normalized = _normalize_url(url, parsed)

    return RouteResult(
        platform=platform,
        acquisition_method=_PLATFORM_ACQUISITION[platform],
        normalized_url=normalized,
        original_url=url,
    )


def supported_platforms() -> list[dict[str, str]]:
    """Return a list of supported platforms and their acquisition methods.

    Useful for frontend display (e.g., showing which URL types are accepted).
    """
    return [
        {
            "platform": p.value,
            "acquisition_method": _PLATFORM_ACQUISITION[p].value,
        }
        for p in Platform
    ]


def get_fetcher_for_url(url: str, default_method: str | None = None):
    """Resolve URL to Platform, then dispatch to fetcher registry.

    This bridges the URL router (resolves URL → Platform) with the fetcher
    registry (provides Platform → ContentFetcher mapping). Callers provide
    a raw creator URL, and get back a ready-to-use ContentFetcher instance.

    Flow:
    1. resolve_url(url) → RouteResult with Platform
    2. get_fetcher(platform, default_method) → ContentFetcher instance

    Args:
        url: Creator URL (YouTube, Instagram, Facebook, or web article)
        default_method: Optional fetcher method name (e.g., "yt-dlp", "brightdata")
                       If not provided, uses platform default from _PLATFORM_ACQUISITION

    Returns:
        ContentFetcher instance for the platform

    Raises:
        InvalidURLError: If the URL is not a valid HTTP(S) URL
        UnsupportedPlatformError: If the URL's platform is not supported
        KeyError: If no fetcher is registered for the resolved platform/method
    """
    from syft_ingest.core.fetcher import ContentFetcher
    from syft_ingest.core.registry import get_fetcher

    # Resolve URL to platform
    route_result = resolve_url(url)
    platform = route_result.platform

    # Use provided method or look up default for this platform
    if default_method is None:
        # Map AcquisitionMethod enum to extractor string names
        method_mapping = {
            AcquisitionMethod.YT_DLP: "yt-dlp",
            AcquisitionMethod.BRIGHT_DATA: "brightdata",
        }
        acquisition_method = _PLATFORM_ACQUISITION[platform]
        default_method = method_mapping.get(acquisition_method)

        if not default_method:
            raise ValueError(
                f"No default fetcher method configured for platform {platform.value}"
            )

    # Get the fetcher from the registry
    fetcher = get_fetcher(platform, default_method)

    # Verify it satisfies the ContentFetcher protocol
    if not isinstance(fetcher, ContentFetcher):
        raise TypeError(
            f"Registered fetcher for {platform.value}/{default_method} "
            f"does not satisfy ContentFetcher protocol"
        )

    return fetcher
