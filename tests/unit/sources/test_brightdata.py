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
    run_fetcher_sync,
)
from syft_ingest.core.models import (
    ContentItem,
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
async def testfetch_async_with_instagram_profile_success(brightdata_fetcher):
    """Successfully fetch Instagram posts via fetch_async (search scraper path)."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        config={"timeout": 30},
    )

    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-001"
    mock_result.data = [
        {
            "post_id": "123",
            "description": "Test caption",
            "user_posted": "testuser",
            "likes": 100,
            "num_comments": 5,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": ["https://example.com/photo.jpg"],
            "url": "https://instagram.com/p/abc123",
        }
    ]

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await brightdata_fetcher.fetch_async(request)

        assert result.remote_job_id == "snap-ig-001"
        assert result.remote_status == "ready"
        assert result.rows_fetched == 1
        assert len(result.items) == 1

        # Verify search was called with correct URL and timeout
        mock_search_ig.posts.assert_called_once_with(
            url="https://instagram.com/testuser",
            timeout=30,
        )


@pytest.mark.asyncio
async def testfetch_async_with_facebook_profile_success(brightdata_fetcher):
    """Successfully fetch Facebook profile via fetch_async."""
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

        result = await brightdata_fetcher.fetch_async(request)

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
async def testfetch_async_uses_default_timeout_and_poll_interval(brightdata_fetcher):
    """When config lacks timeout, Instagram search uses default timeout (180s)."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={},  # Empty config — should use default timeout=180
    )

    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-default"
    mock_result.data = [
        {
            "post_id": "1",
            "description": "Post",
            "user_posted": "testuser",
            "likes": 0,
            "num_comments": 0,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": [],
            "url": "https://instagram.com/p/1",
        }
    ]

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await brightdata_fetcher.fetch_async(request)

        # Verify default timeout was passed to search
        call_kwargs = mock_search_ig.posts.call_args[1]
        assert call_kwargs["timeout"] == 180


# ---- Timeout error tests ----


@pytest.mark.asyncio
async def test_poll_timeout_error_raises_fetch_timeout_error(brightdata_fetcher):
    """When Instagram search raises TimeoutError, raise FetchTimeoutError."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
        config={"timeout": 5},
    )

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    # Simulate timeout during search
    mock_search_ig.posts = AsyncMock(side_effect=TimeoutError("Search timed out"))
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchTimeoutError) as exc_info:
            await brightdata_fetcher.fetch_async(request)

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
            await brightdata_fetcher.fetch_async(request)

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
            await brightdata_fetcher.fetch_async(request)

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
            await brightdata_fetcher.fetch_async(request)

        assert "authentication" in str(exc_info.value).lower()
        assert exc_info.value.platform == "facebook"


# ---- API error tests ----


@pytest.mark.asyncio
async def test_api_error_401_raises_fetch_auth_error(brightdata_fetcher):
    """When Instagram search API returns 401, classify as auth error."""
    from brightdata.exceptions import APIError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    # search.instagram.posts raises APIError with 401
    api_error = APIError("Unauthorized")
    api_error.status_code = 401

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(side_effect=api_error)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchAuthError) as exc_info:
            await brightdata_fetcher.fetch_async(request)

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
            await brightdata_fetcher.fetch_async(request)

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
            await brightdata_fetcher.fetch_async(request)

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
        await brightdata_fetcher.fetch_async(request)

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
        await brightdata_fetcher.fetch_async(request)

    assert "unsupported" in str(exc_info.value).lower()


# ---- Sync bridge tests (via run_fetcher_sync) ----


def test_run_fetcher_sync_with_brightdata(brightdata_fetcher):
    """run_fetcher_sync bridges async BrightDataFetcher to sync callers (Instagram search path)."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-sync-test"
    mock_result.data = [
        {
            "post_id": "1",
            "description": "Sync test post",
            "user_posted": "testuser",
            "likes": 0,
            "num_comments": 0,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": [],
            "url": "https://instagram.com/p/1",
        }
    ]

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        result = run_fetcher_sync(brightdata_fetcher, request)
        assert result.remote_job_id == "snap-sync-test"
        assert len(result.items) >= 1


def test_run_fetcher_sync_propagates_fetch_timeout_error(brightdata_fetcher):
    """run_fetcher_sync propagates FetchTimeoutError from async code."""
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
            run_fetcher_sync(brightdata_fetcher, request)


def test_run_fetcher_sync_propagates_fetch_auth_error(brightdata_fetcher):
    """run_fetcher_sync propagates FetchAuthError from async code."""
    from brightdata.exceptions import AuthenticationError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )
    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = AuthenticationError("Unauthorized")
        with pytest.raises(FetchAuthError):
            run_fetcher_sync(brightdata_fetcher, request)


# ---- Parsing tests ----


def test_parse_instagram_profile_response(brightdata_fetcher):
    """Parse Instagram search-scraper post response into ContentItem."""
    # The search scraper returns a flat list of post dicts
    raw_data = [
        {
            "post_id": "abc123",
            "description": "My bio post",
            "user_posted": "testuser",
            "likes": 1000,
            "num_comments": 50,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": ["https://example.com/pic.jpg"],
            "url": "https://instagram.com/p/abc123",
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    assert len(items) == 1
    assert isinstance(items[0], ContentItem)
    assert items[0].author == "testuser"
    assert items[0].title == "abc123"
    assert items[0].text == "My bio post"
    assert items[0].source_type == SourceType.INSTAGRAM
    assert items[0].metadata["likes"] == 1000


def test_parse_instagram_posts_response(brightdata_fetcher):
    """Parse Instagram legacy profiles_trigger format into ContentItem list."""
    # Legacy profiles_trigger format: profile dict with nested posts list
    raw_data = [
        {
            "account": "testuser",
            "followers": 500,
            "posts_count": 10,
            "posts": [
                {
                    "id": "123",
                    "caption": "Great photo",
                    "likes": 100,
                    "comments": 5,
                    "datetime": "2026-01-01T12:00:00Z",
                    "image_url": "https://example.com/photo.jpg",
                    "content_type": "Image",
                    "url": "https://instagram.com/p/abc123",
                }
            ],
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    # The legacy format produces one ContentItem per nested post (no top-level profile item)
    assert len(items) == 1
    assert isinstance(items[0], ContentItem)
    assert items[0].text == "Great photo"
    assert items[0].author == "testuser"
    assert items[0].metadata["likes"] == 100
    assert items[0].metadata["comments"] == 5
    assert items[0].published_at is not None
    assert items[0].source_type == SourceType.INSTAGRAM


def test_parse_instagram_video_post(brightdata_fetcher):
    """Parse Instagram video post from legacy profiles_trigger format into ContentItem."""
    raw_data = [
        {
            "account": "testuser",
            "followers": 500,
            "posts_count": 5,
            "posts": [
                {
                    "id": "456",
                    "caption": "Check this video",
                    "likes": 200,
                    "comments": 0,
                    "datetime": "2026-01-01T12:00:00Z",
                    "content_type": "Video",
                    "url": "https://instagram.com/p/def456",
                    "video_url": "https://example.com/video.mp4",
                }
            ],
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "instagram")

    # The legacy format produces one ContentItem per nested post (no top-level profile item)
    assert len(items) == 1
    assert isinstance(items[0], ContentItem)
    assert items[0].source_type == SourceType.INSTAGRAM
    assert items[0].metadata["likes"] == 200
    assert items[0].metadata["content_type"] == "Video"


def test_parse_facebook_posts_response(brightdata_fetcher):
    """Parse Facebook posts response into ContentItem."""
    raw_data = [
        {
            "post_id": "789",
            "content": "My post",
            "date_posted": "2026-01-01T12:00:00Z",
            "page_name": "Test Author",
            "url": "https://facebook.com/post/789",
            "likes": 50,
            "num_comments": 10,
            "num_shares": 0,
            "post_type": "Post",
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert isinstance(items[0], ContentItem)
    assert items[0].author == "Test Author"
    assert items[0].text == "My post"
    assert items[0].metadata["likes"] == 50
    assert items[0].metadata["num_comments"] == 10
    assert items[0].published_at is not None
    assert items[0].source_type == SourceType.FACEBOOK


def test_parse_facebook_video_response(brightdata_fetcher):
    """Parse Facebook video/reel post into ContentItem."""
    raw_data = [
        {
            "post_id": "990",
            "content": "Check this",
            "date_posted": "2026-01-01T12:00:00Z",
            "page_name": "Author",
            "url": "https://facebook.com/reel/990",
            "likes": 30,
            "num_comments": 0,
            "num_shares": 0,
            "post_type": "Reel",
            "video_view_count": 100,
            "attachments": [{"type": "Video", "video_length": "120000"}],
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert isinstance(items[0], ContentItem)
    assert items[0].source_type == SourceType.FACEBOOK
    assert items[0].metadata["likes"] == 30
    assert items[0].metadata["post_type"] == "Reel"


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
            await brightdata_fetcher.fetch_async(request)


def test_parse_error_handling_skips_bad_items(brightdata_fetcher):
    """Parse errors skip bad items but keep good ones."""
    raw_data = [
        {
            "post_id": "good",
            "content": "OK",
            "page_name": "User",
            "url": "https://fb.com/1",
            "post_type": "Post",
        },
        {
            "post_id": "bad"
        },  # Missing fields but still parseable (content defaults to "")
        {
            "post_id": "good2",
            "content": "Also OK",
            "page_name": "User2",
            "url": "https://fb.com/3",
            "post_type": "Post",
        },
    ]

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    # All items should parse (content defaults to empty string for bad item)
    assert len(items) >= 2
    assert any(item.text == "OK" for item in items)
    assert any(item.text == "Also OK" for item in items)


def test_unparseable_date_handled_gracefully(brightdata_fetcher):
    """Unparseable dates are handled gracefully (None, not exception)."""
    raw_data = [
        {
            "post_id": "123",
            "content": "Post",
            "date_posted": "invalid-date",
            "page_name": "User",
            "url": "https://fb.com/123",
            "post_type": "Post",
        }
    ]

    items = brightdata_fetcher._parse_response(raw_data, "facebook")

    assert len(items) == 1
    assert items[0].published_at is None  # Not parsed, but no exception


# ---- start_date date conversion tests ----


def test_to_sdk_date_converts_iso_to_mm_dd_yyyy():
    """_to_sdk_date converts YYYY-MM-DD to MM-DD-YYYY (BrightData SDK format)."""
    fetcher = BrightDataFetcher(token="test-token")
    assert fetcher._to_sdk_date("2026-04-01") == "04-01-2026"
    assert fetcher._to_sdk_date("2026-12-31") == "12-31-2026"


def test_to_sdk_date_returns_none_for_none():
    """_to_sdk_date returns None when no date provided."""
    fetcher = BrightDataFetcher(token="test-token")
    assert fetcher._to_sdk_date(None) is None


def test_to_sdk_date_raises_for_invalid_format():
    """_to_sdk_date raises ValueError for non-ISO date strings."""
    fetcher = BrightDataFetcher(token="test-token")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fetcher._to_sdk_date("01-04-2026")  # Wrong format (MM-DD-YYYY input)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fetcher._to_sdk_date("not-a-date")


# ---- start_date passthrough tests (Facebook) ----


@pytest.mark.asyncio
async def test_facebook_trigger_includes_start_date_when_provided(brightdata_fetcher):
    """When start_date is set on FetchRequest, it is passed to posts_by_profile_trigger."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/testuser"],
        start_date="2026-04-01",
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-fb-date"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value=[
            {
                "post_id": "p1",
                "content": "April post",
                "date_posted": "2026-04-02T00:00:00Z",
                "page_name": "Test Page",
                "url": "https://facebook.com/p/p1",
            }
        ]
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        await brightdata_fetcher.fetch_async(request)

    call_kwargs = mock_scraper.posts_by_profile_trigger.call_args[1]
    assert call_kwargs.get("start_date") == "04-01-2026"  # Converted to MM-DD-YYYY


@pytest.mark.asyncio
async def test_facebook_trigger_omits_start_date_when_none(brightdata_fetcher):
    """When start_date is None, posts_by_profile_trigger is called without start_date kwarg."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/testuser"],
        # No start_date
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-fb-nodate"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value=[
            {
                "post_id": "p1",
                "content": "Post",
                "date_posted": "2026-01-01T00:00:00Z",
                "page_name": "Test Page",
                "url": "https://facebook.com/p/p1",
            }
        ]
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        await brightdata_fetcher.fetch_async(request)

    call_kwargs = mock_scraper.posts_by_profile_trigger.call_args[1]
    assert "start_date" not in call_kwargs  # Must not pass start_date=None to SDK


# ---- start_date passthrough tests (Instagram) ----


@pytest.mark.asyncio
async def test_instagram_search_includes_start_date_when_provided(brightdata_fetcher):
    """When start_date is set on FetchRequest, it is passed to search.instagram.posts."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        start_date="2026-04-01",
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-date"
    mock_result.data = [
        {
            "post_id": "ig1",
            "description": "April post",
            "user_posted": "testuser",
            "likes": 10,
            "num_comments": 0,
            "date_posted": "2026-04-02T00:00:00Z",
            "content_type": "Image",
            "photos": [],
            "url": "https://instagram.com/p/ig1",
        }
    ]

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        await brightdata_fetcher.fetch_async(request)

    call_kwargs = mock_search_ig.posts.call_args[1]
    assert call_kwargs.get("start_date") == "04-01-2026"  # Converted to MM-DD-YYYY


@pytest.mark.asyncio
async def test_instagram_search_omits_start_date_when_none(brightdata_fetcher):
    """When start_date is None, search.instagram.posts is called without start_date kwarg."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
        # No start_date
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-nodate"
    mock_result.data = [
        {
            "post_id": "ig1",
            "description": "Post",
            "user_posted": "testuser",
            "likes": 5,
            "num_comments": 0,
            "date_posted": "2026-01-01T00:00:00Z",
            "content_type": "Image",
            "photos": [],
            "url": "https://instagram.com/p/ig1",
        }
    ]

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        await brightdata_fetcher.fetch_async(request)

    call_kwargs = mock_search_ig.posts.call_args[1]
    assert "start_date" not in call_kwargs  # Must not pass start_date=None to SDK


# ---- gather() integration (unit level) ----


def test_gather_passes_start_date_to_fetch_request(monkeypatch):
    """start_date passed to gather() ends up in FetchRequest.start_date (not config dict)."""
    from syft_ingest.core import gather as gather_module

    captured_requests = []

    def fake_run_fetcher_sync(fetcher, request):
        captured_requests.append(request)
        from syft_ingest.core.fetcher import FetchResult

        return FetchResult(items=[])

    monkeypatch.setattr(gather_module, "run_fetcher_sync", fake_run_fetcher_sync)
    monkeypatch.setattr(gather_module, "_fetchers_registered", True)

    from unittest.mock import MagicMock

    dummy_fetcher = MagicMock()
    dummy_fetcher.fetch = MagicMock(return_value=None)

    from syft_ingest.core import registry as registry_module

    monkeypatch.setattr(
        registry_module, "get_fetcher", lambda platform, extractor: dummy_fetcher
    )

    from syft_ingest.core.gather import gather

    gather("facebook", ["https://facebook.com/testuser"], start_date="2026-04-01")

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.start_date == "2026-04-01"
    assert "start_date" not in req.config  # Must NOT leak into config dict


@pytest.mark.asyncio
async def test_end_to_end_instagram_fetch_with_parsing(brightdata_fetcher):
    """End-to-end Instagram fetch with full parsing (search scraper path)."""
    from unittest.mock import MagicMock

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
    )

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-e2e"
    mock_result.data = [
        {
            "post_id": "post-001",
            "description": "My caption",
            "user_posted": "testuser",
            "likes": 1000,
            "num_comments": 50,
            "date_posted": "2026-01-01T12:00:00Z",
            "content_type": "Image",
            "photos": ["https://example.com/photo.jpg"],
            "url": "https://instagram.com/p/post001",
        }
    ]

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
        assert result.rows_fetched == 1
        assert result.fetched_at is not None
        assert result.content_hashes is not None


# ---- engine_timeout kwarg and env-var resolution ----


def test_init_default_engine_timeout_matches_sdk(valid_token, monkeypatch):
    """Default engine_timeout is 30s (the underlying SDK's default)."""
    monkeypatch.delenv("BRIGHTDATA_ENGINE_TIMEOUT", raising=False)
    fetcher = BrightDataFetcher(token="test-token")
    assert fetcher._engine_timeout == 30


def test_init_engine_timeout_kwarg_overrides_default(valid_token, monkeypatch):
    """Explicit engine_timeout kwarg wins over the default."""
    monkeypatch.delenv("BRIGHTDATA_ENGINE_TIMEOUT", raising=False)
    fetcher = BrightDataFetcher(token="test-token", engine_timeout=120)
    assert fetcher._engine_timeout == 120


def test_init_engine_timeout_env_var_applies(valid_token, monkeypatch):
    """BRIGHTDATA_ENGINE_TIMEOUT env var is used when no kwarg is passed."""
    monkeypatch.setenv("BRIGHTDATA_ENGINE_TIMEOUT", "90")
    fetcher = BrightDataFetcher(token="test-token")
    assert fetcher._engine_timeout == 90


def test_init_engine_timeout_kwarg_wins_over_env(valid_token, monkeypatch):
    """An explicit engine_timeout kwarg overrides the env var."""
    monkeypatch.setenv("BRIGHTDATA_ENGINE_TIMEOUT", "200")
    fetcher = BrightDataFetcher(token="test-token", engine_timeout=60)
    assert fetcher._engine_timeout == 60


def test_init_engine_timeout_invalid_env_falls_back(valid_token, monkeypatch):
    """Non-integer env var value is ignored; falls back to the SDK default."""
    monkeypatch.setenv("BRIGHTDATA_ENGINE_TIMEOUT", "not-a-number")
    fetcher = BrightDataFetcher(token="test-token")
    assert fetcher._engine_timeout == 30


def test_init_engine_timeout_non_positive_env_falls_back(valid_token, monkeypatch):
    """Zero or negative env var values are ignored; falls back to SDK default."""
    monkeypatch.setenv("BRIGHTDATA_ENGINE_TIMEOUT", "0")
    assert BrightDataFetcher(token="test-token")._engine_timeout == 30
    monkeypatch.setenv("BRIGHTDATA_ENGINE_TIMEOUT", "-5")
    assert BrightDataFetcher(token="test-token")._engine_timeout == 30


@pytest.mark.asyncio
async def test_fetch_async_passes_engine_timeout_to_brightdata_client(valid_token):
    """The engine_timeout kwarg flows into BrightDataClient as `timeout=...`."""
    fetcher = BrightDataFetcher(token="test-token", engine_timeout=120)
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/testuser"],
    )

    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.snapshot_id = "snap-ig-timeout"
    mock_result.data = []

    mock_client = AsyncMock()
    mock_search_ig = AsyncMock()
    mock_search_ig.posts = AsyncMock(return_value=mock_result)
    mock_client.search.instagram = mock_search_ig

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client
        # Empty results raise FetchEmptyResultError — fine, we only care about
        # how BrightDataClient was constructed.
        with pytest.raises(FetchEmptyResultError):
            await fetcher.fetch_async(request)

    mock_client_class.assert_called_once()
    call_kwargs = mock_client_class.call_args.kwargs
    assert call_kwargs.get("token") == "test-token"
    assert call_kwargs.get("timeout") == 120
