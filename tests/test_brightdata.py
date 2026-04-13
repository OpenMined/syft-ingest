"""Tests for BrightDataFetcher: polling, timeout, SDK error handling, and response parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchTimeoutError,
)
from syft_ingest.core.models import (
    ProfileResult,
    ReelResult,
    SocialPostResult,
    SourceType,
)
from syft_ingest.core.url_router import Platform
from syft_ingest.sources.brightdata import BrightDataFetcher

# ---- Fixtures ----


@pytest.fixture
def valid_token(monkeypatch):
    """Set a valid Bright Data API token in environment."""
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-12345")


@pytest.fixture
def brightdata_fetcher(valid_token):
    """Create a BrightDataFetcher with a test token."""
    return BrightDataFetcher(token="test-token-12345")


@pytest.fixture
def mock_job():
    """Create a mock ScrapeJob with basic properties."""
    job = AsyncMock()
    job.snapshot_id = "mock-job-12345"
    job.wait = AsyncMock()
    job.fetch = AsyncMock(return_value={"profiles": []})
    return job


# ---- Success path tests ----


@pytest.mark.asyncio
async def test_fetch_async_with_instagram_profile_success(brightdata_fetcher):
    """Successfully fetch Instagram profile via _fetch_async."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        config={"timeout": 30},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-ig-001"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "profiles": [
                {
                    "username": "testuser",
                    "name": "Test User",
                    "bio": "Test bio",
                    "followers_count": 100,
                    "posts_count": 10,
                }
            ]
        }
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher._fetch_async(request)

        assert result.remote_job_id == "job-ig-001"
        assert result.remote_status == "ready"
        assert result.rows_fetched == 1
        assert len(result.items) == 1
        assert isinstance(result.items[0], ProfileResult)

        # Verify trigger was called with correct URL
        mock_scraper.profiles_trigger.assert_called_once_with(
            url="https://instagram.com/testuser"
        )

        # Verify job.wait was called with correct timeout
        mock_job.wait.assert_called_once()
        call_kwargs = mock_job.wait.call_args[1]
        assert call_kwargs["timeout"] == 30


@pytest.mark.asyncio
async def test_fetch_async_with_facebook_profile_success(brightdata_fetcher):
    """Successfully fetch Facebook profile via _fetch_async."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/testuser"],
        config={"timeout": 45, "poll_interval": 3},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-fb-002"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "posts": [
                {
                    "id": "post-001",
                    "message": "Test post",
                    "created_time": "2026-01-01T12:00:00Z",
                    "from": {"name": "Test User"},
                    "like_count": 10,
                    "comment_count": 2,
                }
            ]
        }
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher._fetch_async(request)

        assert result.remote_job_id == "job-fb-002"
        assert result.remote_status == "ready"
        assert result.rows_fetched == 1
        assert len(result.items) == 1

        # Verify trigger was called
        mock_scraper.posts_by_profile_trigger.assert_called_once_with(
            url="https://facebook.com/testuser"
        )

        # Verify job.wait was called with custom poll_interval
        call_kwargs = mock_job.wait.call_args[1]
        assert call_kwargs["timeout"] == 45
        assert call_kwargs["poll_interval"] == 3


@pytest.mark.asyncio
async def test_fetch_async_uses_default_timeout_and_poll_interval(brightdata_fetcher):
    """When config lacks timeout/poll_interval, use defaults (180s/5s)."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={},  # Empty config
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-default"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "profiles": [
                {
                    "username": "testuser",
                    "name": "Test",
                    "bio": "Bio",
                    "followers_count": 0,
                    "posts_count": 0,
                }
            ]
        }
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await brightdata_fetcher._fetch_async(request)

        # Verify defaults were used
        call_kwargs = mock_job.wait.call_args[1]
        assert call_kwargs["timeout"] == 180
        assert call_kwargs["poll_interval"] == 5


# ---- Timeout error tests ----


@pytest.mark.asyncio
async def test_poll_timeout_error_raises_fetch_timeout_error(brightdata_fetcher):
    """When job.wait() raises TimeoutError, raise FetchTimeoutError."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={"timeout": 5},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-timeout"
    # Simulate timeout during polling
    mock_job.wait = AsyncMock(side_effect=TimeoutError("Job timed out"))

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchTimeoutError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "timed out" in str(exc_info.value).lower()
        assert exc_info.value.platform == "instagram"


@pytest.mark.asyncio
async def test_data_not_ready_error_raises_fetch_timeout_error(brightdata_fetcher):
    """When job still pending after retries, raise FetchTimeoutError."""
    from brightdata.exceptions import DataNotReadyError

    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/test"],
        config={"timeout": 10},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-not-ready"
    # SDK raises DataNotReadyError when job still pending after max retries
    mock_job.wait = AsyncMock(side_effect=DataNotReadyError("still pending"))

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchTimeoutError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "pending" in str(exc_info.value).lower()
        assert exc_info.value.platform == "facebook"


# ---- Authentication error tests ----


@pytest.mark.asyncio
async def test_validation_error_raises_fetch_auth_error(brightdata_fetcher):
    """When token validation fails, raise FetchAuthError."""
    from brightdata.exceptions import ValidationError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = ValidationError("Invalid token")

        with pytest.raises(FetchAuthError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "token" in str(exc_info.value).lower()
        assert exc_info.value.platform == "instagram"


@pytest.mark.asyncio
async def test_authentication_error_raises_fetch_auth_error(brightdata_fetcher):
    """When token is rejected (401/403), raise FetchAuthError."""
    from brightdata.exceptions import AuthenticationError

    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/test"],
    )

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = AuthenticationError("Unauthorized")

        with pytest.raises(FetchAuthError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "authentication" in str(exc_info.value).lower()
        assert exc_info.value.platform == "facebook"


# ---- API error tests ----


@pytest.mark.asyncio
async def test_api_error_401_raises_fetch_auth_error(brightdata_fetcher):
    """When API returns 401, classify as auth error."""
    from brightdata.exceptions import APIError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-401"
    mock_job.wait = AsyncMock()
    # fetch() raises APIError with 401
    api_error = APIError("Unauthorized")
    api_error.status_code = 401
    mock_job.fetch = AsyncMock(side_effect=api_error)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchAuthError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "auth" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_api_error_403_raises_fetch_auth_error(brightdata_fetcher):
    """When API returns 403, classify as auth error."""
    from brightdata.exceptions import APIError

    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-403"
    mock_job.wait = AsyncMock()
    # fetch() raises APIError with 403
    api_error = APIError("Forbidden")
    api_error.status_code = 403
    mock_job.fetch = AsyncMock(side_effect=api_error)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchAuthError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        assert "auth" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_api_error_500_raises_fetch_error(brightdata_fetcher):
    """When API returns 500+, classify as generic FetchError (not auth)."""
    from brightdata.exceptions import APIError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-500"
    mock_job.wait = AsyncMock()
    # fetch() raises APIError with 500
    api_error = APIError("Internal Server Error")
    api_error.status_code = 500
    mock_job.fetch = AsyncMock(side_effect=api_error)

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchError) as exc_info:
            await brightdata_fetcher._fetch_async(request)

        # Should be FetchError, not FetchAuthError
        assert not isinstance(exc_info.value, FetchAuthError)
        assert exc_info.value.platform == "instagram"


# ---- Platform validation tests ----


@pytest.mark.asyncio
async def test_unsupported_platform_raises_fetch_error(brightdata_fetcher):
    """When platform is not facebook/instagram, raise FetchError immediately."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="brightdata",
        urls=["https://youtube.com/c/test"],
    )

    with pytest.raises(FetchError) as exc_info:
        await brightdata_fetcher._fetch_async(request)

    assert "unsupported" in str(exc_info.value).lower()
    assert exc_info.value.platform == "youtube"


@pytest.mark.asyncio
async def test_tiktok_not_supported_in_phase_2(brightdata_fetcher):
    """TikTok is unsupported in Phase 2."""
    request = FetchRequest(
        platform=Platform.TIKTOK,
        extractor="brightdata",
        urls=["https://tiktok.com/@test"],
    )

    with pytest.raises(FetchError) as exc_info:
        await brightdata_fetcher._fetch_async(request)

    assert "unsupported" in str(exc_info.value).lower()


# ---- Sync fetch() wrapper tests ----


def test_fetch_sync_wrapper_calls_async(brightdata_fetcher):
    """fetch() sync wrapper calls _fetch_async via asyncio.run()."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-sync-test"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "profiles": [
                {
                    "username": "testuser",
                    "name": "Test",
                    "bio": "Bio",
                    "followers_count": 0,
                    "posts_count": 0,
                }
            ]
        }
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = brightdata_fetcher.fetch(request)

        assert result.remote_job_id == "job-sync-test"
        assert result.remote_status == "ready"
        assert len(result.items) >= 1


def test_fetch_sync_wrapper_propagates_fetch_timeout_error(brightdata_fetcher):
    """fetch() wrapper propagates FetchTimeoutError from async code."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/test"],
        config={"timeout": 2},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-timeout-sync"
    mock_job.wait = AsyncMock(side_effect=TimeoutError("Timed out"))

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchTimeoutError):
            brightdata_fetcher.fetch(request)


def test_fetch_sync_wrapper_propagates_fetch_auth_error(brightdata_fetcher):
    """fetch() wrapper propagates FetchAuthError from async code."""
    from brightdata.exceptions import AuthenticationError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = AuthenticationError("Unauthorized")

        with pytest.raises(FetchAuthError):
            brightdata_fetcher.fetch(request)


# ---- Parsing tests ----


def test_parse_instagram_profile_response(brightdata_fetcher):
    """Parse Instagram profile response into ProfileResult."""
    raw_data = {
        "profiles": [
            {
                "username": "testuser",
                "name": "Test User",
                "bio": "My bio",
                "followers_count": 1000,
                "posts_count": 50,
                "profile_picture_url": "https://example.com/pic.jpg",
            }
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    assert len(items) == 1
    assert isinstance(items[0], ProfileResult)
    assert items[0].author == "Test User"
    assert items[0].title == "testuser"
    assert items[0].text == "My bio"
    assert items[0].followers_count == 1000
    assert items[0].posts_count == 50
    assert items[0].source_type == SourceType.INSTAGRAM


def test_parse_instagram_posts_response(brightdata_fetcher):
    """Parse Instagram posts response into SocialPostResult with metadata."""
    raw_data = {
        "posts": [
            {
                "id": "123",
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

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    assert len(items) == 1
    assert isinstance(items[0], SocialPostResult)
    assert items[0].text == "Great photo"
    assert items[0].author == "testuser"
    assert items[0].likes_count == 100
    assert items[0].comments_count == 5
    assert len(items[0].media_urls) == 2
    assert items[0].published_at is not None
    assert items[0].source_type == SourceType.INSTAGRAM


def test_parse_instagram_video_post(brightdata_fetcher):
    """Parse Instagram video post as ReelResult."""
    raw_data = {
        "posts": [
            {
                "id": "456",
                "username": "testuser",
                "caption": "Check this video",
                "likes_count": 200,
                "has_video": True,
                "video_duration_seconds": 60,
                "created_at": "2026-01-01T12:00:00Z",
                "media_urls": ["video_url"],
            }
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    assert len(items) == 1
    assert isinstance(items[0], ReelResult)
    assert items[0].source_type == SourceType.INSTAGRAM
    assert items[0].duration_seconds == 60
    assert items[0].likes_count == 200


def test_parse_facebook_posts_response(brightdata_fetcher):
    """Parse Facebook posts response into SocialPostResult."""
    raw_data = {
        "posts": [
            {
                "id": "789",
                "message": "My post",
                "created_time": "2026-01-01T12:00:00Z",
                "from": {"name": "Test Author"},
                "like_count": 50,
                "comment_count": 10,
            }
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert isinstance(items[0], SocialPostResult)
    assert items[0].author == "Test Author"
    assert items[0].text == "My post"
    assert items[0].likes_count == 50
    assert items[0].comments_count == 10
    assert items[0].published_at is not None
    assert items[0].source_type == SourceType.FACEBOOK


def test_parse_facebook_video_response(brightdata_fetcher):
    """Parse Facebook video post as ReelResult."""
    raw_data = {
        "posts": [
            {
                "id": "990",
                "type": "video",
                "message": "Check this",
                "video": {"length": 120},
                "created_time": "2026-01-01T12:00:00Z",
                "from": {"name": "Author"},
                "like_count": 30,
            }
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert isinstance(items[0], ReelResult)
    assert items[0].source_type == SourceType.FACEBOOK
    assert items[0].duration_seconds == 120
    assert items[0].likes_count == 30


def test_empty_response_returns_empty_list(brightdata_fetcher):
    """Empty response returns empty list."""
    items = brightdata_fetcher._parse_response({}, "instagram")
    assert items == []

    items = brightdata_fetcher._parse_response(None, "facebook")
    assert items == []


@pytest.mark.asyncio
async def test_empty_result_error_in_fetch(brightdata_fetcher):
    """FetchEmptyResultError is raised when parsing returns empty list."""
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


def test_parse_error_handling_skips_bad_items(brightdata_fetcher):
    """Parse errors skip bad items but keep good ones."""
    raw_data = {
        "posts": [
            {"id": "good", "message": "OK", "from": {"name": "User"}},
            {"id": "bad"},  # Missing required fields
            {"id": "good2", "message": "Also OK", "from": {"name": "User2"}},
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    # Should have at least the good items
    assert len(items) >= 2
    assert any(item.text == "OK" for item in items)
    assert any(item.text == "Also OK" for item in items)


def test_unparseable_date_handled_gracefully(brightdata_fetcher):
    """Unparseable dates are handled gracefully (None, not exception)."""
    raw_data = {
        "posts": [
            {
                "id": "123",
                "message": "Post",
                "created_time": "invalid-date",
                "from": {"name": "User"},
            }
        ]
    }

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert items[0].published_at is None  # Not parsed, but no exception


@pytest.mark.asyncio
async def test_end_to_end_instagram_fetch_with_parsing(brightdata_fetcher):
    """End-to-end Instagram fetch with full parsing."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-ig-e2e"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "profiles": [
                {
                    "username": "testuser",
                    "name": "Test User",
                    "bio": "My bio",
                    "followers_count": 1000,
                    "posts_count": 50,
                }
            ]
        }
    )

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
        assert isinstance(result.items[0], ProfileResult)
        assert result.items[0].author == "Test User"
        assert result.rows_fetched == 1
        assert result.fetched_at is not None
        assert result.content_hashes is not None
