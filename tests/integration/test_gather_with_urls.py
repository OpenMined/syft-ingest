"""Integration tests for gather() with URL sources.

Tests verify that gather() correctly:
1. Accepts url_sources parameter
2. Dispatches URLs via get_fetcher_for_url() to fetcher registry
3. Returns Corpus with mixed URL + local sources
4. Handles errors gracefully (FetchError, FetchEmptyResultError)
5. Maintains backward compatibility with existing gather() API
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from syft_ingest.core.fetcher import (
    FetchEmptyResultError,
    FetchError,
    FetchResult,
)
from syft_ingest.core.gather import gather
from syft_ingest.core.models import (
    Corpus,
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


def _reregister_fetchers():
    """Re-register fetchers if they're missing from the registry."""
    from syft_ingest.core.registry import FetcherKey

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
def _ensure_fetchers_registered():
    """Ensure fetchers are registered before each test."""
    _reregister_fetchers()
    yield


class TestGatherWithYouTubeURL:
    """Tests for gather() with YouTube URL sources."""

    def test_gather_youtube_url_source(self):
        """gather(url_sources=['https://youtube.com/watch?v=...']) returns Corpus with VideoResult."""
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

        # Mock YtDlpFetcher.fetch() to return the video
        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(items=[video_result])
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with YouTube URL
            corpus = gather(
                name="test_creator",
                url_sources=["https://www.youtube.com/watch?v=test123"],
            )

            # Verify corpus contains the video
            assert len(corpus.all_items()) == 1
            assert isinstance(corpus.all_items()[0], VideoResult)
            assert corpus.all_items()[0].title == "Test Video"

            # Verify get_fetcher_for_url was called
            mock_get_fetcher.assert_called_once_with(
                "https://www.youtube.com/watch?v=test123"
            )

            # Verify fetch was called
            mock_fetcher.fetch.assert_called_once()


class TestGatherWithInstagramURL:
    """Tests for gather() with Instagram URL sources."""

    def test_gather_instagram_url_source(self):
        """gather(url_sources=['https://instagram.com/user']) returns Corpus with Instagram items."""
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

        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(
                items=[profile_result, post_result]
            )
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with Instagram URL
            corpus = gather(
                name="test_creator",
                url_sources=["https://www.instagram.com/testuser/"],
            )

            # Verify corpus contains both items
            assert len(corpus.all_items()) == 2
            assert isinstance(corpus.all_items()[0], ProfileResult)
            assert isinstance(corpus.all_items()[1], SocialPostResult)

            # Verify get_fetcher_for_url was called
            mock_get_fetcher.assert_called_once_with(
                "https://www.instagram.com/testuser/"
            )


class TestGatherWithFacebookURL:
    """Tests for gather() with Facebook URL sources."""

    def test_gather_facebook_url_source(self):
        """gather(url_sources=['https://facebook.com/page']) returns Corpus with Facebook items."""
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

        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = FetchResult(
                items=[reel_result, post_result]
            )
            mock_get_fetcher.return_value = mock_fetcher

            # Call gather with Facebook URL
            corpus = gather(
                name="test_creator",
                url_sources=["https://www.facebook.com/testpage/"],
            )

            # Verify corpus contains both items
            assert len(corpus.all_items()) == 2
            assert isinstance(corpus.all_items()[0], ReelResult)
            assert isinstance(corpus.all_items()[1], SocialPostResult)

            # Verify get_fetcher_for_url was called
            mock_get_fetcher.assert_called_once_with(
                "https://www.facebook.com/testpage/"
            )


class TestGatherMixedURLAndLocalSources:
    """Tests for gather() with mixed URL and local sources."""

    def test_gather_mixed_url_and_local_sources(self):
        """gather(url_sources=[...], local_dirs=[...]) returns Corpus with mixed items."""
        # Create mock YouTube video
        video_result = VideoResult(
            title="Test Video",
            url="https://www.youtube.com/watch?v=test123",
            author="Test Channel",
            text="Test video content",
            metadata={"platform": "youtube"},
        )

        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            with patch("syft_ingest.sources.local.fetch_local") as mock_fetch_local:
                # Mock the fetcher
                mock_fetcher = MagicMock()
                mock_fetcher.fetch.return_value = FetchResult(items=[video_result])
                mock_get_fetcher.return_value = mock_fetcher

                # Mock fetch_local to return an article
                from syft_ingest.core.models import ArticleResult

                local_article = ArticleResult(
                    title="Local Article",
                    author="Local Author",
                    url="file:///local/article.html",
                    text="Local article content",
                    metadata={"platform": "local"},
                )
                mock_fetch_local.return_value = [local_article]

                # Call gather with both URL and local sources
                corpus = gather(
                    name="test_creator",
                    url_sources=["https://www.youtube.com/watch?v=test123"],
                    sources=["local"],
                    local_dirs=["/tmp/test"],
                )

                # Verify corpus contains both items
                assert len(corpus.all_items()) == 2

                # Check item types
                items = corpus.all_items()
                assert any(isinstance(item, VideoResult) for item in items)
                assert any(isinstance(item, ArticleResult) for item in items)


class TestGatherEmptyURLSourceContinues:
    """Tests for gather() error handling with empty URL sources."""

    def test_gather_empty_url_source_continues(self, caplog):
        """gather() handles FetchEmptyResultError gracefully and continues processing."""
        # Create mock items for the second URL
        video_result = VideoResult(
            title="Test Video",
            url="https://www.youtube.com/watch?v=test456",
            author="Test Channel",
            text="Test video content",
            metadata={"platform": "youtube"},
        )

        def mock_get_fetcher_side_effect(url: str):
            """Different behavior for different URLs."""
            mock_fetcher = MagicMock()

            if "youtube" in url and "test123" in url:
                # First URL returns empty result
                mock_fetcher.fetch.side_effect = FetchEmptyResultError("No results")
            else:
                # Second URL returns data
                mock_fetcher.fetch.return_value = FetchResult(items=[video_result])

            return mock_fetcher

        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_get_fetcher.side_effect = mock_get_fetcher_side_effect

            # Call gather with two URLs (first empty, second has data)
            corpus = gather(
                name="test_creator",
                url_sources=[
                    "https://www.youtube.com/watch?v=test123",  # Empty
                    "https://www.youtube.com/watch?v=test456",  # Has data
                ],
            )

            # Verify corpus contains only the second video
            assert len(corpus.all_items()) == 1
            assert corpus.all_items()[0].title == "Test Video"

            # Verify both URLs were attempted
            assert mock_get_fetcher.call_count == 2


class TestGatherErrorHandling:
    """Tests for gather() error handling with various exceptions."""

    def test_gather_handles_fetch_error(self, caplog):
        """gather() handles FetchError gracefully and continues processing."""
        video_result = VideoResult(
            title="Working Video",
            url="https://www.youtube.com/watch?v=test456",
            author="Test Channel",
            text="Test video content",
            metadata={"platform": "youtube"},
        )

        def mock_get_fetcher_side_effect(url: str):
            """Different behavior for different URLs."""
            mock_fetcher = MagicMock()

            if "test123" in url:
                # First URL raises FetchError
                mock_fetcher.fetch.side_effect = FetchError("Failed to fetch")
            else:
                # Second URL works
                mock_fetcher.fetch.return_value = FetchResult(items=[video_result])

            return mock_fetcher

        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_get_fetcher.side_effect = mock_get_fetcher_side_effect

            # Call gather with two URLs (first fails, second works)
            corpus = gather(
                name="test_creator",
                url_sources=[
                    "https://www.youtube.com/watch?v=test123",  # Fails
                    "https://www.youtube.com/watch?v=test456",  # Works
                ],
            )

            # Verify corpus contains only the successful video
            assert len(corpus.all_items()) == 1
            assert corpus.all_items()[0].title == "Working Video"

    def test_gather_handles_invalid_url(self, caplog):
        """gather() handles ValueError (invalid URL) gracefully."""
        with patch(
            "syft_ingest.core.url_router.get_fetcher_for_url"
        ) as mock_get_fetcher:
            mock_get_fetcher.side_effect = ValueError("Invalid URL format")

            # Call gather with an invalid URL
            corpus = gather(
                name="test_creator",
                url_sources=["not-a-valid-url"],
            )

            # Verify corpus is empty (error was handled)
            assert len(corpus.all_items()) == 0

    def test_gather_backward_compatibility_no_url_sources(self):
        """gather() maintains backward compatibility when url_sources is not provided."""
        # Test that gather works without url_sources parameter
        corpus = gather(name="test_creator")

        # Verify we get an empty corpus
        assert isinstance(corpus, Corpus)
        assert corpus.person == "test_creator"
        assert len(corpus.all_items()) == 0
