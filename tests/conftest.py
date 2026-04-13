from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent / "data" / "creators" / "syft-influencer-test"


@pytest.fixture(scope="function")
def isolated_registry():
    """Provide isolated fetcher registry state for parallel test execution.

    Captures current registry state, ensures fetchers are registered for the test,
    and restores the original state afterward. Prevents race conditions when tests
    run in parallel with pytest-xdist.
    """
    from syft_ingest.core.registry import (
        FETCHER_REGISTRY,
        register_fetcher,
        reset_registry,
    )
    from syft_ingest.core.url_router import Platform
    from syft_ingest.sources.brightdata import BrightDataFetcher
    from syft_ingest.sources.local import LocalFetcher
    from syft_ingest.sources.youtube import YtDlpFetcher

    # Capture initial state
    initial_state = dict(FETCHER_REGISTRY)

    # Register all fetchers for this test
    try:
        register_fetcher(Platform.YOUTUBE, "yt-dlp", YtDlpFetcher())
    except (KeyError, Exception):
        pass  # May fail if env vars not set, that's ok for isolation

    try:
        register_fetcher(
            Platform.FACEBOOK, "brightdata", BrightDataFetcher(token="test-token")
        )
    except (KeyError, Exception):
        pass

    try:
        register_fetcher(
            Platform.INSTAGRAM, "brightdata", BrightDataFetcher(token="test-token")
        )
    except (KeyError, Exception):
        pass

    register_fetcher(Platform.LOCAL, "local", LocalFetcher())

    yield FETCHER_REGISTRY

    # Restore initial state
    reset_registry()
    for key, fetcher in initial_state.items():
        FETCHER_REGISTRY[key] = fetcher


@pytest.fixture(autouse=True)
def _ensure_isolated_registry(isolated_registry):
    """Auto-use isolated registry for all tests to prevent parallel conflicts."""
    pass


@pytest.fixture
def fb_export_path():
    return DATA_DIR / "fb-page-2026-03-18"


@pytest.fixture
def ig_export_path():
    return DATA_DIR / "instagram-2026-03-18"
