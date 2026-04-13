"""End-to-end integration tests for BrightDataFetcher registry dispatch and fetch flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchEmptyResultError,
    FetchRequest,
)
from syft_ingest.core.models import ArticleResult, SourceType, VideoResult
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
    """Sample Instagram profile response."""
    return {
        "profiles": [
            {
                "username": "testuser",
                "name": "Test User",
                "bio": "Test bio",
                "followers_count": 1000,
                "posts_count": 50,
                "profile_picture_url": "https://example.com/pic.jpg",
            }
        ]
    }


@pytest.fixture
def mock_instagram_posts_response():
    """Sample Instagram posts response."""
    return {
        "posts": [
            {
                "id": "post-001",
                "username": "testuser",
                "caption": "Great photo",
                "likes_count": 100,
                "comments_count": 5,
                "shares_count": 2,
                "created_at": "2026-01-01T12:00:00Z",
                "media_urls": ["url1", "url2"],
                "has_video": False,
            }
        ]
    }


@pytest.fixture
def mock_facebook_posts_response():
    """Sample Facebook posts response."""
    return {
        "posts": [
            {
                "id": "post-001",
                "message": "Test post",
                "created_time": "2026-01-01T12:00:00Z",
                "from": {"name": "Test Author"},
                "like_count": 50,
                "comment_count": 10,
            }
        ]
    }


@pytest.fixture
def mock_facebook_video_response():
    """Sample Facebook video response."""
    return {
        "posts": [
            {
                "id": "video-001",
                "type": "video",
                "message": "Check this video",
                "video": {"length": 120},
                "created_time": "2026-01-01T12:00:00Z",
                "from": {"name": "Video Author"},
                "like_count": 30,
            }
        ]
    }


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


def test_fetcher_implements_content_fetcher_protocol(brightdata_fetcher):
    """BrightDataFetcher implements ContentFetcher protocol."""
    from syft_ingest.core.fetcher import ContentFetcher

    assert isinstance(brightdata_fetcher, ContentFetcher)


# ---- End-to-end fetch tests ----


@pytest.mark.asyncio
async def test_end_to_end_instagram_fetch(
    brightdata_fetcher, mock_instagram_profile_response
):
    """End-to-end Instagram fetch with registry dispatch and parsing."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        config={"timeout": 30},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-ig-e2e"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value=mock_instagram_profile_response)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher._fetch_async(request)

        assert result.remote_job_id == "job-ig-e2e"
        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ArticleResult)
        assert result.items[0].author == "Test User"
        assert result.items[0].metadata["followers"] == 1000
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

        result = await brightdata_fetcher._fetch_async(request)

        assert result.remote_job_id == "job-fb-e2e"
        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ArticleResult)
        assert result.items[0].author == "Test Author"
        assert result.items[0].text == "Test post"
        assert result.items[0].metadata["likes"] == 50


@pytest.mark.asyncio
async def test_end_to_end_with_timeout_config(
    brightdata_fetcher, mock_instagram_profile_response
):
    """Timeout config from request is passed through to job.wait()."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={"timeout": 5, "poll_interval": 1},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-timeout"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value=mock_instagram_profile_response)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await brightdata_fetcher._fetch_async(request)

        # Verify job.wait() was called with custom timeout and poll_interval
        call_kwargs = mock_job.wait.call_args[1]
        assert call_kwargs["timeout"] == 5
        assert call_kwargs["poll_interval"] == 1


@pytest.mark.asyncio
async def test_end_to_end_empty_result_error(brightdata_fetcher):
    """Empty result raises FetchEmptyResultError."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-empty"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value={})  # Empty response

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchEmptyResultError):
            await brightdata_fetcher._fetch_async(request)


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
            await brightdata_fetcher._fetch_async(request)


@pytest.mark.asyncio
async def test_end_to_end_facebook_video_fetch(
    brightdata_fetcher, mock_facebook_video_response
):
    """End-to-end Facebook video fetch with VideoResult detection."""
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

        result = await brightdata_fetcher._fetch_async(request)

        assert len(result.items) == 1
        assert isinstance(result.items[0], VideoResult)
        assert result.items[0].source_type == SourceType.YOUTUBE
        assert result.items[0].duration_seconds == 120


# ---- Sync wrapper tests ----


def test_end_to_end_sync_fetch(brightdata_fetcher, mock_instagram_profile_response):
    """Sync fetch() method works end-to-end with registry."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-sync"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(return_value=mock_instagram_profile_response)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = brightdata_fetcher.fetch(request)

        assert result.remote_status == "ready"
        assert len(result.items) == 1
        assert isinstance(result.items[0], ArticleResult)
