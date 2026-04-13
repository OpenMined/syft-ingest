# Sync/Async Fetcher Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fake async wrappers with a clean two-protocol system where sync fetchers implement `fetch()`, async fetchers implement `fetch_async()`, and the framework bridges between them automatically.

**Architecture:** Two protocols (`ContentFetcher` for sync, `AsyncContentFetcher` for async) with a `Fetcher` union type. Two bridge functions (`run_fetcher_sync`, `run_fetcher_async`) in `fetcher.py` handle dispatch. Two gather functions (`gather`, `async_gather`) in `gather.py` provide the public API. Each fetcher implements only its natural I/O model.

**Tech Stack:** Python 3.12+, asyncio, concurrent.futures, Pydantic, pytest, pytest-asyncio

---

## File Structure

| File | Role |
|---|---|
| `syft_ingest/core/fetcher.py` | Protocols (`ContentFetcher`, `AsyncContentFetcher`), `Fetcher` union, `run_fetcher_sync()`, `run_fetcher_async()`, error hierarchy (unchanged) |
| `syft_ingest/core/gather.py` | `gather()` (sync), `async_gather()` (async), shared `_build_request()` helper |
| `syft_ingest/core/registry.py` | Registry accepting `Fetcher` union type |
| `syft_ingest/sources/youtube.py` | Pure sync `YtDlpFetcher` — no async, no `run_async` |
| `syft_ingest/sources/brightdata.py` | Pure async `BrightDataFetcher` — no sync wrapper, no `run_async` |
| `syft_ingest/__init__.py` | Updated exports |
| `tests/unit/test_fetcher.py` | Protocol + bridge tests |
| `tests/unit/sources/test_youtube.py` | Updated for sync-only fetcher |
| `tests/unit/sources/test_brightdata.py` | Updated for async-only fetcher |
| `tests/conftest.py` | No changes needed (registry fixture works with `Fetcher` union) |

---

### Task 1: Add AsyncContentFetcher protocol and bridge functions to fetcher.py

**Files:**
- Modify: `syft_ingest/core/fetcher.py`
- Test: `tests/unit/test_fetcher.py`

- [ ] **Step 1: Write failing tests for AsyncContentFetcher protocol and bridges**

Add these tests to `tests/unit/test_fetcher.py`:

```python
import asyncio
from syft_ingest.core.fetcher import (
    AsyncContentFetcher,
    run_fetcher_sync,
    run_fetcher_async,
)


# ---- Async protocol tests ----


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_fetcher.py -v -k "async_protocol or run_fetcher"`
Expected: FAIL — `AsyncContentFetcher`, `run_fetcher_sync`, `run_fetcher_async` not defined

- [ ] **Step 3: Implement AsyncContentFetcher protocol and bridge functions**

In `syft_ingest/core/fetcher.py`, replace `run_async` and add the new protocol + bridges. The file's imports section becomes:

```python
from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from syft_ingest.core.models import ContentItem
from syft_ingest.core.url_router import Platform
```

Delete the entire `run_async` function (lines 33-49) and the `T = TypeVar("T")` on line 30. Replace with:

```python
@runtime_checkable
class AsyncContentFetcher(Protocol):
    """Strategy interface for async platform-specific content fetching.

    Implementations with native async I/O (e.g. BrightData SDK) implement
    this protocol. The framework bridges to sync callers automatically.
    """

    async def fetch_async(self, request: FetchRequest) -> FetchResult:
        """Fetch content asynchronously.

        Args:
            request: Platform/extractor-specific acquisition request.

        Returns:
            Structured result containing normalized content plus tracking metadata.

        Raises:
            FetchAuthError: Credentials missing or rejected.
            FetchTimeoutError: Scrape/poll exceeded timeout.
            FetchEmptyResultError: Scrape succeeded but returned zero items.
        """
        ...


# Union type for registry — fetchers implement one or the other
Fetcher = Union[ContentFetcher, AsyncContentFetcher]


async def run_fetcher_async(fetcher: Fetcher, request: FetchRequest) -> FetchResult:
    """Async bridge — dispatch to sync or async fetcher transparently.

    AsyncContentFetcher -> await directly
    ContentFetcher -> offload to thread pool via asyncio.to_thread()
    """
    if isinstance(fetcher, AsyncContentFetcher):
        return await fetcher.fetch_async(request)
    return await asyncio.to_thread(fetcher.fetch, request)


def run_fetcher_sync(fetcher: Fetcher, request: FetchRequest) -> FetchResult:
    """Sync bridge — Jupyter-safe wrapper around run_fetcher_async.

    Detects running event loop (Jupyter) and falls back to thread pool.
    """
    coro = run_fetcher_async(fetcher, request)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — normal Python
        return asyncio.run(coro)

    # Already in an event loop (Jupyter, etc.) — run in a worker thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
```

Place `AsyncContentFetcher` right after the existing `ContentFetcher` protocol (after line 236). Place `Fetcher`, `run_fetcher_async`, and `run_fetcher_sync` right after `AsyncContentFetcher`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_fetcher.py -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add syft_ingest/core/fetcher.py tests/unit/test_fetcher.py
git commit -m "feat: add AsyncContentFetcher protocol and bridge functions

Add dual-protocol system: ContentFetcher (sync) and AsyncContentFetcher (async).
Add run_fetcher_sync/run_fetcher_async bridge functions.
Remove run_async helper — bridging is now the framework's job."
```

---

### Task 2: Update registry to accept Fetcher union type

**Files:**
- Modify: `syft_ingest/core/registry.py`
- Test: `tests/unit/test_registry.py`

- [ ] **Step 1: Read current test_registry.py to understand existing tests**

Read `tests/unit/test_registry.py` to see what needs updating.

- [ ] **Step 2: Write failing test for async fetcher registration**

Add to `tests/unit/test_registry.py`:

```python
from syft_ingest.core.fetcher import AsyncContentFetcher, FetchRequest, FetchResult


class _AsyncStubFetcher:
    """Minimal async fetcher for registry tests."""

    async def fetch_async(self, request: FetchRequest) -> FetchResult:
        return FetchResult(items=[], rows_fetched=0)


def test_register_async_fetcher():
    """Async fetchers can be registered and retrieved."""
    from syft_ingest.core.registry import register_fetcher, get_fetcher

    fetcher = _AsyncStubFetcher()
    register_fetcher(Platform.INSTAGRAM, "test-async", fetcher)
    retrieved = get_fetcher(Platform.INSTAGRAM, "test-async")
    assert retrieved is fetcher
    assert isinstance(retrieved, AsyncContentFetcher)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry.py::test_register_async_fetcher -v`
Expected: FAIL — `TypeError: Expected ContentFetcher`

- [ ] **Step 4: Update registry to accept Fetcher union type**

In `syft_ingest/core/registry.py`, change the import:

```python
from syft_ingest.core.fetcher import AsyncContentFetcher, ContentFetcher, Fetcher
```

Update `FETCHER_REGISTRY` type:

```python
FETCHER_REGISTRY: dict[FetcherKey, Fetcher] = {}
```

Update `register_fetcher` signature and isinstance check:

```python
def register_fetcher(
    platform: Platform,
    extractor: str,
    fetcher: Fetcher,
) -> None:
    """Register a fetcher implementation for a platform/extractor pair."""
    if not isinstance(fetcher, (ContentFetcher, AsyncContentFetcher)):
        raise TypeError(f"Expected ContentFetcher or AsyncContentFetcher, got {type(fetcher).__name__}")
    # ... rest unchanged
```

Update `get_fetcher` return type:

```python
def get_fetcher(platform: Platform, extractor: str) -> Fetcher:
```

- [ ] **Step 5: Run all registry tests**

Run: `uv run pytest tests/unit/test_registry.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add syft_ingest/core/registry.py tests/unit/test_registry.py
git commit -m "feat: update registry to accept sync and async fetchers

Registry now accepts Fetcher union type (ContentFetcher | AsyncContentFetcher).
Both sync and async fetchers can be registered and retrieved."
```

---

### Task 3: Convert YtDlpFetcher to pure sync

**Files:**
- Modify: `syft_ingest/sources/youtube.py`
- Modify: `tests/unit/sources/test_youtube.py`

- [ ] **Step 1: Convert YtDlpFetcher to pure sync**

In `syft_ingest/sources/youtube.py`:

1. Remove `run_async` from imports (line 34):
   ```python
   # Remove this line:
   # from syft_ingest.core.fetcher import (..., run_async)
   # Keep:
   from syft_ingest.core.fetcher import (
       FetchAuthError,
       FetchEmptyResultError,
       FetchError,
       FetchRequest,
       FetchResult,
       FetchTimeoutError,
   )
   ```

2. Replace `fetch()` method (lines 88-106) — inline the logic from `_fetch_async`, remove the `run_async` bridge:
   ```python
   def fetch(self, request: FetchRequest) -> FetchResult:
       """Fetch and extract metadata for YouTube videos or channels.
       ...
       """
       # (entire body of current _fetch_async, but without async/await keywords)
   ```

3. Delete `async def _fetch_async` — its body is now in `fetch()`.

4. Convert all `async def` methods to plain `def`:
   - `async def _enumerate_channel(...)` → `def _enumerate_channel(...)`
   - `async def _extract_video_info_and_captions(...)` → `def _extract_video_info_and_captions(...)`
   - `async def _download_video(...)` → `def _download_video(...)`

5. Remove all `await` keywords from method bodies (there are `await self._enumerate_channel(...)`, `await self._extract_video_info_and_captions(...)`, `await self._download_video(...)` calls — change to plain calls).

The full `fetch()` method becomes the current `_fetch_async` body with all `async`/`await` removed. No other logic changes.

- [ ] **Step 2: Update test_youtube.py — remove asyncio.run wrappers**

In `tests/unit/sources/test_youtube.py`, every test that calls `asyncio.run(fetcher._extract_video_info_and_captions(...))` or `asyncio.run(fetcher._enumerate_channel(...))` or `asyncio.run(fetcher._download_video(...))` should be changed to a direct call:

- `asyncio.run(fetcher._extract_video_info_and_captions(url))` → `fetcher._extract_video_info_and_captions(url)`
- `asyncio.run(fetcher._enumerate_channel(url, limit=50))` → `fetcher._enumerate_channel(url, limit=50)`
- `asyncio.run(fetcher._download_video(url, output_dir))` → `fetcher._download_video(url, output_dir)`

Remove `import asyncio` from tests that no longer need it (tests that only used it for `asyncio.run`).

The `fetch()` method tests (`test_fetch_accepts_fetch_request`, `test_fetch_multiple_urls`, `test_fetch_with_mixed_success_and_errors`, `test_sync_fetch_wrapper`, `test_channel_enumeration_with_fetch_request`, etc.) already call `fetcher.fetch(request)` directly — no changes needed for those.

- [ ] **Step 3: Run all YouTube tests**

Run: `uv run pytest tests/unit/sources/test_youtube.py -v`
Expected: All PASS

- [ ] **Step 4: Verify protocol compliance still holds**

Run: `uv run pytest tests/unit/sources/test_youtube.py::test_ytdlp_fetcher_protocol -v`
Expected: PASS — `YtDlpFetcher` still satisfies `ContentFetcher`

- [ ] **Step 5: Commit**

```bash
git add syft_ingest/sources/youtube.py tests/unit/sources/test_youtube.py
git commit -m "refactor: convert YtDlpFetcher to pure sync

Remove fake async wrapper. All methods are plain def.
No async/await keywords — yt-dlp is sync-native.
Framework bridge handles async callers via asyncio.to_thread."
```

---

### Task 4: Convert BrightDataFetcher to pure async

**Files:**
- Modify: `syft_ingest/sources/brightdata.py`
- Modify: `tests/unit/sources/test_brightdata.py`

- [ ] **Step 1: Convert BrightDataFetcher to pure async**

In `syft_ingest/sources/brightdata.py`:

1. Remove `run_async` from imports (line 29):
   ```python
   # Remove run_async from this import:
   from syft_ingest.core.fetcher import (
       FetchAuthError,
       FetchEmptyResultError,
       FetchError,
       FetchRequest,
       FetchResult,
       FetchTimeoutError,
   )
   ```

2. Also remove the `import asyncio as asyncio_module` on line 14 (unused after removing `run_async`).

3. Delete the sync `fetch()` method (lines 87-104) entirely.

4. Rename `_fetch_async` to `fetch_async` (lines 106→ becomes the protocol method):
   ```python
   async def fetch_async(self, request: FetchRequest) -> FetchResult:
       """Trigger/poll/fetch lifecycle using the Bright Data SDK.
       ... (same docstring, same body, just renamed from _fetch_async)
       """
   ```

- [ ] **Step 2: Update test_brightdata.py — rename _fetch_async to fetch_async**

In `tests/unit/sources/test_brightdata.py`, replace all occurrences of `_fetch_async` with `fetch_async`:

- `await brightdata_fetcher._fetch_async(request)` → `await brightdata_fetcher.fetch_async(request)`

This affects tests:
- `test_fetch_async_with_instagram_profile_success` (line 88)
- `test_fetch_async_with_facebook_profile_success` (line 143)
- `test_fetch_async_uses_default_timeout_and_poll_interval` (line 196)
- `test_poll_timeout_error_raises_fetch_timeout_error` (line 231)
- `test_data_not_ready_error_raises_fetch_timeout_error` (line 252)
- `test_validation_error_raises_fetch_auth_error` (line 287)
- `test_authentication_error_raises_fetch_auth_error` (line 308)
- `test_api_error_401_raises_fetch_auth_error` (line 345)
- `test_api_error_403_raises_fetch_auth_error` (line 379)
- `test_api_error_500_raises_fetch_error` (line 411)
- `test_unsupported_platform_raises_fetch_error` (line 431)
- `test_tiktok_not_supported_in_phase_2` (line 447)
- `test_empty_result_error_in_fetch` (line 708)
- `test_end_to_end_instagram_fetch_with_parsing` (line 782)

Also update the sync wrapper tests (lines 452-534). These tested `brightdata_fetcher.fetch(request)` which no longer exists. Replace them with tests that use `run_fetcher_sync`:

```python
from syft_ingest.core.fetcher import run_fetcher_sync


# ---- Sync bridge tests (replaces old sync fetch() wrapper tests) ----


def test_run_fetcher_sync_with_brightdata(brightdata_fetcher):
    """run_fetcher_sync bridges async BrightDataFetcher to sync callers."""
    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-sync-test"
    mock_job.wait = AsyncMock()
    mock_job.fetch = AsyncMock(
        return_value={
            "profiles": [
                {
                    "username": "testuser",
                    "name": "Test",
                    "bio": "Bio",
                    "followers_count": 0,
                    "posts_count": 0,
                }
            ]
        }
    )

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.profiles_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.instagram = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = run_fetcher_sync(brightdata_fetcher, request)

        assert result.remote_job_id == "job-sync-test"
        assert result.remote_status == "ready"
        assert len(result.items) >= 1


def test_run_fetcher_sync_propagates_fetch_timeout_error(brightdata_fetcher):
    """run_fetcher_sync propagates FetchTimeoutError from async code."""
    request = FetchRequest(
        platform=Platform.FACEBOOK,
        extractor="brightdata",
        urls=["https://facebook.com/test"],
        config={"timeout": 2},
    )

    mock_job = AsyncMock()
    mock_job.snapshot_id = "job-timeout-sync"
    mock_job.wait = AsyncMock(side_effect=TimeoutError("Timed out"))

    mock_client = AsyncMock()
    mock_scraper = AsyncMock()
    mock_scraper.posts_by_profile_trigger = AsyncMock(return_value=mock_job)
    mock_client.scrape.facebook = mock_scraper

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(FetchTimeoutError):
            run_fetcher_sync(brightdata_fetcher, request)


def test_run_fetcher_sync_propagates_fetch_auth_error(brightdata_fetcher):
    """run_fetcher_sync propagates FetchAuthError from async code."""
    from brightdata.exceptions import AuthenticationError

    request = FetchRequest(
        platform=Platform.INSTAGRAM,
        extractor="brightdata",
        urls=["https://instagram.com/test"],
    )

    with patch("syft_ingest.sources.brightdata.BrightDataClient") as mock_client_class:
        mock_client_class.side_effect = AuthenticationError("Unauthorized")

        with pytest.raises(FetchAuthError):
            run_fetcher_sync(brightdata_fetcher, request)
```

- [ ] **Step 3: Run all BrightData tests**

Run: `uv run pytest tests/unit/sources/test_brightdata.py -v`
Expected: All PASS

- [ ] **Step 4: Verify async protocol compliance**

Run: `uv run python -c "from syft_ingest.sources.brightdata import BrightDataFetcher; from syft_ingest.core.fetcher import AsyncContentFetcher; f = BrightDataFetcher(token='test'); print(isinstance(f, AsyncContentFetcher))"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add syft_ingest/sources/brightdata.py tests/unit/sources/test_brightdata.py
git commit -m "refactor: convert BrightDataFetcher to pure async

Remove sync fetch() wrapper. Public method is now fetch_async().
Framework bridge handles sync callers via run_fetcher_sync."
```

---

### Task 5: Add async_gather and refactor gather.py

**Files:**
- Modify: `syft_ingest/core/gather.py`

- [ ] **Step 1: Refactor gather.py**

Replace the entire content of `syft_ingest/core/gather.py` with:

```python
from __future__ import annotations

from loguru import logger

from syft_ingest.core.fetcher import FetchRequest, run_fetcher_async, run_fetcher_sync
from syft_ingest.core.models import Corpus
from syft_ingest.core.registry import get_fetcher
from syft_ingest.core.url_router import Platform

_fetchers_registered = False


def _ensure_fetchers() -> None:
    """Register fetchers on first use, not at import time."""
    global _fetchers_registered
    if not _fetchers_registered:
        from syft_ingest.setup import register_fetchers

        register_fetchers()
        _fetchers_registered = True


def _build_request(
    platform: str,
    urls: list[str] | None,
    author: str,
    **config,
) -> tuple[Platform, FetchRequest]:
    """Validate inputs and build FetchRequest. Shared by gather/async_gather."""
    if not urls:
        raise ValueError(f"Platform '{platform}' requires urls list")

    p = Platform(platform)

    request_config = dict(config)
    if author:
        request_config["author"] = author

    request = FetchRequest(
        platform=p,
        urls=urls,
        config=request_config,
    )
    return p, request


def gather(
    platform: str,
    urls: list[str] | None = None,
    author: str = "",
    **config,
) -> Corpus:
    """Gather content from a platform — sync entry point.

    Usage:
        corpus = gather("youtube", ["https://youtube.com/watch?v=..."])
        corpus = gather("instagram", ["https://instagram.com/user/"])
        corpus = gather("local", ["/path/to/export"], author="Andrej Karpathy")

    Args:
        platform: Platform name ("youtube", "facebook", "instagram", "tiktok", "local")
        urls: List of URLs or local directory paths to fetch from
        author: Optional author/person name for metadata
        **config: Fetcher-specific config options

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    _ensure_fetchers()
    corpus = Corpus(person=author)

    try:
        p, request = _build_request(platform, urls, author, **config)
        fetcher = get_fetcher(p, request.extractor)
        result = run_fetcher_sync(fetcher, request)
        corpus.add(result.items)
        logger.info(f"Gathered {len(result.items)} items from {platform}")
    except ValueError as e:
        logger.error(f"Invalid platform: {e}")
        raise
    except KeyError as e:
        logger.error(f"No fetcher registered for {platform}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to fetch from {platform}: {e}")
        raise

    return corpus


async def async_gather(
    platform: str,
    urls: list[str] | None = None,
    author: str = "",
    **config,
) -> Corpus:
    """Gather content from a platform — async entry point.

    Usage:
        corpus = await async_gather("youtube", ["https://youtube.com/watch?v=..."])
        corpus = await async_gather("instagram", ["https://instagram.com/user/"])

    Args:
        platform: Platform name ("youtube", "facebook", "instagram", "tiktok", "local")
        urls: List of URLs or local directory paths to fetch from
        author: Optional author/person name for metadata
        **config: Fetcher-specific config options

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    _ensure_fetchers()
    corpus = Corpus(person=author)

    try:
        p, request = _build_request(platform, urls, author, **config)
        fetcher = get_fetcher(p, request.extractor)
        result = await run_fetcher_async(fetcher, request)
        corpus.add(result.items)
        logger.info(f"Gathered {len(result.items)} items from {platform}")
    except ValueError as e:
        logger.error(f"Invalid platform: {e}")
        raise
    except KeyError as e:
        logger.error(f"No fetcher registered for {platform}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to fetch from {platform}: {e}")
        raise

    return corpus
```

- [ ] **Step 2: Run existing gather tests**

Run: `uv run pytest tests/ -v -k "gather"`
Expected: All PASS (existing gather tests use sync path which still works)

- [ ] **Step 3: Commit**

```bash
git add syft_ingest/core/gather.py
git commit -m "feat: add async_gather and refactor gather.py

Add async_gather() for async callers (Jupyter, async servers).
Extract _build_request() to share between gather/async_gather.
gather() now uses run_fetcher_sync bridge instead of calling fetcher.fetch() directly."
```

---

### Task 6: Update public API exports

**Files:**
- Modify: `syft_ingest/__init__.py`

- [ ] **Step 1: Update __init__.py exports**

Replace `syft_ingest/__init__.py` with:

```python
from syft_ingest.core.fetcher import (
    AsyncContentFetcher,
    ContentFetcher,
    FetchAuthError,
    FetchConfig,
    FetchEmptyResultError,
    FetchError,
    Fetcher,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
    run_fetcher_async,
    run_fetcher_sync,
)
from syft_ingest.core.gather import async_gather, gather
from syft_ingest.core.ingest import (
    ChunkingSpec,
    Embedder,
    EmbeddingSpec,
    IngestError,
    IngestReport,
    MissingDependencyError,
    NoDocumentsError,
    QdrantDestination,
    UnsupportedBackendError,
    ingest_corpus,
    ingest_jsonl,
)
from syft_ingest.core.registry import FetcherKey, get_fetcher, register_fetcher
from syft_ingest.core.source_specs import SocialProfileSource, SourceSpec

__all__ = [
    "AsyncContentFetcher",
    "ChunkingSpec",
    "ContentFetcher",
    "Embedder",
    "EmbeddingSpec",
    "FetchAuthError",
    "FetchConfig",
    "FetchEmptyResultError",
    "FetchError",
    "Fetcher",
    "FetcherKey",
    "FetchRequest",
    "FetchResult",
    "FetchTimeoutError",
    "IngestError",
    "IngestReport",
    "MissingDependencyError",
    "NoDocumentsError",
    "QdrantDestination",
    "SocialProfileSource",
    "SourceSpec",
    "UnsupportedBackendError",
    "async_gather",
    "gather",
    "get_fetcher",
    "ingest_corpus",
    "ingest_jsonl",
    "register_fetcher",
    "run_fetcher_async",
    "run_fetcher_sync",
]
```

Key changes: Added `AsyncContentFetcher`, `Fetcher`, `run_fetcher_async`, `run_fetcher_sync`, `async_gather`. Removed `run_async`.

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from syft_ingest import gather, async_gather, run_fetcher_sync, run_fetcher_async, Fetcher, AsyncContentFetcher; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
git add syft_ingest/__init__.py
git commit -m "feat: update public API exports for sync/async framework

Export AsyncContentFetcher, Fetcher, run_fetcher_sync, run_fetcher_async, async_gather.
Remove run_async (replaced by run_fetcher_sync/run_fetcher_async)."
```

---

### Task 7: Run full test suite and fix any breakage

**Files:**
- Potentially modify: any test file with `run_async` imports or broken references

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All PASS. If any failures, they'll be from stale `run_async` imports or `fetcher.fetch()` calls on async-only fetchers.

- [ ] **Step 2: Search for stale run_async references**

Run: `grep -r "run_async" tests/ syft_ingest/ --include="*.py"` (use Grep tool)

Fix any remaining references:
- `from syft_ingest.core.fetcher import run_async` → remove
- `from syft_ingest import run_async` → remove
- `run_async(...)` → should not exist anywhere after this refactor

- [ ] **Step 3: Search for stale _fetch_async references**

Run: `grep -r "_fetch_async" tests/ syft_ingest/ --include="*.py"` (use Grep tool)

Should return zero matches. If any remain, update them.

- [ ] **Step 4: Search for stale fetcher.fetch() on BrightDataFetcher**

Run: `grep -r "brightdata_fetcher\.fetch(" tests/ --include="*.py"` (use Grep tool)

Should return zero matches (replaced by `run_fetcher_sync` in Task 4).

- [ ] **Step 5: Run full test suite again after fixes**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: clean up stale references from sync/async refactor"
```
