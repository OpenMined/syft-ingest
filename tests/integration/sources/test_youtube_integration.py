"""End-to-end integration tests for YtDlpFetcher registry dispatch and fetch flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from syft_ingest.core.fetcher import (
    FetchEmptyResultError,
    FetchRequest,
)
from syft_ingest.core.models import SourceType, VideoResult
from syft_ingest.core.registry import get_fetcher, reset_registry
from syft_ingest.core.url_router import Platform
from syft_ingest.sources.youtube import YtDlpFetcher


@pytest.fixture(autouse=True)
def setup_teardown():
    """Reset registry before and after each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def ytdlp_fetcher():
    """Create a YtDlpFetcher instance."""
    return YtDlpFetcher()


@pytest.fixture
def sample_video_info():
    """Sample yt-dlp info_dict for a single video with captions.

    Uses yt-dlp's actual subtitle track format: each language maps to a list
    of track dicts with 'url' and 'ext' keys. The json3 track URL is what
    _fetch_and_parse_json3 processes to extract caption segments.
    """
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "description": "This is a test video",
        "uploader": "Test Channel",
        "upload_date": "20260101",
        "duration": 180,
        "view_count": 1000000,
        "like_count": 50000,
        "thumbnail": "https://example.com/thumb.jpg",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "subtitles": {
            "en": [
                {"ext": "vtt", "url": "https://captions.example.com/en.vtt"},
                {"ext": "json3", "url": "https://captions.example.com/en.json3"},
            ]
        },
    }


@pytest.fixture
def sample_channel_info():
    """Sample yt-dlp info_dict for a channel with extract_flat=True."""
    return {
        "id": "UCtest123",
        "title": "Test Channel",
        "entries": [
            {
                "id": "video1",
                "url": "https://www.youtube.com/watch?v=video1",
            },
            {
                "id": "video2",
                "url": "https://www.youtube.com/watch?v=video2",
            },
            {
                "id": "video3",
                "url": "https://www.youtube.com/watch?v=video3",
            },
        ],
    }


# ---- Registry dispatch tests ----


def test_registry_dispatch_youtube(ytdlp_fetcher):
    """get_fetcher(Platform.YOUTUBE, 'yt-dlp') returns YtDlpFetcher."""
    from syft_ingest.core.registry import register_fetcher

    register_fetcher(Platform.YOUTUBE, "yt-dlp", ytdlp_fetcher)
    fetcher = get_fetcher(Platform.YOUTUBE, "yt-dlp")

    assert isinstance(fetcher, YtDlpFetcher)
    assert fetcher is ytdlp_fetcher


def test_fetcher_implements_content_fetcher_protocol(ytdlp_fetcher):
    """YtDlpFetcher implements ContentFetcher protocol."""
    from syft_ingest.core.fetcher import ContentFetcher

    assert isinstance(ytdlp_fetcher, ContentFetcher)


# ---- End-to-end fetch tests ----


def test_end_to_end_single_video_fetch(ytdlp_fetcher, sample_video_info):
    """End-to-end single video fetch: FetchRequest → yt-dlp → FetchResult."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=sample_video_info)
        mock_ydl_class.return_value = mock_ydl

        result = ytdlp_fetcher.fetch(request)

        assert len(result.items) == 1
        assert isinstance(result.items[0], VideoResult)
        assert result.items[0].title == "Test Video"
        assert result.items[0].author == "Test Channel"
        assert result.items[0].duration_seconds == 180
        assert result.items[0].view_count == 1000000
        assert result.items[0].source_type == SourceType.YOUTUBE
        assert result.rows_fetched == 1
        assert result.fetched_at is not None


def test_end_to_end_channel_enumeration(
    ytdlp_fetcher, sample_channel_info, sample_video_info
):
    """End-to-end channel enumeration: enumerate videos, extract metadata."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/channel/UCtest123"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        # First call: enumerate channel (extract_flat=True)
        # Second, third, fourth calls: extract metadata for each video
        def extract_info_side_effect(url, download=False):
            if "channel" in url or "extract_flat" in str(mock_ydl.__dict__):
                return sample_channel_info
            else:
                # Return video metadata
                video_data = sample_video_info.copy()
                video_data["id"] = url.split("=")[-1]
                return video_data

        mock_ydl.extract_info = MagicMock(side_effect=extract_info_side_effect)
        mock_ydl_class.return_value = mock_ydl

        result = ytdlp_fetcher.fetch(request)

        # Should have extracted metadata for all 3 enumerated videos
        assert len(result.items) == 3
        assert all(isinstance(item, VideoResult) for item in result.items)
        assert result.rows_fetched == 3


def test_end_to_end_with_download_config(ytdlp_fetcher, sample_video_info, tmp_path):
    """End-to-end with download_full_video config enabled."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        output_dir=tmp_path,
        config={"download_full_video": True},
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        # Mock both extraction and download
        video_data = sample_video_info.copy()
        video_data["ext"] = "mp4"
        mock_ydl.extract_info = MagicMock(return_value=video_data)
        mock_ydl.download = MagicMock()

        mock_ydl_class.return_value = mock_ydl

        # Create dummy video file to simulate successful download
        video_file = tmp_path / "dQw4w9WgXcQ.mp4"
        video_file.touch()

        result = ytdlp_fetcher.fetch(request)

        assert len(result.items) == 1
        assert result.rows_fetched == 1


def test_end_to_end_video_not_found_error(ytdlp_fetcher):
    """Video not found error is raised as FetchEmptyResultError."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=notfound"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(side_effect=DownloadError("Video not found"))
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(FetchEmptyResultError):
            ytdlp_fetcher.fetch(request)


def test_end_to_end_age_restricted_error(ytdlp_fetcher):
    """Age-restricted video results in FetchEmptyResultError (no items extracted)."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=agerestricted"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(
            side_effect=DownloadError("Video is not available for users")
        )
        mock_ydl_class.return_value = mock_ydl

        # Age-restricted videos are skipped, resulting in no items
        with pytest.raises(FetchEmptyResultError):
            ytdlp_fetcher.fetch(request)


def test_end_to_end_with_custom_timeout(sample_video_info):
    """Custom socket_timeout config is honored."""
    fetcher = YtDlpFetcher(config={"socket_timeout": 5})
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=sample_video_info)
        mock_ydl_class.return_value = mock_ydl

        fetcher.fetch(request)

        # Verify that YoutubeDL was called with socket_timeout=5
        # Check any of the calls (they all should have socket_timeout=5)
        assert any(
            call[0][0].get("socket_timeout") == 5
            for call in mock_ydl_class.call_args_list
        )


def test_end_to_end_with_custom_num_of_posts(sample_channel_info, sample_video_info):
    """Custom num_of_posts config is honored for channel enumeration."""
    fetcher = YtDlpFetcher(config={"num_of_posts": 10})
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/channel/UCtest123"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        # Return channel info on first call, video info on subsequent calls
        extract_calls = [sample_channel_info] + [sample_video_info] * 3
        mock_ydl.extract_info = MagicMock(side_effect=extract_calls)
        mock_ydl_class.return_value = mock_ydl

        fetcher.fetch(request)

        # First call should be with playlistend=10 (yt-dlp's own option, during enumeration)
        first_call_opts = mock_ydl_class.call_args_list[0][0][0]
        assert first_call_opts["playlistend"] == 10


def test_sync_fetch_wrapper(ytdlp_fetcher, sample_video_info):
    """Sync fetch() method works end-to-end."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=sample_video_info)
        mock_ydl_class.return_value = mock_ydl

        # Call sync fetch() method (not async)
        result = ytdlp_fetcher.fetch(request)

        assert result.items is not None
        assert len(result.items) == 1
        assert isinstance(result.items[0], VideoResult)
        assert result.items[0].title == "Test Video"


# ---- Caption extraction integration tests ----


def test_caption_extraction_integrated(ytdlp_fetcher, sample_video_info):
    """Test caption extraction as part of full fetch pipeline.

    Verifies that captions are extracted and stored in metadata
    when videos have subtitles available.
    """
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    parsed_captions = [
        {"text": "Hello", "start": 0.0, "end": 1.5},
        {"text": "This is a test", "start": 1.5, "end": 3.0},
    ]

    with (
        patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class,
        patch.object(
            ytdlp_fetcher,
            "_fetch_and_parse_json3",
            return_value=parsed_captions,
        ),
    ):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=sample_video_info)
        mock_ydl_class.return_value = mock_ydl

        result = ytdlp_fetcher.fetch(request)

        # Verify captions in result
        assert len(result.items) == 1
        video_result = result.items[0]
        assert "captions" in video_result.metadata
        assert "en" in video_result.metadata["captions"]
        captions = video_result.metadata["captions"]["en"]
        assert len(captions) == 2
        assert captions[0]["text"] == "Hello"
        assert captions[0]["start"] == 0.0
        assert captions[0]["end"] == 1.5


def test_captions_in_channel_enumeration(
    ytdlp_fetcher, sample_channel_info, sample_video_info
):
    """Test that captions are extracted for all videos in channel enumeration."""
    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/channel/UCtest123"],
    )

    parsed_captions = [
        {"text": "Hello", "start": 0.0, "end": 1.5},
    ]

    with (
        patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class,
        patch.object(
            ytdlp_fetcher,
            "_fetch_and_parse_json3",
            return_value=parsed_captions,
        ),
    ):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        # First call: enumerate channel
        # Subsequent calls: extract metadata with captions for each video
        def extract_info_side_effect(url, download=False):
            if "channel" in url or "extract_flat" in str(mock_ydl.__dict__):
                return sample_channel_info
            else:
                # Return video metadata with captions (using yt-dlp json3 format)
                video_data = sample_video_info.copy()
                video_data["id"] = url.split("=")[-1]
                return video_data

        mock_ydl.extract_info = MagicMock(side_effect=extract_info_side_effect)
        mock_ydl_class.return_value = mock_ydl

        result = ytdlp_fetcher.fetch(request)

        # Verify all videos have captions
        assert len(result.items) == 3
        for video in result.items:
            assert "captions" in video.metadata
            # sample_video_info has English captions (json3 track format)
            assert "en" in video.metadata["captions"]


def test_missing_captions_in_video_metadata(ytdlp_fetcher):
    """Test that videos without captions still extract successfully.

    Verifies that missing captions don't cause extraction failures.
    """
    video_info_no_captions = {
        "id": "nocaps123",
        "title": "Video Without Captions",
        "description": "This video has no captions",
        "uploader": "Test Channel",
        "upload_date": "20260101",
        "duration": 120,
        "view_count": 500000,
        "like_count": 25000,
        "thumbnail": "https://example.com/thumb.jpg",
        "url": "https://www.youtube.com/watch?v=nocaps123",
        # No 'subtitles' field
    }

    request = FetchRequest(
        platform=Platform.YOUTUBE,
        extractor="yt-dlp",
        urls=["https://www.youtube.com/watch?v=nocaps123"],
    )

    with patch("syft_ingest.sources.youtube.yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=video_info_no_captions)
        mock_ydl_class.return_value = mock_ydl

        result = ytdlp_fetcher.fetch(request)

        # Should still extract successfully
        assert len(result.items) == 1
        video = result.items[0]
        assert video.title == "Video Without Captions"
        # Captions should be present but empty
        assert "captions" in video.metadata
        assert video.metadata["captions"] == {}
