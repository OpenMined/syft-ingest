"""Tests for BrightData status_callback + cancel_callback hooks."""

from __future__ import annotations

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
