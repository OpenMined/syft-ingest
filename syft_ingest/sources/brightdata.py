"""Bright Data API client for programmatic content acquisition.

Implements ContentFetcher for Facebook and Instagram via the official Bright Data SDK.
Handles trigger/poll/fetch lifecycle with configurable timeouts and error classification.

Exceptions from the SDK are wrapped in domain-specific FetchError subclasses:
- FetchAuthError: Token validation or authentication failures
- FetchTimeoutError: Poll deadline exceeded
- FetchError: Generic API or unexpected errors
"""

from __future__ import annotations

import asyncio as asyncio_module

from loguru import logger

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
)

# Import the brightdata SDK
try:
    from brightdata import BrightDataClient
    from brightdata.exceptions import (
        APIError,
        AuthenticationError,
        DataNotReadyError,
        ValidationError,
    )
except ImportError as e:
    raise ImportError(
        "brightdata SDK not installed. Install from .experimentals/sdk-python "
        "or add to dependencies."
    ) from e


class BrightDataFetcher:
    """Strategy fetcher for Facebook and Instagram via Bright Data API.

    Implements the ContentFetcher protocol. Takes a FetchRequest with platform
    (facebook/instagram) and URLs, triggers a scrape job via the Bright Data SDK,
    polls until completion or timeout, and returns results.

    The fetch() method is synchronous (matching the ContentFetcher protocol),
    but internally uses async/await via asyncio.run().

    Attributes:
        _token: Bright Data API token (from environment or constructor).
    """

    def __init__(self, token: str | None = None):
        """Initialize the fetcher with an API token.

        Args:
            token: Bright Data API token. If not provided, will attempt to read
                   from BRIGHTDATA_API_TOKEN environment variable.

        Raises:
            ValueError: If no token provided and environment variable not set.
        """
        import os

        self._token = token or os.getenv("BRIGHTDATA_API_TOKEN")
        if not self._token:
            raise ValueError(
                "No Bright Data API token provided. Set BRIGHTDATA_API_TOKEN "
                "environment variable or pass token= to constructor."
            )

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Synchronous wrapper for async _fetch_async.

        Runs the async method using asyncio.run(). This bridges the
        ContentFetcher protocol (sync) with the SDK's async interface.

        Args:
            request: Fetch request with platform, URLs, and config.

        Returns:
            FetchResult with items, remote_job_id, and status.

        Raises:
            FetchAuthError: Token or authentication failure.
            FetchTimeoutError: Poll deadline exceeded.
            FetchError: Generic API or unexpected error.
        """
        return asyncio_module.run(self._fetch_async(request))

    async def _fetch_async(self, request: FetchRequest) -> FetchResult:
        """Trigger/poll/fetch lifecycle using the Bright Data SDK.

        Steps:
        1. Validate platform (facebook/instagram only in Phase 2)
        2. Extract config (timeout, poll_interval)
        3. Create SDK client (async context manager)
        4. Select platform-specific scraper
        5. Trigger scrape for first URL
        6. Poll for completion with timeout
        7. Fetch raw data
        8. Return FetchResult (items filled in Plan 03)

        Args:
            request: FetchRequest with platform, URLs, config.

        Returns:
            FetchResult with remote_job_id and empty items (for Plan 03).

        Raises:
            FetchAuthError: Token validation or auth failure.
            FetchTimeoutError: Poll deadline exceeded or DataNotReadyError.
            FetchError: API error or unexpected exception.
        """
        # Extract parameters from request
        platform_name = request.platform.value
        urls = request.urls
        timeout = request.config.get("timeout", 180)
        poll_interval = request.config.get("poll_interval", 5)

        logger.info(
            "Fetching {n} URL(s) for {platform}",
            n=len(urls),
            platform=platform_name,
        )

        # Validate platform (Phase 2 only supports facebook/instagram)
        if platform_name not in ["facebook", "instagram"]:
            raise FetchError(
                f"Unsupported platform: {platform_name}. "
                "Phase 2 supports facebook and instagram only.",
                platform=platform_name,
            )

        logger.debug("Using platform scraper: {}", platform_name)

        try:
            async with BrightDataClient(token=self._token) as client:
                # Select scraper and trigger method based on platform
                if platform_name == "instagram":
                    scraper = client.scrape.instagram
                    # Phase 2: profiles only (Phase 3 can add posts vs profiles parsing)
                    trigger_method = scraper.profiles_trigger
                elif platform_name == "facebook":
                    scraper = client.scrape.facebook
                    # Phase 2: posts_by_profile only (Phase 3 can add groups parsing)
                    trigger_method = scraper.posts_by_profile_trigger
                else:
                    # Should not reach here due to earlier validation, but defensive
                    raise FetchError(
                        f"Platform {platform_name} not mapped to scraper",
                        platform=platform_name,
                    )

                # Trigger scrape for first URL only (Phase 4 can add concurrent multi-URL)
                url = urls[0]
                logger.info(
                    "Triggering {platform} scrape for {url}",
                    platform=platform_name,
                    url=url,
                )
                job = await trigger_method(url=url)
                logger.debug("Scrape job created: {job_id}", job_id=job.snapshot_id)

                # Poll for completion with timeout
                logger.info(
                    "Polling job {job_id} with timeout={timeout}s, poll_interval={interval}s",
                    job_id=job.snapshot_id,
                    timeout=timeout,
                    interval=poll_interval,
                )
                await job.wait(
                    timeout=timeout,
                    poll_interval=poll_interval,
                    verbose=False,
                )
                logger.debug("Job {job_id} completed", job_id=job.snapshot_id)

                # Fetch raw data
                raw_data = await job.fetch()
                logger.debug("Fetched {bytes} bytes from job", bytes=len(str(raw_data)))

                # Return FetchResult with remote tracking (items empty for Plan 03)
                return FetchResult(
                    items=[],  # Filled in Plan 03
                    rows_fetched=0,
                    remote_job_id=job.snapshot_id,
                    remote_status="ready",
                )

        except ValidationError as e:
            # Token validation failed
            logger.warning("Token validation failed: {}", e)
            raise FetchAuthError(
                f"Token invalid: {str(e)}", platform=platform_name
            ) from e

        except AuthenticationError as e:
            # Token rejected by API (401/403)
            logger.warning("Authentication failed: {}", e)
            raise FetchAuthError(
                f"Authentication failed: {str(e)}", platform=platform_name
            ) from e

        except TimeoutError as e:
            # job.wait() raised TimeoutError (poll deadline exceeded)
            logger.warning("Poll timeout after {timeout}s", timeout=timeout)
            raise FetchTimeoutError(
                f"Scrape timed out after {timeout}s", platform=platform_name
            ) from e

        except APIError as e:
            # SDK raised APIError (could be auth, server error, etc.)
            status_code = getattr(e, "status_code", None)
            message = getattr(e, "message", None) or str(e)
            logger.warning("API error {status}: {msg}", status=status_code, msg=message)

            # Classify by HTTP status code
            if status_code in (401, 403):
                raise FetchAuthError(
                    f"API auth failed: {str(e)}", platform=platform_name
                ) from e
            else:
                raise FetchError(f"API error: {str(e)}", platform=platform_name) from e

        except DataNotReadyError as e:
            # Job still pending after max retries
            logger.warning("Data not ready after poll deadline: {}", e)
            raise FetchTimeoutError(
                f"Job still pending after {timeout}s", platform=platform_name
            ) from e

        except FetchError:
            # Re-raise our own domain errors unchanged
            raise

        except Exception as e:
            # Unexpected error: wrap in FetchError
            logger.error("Unexpected error during fetch: {}", e, exc_info=True)
            raise FetchError(
                f"Unexpected error: {str(e)}", platform=platform_name
            ) from e
