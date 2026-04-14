"""End-to-end integration tests for BrightDataFetcher registry dispatch and fetch flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchEmptyResultError,
    FetchRequest,
    run_fetcher_sync,
)
from syft_ingest.core.models import (
    ContentItem,
    SourceType,
)
from syft_ingest.core.registry import get_fetcher, reset_registry
from syft_ingest.core.url_router import Platform
from syft_ingest.sources.brightdata import BrightDataFetcher


@pytest.fixture(autouse=True)
def setup_teardown():
    """Reset registry before and after each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def valid_token(monkeypatch):
    """Set a valid Bright Data API token in environment."""
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-12345")


@pytest.fixture
def brightdata_fetcher(valid_token):
    """Create a BrightDataFetcher with a test token."""
    return BrightDataFetcher(token="test-token-12345")


@pytest.fixture
def mock_instagram_profile_response():
    """Sample Instagram search scraper response (flat list of post dicts)."""
    return [
        {
            "post_id": "post-001",
            "description": "Test caption",
            "user_posted": "testuser",
            "likes": 1000,
            "num_comments": 50,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": ["https://example.com/pic.jpg"],
            "url": "https://instagram.com/p/post001",
        }
    ]


@pytest.fixture
def mock_instagram_posts_response():
    """Sample Instagram search scraper response (flat list)."""
    return [
        {
            "post_id": "post-001",
            "description": "Great photo",
            "user_posted": "testuser",
            "likes": 100,
            "num_comments": 5,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": ["url1", "url2"],
            "url": "https://instagram.com/p/post001",
        }
    ]


@pytest.fixture
def mock_facebook_posts_response():
    """Sample Facebook posts response (BrightData flat list format)."""
    return [
        {
            "post_id": "post-001",
            "content": "Test post",
            "date_posted": "2026-01-01T12:00:00Z",
            "page_name": "Test Author",
            "url": "https://facebook.com/post/001",
            "likes": 50,
            "num_comments": 10,
            "num_shares": 0,
            "post_type": "Post",
        }
    ]


@pytest.fixture
def mock_facebook_video_response():
    """Sample Facebook video response (BrightData flat list format)."""
    return [
        {
            "post_id": "video-001",
            "content": "Check this video",
            "date_posted": "2026-01-01T12:00:00Z",
            "page_name": "Video Author",
            "url": "https://facebook.com/reel/001",
            "likes": 30,
            "num_comments": 0,
            "num_shares": 0,
            "post_type": "Reel",
            "video_view_count": 100,
            "attachments": [{"type": "Video", "video_length": "120000"}],
        }
    ]


# ---- Registry dispatch tests ----


def test_registry_dispatch_facebook(brightdata_fetcher):
    """get_fetcher(Platform.FACEBOOK, 'brightdata') returns BrightDataFetcher."""
    from syft_ingest.core.registry import register_fetcher

    register_fetcher(Platform.FACEBOOK, "brightdata", brightdata_fetcher)
    fetcher = get_fetcher(Platform.FACEBOOK, "brightdata")

    assert isinstance(fetcher, BrightDataFetcher)
    assert fetcher is brightdata_fetcher


def test_registry_dispatch_instagram(brightdata_fetcher):
    """get_fetcher(Platform.INSTAGRAM, 'brightdata') returns BrightDataFetcher."""
    from syft_ingest.core.registry import register_fetcher

    register_fetcher(Platform.INSTAGRAM, "brightdata", brightdata_fetcher)
    fetcher = get_fetcher(Platform.INSTAGRAM, "brightdata")

    assert isinstance(fetcher, BrightDataFetcher)
    assert fetcher is brightdata_fetcher


def test_fetcher_implements_async_content_fetcher_protocol(brightdata_fetcher):
    """BrightDataFetcher implements AsyncContentFetcher protocol."""
    from syft_ingest.core.fetcher import AsyncContentFetcher

    assert isinstance(brightdata_fetcher, AsyncContentFetcher)


# ---- End-to-end fetch tests ----


@pytest.mark.asyncio
async def test_end_to_end_instagram_fetch(
    brightdata_fetcher, mock_instagram_profile_response
):
    """End-to-end Instagram fetch with registry dispatch and parsing (search scraper path)."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        config={"timeout": 30},
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-e2e"
    mock_result.data = mock_instagram_profile_response

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher.fetch_async(request)

        assert result.remote_job_id == "snap-ig-e2e"
        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ContentItem)
        assert result.items[0].author == "testuser"
        assert result.items[0].metadata["likes"] == 1000
        assert result.items[0].source_type == SourceType.INSTAGRAM
        assert result.rows_fetched == 1
        assert result.fetched_at is not None


@pytest.mark.asyncio
async def test_end_to_end_facebook_fetch(
    brightdata_fetcher, mock_facebook_posts_response
):
    """End-to-end Facebook fetch with registry dispatch and parsing."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/testpage"],
        config={"timeout": 45, "poll_interval": 3},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-fb-e2e"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value=mock_facebook_posts_response)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher.fetch_async(request)

        assert result.remote_job_id == "job-fb-e2e"
        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ContentItem)
        assert result.items[0].author == "Test Author"
        assert result.items[0].text == "Test post"
        assert result.items[0].metadata["likes"] == 50
        assert result.items[0].source_type == SourceType.FACEBOOK


@pytest.mark.asyncio
async def test_end_to_end_with_timeout_config(
    brightdata_fetcher, mock_instagram_profile_response
):
    """Timeout config from request is passed through to search.instagram.posts()."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={"timeout": 5, "poll_interval": 1},
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-timeout"
    mock_result.data = mock_instagram_profile_response

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await brightdata_fetcher.fetch_async(request)

        # Verify search was called with the custom timeout
        call_kwargs = mock_search_ig.posts.call_args[1]
        assert call_kwargs["timeout"] == 5


@pytest.mark.asyncio
async def test_end_to_end_empty_result_error(brightdata_fetcher):
    """Empty result from search raises FetchEmptyResultError."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-empty"
    mock_result.data = []  # Empty list → no items parsed

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchEmptyResultError):
            await brightdata_fetcher.fetch_async(request)


@pytest.mark.asyncio
async def test_end_to_end_auth_error_flow(brightdata_fetcher):
    """Auth error from SDK is raised as FetchAuthError."""
    from brightdata.exceptions import AuthenticationError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = AuthenticationError("Unauthorized")

        with pytest.raises(FetchAuthError):
            await brightdata_fetcher.fetch_async(request)


@pytest.mark.asyncio
async def test_end_to_end_facebook_video_fetch(
    brightdata_fetcher, mock_facebook_video_response
):
    """End-to-end Facebook video fetch with ContentItem having reel metadata."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/testpage"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-fb-video"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value=mock_facebook_video_response)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher.fetch_async(request)

        assert len(result.items) == 1
        assert isinstance(result.items[0], ContentItem)
        assert result.items[0].source_type == SourceType.FACEBOOK
        assert result.items[0].metadata["post_type"] == "Reel"


# ---- Sync wrapper tests ----


def test_end_to_end_sync_fetch(brightdata_fetcher, mock_instagram_profile_response):
    """Sync bridge run_fetcher_sync() works end-to-end with BrightDataFetcher (search path)."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-sync"
    mock_result.data = mock_instagram_profile_response

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = run_fetcher_sync(brightdata_fetcher, request)

        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ContentItem)
