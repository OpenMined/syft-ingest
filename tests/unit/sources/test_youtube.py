"""Unit tests for YtDlpFetcher metadata extraction and error handling."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from syft_ingest.core.fetcher import (
    ContentFetcher,
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchTimeoutError,
)
from syft_ingest.core.models import SourceType, VideoResult
from syft_ingest.core.url_router import Platform
from syft_ingest.sources import YtDlpFetcher

# ---- Protocol compliance tests ----


def test_ytdlp_fetcher_protocol():
    """Verify YtDlpFetcher implements ContentFetcher protocol.

    Tests that an instance of YtDlpFetcher passes the
    runtime_checkable ContentFetcher protocol check.
    """
    fetcher = YtDlpFetcher()
    assert isinstance(fetcher, ContentFetcher)


# ---- Initialization tests ----


def test_init_with_default_config():
    """Verify YtDlpFetcher initializes with default config."""
    fetcher = YtDlpFetcher()
    assert fetcher._config["socket_timeout"] == 30
    assert fetcher._config["playlistend"] == 50
    assert fetcher._config["download_full_video"] is False


def test_init_with_custom_config():
    """Verify YtDlpFetcher merges custom config with defaults."""
    custom_config = {"socket_timeout": 5}
    fetcher = YtDlpFetcher(config=custom_config)
    assert fetcher._config["socket_timeout"] == 5
    assert fetcher._config["playlistend"] == 50  # default still present


# ---- Metadata extraction tests ----


@patch("yt_dlp.YoutubeDL")
def test_extract_single_video_metadata(mock_ydl_class):
    """Verify metadata extraction from yt-dlp info dict to VideoResult.

    Tests that _extract_video_info_and_captions correctly maps yt-dlp metadata
    fields (title, duration, view_count, etc.) to VideoResult fields.
    """
    # Setup mock
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Captions returned by _fetch_and_parse_json3 (mocked below)
    parsed_captions = [
        {"text": "Hello world", "start": 0.0, "end": 1.5},
        {"text": "This is a test", "start": 1.5, "end": 3.0},
    ]

    # yt-dlp info dict with json3-format subtitle tracks
    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Video Title",
        "description": "Test video description",
        "uploader": "Test Creator",
        "duration": 600,
        "view_count": 10000,
        "like_count": 500,
        "thumbnail": "https://example.com/thumb.jpg",
        "id": "test_video_id",
        "upload_date": "20260413",
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://example.com/captions_en.json3"}]
        },
    }

    # Create fetcher and patch _fetch_and_parse_json3 to return pre-parsed captions
    fetcher = YtDlpFetcher()
    with patch.object(fetcher, "_fetch_and_parse_json3", return_value=parsed_captions):
        video_result = fetcher._extract_video_info_and_captions(
            "https://youtube.com/watch?v=test"
        )

    # Verify VideoResult fields
    assert isinstance(video_result, VideoResult)
    assert video_result.title == "Test Video Title"
    assert video_result.author == "Test Creator"
    assert video_result.text == "Test video description"
    assert video_result.duration_seconds == 600
    assert video_result.view_count == 10000
    assert video_result.source_type == SourceType.YOUTUBE
    assert video_result.url == "https://youtube.com/watch?v=test"

    # Verify captions in metadata
    assert "captions" in video_result.metadata
    assert "en" in video_result.metadata["captions"]
    assert len(video_result.metadata["captions"]["en"]) == 2
    assert video_result.metadata["captions"]["en"][0]["text"] == "Hello world"
    assert video_result.metadata["captions"]["en"][0]["start"] == 0.0
    assert video_result.metadata["captions"]["en"][0]["end"] == 1.5


@patch("yt_dlp.YoutubeDL")
def test_extract_metadata_with_missing_fields(mock_ydl_class):
    """Verify metadata extraction handles missing fields gracefully.

    Tests that _extract_video_info_and_captions provides defaults when yt-dlp
    info dict is missing optional fields.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Minimal info dict (only title required)
    mock_ydl_instance.extract_info.return_value = {
        "title": "Minimal Video",
        "id": "min_id",
    }

    fetcher = YtDlpFetcher()
    video_result = fetcher._extract_video_info_and_captions(
        "https://youtube.com/watch?v=min"
    )

    assert video_result.title == "Minimal Video"
    assert video_result.author == "Unknown"
    assert video_result.text == ""
    assert video_result.duration_seconds is None
    assert video_result.view_count is None


# ---- Caption extraction tests ----


@patch("yt_dlp.YoutubeDL")
def test_extract_captions_with_timestamps(mock_ydl_class):
    """Verify captions are extracted with timestamps (start, end).

    Tests that _extract_video_info_and_captions captures captions from yt-dlp
    with text and timing information preserved.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    parsed_captions = [
        {"text": "First caption", "start": 0.5, "end": 2.0},
        {"text": "Second caption", "start": 2.0, "end": 4.5},
        {"text": "Third caption", "start": 4.5, "end": 7.0},
    ]

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Video",
        "id": "test_id",
        "uploader": "Test Author",
        "description": "Test desc",
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://example.com/captions_en.json3"}]
        },
    }

    fetcher = YtDlpFetcher()
    with patch.object(fetcher, "_fetch_and_parse_json3", return_value=parsed_captions):
        video_result = fetcher._extract_video_info_and_captions(
            "https://youtube.com/watch?v=test"
        )

    # Verify captions extracted with correct format
    assert "captions" in video_result.metadata
    assert "en" in video_result.metadata["captions"]
    captions_en = video_result.metadata["captions"]["en"]
    assert len(captions_en) == 3

    # Verify first caption
    assert captions_en[0]["text"] == "First caption"
    assert captions_en[0]["start"] == 0.5
    assert captions_en[0]["end"] == 2.0

    # Verify second caption
    assert captions_en[1]["text"] == "Second caption"
    assert captions_en[1]["start"] == 2.0
    assert captions_en[1]["end"] == 4.5


@patch("yt_dlp.YoutubeDL")
def test_captions_stored_in_metadata(mock_ydl_class):
    """Verify captions are stored in VideoResult.metadata['captions'].

    Tests that _extract_video_info_and_captions stores parsed captions in the
    metadata dict under the 'captions' key.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    parsed_captions_by_lang = {
        "https://example.com/captions_en.json3": [
            {"text": "English caption", "start": 0.0, "end": 2.0}
        ],
        "https://example.com/captions_es.json3": [
            {"text": "Spanish caption", "start": 0.0, "end": 2.0}
        ],
        "https://example.com/captions_fr.json3": [
            {"text": "French caption", "start": 0.0, "end": 2.0}
        ],
    }

    mock_ydl_instance.extract_info.return_value = {
        "title": "Multilingual Video",
        "id": "multi_id",
        "uploader": "Test Author",
        "description": "Test desc",
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://example.com/captions_en.json3"}],
            "es": [{"ext": "json3", "url": "https://example.com/captions_es.json3"}],
            "fr": [{"ext": "json3", "url": "https://example.com/captions_fr.json3"}],
        },
    }

    fetcher = YtDlpFetcher(config={"subtitleslangs": ["en", "es", "fr"]})
    with patch.object(
        fetcher,
        "_fetch_and_parse_json3",
        side_effect=lambda url: parsed_captions_by_lang[url],
    ):
        video_result = fetcher._extract_video_info_and_captions(
            "https://youtube.com/watch?v=multi"
        )

    # Verify captions dict exists in metadata
    assert "captions" in video_result.metadata
    captions = video_result.metadata["captions"]

    # Verify all languages present
    assert len(captions) == 3
    assert "en" in captions
    assert "es" in captions
    assert "fr" in captions

    # Verify structure
    assert captions["en"][0]["text"] == "English caption"
    assert captions["es"][0]["text"] == "Spanish caption"
    assert captions["fr"][0]["text"] == "French caption"


@patch("yt_dlp.YoutubeDL")
def test_missing_captions_handled_gracefully(mock_ydl_class):
    """Verify missing captions don't crash extraction.

    Tests that _extract_video_info_and_captions handles videos without captions
    gracefully, storing empty captions dict.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # No subtitles field in response
    mock_ydl_instance.extract_info.return_value = {
        "title": "No Captions Video",
        "id": "no_captions_id",
        "uploader": "Test Author",
        "description": "Video without captions",
    }

    fetcher = YtDlpFetcher()
    video_result = fetcher._extract_video_info_and_captions(
        "https://youtube.com/watch?v=nocaptions"
    )

    # Verify captions key exists but is empty
    assert "captions" in video_result.metadata
    assert video_result.metadata["captions"] == {}
    assert video_result.title == "No Captions Video"


def test_fetch_and_parse_json3_helper_method():
    """Verify _fetch_and_parse_json3 parses caption segments correctly.

    Tests the _fetch_and_parse_json3 method directly to ensure json3
    caption URL fetching and parsing works independently.
    """
    import io
    import json
    from unittest.mock import patch as mock_patch

    fetcher = YtDlpFetcher()

    # Sample YouTube json3 caption format
    json3_data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello"}]},
            {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "World"}]},
            {"tStartMs": 2000, "dDurationMs": 1000, "segs": [{"utf8": "Hola"}]},
        ]
    }
    mock_response = io.BytesIO(json.dumps(json3_data).encode())

    with mock_patch("urllib.request.urlopen", return_value=mock_response):
        result = fetcher._fetch_and_parse_json3("https://example.com/captions.json3")

    # Verify structure
    assert len(result) == 3

    # Verify content and timing
    assert result[0] == {"text": "Hello", "start": 0.0, "end": 1.0}
    assert result[1] == {"text": "World", "start": 1.0, "end": 2.0}
    assert result[2] == {"text": "Hola", "start": 2.0, "end": 3.0}


@patch("yt_dlp.YoutubeDL")
def test_download_not_called_by_default(mock_ydl_class):
    """Verify full video download is NOT called by default.

    Tests that _extract_video_info_and_captions with default config does not
    attempt to download the video file (only captions).
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Video",
        "id": "test_id",
        "uploader": "Test Author",
        "description": "Test desc",
    }

    fetcher = YtDlpFetcher()  # Default: download_full_video=False
    video_result = fetcher._extract_video_info_and_captions(
        "https://youtube.com/watch?v=test"
    )

    # Verify download was not called
    assert "video_file_path" not in video_result.metadata
    # download() should never be called
    mock_ydl_instance.download.assert_not_called()


# ---- Error handling tests ----


@patch("yt_dlp.YoutubeDL")
def test_video_not_found_raises_empty_result_error(mock_ydl_class):
    """Verify FetchEmptyResultError is raised for missing videos.

    Tests that yt-dlp DownloadError containing "not found"
    is classified as FetchEmptyResultError.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    from yt_dlp.utils import DownloadError

    mock_ydl_instance.extract_info.side_effect = DownloadError("Video not found")

    fetcher = YtDlpFetcher()
    with pytest.raises(FetchEmptyResultError) as exc_info:
        fetcher._extract_video_info_and_captions("https://youtube.com/watch?v=notfound")

    assert "not found" in str(exc_info.value).lower()


@patch("yt_dlp.YoutubeDL")
def test_age_restricted_video_raises_auth_error(mock_ydl_class):
    """Verify FetchAuthError is raised for age-restricted videos.

    Tests that yt-dlp DownloadError containing "not available for users"
    is classified as FetchAuthError.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    from yt_dlp.utils import DownloadError

    mock_ydl_instance.extract_info.side_effect = DownloadError(
        "Video is not available for users"
    )

    fetcher = YtDlpFetcher()
    with pytest.raises(FetchAuthError) as exc_info:
        fetcher._extract_video_info_and_captions(
            "https://youtube.com/watch?v=agerestricted"
        )

    assert (
        "age-restricted" in str(exc_info.value).lower()
        or "not available" in str(exc_info.value).lower()
    )


@patch("yt_dlp.YoutubeDL")
def test_socket_timeout_raises_timeout_error(mock_ydl_class):
    """Verify FetchTimeoutError is raised for socket timeouts.

    Tests that socket.timeout exceptions are classified as FetchTimeoutError.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.side_effect = socket.timeout("Connection timed out")

    fetcher = YtDlpFetcher()
    with pytest.raises(FetchTimeoutError):
        fetcher._extract_video_info_and_captions("https://youtube.com/watch?v=slow")


@patch("yt_dlp.YoutubeDL")
def test_download_error_timeout_raises_timeout_error(mock_ydl_class):
    """Verify FetchTimeoutError is raised for DownloadError containing 'timeout'.

    Tests that yt-dlp DownloadError containing "timeout" is classified
    as FetchTimeoutError.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    from yt_dlp.utils import DownloadError

    mock_ydl_instance.extract_info.side_effect = DownloadError("Request timeout")

    fetcher = YtDlpFetcher()
    with pytest.raises(FetchTimeoutError):
        fetcher._extract_video_info_and_captions("https://youtube.com/watch?v=slow2")


# ---- Configuration tests ----


@patch("yt_dlp.YoutubeDL")
def test_config_timeout_passed_to_ydl(mock_ydl_class):
    """Verify custom socket_timeout config is passed to yt-dlp.

    Tests that FetchRequest config with socket_timeout is used
    when creating the YoutubeDL instance.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test",
        "id": "test_id",
    }

    fetcher = YtDlpFetcher(config={"socket_timeout": 5})
    fetcher._extract_video_info_and_captions("https://youtube.com/watch?v=test")

    # Verify YoutubeDL was called with correct timeout
    call_args = mock_ydl_class.call_args
    # call_args[0][0] is the dict passed as first positional argument
    assert call_args[0][0]["socket_timeout"] == 5


# ---- Fetch method tests ----


@patch("yt_dlp.YoutubeDL")
def test_fetch_accepts_fetch_request(mock_ydl_class):
    """Verify fetch() method accepts FetchRequest and returns FetchResult.

    Tests that fetch() can be called with a FetchRequest and returns
    a FetchResult with extracted VideoResult items.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Video",
        "id": "test_id",
        "uploader": "Test Author",
        "description": "Test desc",
    }

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/watch?v=test"],
    )

    result = fetcher.fetch(request)

    assert result.items is not None
    assert len(result.items) == 1
    assert isinstance(result.items[0], VideoResult)
    assert result.items[0].title == "Test Video"
    assert result.fetched_at is not None


@patch("yt_dlp.YoutubeDL")
def test_fetch_multiple_urls(mock_ydl_class):
    """Verify fetch() processes multiple URLs in sequence.

    Tests that fetch() correctly handles multiple URLs and returns
    one VideoResult per successful extraction.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    def side_effect_func(url, download=False):
        video_id = url.split("v=")[-1]
        return {
            "title": f"Video {video_id}",
            "id": video_id,
            "uploader": "Author",
            "description": "Desc",
        }

    mock_ydl_instance.extract_info.side_effect = side_effect_func

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=[
            "https://youtube.com/watch?v=vid1",
            "https://youtube.com/watch?v=vid2",
            "https://youtube.com/watch?v=vid3",
        ],
    )

    result = fetcher.fetch(request)

    assert len(result.items) == 3
    assert result.items[0].title == "Video vid1"
    assert result.items[1].title == "Video vid2"
    assert result.items[2].title == "Video vid3"


@patch("yt_dlp.YoutubeDL")
def test_fetch_with_mixed_success_and_errors(mock_ydl_class):
    """Verify fetch() handles partial success when some URLs fail.

    Tests that if some URLs fail, the successful ones are returned
    and the errors are logged (not raised). This supports channel enumeration
    where some videos may be unavailable.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    from yt_dlp.utils import DownloadError

    # First URL succeeds, second raises error, third succeeds
    mock_ydl_instance.extract_info.side_effect = [
        {"title": "Video 1", "id": "vid1", "uploader": "Author", "description": ""},
        DownloadError("Video not found"),
        {"title": "Video 3", "id": "vid3", "uploader": "Author", "description": ""},
    ]

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=[
            "https://youtube.com/watch?v=vid1",
            "https://youtube.com/watch?v=notfound",
            "https://youtube.com/watch?v=vid3",
        ],
    )

    # Should succeed with 2 items (first and third URLs), skipping second
    result = fetcher.fetch(request)
    assert len(result.items) == 2
    assert result.items[0].title == "Video 1"
    assert result.items[1].title == "Video 3"


# ---- Sync/async bridge tests ----


@patch("yt_dlp.YoutubeDL")
def test_sync_fetch_wrapper(mock_ydl_class):
    """Verify fetch() method works as pure sync.

    Tests that the fetch() method executes synchronously and
    returns the expected FetchResult.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Sync Video",
        "id": "sync_test",
        "uploader": "Test Author",
        "description": "Testing sync wrapper",
    }

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/watch?v=synctest"],
    )

    # Call sync fetch() - should work without errors
    result = fetcher.fetch(request)

    assert result is not None
    assert len(result.items) == 1
    assert result.items[0].title == "Test Sync Video"


# ---- Channel enumeration and download tests (Plan 03-02) ----


def test_is_channel_url_detection():
    """Verify channel URL detection heuristics work correctly."""
    fetcher = YtDlpFetcher()

    # Channel URLs should return True
    assert fetcher._is_channel_url("https://youtube.com/channel/UCXXX") is True
    assert fetcher._is_channel_url("https://youtube.com/@creator") is True
    assert fetcher._is_channel_url("https://youtube.com/c/creator") is True
    assert fetcher._is_channel_url("https://youtube.com/playlist?list=PLxxx") is True

    # Single video URLs should return False
    assert fetcher._is_channel_url("https://youtube.com/watch?v=abcd1234") is False
    assert fetcher._is_channel_url("https://youtu.be/abcd1234") is False


@patch("yt_dlp.YoutubeDL")
def test_enumerate_channel_videos(mock_ydl_class):
    """Verify channel enumeration extracts video URLs with extract_flat.

    Tests that _enumerate_channel uses extract_flat=True and returns
    a list of 5 video URLs from the channel.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Mock channel info with entries
    mock_ydl_instance.extract_info.return_value = {
        "entries": [
            {"url": "https://youtube.com/watch?v=vid1", "id": "vid1"},
            {"url": "https://youtube.com/watch?v=vid2", "id": "vid2"},
            {"url": "https://youtube.com/watch?v=vid3", "id": "vid3"},
            {"url": "https://youtube.com/watch?v=vid4", "id": "vid4"},
            {"url": "https://youtube.com/watch?v=vid5", "id": "vid5"},
        ]
    }

    fetcher = YtDlpFetcher()
    video_urls = fetcher._enumerate_channel(
        "https://youtube.com/channel/UCXXX", limit=50
    )

    assert len(video_urls) == 5
    assert all(url.startswith("https://youtube.com/watch?v=") for url in video_urls)
    assert video_urls[0] == "https://youtube.com/watch?v=vid1"

    # Verify extract_flat was passed to YoutubeDL
    call_args = mock_ydl_class.call_args
    ydl_opts = call_args[0][0]
    assert ydl_opts["extract_flat"] is True
    assert ydl_opts["playlistend"] == 50


@patch("yt_dlp.YoutubeDL")
def test_playlistend_config_respected(mock_ydl_class):
    """Verify playlistend config is passed to yt-dlp during enumeration.

    Tests that custom playlistend config value (10) is used
    when enumerating channel videos.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {"entries": []}

    fetcher = YtDlpFetcher(config={"playlistend": 10})
    fetcher._enumerate_channel("https://youtube.com/channel/UCXXX", limit=10)

    # Verify playlistend=10 was passed to YoutubeDL
    call_args = mock_ydl_class.call_args
    ydl_opts = call_args[0][0]
    assert ydl_opts["playlistend"] == 10


@patch("yt_dlp.YoutubeDL")
def test_channel_enumeration_with_fetch_request(mock_ydl_class):
    """Verify channel enumeration in fetch() request processing.

    Tests that fetch() detects channel URLs and enumerates videos,
    returning 3 VideoResults from 3 enumerated videos.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    def side_effect_func(url, download=False):
        if "channel" in url or "@" in url:
            # Channel enumeration (extract_flat=True)
            return {
                "entries": [
                    {"url": "https://youtube.com/watch?v=ch_vid1", "id": "ch_vid1"},
                    {"url": "https://youtube.com/watch?v=ch_vid2", "id": "ch_vid2"},
                    {"url": "https://youtube.com/watch?v=ch_vid3", "id": "ch_vid3"},
                ]
            }
        else:
            # Single video metadata extraction
            video_id = url.split("v=")[-1]
            return {
                "title": f"Channel Video {video_id}",
                "id": video_id,
                "uploader": "Channel Author",
                "description": "Video from enumeration",
            }

    mock_ydl_instance.extract_info.side_effect = side_effect_func

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/channel/UCXXX"],
    )

    result = fetcher.fetch(request)

    assert len(result.items) == 3
    assert result.items[0].title == "Channel Video ch_vid1"
    assert result.items[1].title == "Channel Video ch_vid2"
    assert result.items[2].title == "Channel Video ch_vid3"


@patch("yt_dlp.YoutubeDL")
def test_single_video_url_not_enumerated(mock_ydl_class):
    """Verify single video URLs skip enumeration.

    Tests that fetch() with a single video URL does not call
    _enumerate_channel and extracts metadata directly.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Single video returns full metadata (not enumeration)
    mock_ydl_instance.extract_info.return_value = {
        "title": "Single Video",
        "id": "single_vid",
        "uploader": "Author",
        "description": "Just one video",
    }

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/watch?v=single_vid"],
    )

    result = fetcher.fetch(request)

    assert len(result.items) == 1
    assert result.items[0].title == "Single Video"
    # extract_info is called once for metadata (captions are reused from first call,
    # no second redundant call). No enumeration occurs for single video URLs.
    assert mock_ydl_instance.extract_info.call_count == 1


@patch("yt_dlp.YoutubeDL")
def test_channel_with_mixed_availability(mock_ydl_class):
    """Verify channel enumeration handles mixed success/failure.

    Tests that when some videos fail (age-restricted, not found),
    successful videos are still returned.
    """

    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    from yt_dlp.utils import DownloadError

    def side_effect_func(url, download=False):
        if "channel" in url or "@" in url:
            # Channel enumeration
            return {
                "entries": [
                    {
                        "url": "https://youtube.com/watch?v=available1",
                        "id": "available1",
                    },
                    {
                        "url": "https://youtube.com/watch?v=restricted",
                        "id": "restricted",
                    },
                    {
                        "url": "https://youtube.com/watch?v=available2",
                        "id": "available2",
                    },
                ]
            }
        else:
            # Video extraction
            video_id = url.split("v=")[-1]
            if "restricted" in video_id:
                raise DownloadError("Video is not available for users")
            else:
                return {
                    "title": f"Available Video {video_id}",
                    "id": video_id,
                    "uploader": "Author",
                    "description": "Available",
                }

    mock_ydl_instance.extract_info.side_effect = side_effect_func

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/channel/UCXXX"],
    )

    result = fetcher.fetch(request)

    # Should have 2 successful items (restricted one skipped)
    assert len(result.items) == 2
    assert result.items[0].title == "Available Video available1"
    assert result.items[1].title == "Available Video available2"


@patch("yt_dlp.YoutubeDL")
def test_download_full_video_when_enabled(mock_ydl_class):
    """Verify video download when config['download_full_video']=True.

    Tests that _download_video creates output_dir and downloads file.
    """
    from pathlib import Path
    from tempfile import TemporaryDirectory

    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Mock successful download
    mock_ydl_instance.download.return_value = 0
    mock_ydl_instance.extract_info.return_value = {
        "id": "test_vid",
        "ext": "mp4",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "downloads"
        # Create a dummy downloaded file
        output_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = output_dir / "test_vid.mp4"
        dummy_file.touch()

        fetcher = YtDlpFetcher(config={"download_full_video": True})
        result_path = fetcher._download_video(
            "https://youtube.com/watch?v=test_vid", output_dir
        )

        assert result_path.exists()
        assert result_path.name == "test_vid.mp4"


@patch("yt_dlp.YoutubeDL")
def test_download_skipped_when_disabled(mock_ydl_class):
    """Verify download is skipped when config['download_full_video']=False.

    Tests that fetch() with download_full_video=False does not
    call _download_video.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.extract_info.return_value = {
        "title": "Test Video",
        "id": "test_vid",
        "uploader": "Author",
        "description": "Test",
    }

    fetcher = YtDlpFetcher(config={"download_full_video": False})
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://youtube.com/watch?v=test_vid"],
    )

    result = fetcher.fetch(request)

    # Verify artifact_paths is empty (no download)
    assert result.artifact_paths == {}
    assert len(result.items) == 1


@patch("yt_dlp.YoutubeDL")
def test_download_creates_output_directory(mock_ydl_class):
    """Verify _download_video creates output_dir if it doesn't exist.

    Tests that calling _download_video with a non-existent path
    creates the directory structure.
    """
    from pathlib import Path
    from tempfile import TemporaryDirectory

    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    mock_ydl_instance.download.return_value = 0
    mock_ydl_instance.extract_info.return_value = {
        "id": "test_vid",
        "ext": "mp4",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "nonexistent" / "path"

        # Create dummy file manually since we're mocking
        output_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = output_dir / "test_vid.mp4"
        dummy_file.touch()

        fetcher = YtDlpFetcher()
        result_path = fetcher._download_video(
            "https://youtube.com/watch?v=test_vid", output_dir
        )

        # Verify directory was created
        assert output_dir.exists()
        assert result_path.exists()


@patch("yt_dlp.YoutubeDL")
def test_download_error_handling(mock_ydl_class):
    """Verify download errors raise FetchError (not FetchAuthError).

    Tests that yt-dlp download failures are classified as FetchError,
    not FetchAuthError.
    """
    from pathlib import Path
    from tempfile import TemporaryDirectory

    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Simulate download failure
    mock_ydl_instance.download.side_effect = Exception("Download failed")

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "downloads"

        fetcher = YtDlpFetcher()
        with pytest.raises(FetchError) as exc_info:
            fetcher._download_video("https://youtube.com/watch?v=test_vid", output_dir)

        # Should be FetchError, not FetchAuthError
        assert isinstance(exc_info.value, FetchError)
        assert not isinstance(exc_info.value, FetchAuthError)


# ---- Delta fetching / start_date / dateafter tests ----


def test_to_ytdlp_date_conversion():
    """Verify _to_ytdlp_date converts ISO dates to yt-dlp YYYYMMDD format.

    Tests both the normal conversion case and the None passthrough.
    """
    fetcher = YtDlpFetcher()

    assert fetcher._to_ytdlp_date("2026-04-01") == "20260401"
    assert fetcher._to_ytdlp_date("2024-01-15") == "20240115"
    assert fetcher._to_ytdlp_date("2020-12-31") == "20201231"
    assert fetcher._to_ytdlp_date(None) is None


@patch("yt_dlp.YoutubeDL")
def test_fetch_channel_with_start_date_filters_old_videos(mock_ydl_class):
    """Verify fetch() with start_date on a channel URL filters old videos.

    Date filtering happens post-extraction in _fetch_async by comparing
    each video's published_at against the start_date cutoff.
    Flat enumeration doesn't have upload dates, so all URLs are enumerated
    but old videos are filtered after metadata extraction.
    """
    mock_ydl_instance = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=None)

    # Call 1: channel enumeration (extract_flat=True) — no dates available
    # Call 2: metadata for video 1 (new, after cutoff)
    # Call 3: metadata for video 2 (old, before cutoff)
    mock_ydl_instance.extract_info.side_effect = [
        {
            "entries": [
                {"url": "https://youtube.com/watch?v=new", "id": "new"},
                {"url": "https://youtube.com/watch?v=old", "id": "old"},
            ]
        },
        {
            "title": "New Video",
            "id": "new",
            "uploader": "Creator",
            "description": "A new video",
            "upload_date": "20260408",
        },
        {
            "title": "Old Video",
            "id": "old",
            "uploader": "Creator",
            "description": "An old video",
            "upload_date": "20180621",
        },
    ]

    fetcher = YtDlpFetcher()
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        urls=["https://youtube.com/@creator"],
        start_date="2026-04-01",
    )

    result = fetcher.fetch(request)

    # Only the new video should pass the date filter
    assert len(result.items) == 1
    assert result.items[0].title == "New Video"
