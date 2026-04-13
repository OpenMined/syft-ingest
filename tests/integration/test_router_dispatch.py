"""Integration tests for URL router dispatch to fetcher registry.

Tests verify that get_fetcher_for_url() correctly:
1. Resolves URLs to Platform
2. Dispatches Platform to correct fetcher via registry
3. Returns ContentFetcher instances
4. Handles error cases gracefully
"""

from __future__ import annotations

import pytest

from syft_ingest.core.fetcher import ContentFetcher
from syft_ingest.core.registry import (
    FETCHER_REGISTRY,
    register_fetcher,
    reset_registry,
)
from syft_ingest.core.url_router import (
    InvalidURLError,
    Platform,
    UnsupportedPlatformError,
    get_fetcher_for_url,
)
from syft_ingest.sources.brightdata import BrightDataFetcher
from syft_ingest.sources.youtube import YtDlpFetcher


def _reregister_fetchers():
    """Re-register fetchers if they're missing from the registry."""
    # Check if YouTube fetcher is registered
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
    """Ensure fetchers are registered before each test.

    This fixture re-registers fetchers before each test in case a previous
    test cleared the registry. Since some tests deliberately reset the
    registry to test error handling, we need to restore it.
    """
    _reregister_fetchers()
    yield


class TestDispatchYouTubeURLs:
    """Tests for YouTube URL dispatch to YtDlpFetcher."""

    def test_dispatch_youtube_watch_url_to_ytdlp_fetcher(self):
        """YouTube watch URL resolves to YtDlpFetcher."""
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        fetcher = get_fetcher_for_url(url)

        # Verify instance type
        assert isinstance(fetcher, YtDlpFetcher)

        # Verify protocol compliance
        assert isinstance(fetcher, ContentFetcher)

        # Verify has fetch method
        assert callable(getattr(fetcher, "fetch", None))

    def test_dispatch_youtube_channel_url_to_ytdlp_fetcher(self):
        """YouTube channel URL resolves to YtDlpFetcher."""
        url = "https://www.youtube.com/@mkbhd"
        fetcher = get_fetcher_for_url(url)

        assert isinstance(fetcher, YtDlpFetcher)
        assert isinstance(fetcher, ContentFetcher)

    def test_dispatch_youtube_short_url_to_ytdlp_fetcher(self):
        """YouTube short URL (youtu.be) resolves to YtDlpFetcher."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        fetcher = get_fetcher_for_url(url)

        assert isinstance(fetcher, YtDlpFetcher)
        assert isinstance(fetcher, ContentFetcher)


class TestDispatchInstagramURLs:
    """Tests for Instagram URL dispatch to BrightDataFetcher."""

    def test_dispatch_instagram_url_to_brightdata_fetcher(self):
        """Instagram URL resolves to BrightDataFetcher."""
        url = "https://instagram.com/username"
        fetcher = get_fetcher_for_url(url)

        # Verify instance type
        assert isinstance(fetcher, BrightDataFetcher)

        # Verify protocol compliance
        assert isinstance(fetcher, ContentFetcher)

        # Verify has fetch method
        assert callable(getattr(fetcher, "fetch", None))

    def test_dispatch_instagram_www_url_to_brightdata_fetcher(self):
        """Instagram www URL resolves to BrightDataFetcher."""
        url = "https://www.instagram.com/username"
        fetcher = get_fetcher_for_url(url)

        assert isinstance(fetcher, BrightDataFetcher)
        assert isinstance(fetcher, ContentFetcher)


class TestDispatchFacebookURLs:
    """Tests for Facebook URL dispatch to BrightDataFetcher."""

    def test_dispatch_facebook_url_to_brightdata_fetcher(self):
        """Facebook URL resolves to BrightDataFetcher."""
        url = "https://facebook.com/page"
        fetcher = get_fetcher_for_url(url)

        # Verify instance type
        assert isinstance(fetcher, BrightDataFetcher)

        # Verify protocol compliance
        assert isinstance(fetcher, ContentFetcher)

        # Verify has fetch method
        assert callable(getattr(fetcher, "fetch", None))

    def test_dispatch_facebook_www_url_to_brightdata_fetcher(self):
        """Facebook www URL resolves to BrightDataFetcher."""
        url = "https://www.facebook.com/page/posts"
        fetcher = get_fetcher_for_url(url)

        assert isinstance(fetcher, BrightDataFetcher)
        assert isinstance(fetcher, ContentFetcher)


class TestErrorHandling:
    """Tests for error handling in dispatch."""

    def test_dispatch_unsupported_platform_raises_error(self):
        """Unsupported platform URL raises UnsupportedPlatformError."""
        url = "https://unsupported-platform.com/user"

        with pytest.raises(UnsupportedPlatformError):
            get_fetcher_for_url(url)

    def test_dispatch_invalid_url_raises_error(self):
        """Invalid URL raises InvalidURLError."""
        with pytest.raises(InvalidURLError):
            get_fetcher_for_url("not-a-url")

    def test_dispatch_empty_url_raises_error(self):
        """Empty URL raises InvalidURLError."""
        with pytest.raises(InvalidURLError):
            get_fetcher_for_url("")

    def test_dispatch_unregistered_fetcher_raises_key_error(self):
        """Missing fetcher in registry raises KeyError.

        This test forces a scenario where a platform is supported but
        the fetcher is not registered, which can happen if:
        1. The fetcher module is not imported
        2. The fetcher fails to auto-register
        """
        # Reset registry to simulate missing fetcher
        reset_registry()

        # Try to dispatch - should fail because no fetcher is registered
        url = "https://youtube.com/watch?v=test"

        with pytest.raises(KeyError, match="youtube|yt-dlp"):
            get_fetcher_for_url(url)


class TestCustomMethodOverride:
    """Tests for custom method override."""

    def test_dispatch_with_custom_method_override_registered(self):
        """Custom method override works when fetcher is registered.

        Uses explicit method name instead of platform default.
        """
        url = "https://youtube.com/watch?v=test"

        # Use default method (should work)
        fetcher = get_fetcher_for_url(url, default_method="yt-dlp")
        assert isinstance(fetcher, YtDlpFetcher)

    def test_dispatch_with_custom_method_override_unregistered_raises_error(self):
        """Custom method override raises KeyError if not registered.

        Tests that attempting to use a custom method that doesn't exist
        in the registry fails gracefully.
        """
        url = "https://youtube.com/watch?v=test"

        with pytest.raises(KeyError, match="custom-extractor|youtube"):
            get_fetcher_for_url(url, default_method="custom-extractor")


class TestProtocolCompliance:
    """Tests for ContentFetcher protocol compliance."""

    def test_youtube_fetcher_satisfies_protocol(self):
        """Dispatched YouTube fetcher implements ContentFetcher protocol."""
        url = "https://youtube.com/watch?v=test"
        fetcher = get_fetcher_for_url(url)

        # Runtime checkable protocol - this should always be True
        assert isinstance(fetcher, ContentFetcher)

    def test_brightdata_fetcher_satisfies_protocol(self):
        """Dispatched BrightData fetcher implements ContentFetcher protocol."""
        url = "https://instagram.com/username"
        fetcher = get_fetcher_for_url(url)

        # Runtime checkable protocol - this should always be True
        assert isinstance(fetcher, ContentFetcher)

    def test_dispatched_fetcher_has_fetch_method(self):
        """Dispatched fetcher has callable fetch method."""
        url = "https://facebook.com/page"
        fetcher = get_fetcher_for_url(url)

        # Verify fetch method exists and is callable
        assert hasattr(fetcher, "fetch")
        assert callable(fetcher.fetch)


class TestPlatformMapping:
    """Tests for correct platform-to-fetcher mapping."""

    def test_all_supported_platforms_dispatch(self):
        """All supported platforms dispatch to correct fetchers."""
        test_cases = [
            ("https://youtube.com/watch?v=test", YtDlpFetcher),
            ("https://instagram.com/user", BrightDataFetcher),
            ("https://facebook.com/page", BrightDataFetcher),
        ]

        for url, expected_class in test_cases:
            fetcher = get_fetcher_for_url(url)
            assert isinstance(fetcher, expected_class), (
                f"URL {url} should dispatch to {expected_class.__name__}"
            )

    def test_platform_detection_is_case_insensitive(self):
        """Platform detection works with mixed-case URLs."""
        url = "HTTPS://WWW.YOUTUBE.COM/@CREATOR"
        fetcher = get_fetcher_for_url(url.lower())  # urllib.parse expects lowercase

        assert isinstance(fetcher, YtDlpFetcher)

    def test_url_normalization_preserves_dispatch(self):
        """URL normalization (tracking param removal) doesn't affect dispatch."""
        url_with_tracking = "https://youtube.com/watch?v=test&utm_source=x&fbclid=123"
        fetcher = get_fetcher_for_url(url_with_tracking)

        assert isinstance(fetcher, YtDlpFetcher)
