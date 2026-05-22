"""Tests for the public snapshot lifecycle API (syft_ingest.core.lifecycle).

These drive the real download path (download_snapshot → _download_snapshot_data)
with httpx mocked, so they pin the headline guarantees: a resume returns the
same content a fresh fetch would WITHOUT re-triggering, an expired snapshot is a
typed catchable signal, and the planned lifecycle steps fail loud.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syft_ingest import (
    FetchCancelled,
    FetchEmptyResultError,
    SnapshotHandle,
    SnapshotNotFoundError,
    attach,
    cancel,
    download_snapshot,
    poll_status,
    trigger,
)
from syft_ingest.core.models import Corpus
from syft_ingest.sources.brightdata import BrightDataFetcher

# A realistic ready Instagram snapshot body (search/discovery shape).
_IG_SNAPSHOT = [
    {
        "post_id": "1",
        "description": "hello world",
        "user_posted": "nasa",
        "date_posted": "2025-01-01T00:00:00Z",
        "url": "https://instagram.com/p/1",
        "likes": 5,
        "num_comments": 1,
        "content_type": "Image",
        "photos": [],
    }
]


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")


def _stream_response(status_code: int, chunks=None, body: bytes = b""):
    resp = MagicMock()
    resp.status_code = status_code
    _chunks = list(chunks or [])

    async def _aiter_bytes(chunk_size=None):
        for c in _chunks:
            yield c

    resp.aiter_bytes = _aiter_bytes
    resp.aread = AsyncMock(return_value=body)
    return resp


def _patched_httpx(responses):
    resp_iter = iter(responses)

    def _stream(method, url, **kwargs):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=next(resp_iter))
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    client = MagicMock()
    client.stream = MagicMock(side_effect=_stream)
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return patch("syft_ingest.sources.brightdata.httpx.AsyncClient", cls)


# ---- download_snapshot: the headline re-attach guarantee ----


@pytest.mark.asyncio
async def test_download_snapshot_matches_fresh_without_triggering(token_env):
    """Resume returns the SAME content a fresh fetch would normalize, and makes
    ZERO trigger calls (the whole point: no re-collection, no re-bill).

    'Same content' = the items BrightDataFetcher._parse_response produces from
    the identical raw body during a normal fetch. 'No trigger' = the SDK
    BrightDataClient is never even constructed on the resume path.
    """
    raw = json.dumps(_IG_SNAPSHOT).encode()
    expected_items = BrightDataFetcher()._parse_response(_IG_SNAPSHOT, "instagram", {})

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_sdk:
        with _patched_httpx([_stream_response(200, chunks=[raw])]):
            corpus = await download_snapshot("instagram", "sd_ready")

    assert isinstance(corpus, Corpus)
    assert corpus.instagram == expected_items
    # No re-trigger: the SDK client (the only thing that triggers a scrape) was
    # never touched.
    mock_sdk.assert_not_called()


@pytest.mark.asyncio
async def test_download_snapshot_expired_raises_not_found(token_env):
    """An expired/missing snapshot (404) is a typed SnapshotNotFoundError, not a
    crash and not an empty result — so the caller can fall back to a fresh
    trigger deliberately."""
    with _patched_httpx([_stream_response(404, body=b"not found")]):
        with pytest.raises(SnapshotNotFoundError) as exc:
            await download_snapshot("facebook", "sd_expired")
    assert exc.value.snapshot_id == "sd_expired"


@pytest.mark.asyncio
async def test_download_snapshot_cancel_aborts(token_env):
    """A cancel during the resume download raises FetchCancelled (propagated
    from the between-chunks check)."""
    calls = {"n": 0}

    def _cancel() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    with patch("syft_ingest.sources.brightdata._cancel_snapshot", AsyncMock()):
        with _patched_httpx(
            [_stream_response(200, chunks=[b'[{"post_id":"1"}', b"]"])]
        ):
            with pytest.raises(FetchCancelled):
                await download_snapshot(
                    "instagram", "sd_cancel", cancel_callback=_cancel
                )


@pytest.mark.asyncio
async def test_download_snapshot_empty_raises_empty_result(token_env):
    """A ready snapshot with no items raises FetchEmptyResultError (the historic
    'genuinely no content' path), distinct from SnapshotNotFoundError."""
    with _patched_httpx([_stream_response(200, chunks=[b"[]"])]):
        with pytest.raises(FetchEmptyResultError):
            await download_snapshot("instagram", "sd_empty")


@pytest.mark.asyncio
async def test_download_snapshot_rejects_unsupported_platform(token_env):
    """Only platforms we can normalize are downloadable; others fail fast with a
    clear ValueError rather than silently producing an empty Corpus."""
    with pytest.raises(ValueError):
        await download_snapshot("youtube", "sd_x")


# ---- cancel ----


@pytest.mark.asyncio
async def test_cancel_delegates_to_cancel_snapshot():
    """cancel() is a thin wrapper over the best-effort _cancel_snapshot."""
    with patch(
        "syft_ingest.sources.brightdata._cancel_snapshot", AsyncMock()
    ) as mock_cancel:
        await cancel("sd_running")
    mock_cancel.assert_awaited_once_with("sd_running")


@pytest.mark.asyncio
async def test_cancel_accepts_platform_kwarg_without_failing():
    """platform is accepted (call-site symmetry) and ignored — cancel is keyed
    only by snapshot id."""
    with patch(
        "syft_ingest.sources.brightdata._cancel_snapshot", AsyncMock()
    ) as mock_cancel:
        await cancel("sd_running", platform="facebook")
    mock_cancel.assert_awaited_once_with("sd_running")


# ---- signposts: honest, loud failures ----


def test_snapshot_handle_is_frozen_value_object():
    h = SnapshotHandle(platform="facebook", snapshot_id="sd_1")
    assert h.platform == "facebook"
    assert h.snapshot_id == "sd_1"
    with pytest.raises(Exception):
        h.snapshot_id = "sd_2"  # frozen dataclass


@pytest.mark.asyncio
async def test_trigger_stub_raises_with_guidance():
    with pytest.raises(NotImplementedError) as exc:
        await trigger("instagram", ["https://instagram.com/x/"])
    assert "gather" in str(exc.value)


@pytest.mark.asyncio
async def test_poll_status_stub_raises_with_guidance():
    with pytest.raises(NotImplementedError) as exc:
        await poll_status(SnapshotHandle("instagram", "sd_1"))
    assert "gather" in str(exc.value)


@pytest.mark.asyncio
async def test_attach_stub_raises_with_guidance():
    with pytest.raises(NotImplementedError) as exc:
        await attach("instagram", "sd_1")
    assert "download_snapshot" in str(exc.value)
