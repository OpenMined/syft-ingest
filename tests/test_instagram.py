import pytest

from syft_ingest.core.models import SourceType
from syft_ingest.sources._meta_utils import is_bare_url
from syft_ingest.sources.instagram import (
    _extract_post_text,
    is_instagram_export,
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
