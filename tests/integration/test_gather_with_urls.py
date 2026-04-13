"""Integration tests for gather() with platform-first API.

Tests verify that gather(platform, urls, author, **config) correctly:
1. Accepts platform + URLs as positional arguments
2. Supports optional author and config kwargs
3. Dispatches to fetcher registry with auto-detected extractors
4. Returns Corpus with fetched content
5. Handles errors gracefully (FetchError, FetchEmptyResultError)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from syft_ingest.core.fetcher import (
    FetchError,
    FetchResult,
)
from syft_ingest.core.gather import gather
from syft_ingest.core.models import (
    ProfileResult,
    ReelResult,
    SocialPostResult,
    SourceType,
    VideoResult,
)
from syft_ingest.core.registry import (
    FETCHER_REGISTRY,
    register_fetcher,
)
from syft_ingest.core.url_router import Platform
from syft_ingest.sources.brightdata import BrightDataFetcher
from syft_ingest.sources.youtube import YtDlpFetcher


def _reregister_fetchers(monkeypatch=None):
    """Re-register fetchers if they're missing from the registry."""
    from syft_ingest.core.registry import FetcherKey

    # Set test token for BrightDataFetcher if monkeypatch is available
    if monkeypatch:
        monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-for-testing")

    yt_key = FetcherKey(platform=Platform.YOUTUBE, extractor="yt-dlp")
    fb_key = FetcherKey(platform=Platform.FACEBOOK, extractor="brightdata")
    ig_key = FetcherKey(platform=Platform.INSTAGRAM, extractor="brightdata")

    if yt_key not in FETCHER_REGISTRY:
        register_fetcher(Platform.YOUTUBE, "yt-dlp", YtDlpFetcher())

    if fb_key not in FETCHER_REGISTRY:
        register_fetcher(Platform.FACEBOOK, "brightdata", BrightDataFetcher())

    if ig_key not in FETCHER_REGISTRY:
        register_fetcher(Platform.INSTAGRAM, "brightdata", BrightDataFetcher())


@pytest.fixture(autouse=True)
def _ensure_fetchers_registered(monkeypatch):
    """Ensure fetchers are registered before each test."""
    _reregister_fetchers(monkeypatch=monkeypatch)
    yield


class TestGatherWithYouTubeURL:
    """Tests for gather() with YouTube platform."""

    def test_gather_youtube_url_source(self):
        """gather("youtube", [urls]) returns Corpus with VideoResult."""
        # Create a mock VideoResult
        video_result = VideoResult(
            title="Test Video",
            url="https://www.youtube.com/watch?v=test123",
            author="Test Channel",
            text="Test video content",
            metadata={
                "platform": "youtube",
                "extractor": "yt-dlp",
            },
        )

        # Mock get_fetcher to return a mock fetcher
        with patch("syft_ingest.core.registry.get_fetcher") as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(items=[video_result])
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with YouTube platform and URL
            corpus = gather("youtube", ["https://www.youtube.com/watch?v=test123"])

            # Verify corpus contains the video
            assert len(corpus.all_items()) == 1
            assert isinstance(corpus.all_items()[0], VideoResult)
            assert corpus.all_items()[0].title == "Test Video"

            # Verify get_fetcher was called with correct platform and extractor
            mock_get_fetcher.assert_called_once_with(Platform.YOUTUBE, "yt-dlp")

            # Verify fetch was called
            mock_fetcher.fetch.assert_called_once()


class TestGatherWithInstagramURL:
    """Tests for gather() with Instagram platform."""

    def test_gather_instagram_url_source(self):
        """gather("instagram", [urls]) returns Corpus with Instagram items."""
        # Create mock Instagram items
        profile_result = ProfileResult(
            title="Test User",
            author="Test User",
            url="https://www.instagram.com/testuser/",
            text="Test user profile",
            source_type=SourceType.INSTAGRAM,
            metadata={
                "platform": "instagram",
                "extractor": "brightdata",
            },
        )

        post_result = SocialPostResult(
            title="Test Post",
            url="https://www.instagram.com/p/ABC123/",
            author="Test User",
            text="Test post content",
            source_type=SourceType.INSTAGRAM,
            metadata={
                "platform": "instagram",
                "extractor": "brightdata",
            },
        )

        with patch("syft_ingest.core.registry.get_fetcher") as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(
                items=[profile_result, post_result]
            )
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with Instagram platform and URL
            corpus = gather("instagram", ["https://www.instagram.com/testuser/"])

            # Verify corpus contains both items
            assert len(corpus.all_items()) == 2
            assert isinstance(corpus.all_items()[0], ProfileResult)
            assert isinstance(corpus.all_items()[1], SocialPostResult)

            # Verify get_fetcher was called with correct platform and extractor
            mock_get_fetcher.assert_called_once_with(Platform.INSTAGRAM, "brightdata")


class TestGatherWithFacebookURL:
    """Tests for gather() with Facebook platform."""

    def test_gather_facebook_url_source(self):
        """gather("facebook", [urls]) returns Corpus with Facebook items."""
        # Create mock Facebook items
        reel_result = ReelResult(
            title="Test Reel",
            url="https://www.facebook.com/watch/?v=test123",
            author="Test Page",
            text="Test reel content",
            source_type=SourceType.FACEBOOK,
            metadata={
                "platform": "facebook",
                "extractor": "brightdata",
            },
        )

        post_result = SocialPostResult(
            title="Test Post",
            url="https://www.facebook.com/testpage/posts/123",
            author="Test Page",
            text="Test post content",
            source_type=SourceType.FACEBOOK,
            metadata={
                "platform": "facebook",
                "extractor": "brightdata",
            },
        )

        with patch("syft_ingest.core.registry.get_fetcher") as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(
                items=[reel_result, post_result]
            )
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with Facebook platform and URL
            corpus = gather("facebook", ["https://www.facebook.com/testpage/"])

            # Verify corpus contains both items
            assert len(corpus.all_items()) == 2
            assert isinstance(corpus.all_items()[0], ReelResult)
            assert isinstance(corpus.all_items()[1], SocialPostResult)

            # Verify get_fetcher was called with correct platform and extractor
            mock_get_fetcher.assert_called_once_with(Platform.FACEBOOK, "brightdata")


class TestGatherWithLocalDirectory:
    """Tests for gather() with local directory platform."""

    def test_gather_local_directory(self):
        """gather("local", [dirs]) returns Corpus with items from local export."""
        from syft_ingest.core.models import ArticleResult

        local_article = ArticleResult(
            title="Local Article",
            author="Local Author",
            url="file:///local/article.html",
            text="Local article content",
            metadata={"platform": "local"},
        )

        with patch("syft_ingest.sources.local.fetch_local") as mock_fetch_local:
            mock_fetch_local.return_value = [local_article]

            # Call gather with local platform
            corpus = gather("local", ["/tmp/test"], author="Local Creator")

            # Verify corpus contains the article and author is set
            assert len(corpus.all_items()) == 1
            assert isinstance(corpus.all_items()[0], ArticleResult)
            assert corpus.person == "Local Creator"

            # Verify fetch_local was called with correct directory
            mock_fetch_local.assert_called_once_with(
                ["/tmp/test"], author="Local Creator"
            )


class TestGatherErrorHandling:
    """Tests for gather() error handling."""

    def test_gather_handles_fetch_error(self):
        """gather() raises FetchError when fetcher fails."""
        with patch("syft_ingest.core.registry.get_fetcher") as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.side_effect = FetchError("Network error")
            mock_get_fetcher.return_value = mock_fetcher

            # Verify error is raised
            with pytest.raises(FetchError):
                gather("youtube", ["https://www.youtube.com/watch?v=test123"])

    def test_gather_handles_invalid_url(self):
        """gather() raises ValueError for invalid platform."""
        with pytest.raises(ValueError):
            gather("invalid_platform", ["https://example.com"])

    def test_gather_backward_compatibility_no_urls(self):
        """gather() raises ValueError when urls not provided."""
        with pytest.raises(ValueError):
            gather("youtube", None)
