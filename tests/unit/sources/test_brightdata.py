"""Unit tests for BrightDataFetcher authentication and protocol compliance."""

from __future__ import annotations

import pytest

from syft_ingest.core.fetcher import ContentFetcher, FetchAuthError, FetchRequest
from syft_ingest.core.url_router import Platform
from syft_ingest.sources import BrightDataFetcher


class TestBrightDataFetcherAuth:
    """Test suite for BrightDataFetcher authentication handling."""

    def test_brightdata_fetcher_protocol(self, monkeypatch):
        """Verify BrightDataFetcher implements ContentFetcher protocol.

        Tests that an instance of BrightDataFetcher passes the
        runtime_checkable ContentFetcher protocol check.
        """
        monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token-value")
        fetcher = BrightDataFetcher()
        assert isinstance(fetcher, ContentFetcher)

    def test_missing_token_raises_auth_error(self, monkeypatch):
        """Verify FetchAuthError is raised when token is missing.

        Tests that calling BrightDataFetcher() without a token parameter
        and without BRIGHTDATA_API_TOKEN environment variable raises
        FetchAuthError with appropriate message.
        """
        monkeypatch.delenv("BRIGHTDATA_API_TOKEN", raising=False)
        with pytest.raises(FetchAuthError) as exc_info:
            BrightDataFetcher()
        assert "BRIGHTDATA_API_TOKEN" in str(exc_info.value)

    def test_token_from_env(self, monkeypatch):
        """Verify token is loaded from BRIGHTDATA_API_TOKEN environment variable.

        Tests that BrightDataFetcher() without a token parameter loads
        the token from the environment variable and stores it correctly.
        """
        test_token = "test-token-value"
        monkeypatch.setenv("BRIGHTDATA_API_TOKEN", test_token)
        fetcher = BrightDataFetcher()
        assert fetcher._token == test_token

    def test_token_parameter_overrides_env(self, monkeypatch):
        """Verify explicit token parameter overrides environment variable.

        Tests that when both a token parameter and BRIGHTDATA_API_TOKEN
        environment variable are provided, the parameter takes precedence.
        """
        monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "env-token")
        override_token = "override-token"
        fetcher = BrightDataFetcher(token=override_token)
        assert fetcher._token == override_token

    def test_fetch_accepts_fetch_request(self, monkeypatch):
        """Verify fetch() method accepts FetchRequest and has correct signature.

        Tests that the fetch() method exists, accepts a FetchRequest,
        and currently raises NotImplementedError (since _fetch_async is a stub).
        """
        monkeypatch.setenv("BRIGHTDATA_API_TOKEN", "test-token")
        fetcher = BrightDataFetcher()
        request = FetchRequest(
            platform=Platform.INSTAGRAM,
            extractor="bright-data",
            urls=["https://www.instagram.com/testuser"],
        )
        with pytest.raises(NotImplementedError):
            fetcher.fetch(request)
