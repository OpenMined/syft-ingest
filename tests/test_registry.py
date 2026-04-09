"""Tests for fetcher registry: register, get, swap, reset, Protocol validation."""

from __future__ import annotations

import pytest

from syft_ingest.core.models import ContentItem
from syft_ingest.core.registry import (
    FETCHER_REGISTRY,
    get_fetcher,
    register_fetcher,
    reset_registry,
)
from syft_ingest.core.url_router import Platform

# ---- Helpers ----


class _StubFetcher:
    """Minimal class that satisfies the ContentFetcher Protocol."""

    def fetch(self, urls: list[str]) -> list[ContentItem]:
        return []


class _AltFetcher:
    """Alternative fetcher for swap tests."""

    def fetch(self, urls: list[str]) -> list[ContentItem]:
        return []


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
    register_fetcher(Platform.YOUTUBE, stub)
    result = get_fetcher(Platform.YOUTUBE)
    assert result is stub


def test_get_unregistered_raises_key_error():
    """get_fetcher raises KeyError with platform name when no fetcher registered."""
    with pytest.raises(KeyError, match="facebook"):
        get_fetcher(Platform.FACEBOOK)


def test_swap_replaces_fetcher():
    """Registering a second fetcher for the same platform replaces the first."""
    stub = _StubFetcher()
    alt = _AltFetcher()
    register_fetcher(Platform.YOUTUBE, stub)
    register_fetcher(Platform.YOUTUBE, alt)
    result = get_fetcher(Platform.YOUTUBE)
    assert result is alt
    assert result is not stub


def test_reset_clears_registry():
    """reset_registry clears all registrations; get_fetcher raises afterward."""
    register_fetcher(Platform.YOUTUBE, _StubFetcher())
    reset_registry()
    with pytest.raises(KeyError):
        get_fetcher(Platform.YOUTUBE)


def test_register_non_protocol_raises_type_error():
    """Registering an object that does NOT satisfy ContentFetcher raises TypeError."""
    with pytest.raises(TypeError, match="ContentFetcher"):
        register_fetcher(Platform.FACEBOOK, _NotAFetcher())  # type: ignore[arg-type]


def test_multiple_platforms_independent():
    """Multiple platforms can have different fetchers simultaneously."""
    yt_fetcher = _StubFetcher()
    fb_fetcher = _AltFetcher()
    register_fetcher(Platform.YOUTUBE, yt_fetcher)
    register_fetcher(Platform.FACEBOOK, fb_fetcher)

    assert get_fetcher(Platform.YOUTUBE) is yt_fetcher
    assert get_fetcher(Platform.FACEBOOK) is fb_fetcher


def test_registry_dict_accessible():
    """FETCHER_REGISTRY dict is accessible for inspection."""
    stub = _StubFetcher()
    register_fetcher(Platform.TIKTOK, stub)
    assert Platform.TIKTOK in FETCHER_REGISTRY
    assert FETCHER_REGISTRY[Platform.TIKTOK] is stub
