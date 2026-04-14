"""Bright Data API client for programmatic content acquisition.

Implements AsyncContentFetcher for Facebook and Instagram via the official Bright Data SDK.
Handles trigger/poll/fetch lifecycle with configurable timeouts and error classification.

Exceptions from the SDK are wrapped in domain-specific FetchError subclasses:
- FetchAuthError: Token validation or authentication failures
- FetchTimeoutError: Poll deadline exceeded
- FetchError: Generic API or unexpected errors
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
)
from syft_ingest.core.models import (
    ContentItem,
    SourceType,
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

    Implements the AsyncContentFetcher (@runtime_checkable protocol).
    isinstance(fetcher, AsyncContentFetcher) returns True as long as the object has a `fetch_async` method.
    Takes a FetchRequest with platform (facebook/instagram) and
    URLs, triggers a scrape job via the Bright Data SDK, polls until completion
    or timeout, and returns results.

    Attributes:
        _token: Bright Data API token (from environment or constructor).
    """

    def __init__(self, token: str | None = None):
        """Initialize the fetcher with an API token.

        Args:
            token: Bright Data API token. If not provided, will attempt to read
                   from BRIGHTDATA_API_TOKEN environment variable.

        Raises:
            FetchAuthError: If no token provided and environment variable not set.
        """
        self._token = token or os.getenv("BRIGHTDATA_API_TOKEN")
        if not self._token:
            raise FetchAuthError(
                "No Bright Data API token provided. Set BRIGHTDATA_API_TOKEN "
                "environment variable or pass token= to constructor.",
                platform="bright-data",
            )

    @staticmethod
    def _to_sdk_date(date_str: str | None) -> str | None:
        """Convert YYYY-MM-DD (caller format) to MM-DD-YYYY (BrightData SDK format).

        Returns None if date_str is None. Raises ValueError if format is wrong.
        """
        if date_str is None:
            return None
        try:
            from datetime import datetime as _datetime

            dt = _datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%m-%d-%Y")
        except ValueError:
            raise ValueError(
                f"start_date must be in YYYY-MM-DD format, got: {date_str!r}"
            )

    async def fetch_async(self, request: FetchRequest) -> FetchResult:
        """Trigger/poll/fetch lifecycle using the Bright Data SDK.

        Steps:
        1. Validate platform (facebook/instagram/tiktok supported)
        2. Extract config (timeout, poll_interval)
        3. Create SDK client (async context manager)
        4. Select platform-specific scraper
        5. Trigger scrape for first URL
        6. Poll for completion with timeout
        7. Fetch raw data
        8. Parse response into ContentItem list
        9. Return FetchResult with parsed items

        Args:
            request: FetchRequest with platform, URLs, config.

        Returns:
            FetchResult with parsed items, row count, job ID, and content hashes.

        Raises:
            FetchAuthError: Token validation or auth failure.
            FetchTimeoutError: Poll deadline exceeded or DataNotReadyError.
            FetchEmptyResultError: No items found in API response.
            FetchError: API error or unexpected exception.
        """
        # Extract parameters from request
        platform_name = request.platform.value
        urls = request.urls
        timeout = request.config.get("timeout", 180)
        poll_interval = request.config.get("poll_interval", 5)

        # Convert start_date from caller format (YYYY-MM-DD) to SDK format (MM-DD-YYYY)
        try:
            sdk_start_date = self._to_sdk_date(request.start_date)
        except ValueError as e:
            raise FetchError(
                f"Invalid start_date format: {request.start_date!r}. "
                f"Expected YYYY-MM-DD: {e}",
                platform=platform_name,
            ) from e

        logger.info(
            "Fetching {n} URL(s) for {platform}",
            n=len(urls),
            platform=platform_name,
        )
        if sdk_start_date:
            logger.info(
                "Filtering {platform} posts from {date} onward",
                platform=platform_name,
                date=sdk_start_date,
            )

        # Validate platform (Phase 2 only supports facebook/instagram)
        if platform_name not in ["facebook", "instagram"]:
            raise FetchError(
                f"Unsupported platform: {platform_name}. "
                "We are only supporting facebook and instagram for now.",
                platform=platform_name,
            )

        logger.debug("Using platform scraper: {}", platform_name)

        try:
            async with BrightDataClient(token=self._token) as client:
                url = urls[0]
                posts_limit = request.config.get("posts_limit")

                if platform_name == "instagram":
                    # Instagram: use search scraper (supports num_of_posts server-side)
                    logger.info(
                        "Searching Instagram posts for {url}",
                        url=url,
                    )
                    search_kwargs: dict[str, Any] = {
                        "url": url,
                        "timeout": timeout,
                    }
                    if posts_limit:
                        search_kwargs["num_of_posts"] = posts_limit
                    if sdk_start_date:
                        search_kwargs["start_date"] = sdk_start_date
                    result = await client.search.instagram.posts(**search_kwargs)
                    raw_data = result.data
                    snapshot_id = result.snapshot_id
                    logger.debug(
                        "Instagram search completed: {snap_id}",
                        snap_id=snapshot_id,
                    )

                elif platform_name == "facebook":
                    # Facebook: use trigger/poll/fetch pattern
                    trigger_method = client.scrape.facebook.posts_by_profile_trigger
                    logger.info(
                        "Triggering facebook scrape for {url}",
                        url=url,
                    )
                    trigger_kwargs: dict[str, Any] = {"url": url}
                    if posts_limit:
                        trigger_kwargs["num_of_posts"] = posts_limit
                    if sdk_start_date:
                        trigger_kwargs["start_date"] = sdk_start_date
                    job = await trigger_method(**trigger_kwargs)
                    logger.debug("Scrape job created: {job_id}", job_id=job.snapshot_id)

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

                    raw_data = await job.fetch()
                    snapshot_id = job.snapshot_id
                    logger.debug(
                        "Fetched {bytes} bytes from job", bytes=len(str(raw_data))
                    )

                else:
                    raise FetchError(
                        f"Platform {platform_name} not mapped to scraper",
                        platform=platform_name,
                    )

                # Parse response into ContentItem list
                items = self._parse_response(raw_data, platform_name, request.config)

                if not items:
                    raise FetchEmptyResultError(
                        f"No content items found in {platform_name} response",
                        platform=platform_name,
                    )

                fetched_at = datetime.now(UTC)
                content_hashes = {
                    item.url or item.title: hashlib.sha256(
                        item.title.encode()
                    ).hexdigest()
                    for item in items
                }

                return FetchResult(
                    items=items,
                    rows_fetched=len(items),
                    remote_job_id=snapshot_id,
                    remote_status="ready",
                    fetched_at=fetched_at,
                    content_hashes=content_hashes,
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

    def _parse_response(
        self, raw_data: Any, platform: str, config: dict | None = None
    ) -> list[ContentItem]:
        """Parse raw Bright Data response into ContentItem list.

        Handles platform-specific field extraction and error handling.

        Args:
            raw_data: Raw response from Bright Data API (dict-like).
            platform: Platform name ("instagram" or "facebook").
            config: Optional config dict with `posts_limit` for testing.

        Returns:
            List of ContentItem instances with raw BrightData data in metadata.
            Empty list if response is empty or None.
        """
        if not raw_data:
            return []

        config = config or {}
        items: list[ContentItem] = []

        try:
            if platform == "instagram":
                items = self._parse_instagram_response(raw_data)
            elif platform == "facebook":
                items = self._parse_facebook_response(raw_data)
            else:
                logger.warning("Unknown platform for parsing: {}", platform)
        except Exception as e:
            logger.error("Error parsing {} response: {}", platform, e, exc_info=True)

        # Apply posts_limit if configured (for testing/sampling)
        posts_limit = config.get("posts_limit")
        if posts_limit and posts_limit > 0:
            items = items[:posts_limit]
            logger.info(
                "Limited {platform} items to {limit} (posts_limit config)",
                platform=platform,
                limit=posts_limit,
            )

        logger.info(
            "Parsed {n} items from {platform} response",
            n=len(items),
            platform=platform,
        )
        return items

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        """Parse ISO date string, handling 'Z' suffix."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def _parse_instagram_response(
        self, raw_data: dict[str, Any] | list[dict[str, Any]]
    ) -> list[ContentItem]:
        """Parse Instagram response — 5-field envelope + raw_data passthrough."""
        items: list[ContentItem] = []

        if not isinstance(raw_data, list):
            raw_data = [raw_data] if isinstance(raw_data, dict) else []

        for entry in raw_data:
            if not isinstance(entry, dict):
                continue

            if "posts" in entry and isinstance(entry.get("posts"), list):
                # Legacy profiles_trigger format: flatten nested posts
                username = entry.get("account") or entry.get("username") or "Unknown"
                for post in entry["posts"]:
                    try:
                        items.append(
                            ContentItem(
                                title=str(post.get("id", "")),
                                author=username,
                                text=post.get("caption") or "",
                                url=post.get("url"),
                                source_type=SourceType.INSTAGRAM,
                                published_at=self._parse_date(post.get("datetime")),
                                metadata={
                                    "likes": post.get("likes"),
                                    "comments": post.get("comments"),
                                    "content_type": post.get("content_type"),
                                },
                                raw_data=post,
                            )
                        )
                    except Exception as e:
                        logger.warning("Failed to parse Instagram post: {}", e)
            else:
                # Search scraper format: flat post dict
                try:
                    items.append(
                        ContentItem(
                            title=entry.get("post_id") or entry.get("shortcode") or "",
                            author=entry.get("user_posted") or "",
                            text=entry.get("description") or "",
                            url=entry.get("url") or "",
                            source_type=SourceType.INSTAGRAM,
                            published_at=self._parse_date(entry.get("date_posted")),
                            metadata={
                                "likes": entry.get("likes"),
                                "num_comments": entry.get("num_comments"),
                                "content_type": entry.get("content_type"),
                                "photos": entry.get("photos", []),
                            },
                            raw_data=entry,
                        )
                    )
                except Exception as e:
                    logger.warning("Failed to parse Instagram post: {}", e)

        return items

    def _parse_facebook_response(
        self, raw_data: dict[str, Any] | list[dict[str, Any]]
    ) -> list[ContentItem]:
        """Parse Facebook response — 5-field envelope + raw_data passthrough."""
        items: list[ContentItem] = []

        if isinstance(raw_data, list):
            posts = raw_data
        elif isinstance(raw_data, dict):
            posts = raw_data.get("posts", [])
        else:
            return items

        for post in posts:
            try:
                items.append(
                    ContentItem(
                        title=post.get("post_id") or "",
                        author=post.get("page_name")
                        or post.get("user_username_raw")
                        or "",
                        text=post.get("content") or "",
                        url=post.get("url") or "",
                        source_type=SourceType.FACEBOOK,
                        published_at=self._parse_date(post.get("date_posted")),
                        metadata={
                            "likes": post.get("likes"),
                            "num_comments": post.get("num_comments"),
                            "num_shares": post.get("num_shares"),
                            "post_type": post.get("post_type"),
                            "video_view_count": post.get("video_view_count"),
                        },
                        raw_data=post,
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse Facebook post: {}", e)

        return items
