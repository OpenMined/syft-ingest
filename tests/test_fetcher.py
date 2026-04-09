"""Tests for ContentFetcher Protocol and FetchError hierarchy."""

from __future__ import annotations

from syft_ingest.core.fetcher import (
    ContentFetcher,
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchTimeoutError,
)
from syft_ingest.core.models import ContentItem

# ---- Helpers ----


class _StubFetcher:
    """Minimal class that satisfies the ContentFetcher Protocol."""

    def fetch(self, urls: list[str]) -> list[ContentItem]:
        return []


class _NotAFetcher:
    """Class that does NOT satisfy the ContentFetcher Protocol."""

    pass


# ---- Protocol tests ----


def test_protocol_satisfied():
    """A class with the correct fetch signature satisfies isinstance check."""
    fetcher = _StubFetcher()
    assert isinstance(fetcher, ContentFetcher)


def test_protocol_rejected():
    """A class missing the fetch method does NOT satisfy isinstance check."""
    obj = _NotAFetcher()
    assert not isinstance(obj, ContentFetcher)


# ---- Error hierarchy tests ----


def test_error_hierarchy():
    """FetchError is the base; all subclasses are proper subclasses."""
    assert issubclass(FetchAuthError, FetchError)
    assert issubclass(FetchTimeoutError, FetchError)
    assert issubclass(FetchEmptyResultError, FetchError)
    assert issubclass(FetchError, Exception)


def test_error_attributes():
    """Each error stores message and optional platform."""
    for cls in (FetchAuthError, FetchTimeoutError, FetchEmptyResultError):
        err = cls(message="something went wrong", platform="facebook")
        assert err.message == "something went wrong"
        assert err.platform == "facebook"

    # platform defaults to None
    err_no_platform = FetchError(message="bare error")
    assert err_no_platform.message == "bare error"
    assert err_no_platform.platform is None


def test_catch_base_error():
    """except FetchError catches all subclass exceptions."""
    for cls in (FetchAuthError, FetchTimeoutError, FetchEmptyResultError):
        try:
            raise cls(message="test")
        except FetchError:
            pass  # expected
        else:
            raise AssertionError(f"{cls.__name__} was not caught by except FetchError")


def test_stub_fetcher_callable():
    """A minimal stub fetcher can be instantiated and called, returning empty list."""
    fetcher = _StubFetcher()
    result = fetcher.fetch(["https://example.com"])
    assert result == []
    assert isinstance(result, list)
