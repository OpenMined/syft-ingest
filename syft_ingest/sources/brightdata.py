"""BrightData API client for programmatic content fetching.

This module provides BrightDataFetcher, a ContentFetcher implementation
that handles authentication and provides a bridge to the Bright Data API.

The implementation follows a sync/async bridge pattern where the public
fetch() method is synchronous (per ContentFetcher contract), but delegates
to async _fetch_async() for actual work.

Authentication is handled via environment variables at initialization time,
following fail-fast principles: missing tokens are caught immediately.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchRequest,
    FetchResult,
)

if TYPE_CHECKING:
    pass


class BrightDataFetcher:
    """ContentFetcher implementation for Bright Data API.

    Fetches social media content (Facebook, Instagram, TikTok) via the
    Bright Data API. Handles credential loading from environment variables
    and provides the ContentFetcher protocol interface.

    Example::

        # Token from environment
        fetcher = BrightDataFetcher()

        # Or explicit token
        fetcher = BrightDataFetcher(token="your-api-token")

        # Raises FetchAuthError if BRIGHTDATA_API_TOKEN not set and no token provided
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialize BrightDataFetcher with authentication.

        Args:
            token: Bright Data API token. If None, loads from
                BRIGHTDATA_API_TOKEN environment variable.

        Raises:
            FetchAuthError: If token is None and BRIGHTDATA_API_TOKEN
                environment variable is not set.
        """
        if token is None:
            token = os.getenv("BRIGHTDATA_API_TOKEN")

        if token is None:
            raise FetchAuthError(
                "BRIGHTDATA_API_TOKEN environment variable not set and no token provided",
                platform="bright-data",
            )

        self._token = token
        masked_token = "***" if self._token else "MISSING"
        logger.debug(f"BrightDataFetcher initialized with token: {masked_token}")

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch content for the given request.

        Delegates to async _fetch_async() via asyncio.run().

        Args:
            request: Platform/extractor-specific acquisition request.

        Returns:
            Structured result containing normalized content plus tracking
            metadata such as remote job IDs and artifact paths.

        Raises:
            FetchAuthError: Credentials missing or rejected.
            FetchTimeoutError: Scrape/poll exceeded timeout.
            FetchEmptyResultError: Scrape succeeded but returned zero items.
        """
        return asyncio.run(self._fetch_async(request))

    async def _fetch_async(self, request: FetchRequest) -> FetchResult:
        """Async implementation of fetch.

        This is where the actual Bright Data API calls will be made.
        For now, it's a stub to establish the sync/async bridge.

        Args:
            request: Platform/extractor-specific acquisition request.

        Returns:
            Structured result containing normalized content plus tracking
            metadata such as remote job IDs and artifact paths.
        """
        raise NotImplementedError("_fetch_async will be implemented in Plan 02")
