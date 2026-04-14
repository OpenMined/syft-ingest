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
    ProfileResult,
    ReelResult,
    SocialPostResult,
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

        logger.info(
            "Fetching {n} URL(s) for {platform}",
            n=len(urls),
            platform=platform_name,
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
                # Pass server-side post limit if configured (saves API cost/time)
                trigger_kwargs: dict[str, Any] = {"url": url}
                posts_limit = request.config.get("posts_limit")
                if posts_limit:
                    trigger_kwargs["num_of_posts"] = posts_limit
                job = await trigger_method(**trigger_kwargs)
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

                # Parse response into ContentItem list
                items = self._parse_response(raw_data, platform_name, request.config)

                # Raise FetchEmptyResultError if no items parsed
                if not items:
                    raise FetchEmptyResultError(
                        f"No content items found in {platform_name} response",
                        platform=platform_name,
                    )

                # Return FetchResult with parsed items
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
                    remote_job_id=job.snapshot_id,
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
            List of ContentItem subclass instances (ProfileResult, SocialPostResult, or ReelResult).
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

    def _parse_instagram_response(self, raw_data: dict[str, Any]) -> list[ContentItem]:
        """Parse Instagram scraper response into ContentItem list.

        Handles profiles, posts (image/text), and reels (video).

        Args:
            raw_data: Response dict from Instagram scraper.

        Returns:
            List of ProfileResult, SocialPostResult, or ReelResult items.
        """
        items: list[ContentItem] = []

        # Parse profiles if present
        if "profiles" in raw_data:
            for profile in raw_data.get("profiles", []):
                try:
                    username = profile.get("username", "Unknown")
                    name = profile.get("name", username)
                    bio = profile.get("bio", "")
                    followers = profile.get("followers_count", 0)
                    following = profile.get("following_count", 0)
                    posts_count = profile.get("posts_count", 0)
                    profile_picture_url = profile.get("profile_picture_url")
                    verified = profile.get("verified", False)

                    item = ProfileResult(
                        title=username,
                        author=name,
                        text=bio,
                        url=f"https://instagram.com/{username}",
                        source_type=SourceType.INSTAGRAM,
                        published_at=None,
                        followers_count=followers,
                        following_count=following,
                        posts_count=posts_count,
                        profile_picture_url=profile_picture_url,
                        verified=verified,
                        bio=bio,
                    )
                    items.append(item)
                except Exception as e:
                    logger.warning("Failed to parse Instagram profile: {}", e)

        # Parse posts if present
        if "posts" in raw_data:
            for post in raw_data.get("posts", []):
                try:
                    post_id = post.get("id", "Unknown Post")
                    username = post.get("username", "Unknown")
                    caption = post.get("caption", "")
                    likes = post.get("likes_count", 0)
                    comments = post.get("comments_count", 0)
                    shares = post.get("shares_count", 0)
                    created_at_str = post.get("created_at")
                    media_urls = post.get("media_urls", [])
                    has_video = post.get("has_video", False)
                    video_duration = post.get("video_duration_seconds")

                    # Parse datetime if provided
                    published_at = None
                    if created_at_str:
                        try:
                            published_at = datetime.fromisoformat(
                                created_at_str.replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            logger.debug("Could not parse date {}", created_at_str)

                    if has_video or video_duration:
                        item = ReelResult(
                            title=post_id,
                            author=username,
                            text=caption,
                            url=post.get("post_url"),
                            source_type=SourceType.INSTAGRAM,
                            published_at=published_at,
                            duration_seconds=video_duration,
                            likes_count=likes,
                            comments_count=comments,
                            shares_count=shares,
                            media_urls=media_urls,
                        )
                    else:
                        item = SocialPostResult(
                            title=post_id,
                            author=username,
                            text=caption,
                            url=post.get("post_url"),
                            source_type=SourceType.INSTAGRAM,
                            published_at=published_at,
                            likes_count=likes,
                            comments_count=comments,
                            shares_count=shares,
                            media_urls=media_urls,
                        )

                    items.append(item)
                except Exception as e:
                    logger.warning("Failed to parse Instagram post: {}", e)

        return items

    def _parse_facebook_response(
        self, raw_data: dict[str, Any] | list[dict[str, Any]]
    ) -> list[ContentItem]:
        """Parse Facebook scraper response into ContentItem list.

        BrightData returns a flat list of post dicts (not wrapped in {"posts": [...]}).
        Each post has fields: post_id, content, date_posted, page_name, url,
        likes, num_comments, num_shares, post_type, attachments, etc.

        Args:
            raw_data: Response from BrightData — either a list of post dicts
                      or a dict with a "posts" key (legacy format).

        Returns:
            List of SocialPostResult or ReelResult items.
        """
        items: list[ContentItem] = []

        # BrightData returns a flat list; legacy format wraps in {"posts": [...]}
        if isinstance(raw_data, list):
            posts = raw_data
        elif isinstance(raw_data, dict):
            posts = raw_data.get("posts", [])
        else:
            return items

        for post in posts:
            try:
                post_id = post.get("post_id", "Unknown Post")
                text = post.get("content", "")
                created_time_str = post.get("date_posted")
                permalink_url = post.get("url", "")
                author = post.get("page_name") or post.get(
                    "user_username_raw", "Unknown"
                )

                # Parse datetime if provided
                published_at = None
                if created_time_str:
                    try:
                        published_at = datetime.fromisoformat(
                            created_time_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        logger.debug("Could not parse date {}", created_time_str)

                # Engagement metrics
                likes_count = post.get("likes", 0) or 0
                comments_count = post.get("num_comments", 0) or 0
                shares_count = post.get("num_shares", 0) or 0

                # Detect video/reel posts
                post_type = post.get("post_type", "").lower()
                is_video = (
                    post_type == "reel" or post.get("video_view_count") is not None
                )

                # Extract media URLs from attachments
                media_urls = []
                attachments = post.get("attachments", [])
                for att in attachments:
                    if att.get("video_url"):
                        media_urls.append(att["video_url"])
                    elif att.get("url"):
                        media_urls.append(att["url"])

                if is_video:
                    # Parse duration from first video attachment (milliseconds -> seconds)
                    duration = None
                    for att in attachments:
                        if att.get("video_length"):
                            try:
                                duration = int(int(att["video_length"]) / 1000)
                            except (ValueError, TypeError):
                                pass
                            break

                    item = ReelResult(
                        title=post_id,
                        author=author,
                        text=text,
                        url=permalink_url,
                        source_type=SourceType.FACEBOOK,
                        published_at=published_at,
                        duration_seconds=duration,
                        likes_count=likes_count,
                        comments_count=comments_count,
                        shares_count=shares_count,
                        media_urls=media_urls,
                    )
                else:
                    item = SocialPostResult(
                        title=post_id,
                        author=author,
                        text=text,
                        url=permalink_url,
                        source_type=SourceType.FACEBOOK,
                        published_at=published_at,
                        likes_count=likes_count,
                        comments_count=comments_count,
                        shares_count=shares_count,
                        media_urls=media_urls,
                    )

                items.append(item)
            except Exception as e:
                logger.warning("Failed to parse Facebook post: {}", e)

        return items
