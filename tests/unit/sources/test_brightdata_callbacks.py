"""Tests for BrightData status_callback + cancel_callback hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from syft_ingest import FetchCancelled, FetchError, FetchRequest


def test_fetchcancelled_is_subclass_of_fetcherror():
    """FetchCancelled must inherit from FetchError so existing
    `except FetchError` handlers continue to catch it."""
    assert issubclass(FetchCancelled, FetchError)


def test_fetchcancelled_carries_message_and_platform():
    """FetchCancelled forwards message + platform like other FetchError subclasses."""
    err = FetchCancelled("user requested cancel", platform="facebook")
    assert err.message == "user requested cancel"
    assert err.platform == "facebook"
    assert str(err) == "user requested cancel"


def test_fetchrequest_accepts_status_callback():
    """FetchRequest must accept a status_callback callable."""
    captured: list[tuple[str, str]] = []

    def _on_status(snap_id: str, status: str) -> None:
        captured.append((snap_id, status))

    req = FetchRequest(
        platform="instagram",
        urls=["https://instagram.com/test/"],
        status_callback=_on_status,
    )
    # Field is exposed but excluded from serialization (callable, non-JSON).
    req.status_callback("sd_xyz", "ready")
    assert captured == [("sd_xyz", "ready")]


def test_fetchrequest_accepts_cancel_callback():
    """FetchRequest must accept a cancel_callback() -> bool callable."""
    flag = {"cancelled": False}

    def _should_cancel() -> bool:
        return flag["cancelled"]

    req = FetchRequest(
        platform="facebook",
        urls=["https://facebook.com/test"],
        cancel_callback=_should_cancel,
    )
    assert req.cancel_callback() is False
    flag["cancelled"] = True
    assert req.cancel_callback() is True


def test_fetchrequest_callbacks_default_to_none():
    """Both new callbacks default to None for backward compatibility."""
    req = FetchRequest(
        platform="youtube",
        urls=["https://www.youtube.com/@test"],
    )
    assert req.status_callback is None
    assert req.cancel_callback is None


def test_fetchrequest_callbacks_excluded_from_serialization():
    """Callables can't be JSON-serialized — Pydantic must exclude them."""
    req = FetchRequest(
        platform="instagram",
        urls=["https://instagram.com/test/"],
        status_callback=lambda s, r: None,
        cancel_callback=lambda: False,
    )
    dumped = req.model_dump()
    assert "status_callback" not in dumped
    assert "cancel_callback" not in dumped


@pytest.mark.asyncio
async def test_cancel_snapshot_no_token_logs_warning_and_returns(monkeypatch):
    """When BRIGHTDATA_API_TOKEN is unset, _cancel_snapshot logs a warning
    and returns silently — never raises (best-effort contract)."""
    from syft_ingest.sources.brightdata import _cancel_snapshot

    monkeypatch.delenv("BRIGHTDATA_API_TOKEN", raising=False)

    # Should NOT raise, should NOT make any HTTP call.
    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient") as mock_client_cls:
        await _cancel_snapshot("sd_test123")
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_snapshot_posts_to_correct_url_with_bearer_token(monkeypatch):
    """_cancel_snapshot POSTs to /datasets/v3/snapshot/{id}/cancel with Bearer auth."""
    from syft_ingest.sources.brightdata import _cancel_snapshot

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-abc")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        await _cancel_snapshot("sd_motthp1rn0zlfpwjx")

    mock_client.post.assert_awaited_once_with(
        "https://api.brightdata.com/datasets/v3/snapshot/sd_motthp1rn0zlfpwjx/cancel",
        headers={"Authorization": "Bearer test-token-abc"},
    )
    mock_response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_snapshot_http_error_logs_and_returns(monkeypatch):
    """An HTTP error during cancel is logged but does NOT raise — the
    FetchCancelled exception in the poll loop is the contract surface, not
    the cancel API."""
    from syft_ingest.sources.brightdata import _cancel_snapshot

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-abc")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response
        )
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        # Must NOT raise.
        await _cancel_snapshot("sd_test123")


def _make_mock_job(snapshot_id: str = "sd_test", statuses: list[str] | None = None):
    """Build an AsyncMock job that walks through the given status sequence."""
    job = AsyncMock()
    job.snapshot_id = snapshot_id
    statuses = statuses or ["ready"]
    status_iter = iter(statuses)

    async def _status(refresh: bool = True) -> str:
        return next(status_iter)

    job.status = _status
    return job


@pytest.mark.asyncio
async def test_poll_loop_breaks_on_ready_status():
    """The loop must return cleanly when status reaches 'ready'."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    job = _make_mock_job(statuses=["in_progress", "ready"])
    await _poll_until_ready(
        job,
        request=FetchRequest(platform="instagram", urls=["https://instagram.com/x/"]),
        timeout=10,
        poll_interval=0,  # tests run instant — no real sleep
        platform_name="instagram",
    )
    # No exception raised — that IS the success signal.


@pytest.mark.asyncio
async def test_poll_loop_raises_FetchError_on_failed_status():
    """status='failed' must raise FetchError carrying the snapshot_id."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    job = _make_mock_job(snapshot_id="sd_xyz", statuses=["in_progress", "failed"])

    with pytest.raises(FetchError) as excinfo:
        await _poll_until_ready(
            job,
            request=FetchRequest(platform="facebook", urls=["https://facebook.com/x"]),
            timeout=10,
            poll_interval=0,
            platform_name="facebook",
        )
    assert "sd_xyz" in str(excinfo.value)


@pytest.mark.asyncio
async def test_poll_loop_raises_FetchError_on_error_status():
    """status='error' is treated identically to 'failed'."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    job = _make_mock_job(statuses=["error"])

    with pytest.raises(FetchError):
        await _poll_until_ready(
            job,
            request=FetchRequest(
                platform="instagram", urls=["https://instagram.com/x/"]
            ),
            timeout=10,
            poll_interval=0,
            platform_name="instagram",
        )


@pytest.mark.asyncio
async def test_status_callback_fires_on_each_transition():
    """status_callback fires once per distinct status value (transition-only,
    not every poll tick) with (snapshot_id, status)."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    captured: list[tuple[str, str]] = []

    def _on_status(snap_id: str, status: str) -> None:
        captured.append((snap_id, status))

    job = _make_mock_job(
        snapshot_id="sd_abc",
        statuses=["in_progress", "in_progress", "in_progress", "ready"],
    )
    await _poll_until_ready(
        job,
        request=FetchRequest(
            platform="facebook",
            urls=["https://facebook.com/x"],
            status_callback=_on_status,
        ),
        timeout=10,
        poll_interval=0,
        platform_name="facebook",
    )

    # First synthetic 'triggered' before the loop, then transitions:
    # 'triggered' -> 'in_progress' -> 'ready'. Three repeated 'in_progress'
    # ticks coalesce.
    assert captured == [
        ("sd_abc", "triggered"),
        ("sd_abc", "in_progress"),
        ("sd_abc", "ready"),
    ]


@pytest.mark.asyncio
async def test_status_callback_exceptions_are_swallowed():
    """A buggy status_callback must NOT abort the fetch — the callback is
    a side-channel for observability, not control flow."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    def _broken(snap_id: str, status: str) -> None:
        raise RuntimeError("DB write failed")

    job = _make_mock_job(statuses=["in_progress", "ready"])
    # Should complete normally despite the broken callback.
    await _poll_until_ready(
        job,
        request=FetchRequest(
            platform="instagram",
            urls=["https://instagram.com/x/"],
            status_callback=_broken,
        ),
        timeout=10,
        poll_interval=0,
        platform_name="instagram",
    )


@pytest.mark.asyncio
async def test_poll_loop_raises_FetchTimeoutError_when_deadline_exceeded():
    """If status never reaches 'ready' within `timeout`, FetchTimeoutError
    fires with the snapshot_id in the message."""
    from syft_ingest import FetchTimeoutError
    from syft_ingest.sources.brightdata import _poll_until_ready

    # Job that never returns 'ready'.
    job = AsyncMock()
    job.snapshot_id = "sd_timeout"

    async def _always_in_progress(refresh: bool = True) -> str:
        return "in_progress"

    job.status = _always_in_progress

    with pytest.raises(FetchTimeoutError) as excinfo:
        await _poll_until_ready(
            job,
            request=FetchRequest(platform="facebook", urls=["https://facebook.com/x"]),
            timeout=0,  # already expired — first deadline check fires
            poll_interval=0,
            platform_name="facebook",
        )
    assert "sd_timeout" in str(excinfo.value)


def test_build_request_pops_status_and_cancel_callbacks_from_config():
    """_build_request must lift status_callback / cancel_callback out of the
    `config` kwargs dict and pass them as top-level FetchRequest fields, so
    they reach the fetcher's poll loop instead of being treated as opaque
    extractor config (which would be ignored)."""
    from syft_ingest.core.gather import _build_request

    def _on_status(s: str, r: str) -> None: ...
    def _on_cancel() -> bool:
        return False

    fetcher, request = _build_request(
        platform="instagram",
        urls=["https://instagram.com/test/"],
        author=None,
        status_callback=_on_status,
        cancel_callback=_on_cancel,
    )

    assert request.status_callback is _on_status
    assert request.cancel_callback is _on_cancel
    # And the callbacks must NOT linger in config (would pollute the
    # extractor-specific options).
    assert "status_callback" not in request.config
    assert "cancel_callback" not in request.config


@pytest.mark.asyncio
async def test_cancel_callback_returning_true_raises_FetchCancelled(monkeypatch):
    """When cancel_callback returns True mid-poll, the loop calls
    _cancel_snapshot and raises FetchCancelled."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")

    job = _make_mock_job(
        snapshot_id="sd_cancelme", statuses=["in_progress", "in_progress"]
    )

    cancel_calls = {"n": 0}

    def _cancel_after_first_tick() -> bool:
        cancel_calls["n"] += 1
        return cancel_calls["n"] >= 1  # True from the first check

    # Mock httpx so we can verify _cancel_snapshot got called.
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        with pytest.raises(FetchCancelled) as excinfo:
            await _poll_until_ready(
                job,
                request=FetchRequest(
                    platform="facebook",
                    urls=["https://facebook.com/x"],
                    cancel_callback=_cancel_after_first_tick,
                ),
                timeout=10,
                poll_interval=0,
                platform_name="facebook",
            )

    assert "sd_cancelme" in str(excinfo.value)
    # Cancel API was actually called.
    mock_client.post.assert_awaited_once()
    cancel_url = mock_client.post.await_args.args[0]
    assert cancel_url.endswith("/snapshot/sd_cancelme/cancel")


@pytest.mark.asyncio
async def test_cancel_on_same_tick_as_ready_loses_to_ready(monkeypatch):
    """If cancel_callback would return True but the SAME tick reports 'ready',
    the snapshot completes normally (no cancel API call, no FetchCancelled).
    Status read is sequenced BEFORE the cancel check for exactly this reason."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")

    job = _make_mock_job(snapshot_id="sd_winrace", statuses=["ready"])

    def _always_cancel() -> bool:
        return True

    mock_client_cls = MagicMock()
    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        # Should NOT raise FetchCancelled — ready wins.
        await _poll_until_ready(
            job,
            request=FetchRequest(
                platform="instagram",
                urls=["https://instagram.com/x/"],
                cancel_callback=_always_cancel,
            ),
            timeout=10,
            poll_interval=0,
            platform_name="instagram",
        )

    # Cancel API was never invoked.
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_callback_none_skipped(monkeypatch):
    """Backward compat: a request without cancel_callback never invokes
    httpx and never raises FetchCancelled."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")
    job = _make_mock_job(statuses=["in_progress", "ready"])

    mock_client_cls = MagicMock()
    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        await _poll_until_ready(
            job,
            request=FetchRequest(platform="facebook", urls=["https://facebook.com/x"]),
            timeout=10,
            poll_interval=0,
            platform_name="facebook",
        )
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_api_failure_does_not_mask_FetchCancelled(monkeypatch):
    """If the cancel API itself returns 4xx/5xx, _cancel_snapshot logs and
    swallows it — the loop still raises FetchCancelled so callers see a
    coherent contract."""
    from syft_ingest.sources.brightdata import _poll_until_ready

    monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")
    job = _make_mock_job(snapshot_id="sd_apifail", statuses=["in_progress"])

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_response
        )
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("syft_ingest.sources.brightdata.httpx.AsyncClient", mock_client_cls):
        with pytest.raises(FetchCancelled):
            await _poll_until_ready(
                job,
                request=FetchRequest(
                    platform="facebook",
                    urls=["https://facebook.com/x"],
                    cancel_callback=lambda: True,
                ),
                timeout=10,
                poll_interval=0,
                platform_name="facebook",
            )
