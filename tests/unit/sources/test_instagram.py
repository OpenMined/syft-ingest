import json

import pytest

from syft_ingest.core.models import SourceType
from syft_ingest.sources._meta_utils import is_bare_url
from syft_ingest.sources.instagram import (
    _extract_post_text,
    is_instagram_export,
    parse_instagram_brightdata_file,
    parse_instagram_export,
)


def test_extract_post_text_from_title():
    post = {"title": "Hello world"}
    assert _extract_post_text(post) == "Hello world"


def test_extract_post_text_from_media_title():
    post = {"media": [{"title": "Media caption", "uri": "photo.jpg"}]}
    assert _extract_post_text(post) == "Media caption"


def test_extract_post_text_none_when_empty():
    post = {"media": [{"uri": "photo.jpg"}]}
    assert _extract_post_text(post) is None


def test_is_instagram_export(ig_export_path):
    if not ig_export_path.exists():
        pytest.skip("Test data not available")
    assert is_instagram_export(ig_export_path)


def test_is_instagram_export_negative(tmp_path):
    assert not is_instagram_export(tmp_path)


def test_is_instagram_export_detects_brightdata_json(tmp_path):
    brightdata = [
        {
            "url": "https://www.instagram.com/p/DIWPWGpsUQX/",
            "user_posted": "paintedwildflower",
            "description": "Carousel caption #watercolor",
            "hashtags": ["#watercolor", "#painting"],
            "date_posted": "2025-04-12T13:03:14.000Z",
            "photos": [
                "https://cdninstagram.com/example/photo-1.jpg",
                "https://cdninstagram.com/example/photo-2.jpg",
            ],
        }
    ]
    (tmp_path / "brightdata-instagram.json").write_text(
        json.dumps(brightdata), encoding="utf-8"
    )
    assert is_instagram_export(tmp_path)


def test_parse_instagram_export_brightdata_extracts_post_representation(tmp_path):
    brightdata = [
        {
            "url": "https://www.instagram.com/p/DIWPWGpsUQX/",
            "shortcode": "DIWPWGpsUQX",
            "user_posted": "paintedwildflower",
            "description": "Carousel caption #watercolor with @flora",
            "hashtags": ["#painting"],
            "date_posted": "2025-04-12T13:03:14.000Z",
            "photos": [
                "https://cdninstagram.com/example/photo-1.jpg",
                "https://cdninstagram.com/example/photo-2.jpg",
            ],
            "post_content": [
                {
                    "type": "Image",
                    "display_url": "https://cdninstagram.com/example/photo-1.jpg",
                    "alt_text": "Photo by Painted Wildflower",
                }
            ],
        }
    ]
    (tmp_path / "brightdata-instagram.json").write_text(
        json.dumps(brightdata), encoding="utf-8"
    )

    items = parse_instagram_export(tmp_path, author="Fallback Author")
    assert len(items) == 1
    item = items[0]

    assert item.source_type == SourceType.LOCAL
    assert item.author == "paintedwildflower"
    assert item.metadata["platform"] == "instagram"
    assert item.metadata["extractor"] == "brightdata"
    assert item.metadata["tags"] == ["watercolor", "painting"]
    assert item.metadata["mentions"] == ["flora"]
    assert item.metadata["post_ref"]["post_id"] == "DIWPWGpsUQX"
    assert item.metadata["post_ref"]["shortcode"] == "DIWPWGpsUQX"
    assert (
        item.metadata["post_ref"]["url"] == "https://www.instagram.com/p/DIWPWGpsUQX/"
    )

    post_repr = item.metadata["post_representation"]
    assert post_repr["author"] == "paintedwildflower"
    assert post_repr["tags"] == ["watercolor", "painting"]
    assert post_repr["mentions"] == ["flora"]
    assert len(post_repr["media"]) == 2
    assert all(entry["media_type"] == "image" for entry in post_repr["media"])
    assert item.text.startswith(
        "[Instagram post by paintedwildflower | Published: 2025-04-12]"
    )


def test_parse_instagram_brightdata_file_direct(tmp_path):
    brightdata = [
        {
            "url": "https://www.instagram.com/p/direct-1/",
            "shortcode": "direct-1",
            "user_posted": "paintedwildflower",
            "description": "",
            "date_posted": "2025-04-12T13:03:14.000Z",
            "post_content": [
                {
                    "type": "Video",
                    "video_url": "https://cdninstagram.com/example/video-1.mp4",
                }
            ],
        }
    ]
    file_path = tmp_path / "brightdata-instagram-direct.json"
    file_path.write_text(json.dumps(brightdata), encoding="utf-8")

    items = parse_instagram_brightdata_file(file_path, author="Fallback Author")
    assert len(items) == 1
    assert items[0].metadata["extractor"] == "brightdata"
    assert items[0].metadata["post_ref"]["post_id"] == "direct-1"
    media = items[0].metadata["post_representation"]["media"]
    assert len(media) == 1
    assert media[0]["media_type"] == "video"
    assert "Media-only Instagram post." in items[0].text


def test_parse_instagram_brightdata_file_preserves_rich_media_metadata(tmp_path):
    brightdata = [
        {
            "url": "https://www.instagram.com/p/DWCU6pojQMN/",
            "shortcode": "DWCU6pojQMN",
            "user_posted": "katykicker",
            "profile_url": "https://www.instagram.com/katykicker/",
            "description": "Video caption #money with @syftbox",
            "date_posted": "2026-03-18T18:47:21.000Z",
            "content_type": "Video",
            "photos": ["https://cdninstagram.com/example/cover.jpg"],
            "videos": ["https://cdninstagram.com/example/video.mp4"],
            "thumbnail": "https://cdninstagram.com/example/thumb.jpg",
            "audio": {
                "audio_asset_id": "audio-123",
                "original_audio_title": "Original sound",
            },
            "post_content": [
                {
                    "index": 0,
                    "type": "Video",
                    "url": "https://cdninstagram.com/example/video.mp4",
                    "id": "3855736222346183437",
                    "alt_text": None,
                }
            ],
            "latest_comments": [
                {
                    "comments": "Helpful video",
                    "user_commenting": "commenter_1",
                    "date_of_comment": "2026-03-18",
                    "likes": 2,
                }
            ],
        }
    ]
    file_path = tmp_path / "brightdata-instagram-rich.json"
    file_path.write_text(json.dumps(brightdata), encoding="utf-8")

    items = parse_instagram_brightdata_file(file_path, author="Fallback Author")
    assert len(items) == 1
    item = items[0]
    post_repr = item.metadata["post_representation"]

    assert item.author == "katykicker"
    assert item.metadata["profile_url"] == "https://www.instagram.com/katykicker/"
    assert post_repr["content_type"] == "Video"
    assert post_repr["thumbnail_url"] == "https://cdninstagram.com/example/thumb.jpg"
    assert post_repr["audio"]["audio_asset_id"] == "audio-123"
    assert len(post_repr["content_items"]) == 1
    assert len(post_repr["latest_comments"]) == 1
    assert post_repr["latest_comments"][0]["user_commenting"] == "commenter_1"
    media = post_repr["media"]
    assert len(media) == 3
    assert {entry["media_type"] for entry in media} == {"image", "video"}
    assert item.metadata["tags"] == ["money"]
    assert item.metadata["mentions"] == ["syftbox"]


def test_parse_instagram_export_real_data(ig_export_path):
    if not ig_export_path.exists():
        pytest.skip("Test data not available")

    items = parse_instagram_export(ig_export_path, author="Syft Influencer Test")
    assert len(items) > 0

    for item in items:
        assert item.source_type == SourceType.LOCAL
        assert item.author == "Syft Influencer Test"
        assert item.published_at is not None
        assert item.metadata.get("content_hash")
        assert item.metadata.get("platform") == "instagram"
        assert item.text.startswith("[Instagram post by")

    # Encoding should be fixed
    for item in items:
        assert "\u00e2\u0080\u0099" not in item.text
        assert "\u00c2\u00a3" not in item.text

    # No bare-URL-only posts
    for item in items:
        raw_text = item.text.split("\n\n", 1)[-1]
        assert not is_bare_url(raw_text)

    # Should have hashtags on some items
    items_with_tags = [item for item in items if item.metadata.get("tags")]
    assert len(items_with_tags) > 0

    # Cross-post detection: all test data is cross-posted from FB
    items_with_cross_post = [
        item for item in items if item.metadata.get("cross_post_source")
    ]
    assert len(items_with_cross_post) > 0
    for item in items_with_cross_post:
        assert item.metadata["cross_post_source"] == "FB"
