"""Application setup and initialization.

Handles explicit registration of content fetchers at application startup
to ensure no import-time side effects.
"""

from __future__ import annotations

from loguru import logger

from syft_ingest.core.registry import register_fetcher
from syft_ingest.core.url_router import Platform


def register_fetchers() -> None:
    """Register all available content fetchers.

    Called explicitly at application startup to ensure:
    - No side effects from module imports
    - Clear initialization order
    - Easy testing (tests can skip or mock registration)
    - Failures are explicit and loud at startup, not on import
    """
    try:
        from syft_ingest.sources.youtube import YtDlpFetcher

        register_fetcher(Platform.YOUTUBE, "yt-dlp", YtDlpFetcher())
        logger.debug("Registered YtDlpFetcher for YouTube")
    except Exception as e:
        logger.warning(f"Failed to register YtDlpFetcher: {e}")

    try:
        from syft_ingest.sources.brightdata import BrightDataFetcher

        register_fetcher(Platform.FACEBOOK, "brightdata", BrightDataFetcher())
        register_fetcher(Platform.INSTAGRAM, "brightdata", BrightDataFetcher())
        logger.debug("Registered BrightDataFetcher for Facebook and Instagram")
    except Exception as e:
        logger.warning(f"Failed to register BrightDataFetcher: {e}")

    try:
        from syft_ingest.sources.local import LocalFetcher

        register_fetcher(Platform.LOCAL, "local", LocalFetcher())
        logger.debug("Registered LocalFetcher for local directories")
    except Exception as e:
        logger.warning(f"Failed to register LocalFetcher: {e}")
