"""Fetcher registry: maps (platform, extractor) to ContentFetcher instances.

Provides a global registry for extractor-aware fetcher dispatch. Callers
register concrete implementations (Bright Data, yt-dlp, etc.) at import time,
and consumers retrieve them via ``get_fetcher(platform, extractor)``. Runtime
swapping is supported — re-registering the same key replaces the previous
fetcher without changing any consuming code.

Usage::

    from syft_ingest.core.registry import register_fetcher, get_fetcher
    from syft_ingest.core.url_router import Platform

    register_fetcher(Platform.YOUTUBE, "yt-dlp", YtDlpFetcher())
    fetcher = get_fetcher(Platform.YOUTUBE, "yt-dlp")
    result = fetcher.fetch(request)
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from syft_ingest.core.fetcher import AsyncContentFetcher, ContentFetcher, Fetcher
from syft_ingest.core.url_router import Platform


@dataclass(frozen=True)
class FetcherKey:
    platform: Platform
    extractor: str


def _normalize_extractor(extractor: str) -> str:
    normalized = str(extractor or "").strip().lower()
    if not normalized:
        raise ValueError("Extractor must be a non-empty string")
    return normalized


# Module-level registry — starts empty. Implementations register themselves in
# their own modules when imported.
FETCHER_REGISTRY: dict[FetcherKey, Fetcher] = {}


def register_fetcher(
    platform: Platform,
    extractor: str,
    fetcher: Fetcher,
) -> None:
    """Register a fetcher implementation for a platform/extractor pair.

    Args:
        platform: The platform this fetcher handles.
        extractor: The acquisition backend, e.g. ``"brightdata"`` or ``"yt-dlp"``.
        fetcher: An object satisfying the ``ContentFetcher`` or ``AsyncContentFetcher`` Protocol.

    Raises:
        TypeError: If *fetcher* does not satisfy either fetcher Protocol.
    """
    if not isinstance(fetcher, (ContentFetcher, AsyncContentFetcher)):
        raise TypeError(
            f"Expected ContentFetcher or AsyncContentFetcher, got {type(fetcher).__name__}"
        )

    key = FetcherKey(platform=platform, extractor=_normalize_extractor(extractor))
    existing = FETCHER_REGISTRY.get(key)
    if existing is not None:
        logger.warning(
            "Replacing fetcher for {}/{}: {} -> {}",
            platform.value,
            key.extractor,
            type(existing).__name__,
            type(fetcher).__name__,
        )

    FETCHER_REGISTRY[key] = fetcher
    logger.info(
        "Registered fetcher {} for {}/{}",
        type(fetcher).__name__,
        platform.value,
        key.extractor,
    )


def get_fetcher(platform: Platform, extractor: str) -> Fetcher:
    """Return the registered fetcher for *platform* and *extractor*.

    Args:
        platform: The platform to look up.
        extractor: The acquisition backend to look up.

    Returns:
        The ``Fetcher`` (``ContentFetcher`` or ``AsyncContentFetcher``) registered for this key.

    Raises:
        KeyError: If no fetcher has been registered for this platform/extractor.
    """
    key = FetcherKey(platform=platform, extractor=_normalize_extractor(extractor))
    try:
        return FETCHER_REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"No fetcher registered for platform {platform.value!r} "
            f"and extractor {key.extractor!r}. Register one with register_fetcher()."
        ) from None


def reset_registry() -> None:
    """Clear all registered fetchers.

    Intended for test isolation — call in a pytest fixture to ensure each
    test starts with a clean registry.
    """
    FETCHER_REGISTRY.clear()
    logger.debug("Fetcher registry cleared")
