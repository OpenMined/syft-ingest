import json

import pytest

from syft_ingest.core.models import SourceType
from syft_ingest.sources._meta_utils import is_bare_url
from syft_ingest.sources.facebook import (
    _extract_post_text,
    _extract_post_url,
    is_facebook_export,
    parse_facebook_brightdata_file,
    parse_facebook_export,
)


def test_extract_post_text_from_data():
    post = {"data": [{"post": "Hello world"}]}
    assert _extract_post_text(post) == "Hello world"


def test_extract_post_text_fallback_to_media_description():
    post = {
        "data": [{"update_timestamp": 123}],
        "attachments": [{"data": [{"media": {"description": "Fallback text"}}]}],
    }
    assert _extract_post_text(post) == "Fallback text"


def test_extract_post_text_none_when_empty():
    post = {"data": [{"update_timestamp": 123}]}
    assert _extract_post_text(post) is None


def test_extract_post_url_from_external_context():
    post = {
        "attachments": [
            {"data": [{"external_context": {"url": "https://example.com"}}]}
        ],
    }
    assert _extract_post_url(post) == "https://example.com"


def test_extract_post_url_from_text():
    post = {
        "data": [{"post": "Check out https://example.com for more"}],
        "attachments": [],
    }
    assert _extract_post_url(post) == "https://example.com"


def test_is_facebook_export(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")
    assert is_facebook_export(fb_export_path)


def test_is_facebook_export_negative(tmp_path):
    assert not is_facebook_export(tmp_path)


def test_is_facebook_export_detects_brightdata_json(tmp_path):
    brightdata = [
        {
            "post_id": "123",
            "url": "https://www.facebook.com/reel/123/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "Paint #watercolor florals",
            "attachments": [
                {
                    "video_url": "https://video-ord5-3.xx.fbcdn.net/example/video.mp4",
                    "thumbnail_url": (
                        "https://scontent-ord5-1.xx.fbcdn.net/example/thumb.jpg"
                    ),
                }
            ],
        }
    ]
    (tmp_path / "brightdata-sample.json").write_text(
        json.dumps(brightdata), encoding="utf-8"
    )
    assert is_facebook_export(tmp_path)


def test_parse_facebook_export_brightdata_extracts_post_representation(tmp_path):
    brightdata = [
        {
            "post_id": "122243006504090679",
            "url": "https://www.facebook.com/reel/1378171301018195/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "Easy flower tutorial #Watercolor with @Flora",
            "hashtags": ["florals", "#painting"],
            "attachments": [
                {
                    "video_url": "https://video-ord5-3.xx.fbcdn.net/example/video.mp4",
                    "thumbnail_url": (
                        "https://scontent-ord5-1.xx.fbcdn.net/example/thumb.jpg"
                    ),
                }
            ],
        }
    ]
    (tmp_path / "brightdata-sample.json").write_text(
        json.dumps(brightdata), encoding="utf-8"
    )

    items = parse_facebook_export(tmp_path, author="Fallback Author")
    assert len(items) == 1
    item = items[0]

    assert item.source_type == SourceType.LOCAL
    assert item.author == "Painted Wildflowers"  # page name overrides fallback author
    assert item.metadata["platform"] == "facebook"
    assert item.metadata["extractor"] == "brightdata"
    assert item.metadata["post_ref"]["post_id"] == "122243006504090679"
    assert (
        item.metadata["post_ref"]["url"]
        == "https://www.facebook.com/reel/1378171301018195/"
    )

    post_repr = item.metadata["post_representation"]
    assert post_repr["author"] == "Painted Wildflowers"
    assert post_repr["tags"] == ["watercolor", "florals", "painting"]
    assert post_repr["mentions"] == ["flora"]
    assert len(post_repr["media"]) == 2
    assert sum(1 for entry in post_repr["media"] if entry["media_type"] == "video") == 1
    assert sum(1 for entry in post_repr["media"] if entry["media_type"] == "image") == 1


def test_parse_facebook_export_brightdata_keeps_media_only_posts(tmp_path):
    brightdata = [
        {
            "post_id": "media-only-1",
            "url": "https://www.facebook.com/reel/999/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "",
            "attachments": [
                {
                    "video_url": "https://video-ord5-3.xx.fbcdn.net/example/video.mp4",
                }
            ],
        }
    ]
    (tmp_path / "brightdata-media-only.json").write_text(
        json.dumps(brightdata), encoding="utf-8"
    )

    items = parse_facebook_export(tmp_path, author="Fallback Author")
    assert len(items) == 1
    assert "Media-only Facebook post." in items[0].text
    media = items[0].metadata["post_representation"]["media"]
    assert sum(1 for entry in media if entry["media_type"] == "video") == 1
    assert sum(1 for entry in media if entry["media_type"] == "image") == 0


def test_parse_facebook_brightdata_file_direct(tmp_path):
    brightdata = [
        {
            "post_id": "direct-1",
            "url": "https://www.facebook.com/reel/direct-1/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "Direct parse #watercolor",
            "attachments": [
                {
                    "video_url": "https://video-ord5-3.xx.fbcdn.net/example/video.mp4",
                }
            ],
        }
    ]
    file_path = tmp_path / "brightdata-direct.json"
    file_path.write_text(json.dumps(brightdata), encoding="utf-8")

    items = parse_facebook_brightdata_file(
        file_path,
        author="Fallback Author",
    )
    assert len(items) == 1
    assert items[0].metadata["extractor"] == "brightdata"
    assert items[0].metadata["post_ref"]["post_id"] == "direct-1"
    media = items[0].metadata["post_representation"]["media"]
    assert sum(1 for entry in media if entry["media_type"] == "video") == 1


def test_parse_facebook_export_real_data(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    items = parse_facebook_export(fb_export_path, author="Syft Influencer Test")
    assert len(items) > 0

    for item in items:
        assert item.source_type == SourceType.LOCAL
        assert item.author == "Syft Influencer Test"
        assert item.published_at is not None
        assert item.metadata.get("content_hash")
        assert item.metadata.get("platform") == "facebook"
        assert item.text.startswith("[Facebook post by")

    # Encoding should be fixed
    for item in items:
        assert "\u00e2\u0080\u0099" not in item.text  # broken curly quote
        assert "\u00c2\u00a3" not in item.text  # broken pound sign

    # No duplicate URLs
    urls = [item.url for item in items if item.url]
    assert len(urls) == len(set(urls))

    # No bare-URL-only posts
    for item in items:
        raw_text = item.text.split("\n\n", 1)[-1]  # strip context header
        assert not is_bare_url(raw_text)

    # Should have hashtags on some items
    items_with_tags = [
        item
        for item in items
        if item.metadata.get("post_representation", {}).get("tags")
    ]
    assert len(items_with_tags) > 0
