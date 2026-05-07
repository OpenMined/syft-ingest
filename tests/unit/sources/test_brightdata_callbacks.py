"""Tests for BrightData status_callback + cancel_callback hooks."""

from __future__ import annotations

from syft_ingest import FetchCancelled, FetchError


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
