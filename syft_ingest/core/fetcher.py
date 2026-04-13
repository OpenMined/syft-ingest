"""ContentFetcher Protocol and domain-specific error hierarchy.

Defines the contract that all content fetcher implementations must satisfy.
Fetcher implementations (Bright Data, yt-dlp, web scraper) are registered
per platform/extractor pair and dispatched via the Strategy pattern.

The fetch contract is intentionally richer than ``urls -> list[ContentItem]``
because real caller flows need to pass source identity, time windows,
extractor-specific config, and optional artifact output paths, and they need
tracking metadata back (remote job IDs, row counts, artifact paths).

The error hierarchy ensures callers never see raw HTTP or library exceptions;
all failures are wrapped in domain-specific ``FetchError`` subclasses.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from syft_ingest.core.models import ContentItem
from syft_ingest.core.url_router import Platform


class FetchConfig(BaseModel):
    """Configuration options for content fetching.

    Platform-agnostic config model that validates options for all fetchers.
    Each fetcher uses only the options relevant to its platform.

    YouTube (yt-dlp):
        socket_timeout: Network timeout in seconds (default: 30)
        playlistend: Max videos from channel/playlist (default: 50)
        download_full_video: Enable full video download (default: false)

    Instagram/Facebook (BrightData):
        timeout: Total scrape job timeout in seconds (default: 180)
        poll_interval: Check job completion every N seconds (default: 5)
        posts_limit: Limit posts fetched for testing (default: no limit)
    """

    # YouTube options
    socket_timeout: int | None = Field(
        default=None, ge=1, description="Network timeout in seconds"
    )
    playlistend: int | None = Field(
        default=None, ge=1, description="Max videos from channel/playlist"
    )
    download_full_video: bool = Field(
        default=False, description="Enable full video download"
    )

    # BrightData options
    timeout: int | None = Field(
        default=None, ge=1, description="Scrape job timeout in seconds"
    )
    poll_interval: int | None = Field(
        default=None, ge=1, description="Job status check interval in seconds"
    )
    posts_limit: int | None = Field(
        default=None, ge=1, description="Limit posts fetched (for testing)"
    )

    model_config = ConfigDict(
        extra="allow",  # Allow extra fields for forward compatibility
        validate_assignment=True,  # Validate on assignment
    )


class FetchRequest(BaseModel):
    """Typed request payload for programmatic data acquisition.

    This mirrors the information an orchestrating app typically already has
    when starting a sync job: what platform/extractor to use, which profile or
    URLs to fetch, optional source identity, date window, and extractor-specific
    knobs carried in ``config``.

    Simplified API: ``platform`` and ``extractor`` are auto-detected and optional.
    ``config`` is validated via FetchConfig model with IDE support.

    Examples:
        # Minimal: just URLs
        FetchRequest(
            platform="youtube",
            urls=["https://www.youtube.com/@user"]
        )

        # With config options (validated)
        FetchRequest(
            platform="youtube",
            urls=["https://www.youtube.com/@user"],
            config={"playlistend": 10, "socket_timeout": 60}
        )

        # Instagram with post limit for testing
        FetchRequest(
            platform="instagram",
            urls=["https://www.instagram.com/user/"],
            config={"posts_limit": 5}
        )
    """

    platform: Platform | str  # Accept string (e.g. "instagram") or Platform enum
    extractor: str | None = None  # Auto-detected from platform if not provided
    urls: list[str] = Field(min_length=1)
    source_kind: str | None = None
    handle: str | None = None
    profile_url: str | None = None
    external_account_id: str | None = None
    source_slug: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    output_dir: Path | None = None
    config: FetchConfig | dict[str, Any] = Field(
        default_factory=dict,
        description="Fetcher-specific options (validated via FetchConfig, converted to dict)",
    )

    @field_validator("platform", mode="before")
    @classmethod
    def validate_platform(cls, v: Platform | str) -> Platform:
        """Accept platform as string name (e.g. 'instagram') or Platform enum."""
        if isinstance(v, Platform):
            return v
        if isinstance(v, str):
            # Convert string to Platform enum
            try:
                return Platform(v.lower())
            except ValueError:
                valid = ", ".join(p.value for p in Platform)
                raise ValueError(f"Invalid platform '{v}'. Valid: {valid}") from None
        raise ValueError(f"platform must be Platform enum or string, got {type(v)}")

    @model_validator(mode="after")
    def auto_detect_extractor(self) -> FetchRequest:
        """Auto-detect extractor from platform if not provided."""
        if self.extractor is None:
            # Map platform to default extractor
            extractor_map = {
                Platform.YOUTUBE: "yt-dlp",
                Platform.INSTAGRAM: "brightdata",
                Platform.FACEBOOK: "brightdata",
                Platform.TIKTOK: "brightdata",
                Platform.LOCAL: "local",
            }
            self.extractor = extractor_map.get(self.platform)

        # Convert FetchConfig to dict for fetcher compatibility
        if isinstance(self.config, FetchConfig):
            self.config = self.config.model_dump(exclude_none=True)

        return self


class FetchResult(BaseModel):
    """Structured fetch result with content plus acquisition metadata."""

    items: list[ContentItem] = Field(default_factory=list)
    rows_fetched: int | None = None
    remote_job_id: str | None = None
    remote_status: str | None = None
    artifact_paths: dict[str, Path] = Field(default_factory=dict)
    fetched_at: datetime | None = (
        None  # When the fetch completed (Phase 6: delta tracking)
    )
    content_hashes: dict[str, str] = Field(
        default_factory=dict
    )  # SHA256 hashes for deduplication


@runtime_checkable
class ContentFetcher(Protocol):
    """Strategy interface for platform-specific content fetching.

    Each implementation knows how to fetch content for a single platform
    (e.g. ``BrightDataFetcher`` for Facebook/Instagram, ``YtDlpFetcher``
    for YouTube). The platform/extractor binding is set at registration time.

    Implementations must be **synchronous** and return a ``FetchResult``.
    They should use ``FetchRequest.config`` for extractor-specific options
    such as post count, poll interval, or media type filters.

    Example::

        class MyFetcher:
            def fetch(self, request: FetchRequest) -> FetchResult:
                ...

        assert isinstance(MyFetcher(), ContentFetcher)  # runtime_checkable
    """

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch content for the given request.

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
        ...


# ---------------------------------------------------------------------------
# Domain-specific error hierarchy
# ---------------------------------------------------------------------------


class FetchError(Exception):
    """Base exception for all content-fetching failures.

    Callers can ``except FetchError`` to catch any fetcher failure regardless
    of the underlying cause.

    Attributes:
        message: Human-readable description of the failure.
        platform: Optional platform identifier (e.g. ``"facebook"``).
    """

    def __init__(self, message: str, platform: str | None = None) -> None:
        self.message = message
        self.platform = platform
        super().__init__(message)


class FetchAuthError(FetchError):
    """Authentication or credential failure during content fetching.

    Raised when API keys are missing, expired, or rejected by the upstream
    service (e.g. Bright Data returns 401/403).
    """


class FetchTimeoutError(FetchError):
    """Scrape or poll operation exceeded the allowed timeout.

    Raised when a long-running scrape job does not complete within the
    configured deadline.
    """


class FetchEmptyResultError(FetchError):
    """Scrape completed successfully but returned zero content items.

    This is distinct from a timeout or auth failure — the upstream service
    responded, but the result set was empty (e.g. the profile has no posts).
    """
