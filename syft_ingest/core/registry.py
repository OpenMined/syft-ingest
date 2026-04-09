"""Fetcher registry: maps Platform enum values to ContentFetcher instances.

Provides a global registry for per-platform fetcher dispatch.  Callers register
concrete fetcher implementations (Bright Data, yt-dlp, etc.) at import time,
and consumers retrieve them via ``get_fetcher(platform)``.  Runtime swapping
is supported — re-registering a platform replaces the previous fetcher without
changing any consuming code.

Usage::

    from syft_ingest.core.registry import register_fetcher, get_fetcher
    from syft_ingest.core.url_router import Platform

    register_fetcher(Platform.YOUTUBE, YtDlpFetcher())
    fetcher = get_fetcher(Platform.YOUTUBE)
    items = fetcher.fetch(["https://youtube.com/@creator"])
"""

from __future__ import annotations

from loguru import logger

from syft_ingest.core.fetcher import ContentFetcher
from syft_ingest.core.url_router import Platform

# Module-level registry — starts empty.
# Implementations register themselves in their own modules (Phases 2, 3, 5).
FETCHER_REGISTRY: dict[Platform, ContentFetcher] = {}


def register_fetcher(platform: Platform, fetcher: ContentFetcher) -> None:
    """Register a fetcher implementation for a platform.

    Args:
        platform: The platform this fetcher handles.
        fetcher: An object satisfying the ``ContentFetcher`` Protocol.

    Raises:
        TypeError: If *fetcher* does not satisfy the ``ContentFetcher`` Protocol.
    """
    if not isinstance(fetcher, ContentFetcher):
        raise TypeError(f"Expected ContentFetcher, got {type(fetcher).__name__}")

    existing = FETCHER_REGISTRY.get(platform)
    if existing is not None:
        logger.warning(
            "Replacing fetcher for {}: {} -> {}",
            platform.value,
            type(existing).__name__,
            type(fetcher).__name__,
        )

    FETCHER_REGISTRY[platform] = fetcher
    logger.info(
        "Registered fetcher {} for {}",
        type(fetcher).__name__,
        platform.value,
    )


def get_fetcher(platform: Platform) -> ContentFetcher:
    """Return the registered fetcher for *platform*.

    Args:
        platform: The platform to look up.

    Returns:
        The ``ContentFetcher`` implementation registered for this platform.

    Raises:
        KeyError: If no fetcher has been registered for *platform*.
    """
    try:
        return FETCHER_REGISTRY[platform]
    except KeyError:
        raise KeyError(
            f"No fetcher registered for platform {platform.value!r}. "
            "Register one with register_fetcher()."
        ) from None


def reset_registry() -> None:
    """Clear all registered fetchers.

    Intended for test isolation — call in a pytest fixture to ensure each
    test starts with a clean registry.
    """
    FETCHER_REGISTRY.clear()
    logger.debug("Fetcher registry cleared")
