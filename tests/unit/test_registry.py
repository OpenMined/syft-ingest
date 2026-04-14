"""Tests for extractor-aware fetcher registry operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from syft_ingest.core.fetcher import FetchRequest, FetchResult
from syft_ingest.core.registry import (
    FETCHER_REGISTRY,
    FetcherKey,
    get_fetcher,
    register_fetcher,
    reset_registry,
)
from syft_ingest.core.url_router import Platform

# ---- Helpers ----


class _StubFetcher:
    """Minimal class that satisfies the ContentFetcher Protocol."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(rows_fetched=len(request.urls))


class _AltFetcher:
    """Alternative fetcher for swap tests."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(remote_status="swapped")


class _NotAFetcher:
    """Class that does NOT satisfy the ContentFetcher Protocol."""

    pass


# ---- Fixtures ----


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry before and after each test for isolation."""
    reset_registry()
    yield
    reset_registry()


# ---- Tests ----


def test_register_and_get_fetcher():
    """register_fetcher adds to registry; get_fetcher returns the same instance."""
    stub = _StubFetcher()
    register_fetcher(Platform.YOUTUBE, "yt-dlp", stub)
    result = get_fetcher(Platform.YOUTUBE, "yt-dlp")
    assert result is stub


def test_get_unregistered_raises_key_error():
    """get_fetcher raises KeyError with platform and extractor when missing."""
    with pytest.raises(KeyError, match="facebook"):
        get_fetcher(Platform.FACEBOOK, "brightdata")


def test_swap_replaces_fetcher():
    """Registering a second fetcher for the same key replaces the first."""
    stub = _StubFetcher()
    alt = _AltFetcher()
    register_fetcher(Platform.YOUTUBE, "yt-dlp", stub)
    register_fetcher(Platform.YOUTUBE, "yt-dlp", alt)
    result = get_fetcher(Platform.YOUTUBE, "yt-dlp")
    assert result is alt
    assert result is not stub


def test_reset_clears_registry():
    """reset_registry clears all registrations; get_fetcher raises afterward."""
    register_fetcher(Platform.YOUTUBE, "yt-dlp", _StubFetcher())
    reset_registry()
    with pytest.raises(KeyError):
        get_fetcher(Platform.YOUTUBE, "yt-dlp")


def test_register_non_protocol_raises_type_error():
    """Registering an object that does NOT satisfy ContentFetcher raises TypeError."""
    with pytest.raises(TypeError, match="ContentFetcher"):
        register_fetcher(
            Platform.FACEBOOK,
            "brightdata",
            _NotAFetcher(),  # type: ignore[arg-type]
        )


def test_multiple_keys_independent():
    """Different platform/extractor pairs can coexist without clobbering."""
    yt_fetcher = _StubFetcher()
    ig_brightdata = _AltFetcher()
    ig_native = _StubFetcher()
    register_fetcher(Platform.YOUTUBE, "yt-dlp", yt_fetcher)
    register_fetcher(Platform.INSTAGRAM, "brightdata", ig_brightdata)
    register_fetcher(Platform.INSTAGRAM, "native", ig_native)

    assert get_fetcher(Platform.YOUTUBE, "yt-dlp") is yt_fetcher
    assert get_fetcher(Platform.INSTAGRAM, "brightdata") is ig_brightdata
    assert get_fetcher(Platform.INSTAGRAM, "native") is ig_native


def test_registry_dict_uses_fetcher_keys():
    """FETCHER_REGISTRY is inspectable and keyed by platform/extractor."""
    stub = _StubFetcher()
    register_fetcher(Platform.TIKTOK, "brightdata", stub)
    key = FetcherKey(platform=Platform.TIKTOK, extractor="brightdata")
    assert key in FETCHER_REGISTRY
    assert FETCHER_REGISTRY[key] is stub


def test_get_fetcher_normalizes_extractor_case():
    """Extractor lookup is case-insensitive after normalization."""
    stub = _StubFetcher()
    register_fetcher(Platform.INSTAGRAM, "BrightData", stub)
    assert get_fetcher(Platform.INSTAGRAM, "brightdata") is stub
    assert get_fetcher(Platform.INSTAGRAM, " BRIGHTDATA ") is stub


def test_fetcher_can_be_called_after_lookup():
    """Registry consumers get back a fetcher implementing the richer contract."""
    stub = _StubFetcher()
    register_fetcher(Platform.FACEBOOK, "brightdata", stub)
    fetcher = get_fetcher(Platform.FACEBOOK, "brightdata")
    result = fetcher.fetch(
        FetchRequest(
            platform=Platform.FACEBOOK,
            extractor="brightdata",
            urls=["https://www.facebook.com/groups/example"],
            output_dir=Path("/tmp/fb"),
        )
    )
    assert result.rows_fetched == 1


def test_register_async_fetcher():
    """Async fetchers can be registered and retrieved."""
    from syft_ingest.core.fetcher import AsyncContentFetcher, FetchResult

    class _AsyncStubFetcher:
        async def fetch_async(self, request: FetchRequest) -> FetchResult:
            return FetchResult(items=[], rows_fetched=0)

    fetcher = _AsyncStubFetcher()
    register_fetcher(Platform.INSTAGRAM, "test-async", fetcher)
    retrieved = get_fetcher(Platform.INSTAGRAM, "test-async")
    assert retrieved is fetcher
    assert isinstance(retrieved, AsyncContentFetcher)
