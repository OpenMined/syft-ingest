"""Bright Data API client for programmatic content acquisition.

Implements AsyncContentFetcher for Facebook and Instagram via the official Bright Data SDK.
Handles trigger/poll/fetch lifecycle with configurable timeouts and error classification.

Exceptions from the SDK are wrapped in domain-specific FetchError subclasses:
- FetchAuthError: Token validation or authentication failures
- FetchTimeoutError: Poll deadline exceeded
- FetchError: Generic API or unexpected errors
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchCancelled,
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
from syft_ingest.sources._meta_utils import (
    derive_title_from_post,
    extract_first_text_field,
    fallback_title_for_empty_post,
)

# Per-platform text-field walk order. Both `title` (truncated to 80 chars)
# and `text` (full body for RAG) walk the same list so a media-only post
# whose `content` is empty but `description` carries the body still produces
# a coherent ContentItem — title from description, body from description.
_FB_TEXT_FIELDS: tuple[str, ...] = (
    "content",
    "attached_post_text",
    "description",
    "caption",
)
_IG_LEGACY_TEXT_FIELDS: tuple[str, ...] = ("caption", "description", "text")
_IG_SEARCH_TEXT_FIELDS: tuple[str, ...] = ("description", "caption", "text")

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


# Matches the underlying `brightdata` SDK's AsyncEngine default (30s). Exposed
# here so callers can depend on a stable name instead of the SDK's internal one.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


def _default_request_timeout() -> int:
    """Resolve the per-request timeout from env, falling back to SDK default.

    Reads BRIGHTDATA_REQUEST_TIMEOUT env var if set to a positive integer.
    Lets operators bump the timeout without code changes when Bright Data's
    /progress endpoint is responding slower than the 30s per-request limit.
    """
    raw = os.getenv("BRIGHTDATA_REQUEST_TIMEOUT", "").strip()
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return DEFAULT_REQUEST_TIMEOUT_SECONDS


_BRIGHTDATA_CANCEL_URL = (
    "https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}/cancel"
)


async def _cancel_snapshot(snapshot_id: str) -> None:
    """Best-effort cancel of a BrightData snapshot.

    POSTs to BrightData's cancel endpoint with the same Bearer token the SDK
    uses (env var ``BRIGHTDATA_API_TOKEN``). Logs failures rather than raising:
    callers see ``FetchCancelled`` as the contract surface, and a 4xx/5xx on
    the cancel API does not change that — the snapshot may continue running
    on BrightData's side, but the fetcher has stopped polling it either way.
    """
    token = os.getenv("BRIGHTDATA_API_TOKEN")
    if not token:
        logger.warning(
            "BRIGHTDATA_API_TOKEN not set; cannot cancel snapshot {sid}",
            sid=snapshot_id,
        )
        return

    url = _BRIGHTDATA_CANCEL_URL.format(snapshot_id=snapshot_id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
        logger.info("Cancelled BrightData snapshot {sid}", sid=snapshot_id)
    except httpx.HTTPError as e:
        logger.warning(
            "Failed to cancel BrightData snapshot {sid}: {err}",
            sid=snapshot_id,
            err=e,
        )


_MAX_TRANSIENT_STATUS_FAILURES = 5
"""Tolerate up to N consecutive status() failures before giving up. A 30-second
network hiccup at poll_interval=15s would be 2 misses; 5 gives us margin without
keeping a doomed fetch alive forever."""


async def _poll_until_ready(
    job: Any,
    *,
    request: FetchRequest,
    timeout: int,
    poll_interval: int,
    platform_name: str,
) -> None:
    """Poll a BrightData ScrapeJob until it reaches the 'ready' state.

    Replaces the SDK's blocking ``job.wait(timeout, poll_interval)`` with an
    explicit loop driven by the SDK's ``job.status(refresh=True)``. The loop
    fires ``request.status_callback`` on every status transition (de-duped,
    not every tick), consults ``request.cancel_callback`` after each status
    read (cancelling the remote snapshot via httpx and raising
    ``FetchCancelled`` if it returns True), and tolerates up to
    ``_MAX_TRANSIENT_STATUS_FAILURES`` consecutive unexpected exceptions
    from ``job.status()`` before giving up — so a brief network outage
    does not kill a long-running fetch.

    Args:
        job: A ``brightdata.scrapers.base.ScrapeJob`` (or any object with
            ``.snapshot_id`` and an async ``.status(refresh=True)`` method).
        request: The active FetchRequest, source of optional callbacks.
        timeout: Total seconds before raising FetchTimeoutError.
        poll_interval: Seconds between status() calls.
        platform_name: Used for FetchError ``platform`` attribution.

    Raises:
        FetchCancelled: ``cancel_callback`` returned True; remote snapshot
            has been signalled to cancel (best-effort).
        FetchError: Snapshot transitioned to ``error``/``failed``, or
            ``job.status()`` raised an unexpected error
            ``_MAX_TRANSIENT_STATUS_FAILURES`` times in a row.
        FetchTimeoutError: Snapshot did not reach ``ready`` before deadline.
    """
    snapshot_id: str = job.snapshot_id
    last_status: str | None = None

    def _emit_status(status: str) -> None:
        """Fire status_callback only on transitions; swallow exceptions."""
        nonlocal last_status
        if status == last_status:
            return
        last_status = status
        if request.status_callback is None:
            return
        try:
            request.status_callback(snapshot_id, status)
        except Exception as e:
            logger.debug(
                "status_callback raised for {sid}: {err}",
                sid=snapshot_id,
                err=e,
            )

    # Synthetic 'triggered' so callers see immediate signal even before the
    # first /progress/ call returns.
    _emit_status("triggered")

    deadline = time.monotonic() + timeout
    transient_failures = 0
    while True:
        try:
            status_str = await job.status(refresh=True)
            transient_failures = 0  # success resets the budget
        except (
            AuthenticationError,
            APIError,
            DataNotReadyError,
            ValidationError,
            TimeoutError,
            FetchError,
        ):
            # SDK / domain errors carry specific semantics — let the outer
            # fetch_async handler classify them (auth → FetchAuthError,
            # not-ready → FetchTimeoutError, etc.). They are NOT transient.
            raise
        except Exception as e:
            # Truly unexpected error (network blip, connection reset, etc.)
            # — count against the retry budget so a 30s outage doesn't kill
            # a 1-hour fetch.
            transient_failures += 1
            logger.warning(
                "status() failed for {sid} ({n}/{max}): {err}",
                sid=snapshot_id,
                n=transient_failures,
                max=_MAX_TRANSIENT_STATUS_FAILURES,
                err=e,
            )
            if transient_failures >= _MAX_TRANSIENT_STATUS_FAILURES:
                raise FetchError(
                    f"status() failed {_MAX_TRANSIENT_STATUS_FAILURES} times "
                    f"for snapshot {snapshot_id}: {e}",
                    platform=platform_name,
                ) from e
            if time.monotonic() >= deadline:
                raise FetchTimeoutError(
                    f"Snapshot {snapshot_id} polling exceeded {timeout}s "
                    f"(during transient-error backoff)",
                    platform=platform_name,
                ) from e
            await asyncio.sleep(poll_interval)
            continue

        _emit_status(status_str)

        if status_str == "ready":
            return
        if status_str in ("error", "failed"):
            raise FetchError(
                f"Snapshot {snapshot_id} failed with status: {status_str}",
                platform=platform_name,
            )

        # Cancel check happens AFTER status read so a same-tick 'ready' wins
        # over a Remove click — we don't want to cancel a snapshot whose data
        # has already been collected and is one fetch() call away.
        if request.cancel_callback is not None and request.cancel_callback():
            await _cancel_snapshot(snapshot_id)
            raise FetchCancelled(
                f"Cancellation requested for snapshot {snapshot_id}",
                platform=platform_name,
            )

        if time.monotonic() >= deadline:
            raise FetchTimeoutError(
                f"Snapshot {snapshot_id} polling exceeded {timeout}s",
                platform=platform_name,
            )

        await asyncio.sleep(poll_interval)


class BrightDataFetcher:
    """Strategy fetcher for Facebook and Instagram via Bright Data API.

    Implements the AsyncContentFetcher (@runtime_checkable protocol).
    isinstance(fetcher, AsyncContentFetcher) returns True as long as the object has a `fetch_async` method.
    Takes a FetchRequest with platform (facebook/instagram) and
    URLs, triggers a scrape job via the Bright Data SDK, polls until completion
    or timeout, and returns results.

    Attributes:
        _token: Bright Data API token (from environment or constructor).
        _request_timeout: Per-request aiohttp timeout (seconds) passed through
            to the underlying BrightDataClient/AsyncEngine for every HTTP call
            (trigger, poll, fetch).
    """

    def __init__(
        self,
        token: str | None = None,
        request_timeout: int | None = None,
    ):
        """Initialize the fetcher with an API token.

        Args:
            token: Bright Data API token. If not provided, will attempt to read
                   from BRIGHTDATA_API_TOKEN environment variable.
            request_timeout: Per-request timeout in seconds for every HTTP call
                   the SDK makes to api.brightdata.com. Bumping this helps when
                   the /progress endpoint is slow enough to exceed the 30s
                   default during long-running scrape polls. None (the default)
                   falls back to the BRIGHTDATA_REQUEST_TIMEOUT env var, then to
                   30s if neither is set. Do not confuse with the outer poll
                   budget, which is set per-request via FetchRequest.config
                   ("timeout" key) and governs the total deadline for the
                   _poll_until_ready helper.

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
        self._request_timeout = (
            request_timeout
            if request_timeout is not None
            else _default_request_timeout()
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

        # Convert start_date / end_date from caller format (YYYY-MM-DD) to SDK format (MM-DD-YYYY)
        try:
            sdk_start_date = self._to_sdk_date(request.start_date)
        except ValueError as e:
            raise FetchError(
                f"Invalid start_date format: {request.start_date!r}. "
                f"Expected YYYY-MM-DD: {e}",
                platform=platform_name,
            ) from e

        try:
            sdk_end_date = self._to_sdk_date(request.end_date)
        except ValueError as e:
            raise FetchError(
                f"Invalid end_date format: {request.end_date!r}. "
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
        if sdk_end_date:
            logger.info(
                "Filtering {platform} posts until {date}",
                platform=platform_name,
                date=sdk_end_date,
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
            async with BrightDataClient(
                token=self._token, timeout=self._request_timeout
            ) as client:
                url = urls[0]
                num_of_posts = request.config.get("num_of_posts")
                posts_to_not_include = request.config.get("posts_to_not_include")
                post_type = request.config.get("post_type")

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
                    if num_of_posts:
                        search_kwargs["num_of_posts"] = num_of_posts
                    if sdk_start_date:
                        search_kwargs["start_date"] = sdk_start_date
                    if sdk_end_date:
                        search_kwargs["end_date"] = sdk_end_date
                    # Empty list is "no IDs to skip" → omit the kwarg so the SDK
                    # does not see a meaningless [] payload.
                    if posts_to_not_include:
                        search_kwargs["posts_to_not_include"] = posts_to_not_include
                    if post_type:
                        search_kwargs["post_type"] = post_type
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
                    if num_of_posts:
                        trigger_kwargs["num_of_posts"] = num_of_posts
                    if sdk_start_date:
                        trigger_kwargs["start_date"] = sdk_start_date
                    if sdk_end_date:
                        trigger_kwargs["end_date"] = sdk_end_date
                    # Empty list is "no IDs to skip" → omit the kwarg so the SDK
                    # does not see a meaningless [] payload.
                    if posts_to_not_include:
                        trigger_kwargs["posts_to_not_include"] = posts_to_not_include
                    # post_type is not forwarded for Facebook: the FB
                    # posts_by_profile_trigger SDK method does not expose a
                    # post-type filter today. Caller passes it harmlessly.
                    job = await trigger_method(**trigger_kwargs)
                    logger.debug("Scrape job created: {job_id}", job_id=job.snapshot_id)

                    logger.info(
                        "Polling job {job_id} with timeout={timeout}s, poll_interval={interval}s",
                        job_id=job.snapshot_id,
                        timeout=timeout,
                        interval=poll_interval,
                    )
                    await _poll_until_ready(
                        job,
                        request=request,
                        timeout=timeout,
                        poll_interval=poll_interval,
                        platform_name=platform_name,
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

                if request.progress_callback:
                    try:
                        request.progress_callback(len(items))
                    except Exception:
                        pass  # never let callback failures affect fetching

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
            # Builtin TimeoutError surfaced from the SDK (e.g. raised by
            # job.status() when the underlying HTTP call times out).
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
            config: Optional config dict with `num_of_posts` for testing.

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

        # Apply num_of_posts if configured (for testing/sampling)
        num_of_posts = config.get("num_of_posts")
        if num_of_posts and num_of_posts > 0:
            items = items[:num_of_posts]
            logger.info(
                "Limited {platform} items to {limit} (num_of_posts config)",
                platform=platform,
                limit=num_of_posts,
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
                        text = extract_first_text_field(post, _IG_LEGACY_TEXT_FIELDS)
                        post_id = str(post.get("id", ""))
                        items.append(
                            ContentItem(
                                title=derive_title_from_post(
                                    post, _IG_LEGACY_TEXT_FIELDS
                                )
                                or fallback_title_for_empty_post("Instagram", post_id),
                                author=username,
                                text=text,
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
                    text = extract_first_text_field(entry, _IG_SEARCH_TEXT_FIELDS)
                    post_id = entry.get("post_id") or entry.get("shortcode") or ""
                    items.append(
                        ContentItem(
                            title=derive_title_from_post(entry, _IG_SEARCH_TEXT_FIELDS)
                            or fallback_title_for_empty_post("Instagram", post_id),
                            author=entry.get("user_posted") or "",
                            text=text,
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
                text = extract_first_text_field(post, _FB_TEXT_FIELDS)
                post_id = post.get("post_id") or ""
                items.append(
                    ContentItem(
                        title=derive_title_from_post(post, _FB_TEXT_FIELDS)
                        or fallback_title_for_empty_post("Facebook", post_id),
                        author=post.get("page_name")
                        or post.get("user_username_raw")
                        or "",
                        text=text,
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
