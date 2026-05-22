"""Tests for ContentFetcher Protocol and fetch request/result contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from syft_ingest.core.fetcher import (
    AsyncContentFetcher,
    ContentFetcher,
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
    SnapshotNotFoundError,
    run_fetcher_async,
    run_fetcher_sync,
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
    assert issubclass(SnapshotNotFoundError, FetchError)
    assert issubclass(FetchError, Exception)


def test_snapshot_not_found_error_distinct_from_empty_result():
    """SnapshotNotFoundError must NOT be a subclass of FetchEmptyResultError.

    Defends: an expired/missing snapshot is a *typed, catchable* signal that the
    caller should fall back to a fresh trigger — semantically distinct from
    'the scrape ran but found no posts'. Collapsing the two would make a caller
    treat retention expiry as an empty profile and never re-trigger.
    """
    assert not issubclass(SnapshotNotFoundError, FetchEmptyResultError)


def test_snapshot_not_found_error_carries_snapshot_id():
    """SnapshotNotFoundError forwards message + platform and stores snapshot_id."""
    err = SnapshotNotFoundError(
        "snapshot gone", platform="instagram", snapshot_id="sd_expired"
    )
    assert err.message == "snapshot gone"
    assert err.platform == "instagram"
    assert err.snapshot_id == "sd_expired"


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


# ---- Async protocol helpers ----


class _AsyncStubFetcher:
    """Minimal class that satisfies the AsyncContentFetcher Protocol."""

    async def fetch_async(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            items=[
                ContentItem(
                    title="AsyncSample",
                    author="AsyncTester",
                    source_type="local",
                    url=request.urls[0],
                    text="async hello",
                )
            ],
            rows_fetched=1,
        )


class _NotAnAsyncFetcher:
    """Class that does NOT satisfy AsyncContentFetcher Protocol."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(items=[], rows_fetched=0)


# ---- Async protocol tests ----


def test_async_protocol_satisfied():
    """A class with fetch_async satisfies AsyncContentFetcher isinstance check."""
    fetcher = _AsyncStubFetcher()
    assert isinstance(fetcher, AsyncContentFetcher)


def test_async_protocol_rejected():
    """A class with only sync fetch does NOT satisfy AsyncContentFetcher."""
    fetcher = _NotAnAsyncFetcher()
    assert not isinstance(fetcher, AsyncContentFetcher)


def test_sync_fetcher_does_not_satisfy_async_protocol():
    """A sync-only fetcher does NOT satisfy AsyncContentFetcher."""
    fetcher = _StubFetcher()
    assert not isinstance(fetcher, AsyncContentFetcher)


# ---- Bridge function tests ----


def test_run_fetcher_sync_with_sync_fetcher():
    """run_fetcher_sync dispatches sync fetcher correctly."""
    fetcher = _StubFetcher()
    request = FetchRequest(
        platform=Platform.LOCAL,
        extractor="local",
        urls=["https://example.com/test"],
    )
    result = run_fetcher_sync(fetcher, request)
    assert isinstance(result, FetchResult)
    assert result.rows_fetched == 1
    assert result.items[0].title == "Sample"


def test_run_fetcher_sync_with_async_fetcher():
    """run_fetcher_sync dispatches async fetcher correctly (bridges to sync)."""
    fetcher = _AsyncStubFetcher()
    request = FetchRequest(
        platform=Platform.LOCAL,
        extractor="local",
        urls=["https://example.com/test"],
    )
    result = run_fetcher_sync(fetcher, request)
    assert isinstance(result, FetchResult)
    assert result.rows_fetched == 1
    assert result.items[0].title == "AsyncSample"


@pytest.mark.asyncio
async def test_run_fetcher_async_with_sync_fetcher():
    """run_fetcher_async offloads sync fetcher to thread."""
    fetcher = _StubFetcher()
    request = FetchRequest(
        platform=Platform.LOCAL,
        extractor="local",
        urls=["https://example.com/test"],
    )
    result = await run_fetcher_async(fetcher, request)
    assert isinstance(result, FetchResult)
    assert result.rows_fetched == 1
    assert result.items[0].title == "Sample"


@pytest.mark.asyncio
async def test_run_fetcher_async_with_async_fetcher():
    """run_fetcher_async awaits async fetcher directly."""
    fetcher = _AsyncStubFetcher()
    request = FetchRequest(
        platform=Platform.LOCAL,
        extractor="local",
        urls=["https://example.com/test"],
    )
    result = await run_fetcher_async(fetcher, request)
    assert isinstance(result, FetchResult)
    assert result.rows_fetched == 1
    assert result.items[0].title == "AsyncSample"
