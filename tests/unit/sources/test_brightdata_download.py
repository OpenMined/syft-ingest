"""Tests for the universal streamed snapshot download helper.

``_download_snapshot_data`` is the single download seam shared by every
BrightData platform (Facebook, Instagram, future X/TikTok) and by the
re-attach path (``download_snapshot``). It streams ``GET
/datasets/v3/snapshot/{id}`` and checks ``cancel_callback`` between chunks so a
mid-download cancel aborts within one chunk — that is the whole point of routing
all platforms through it. These tests pin that contract directly, without going
through ``fetch_async``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchCancelled,
    FetchError,
    FetchTimeoutError,
    SnapshotNotFoundError,
)
from syft_ingest.sources.brightdata import _download_snapshot_data


@pytest.fixture
def token_env(monkeypatch):
    """A valid token so the helper does not short-circuit on auth."""
    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")


def _stream_response(status_code: int, chunks=None, body: bytes = b""):
    """Build a mock httpx streamed response.

    ``aiter_bytes`` yields the given chunks (so tests can interleave a cancel
    between them); ``aread`` returns ``body`` for the error-path message.
    """
    resp = MagicMock()
    resp.status_code = status_code
    _chunks = list(chunks or [])

    async def _aiter_bytes(chunk_size=None):
        for c in _chunks:
            yield c

    resp.aiter_bytes = _aiter_bytes
    resp.aread = AsyncMock(return_value=body)
    return resp


def _patched_client(responses):
    """Patch httpx.AsyncClient so client.stream(...) yields ``responses`` in order.

    Returns (patcher, client) — the client exposes .stream call_count so tests
    can assert how many GETs the wait-for-ready loop made.
    """
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
    return patch("syft_ingest.sources.brightdata.httpx.AsyncClient", cls), client


@pytest.mark.asyncio
async def test_returns_parsed_json_across_chunks(token_env):
    """A ready (200) snapshot streamed in multiple chunks parses back to the
    same JSON the upstream sent — proving chunk reassembly is lossless."""
    doc = [{"post_id": "1", "description": "hi"}, {"post_id": "2"}]
    raw = json.dumps(doc).encode()
    patcher, _ = _patched_client(
        [_stream_response(200, chunks=[raw[:7], raw[7:20], raw[20:]])]
    )
    with patcher:
        out = await _download_snapshot_data("sd_ok", platform_name="instagram")
    assert out == doc


@pytest.mark.asyncio
async def test_cancel_between_chunks_raises_and_cancels_upstream(token_env):
    """cancel_callback flipping True mid-stream aborts within one chunk and
    best-effort cancels the upstream snapshot. This is the native mid-download
    cancel the whole design exists for."""
    calls = {"n": 0}

    def _cancel() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2  # False on first chunk, True on second

    patcher, _ = _patched_client(
        [_stream_response(200, chunks=[b'[{"a":1}', b',{"b":2}]'])]
    )
    with patch(
        "syft_ingest.sources.brightdata._cancel_snapshot", AsyncMock()
    ) as mock_cancel:
        with patcher:
            with pytest.raises(FetchCancelled) as exc:
                await _download_snapshot_data(
                    "sd_cancel", platform_name="facebook", cancel_callback=_cancel
                )
    assert "sd_cancel" in str(exc.value)
    # Cancel uses the same resolved credentials the download used (env here).
    mock_cancel.assert_awaited_once_with("sd_cancel", token="test-token")


@pytest.mark.asyncio
async def test_404_raises_snapshot_not_found(token_env):
    """A 404 (retention expired / never created) is a typed SnapshotNotFoundError
    carrying the id, so a resuming caller can fall back to a fresh trigger."""
    patcher, _ = _patched_client([_stream_response(404, body=b"snapshot not found")])
    with patcher:
        with pytest.raises(SnapshotNotFoundError) as exc:
            await _download_snapshot_data("sd_gone", platform_name="instagram")
    assert exc.value.snapshot_id == "sd_gone"


@pytest.mark.asyncio
async def test_waits_when_running_then_downloads(token_env):
    """wait_for_ready=True polls the snapshot endpoint past a 202 (still
    building) until it returns 200, then downloads — the resume case where the
    snapshot we re-attach to has not finished collecting yet."""
    doc = [{"post_id": "1"}]
    raw = json.dumps(doc).encode()
    patcher, client = _patched_client(
        [_stream_response(202), _stream_response(200, chunks=[raw])]
    )
    with patcher:
        out = await _download_snapshot_data(
            "sd_run",
            platform_name="facebook",
            wait_for_ready=True,
            poll_interval=0,
        )
    assert out == doc
    assert client.stream.call_count == 2


@pytest.mark.asyncio
async def test_202_without_wait_raises_timeout(token_env):
    """Without wait_for_ready, a 202 means 'caller said ready but it isn't' —
    surface as FetchTimeoutError (matches the SDK's DataNotReady mapping), not a
    silent empty download."""
    patcher, _ = _patched_client([_stream_response(202)])
    with patcher:
        with pytest.raises(FetchTimeoutError):
            await _download_snapshot_data("sd_busy", platform_name="instagram")


@pytest.mark.asyncio
async def test_no_token_raises_auth_error(monkeypatch):
    """No token → FetchAuthError before any HTTP attempt (boundary defense)."""
    monkeypatch.delenv("BRIGHTDATA_API_TOKEN", raising=False)
    with pytest.raises(FetchAuthError):
        await _download_snapshot_data("sd_x", platform_name="instagram")


@pytest.mark.asyncio
async def test_network_error_mid_stream_wrapped_as_fetch_error(token_env):
    """A raw httpx error mid-download must NOT leak to callers — it is wrapped
    in FetchError. This is the boundary defense download_snapshot relies on:
    unlike fetch_async, the resume path has no outer SDK try/except, so the
    helper itself must never surface httpx.HTTPError."""
    resp = MagicMock()
    resp.status_code = 200

    async def _boom(chunk_size=None):
        yield b'[{"post_id":"1"}'
        raise httpx.ReadError("connection reset mid-stream")

    resp.aiter_bytes = _boom
    resp.aread = AsyncMock(return_value=b"")

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    client = MagicMock()
    client.stream = MagicMock(return_value=cm)
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", cls):
        with pytest.raises(FetchError):
            await _download_snapshot_data("sd_neterr", platform_name="instagram")


@pytest.mark.asyncio
async def test_connect_error_wrapped_as_fetch_error(token_env):
    """A connect-time httpx error (before any status code) is also wrapped."""
    client = MagicMock()
    client.stream = MagicMock(side_effect=httpx.ConnectError("no route"))
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", cls):
        with pytest.raises(FetchError):
            await _download_snapshot_data("sd_conn", platform_name="facebook")


@pytest.mark.asyncio
async def test_emits_ready_status(token_env):
    """status_callback receives (snapshot_id, 'ready') when the download starts,
    so an external orchestrator can report progress on a resume."""
    doc = [{"post_id": "1"}]
    raw = json.dumps(doc).encode()
    seen: list[tuple[str, str]] = []
    patcher, _ = _patched_client([_stream_response(200, chunks=[raw])])
    with patcher:
        await _download_snapshot_data(
            "sd_status",
            platform_name="instagram",
            status_callback=lambda sid, st: seen.append((sid, st)),
        )
    assert ("sd_status", "ready") in seen
