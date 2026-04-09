"""ContentFetcher Protocol and domain-specific error hierarchy.

Defines the contract that all content fetcher implementations must satisfy.
Fetcher implementations (Bright Data, yt-dlp, web scraper) are registered
per-platform and dispatched via the Strategy pattern — callers interact only
with this Protocol, never with concrete implementations directly.

The error hierarchy ensures callers never see raw HTTP or library exceptions;
all failures are wrapped in domain-specific ``FetchError`` subclasses.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from syft_ingest.core.models import ContentItem


@runtime_checkable
class ContentFetcher(Protocol):
    """Strategy interface for platform-specific content fetching.

    Each implementation knows how to fetch content for a single platform
    (e.g. ``BrightDataFetcher`` for Facebook/Instagram, ``YtDlpFetcher``
    for YouTube).  The platform is bound at registration time, not at
    call time — ``fetch()`` simply receives URLs to process.

    Implementations must be **synchronous** and return a flat list of
    ``ContentItem`` instances (not ``Corpus``).

    Example::

        class MyFetcher:
            def fetch(self, urls: list[str]) -> list[ContentItem]:
                ...

        assert isinstance(MyFetcher(), ContentFetcher)  # runtime_checkable
    """

    def fetch(self, urls: list[str]) -> list[ContentItem]:
        """Fetch content from the given URLs.

        Args:
            urls: One or more creator/content URLs to scrape or download.

        Returns:
            Normalized content items ready for downstream processing.

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
