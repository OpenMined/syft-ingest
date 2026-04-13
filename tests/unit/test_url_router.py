"""Tests for URL router — platform detection, validation, and normalization."""

from __future__ import annotations

import pytest

from syft_ingest.core.url_router import (
    AcquisitionMethod,
    InvalidURLError,
    Platform,
    UnsupportedPlatformError,
    resolve_url,
    supported_platforms,
)

# ---------------------------------------------------------------------------
# Happy path: platform detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com/zuck",
        "https://facebook.com/zuck/posts/123",
        "https://m.facebook.com/profile.php?id=100001234",
        "https://fb.com/some.page",
        "https://fb.watch/abc123",
    ],
)
def test_facebook_urls(url: str):
    result = resolve_url(url)
    assert result.platform == Platform.FACEBOOK
    assert result.acquisition_method == AcquisitionMethod.BRIGHT_DATA


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/natgeo/",
        "https://instagram.com/p/ABC123/",
        "https://www.instagram.com/reel/DEF456/",
        "https://instagr.am/stories/user/789/",
    ],
)
def test_instagram_urls(url: str):
    result = resolve_url(url)
    assert result.platform == Platform.INSTAGRAM
    assert result.acquisition_method == AcquisitionMethod.BRIGHT_DATA


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@mkbhd",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/channel/UC123",
        "https://music.youtube.com/watch?v=abc",
    ],
)
def test_youtube_urls(url: str):
    result = resolve_url(url)
    assert result.platform == Platform.YOUTUBE
    assert result.acquisition_method == AcquisitionMethod.YT_DLP


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@charlidamelio",
        "https://tiktok.com/@user/video/123456",
        "https://vm.tiktok.com/ZMx123/",
        "https://m.tiktok.com/@user",
    ],
)
def test_tiktok_urls(url: str):
    result = resolve_url(url)
    assert result.platform == Platform.TIKTOK
    assert result.acquisition_method == AcquisitionMethod.BRIGHT_DATA


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def test_strips_tracking_params():
    url = "https://www.youtube.com/watch?v=abc&utm_source=twitter&feature=share"
    result = resolve_url(url)
    assert "utm_source" not in result.normalized_url
    assert "feature" not in result.normalized_url
    assert "v=abc" in result.normalized_url


def test_strips_fbclid():
    url = "https://www.facebook.com/zuck?fbclid=abc123xyz"
    result = resolve_url(url)
    assert "fbclid" not in result.normalized_url


def test_strips_igshid():
    url = "https://www.instagram.com/natgeo/?igshid=abc123"
    result = resolve_url(url)
    assert "igshid" not in result.normalized_url


def test_strips_tiktok_tracking():
    url = "https://www.tiktok.com/@user?tt_from=copy&is_from_webapp=1"
    result = resolve_url(url)
    assert "tt_from" not in result.normalized_url
    assert "is_from_webapp" not in result.normalized_url


def test_preserves_meaningful_params():
    url = "https://www.youtube.com/watch?v=abc&list=PLxyz"
    result = resolve_url(url)
    assert "v=abc" in result.normalized_url
    assert "list=PLxyz" in result.normalized_url


def test_strips_trailing_slash():
    url = "https://www.instagram.com/natgeo/"
    result = resolve_url(url)
    assert result.normalized_url.endswith("/natgeo")


def test_lowercases_host():
    url = "https://WWW.YOUTUBE.COM/watch?v=abc"
    result = resolve_url(url)
    assert "www.youtube.com" in result.normalized_url


def test_preserves_original_url():
    url = "https://www.youtube.com/@mkbhd?utm_source=twitter"
    result = resolve_url(url)
    assert result.original_url == url
    assert result.normalized_url != url


# ---------------------------------------------------------------------------
# Validation: unsupported platforms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,host",
    [
        ("https://twitter.com/elonmusk", "twitter.com"),
        ("https://www.linkedin.com/in/someone", "www.linkedin.com"),
        ("https://open.spotify.com/show/abc", "open.spotify.com"),
        ("https://www.reddit.com/r/python", "www.reddit.com"),
        ("https://example.com/some/page", "example.com"),
    ],
)
def test_unsupported_raises(url: str, host: str):
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        resolve_url(url)
    assert host in str(exc_info.value)
    assert "Supported:" in str(exc_info.value)


def test_error_lists_supported_platforms():
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        resolve_url("https://twitter.com/user")
    msg = str(exc_info.value)
    for platform in Platform:
        assert platform.value in msg


# ---------------------------------------------------------------------------
# Validation: invalid URLs
# ---------------------------------------------------------------------------


def test_empty_string():
    with pytest.raises(InvalidURLError):
        resolve_url("")


def test_whitespace_only():
    with pytest.raises(InvalidURLError):
        resolve_url("   ")


def test_not_a_string():
    with pytest.raises(InvalidURLError):
        resolve_url(None)  # type: ignore[arg-type]


def test_ftp_scheme():
    with pytest.raises(InvalidURLError, match="scheme"):
        resolve_url("ftp://files.example.com/video.mp4")


def test_no_scheme():
    with pytest.raises(InvalidURLError):
        resolve_url("youtube.com/watch?v=abc")


def test_javascript_scheme():
    with pytest.raises(InvalidURLError, match="scheme"):
        resolve_url("javascript:alert(1)")


def test_data_uri():
    with pytest.raises(InvalidURLError, match="scheme"):
        resolve_url("data:text/html,<h1>hi</h1>")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_url_with_leading_trailing_whitespace():
    result = resolve_url("  https://www.youtube.com/@mkbhd  ")
    assert result.platform == Platform.YOUTUBE


def test_case_insensitive_host():
    result = resolve_url("https://WWW.FACEBOOK.COM/zuck")
    assert result.platform == Platform.FACEBOOK


def test_route_result_is_serializable():
    result = resolve_url("https://www.youtube.com/@mkbhd")
    data = result.model_dump()
    assert data["platform"] == "youtube"
    assert data["acquisition_method"] == "yt-dlp"


# ---------------------------------------------------------------------------
# supported_platforms() helper
# ---------------------------------------------------------------------------


def test_returns_all_platforms():
    platforms = supported_platforms()
    names = {p["platform"] for p in platforms}
    assert names == {p.value for p in Platform}


def test_each_has_acquisition_method():
    for p in supported_platforms():
        assert "acquisition_method" in p
        assert p["acquisition_method"] in {m.value for m in AcquisitionMethod}
