import pytest

from syft_ingest.core.models import SourceType
from syft_ingest.sources._meta_utils import is_bare_url
from syft_ingest.sources.facebook import (
    _extract_post_text,
    _extract_post_url,
    is_facebook_export,
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
    items_with_tags = [item for item in items if item.metadata.get("tags")]
    assert len(items_with_tags) > 0
