"""Tests for ContentFetcher Protocol and fetch request/result contracts."""

from __future__ import annotations

from pathlib import Path

from syft_ingest.core.fetcher import (
    ContentFetcher,
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
)
from syft_ingest.core.models import ContentItem
from syft_ingest.core.url_router import Platform

# ---- Helpers ----


class _StubFetcher:
    """Minimal class that satisfies the ContentFetcher Protocol."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            items=[
                ContentItem(
                    title="Sample",
                    author="Tester",
                    source_type="local",
                    url=request.urls[0],
                    text="hello world",
                )
            ],
            rows_fetched=1,
            remote_job_id="remote-job-123",
            remote_status="ready",
            artifact_paths={"raw": Path("/tmp/raw.json")},
        )


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
    """A minimal stub fetcher can be instantiated and called with FetchRequest."""
    fetcher = _StubFetcher()
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://example.com/profile"],
        handle="creator",
        output_dir=Path("/tmp/fetch-output"),
        config={"num_posts": 2},
    )
    result = fetcher.fetch(request)
    assert isinstance(result, FetchResult)
    assert result.rows_fetched == 1
    assert result.remote_job_id == "remote-job-123"
    assert result.remote_status == "ready"
    assert result.artifact_paths["raw"] == Path("/tmp/raw.json")
    assert result.items[0].url == "https://example.com/profile"


def test_fetch_request_carries_worker_context():
    """FetchRequest stores the source/job context the worker already has."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        source_kind="profile-posts",
        urls=["https://www.instagram.com/katykicker/"],
        handle="katykicker",
        profile_url="https://www.instagram.com/katykicker/",
        external_account_id="17841436323898109",
        source_slug="katy-instagram",
        start_date="2026-01-01",
        end_date="2026-02-01",
        output_dir=Path("/tmp/katy"),
        config={"num_posts": 10, "post_type": "reel"},
    )
    assert request.platform == Platform.INSTAGRAM
    assert request.extractor == "brightdata"
    assert request.source_kind == "profile-posts"
    assert request.handle == "katykicker"
    assert request.external_account_id == "17841436323898109"
    assert request.config == {"num_posts": 10, "post_type": "reel"}
