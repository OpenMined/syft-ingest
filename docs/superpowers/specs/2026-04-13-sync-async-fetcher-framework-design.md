# Sync/Async Fetcher Framework

**Date:** 2026-04-13
**Status:** Draft
**Branch:** `feat/sync-async-fetchers`

## Problem

The current `ContentFetcher` protocol is sync-only (`def fetch()`), but the two fetcher implementations have different native I/O models:

- **YtDlpFetcher** — sync-native (yt-dlp is a blocking library)
- **BrightDataFetcher** — async-native (BrightData SDK uses `async with`, `await`)

Both are forced through the same sync protocol, leading to:

1. YtDlpFetcher declares `async def _fetch_async` but never awaits anything — fake async
2. BrightDataFetcher has genuinely async internals but wraps them in `run_async()` to conform
3. Every fetcher duplicates the `run_async()` bridging boilerplate
4. `gather()` is sync-only — `await gather(...)` fails with `TypeError` in Jupyter

## Design

### Two Protocols

Fetcher authors implement whichever is natural for their underlying library. No bridging code in fetchers.

```python
@runtime_checkable
class ContentFetcher(Protocol):
    """Sync fetcher — for blocking I/O libraries (yt-dlp, local file reader)."""
    def fetch(self, request: FetchRequest) -> FetchResult: ...

@runtime_checkable
class AsyncContentFetcher(Protocol):
    """Async fetcher — for native async I/O libraries (BrightData SDK)."""
    async def fetch_async(self, request: FetchRequest) -> FetchResult: ...

Fetcher = ContentFetcher | AsyncContentFetcher
```

### Framework Bridge

Two bridge functions in `fetcher.py`. Fetchers never write bridging code.

```python
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

    Detects running event loop (Jupyter) and falls back to thread.
    """
    coro = run_fetcher_async(fetcher, request)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in event loop (Jupyter) — run in worker thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
```

### Two gather functions

Follows Python ecosystem convention (`httpx.Client`/`AsyncClient`, `sqlalchemy.Session`/`AsyncSession`). Each function has one return type — no flag that changes behavior. Both share request-building logic via a private `_build_request` helper.

```python
def gather(platform, urls, author="", **config) -> Corpus:
    """Sync entry point — scripts, CLI, tests."""
    ...
    result = run_fetcher_sync(fetcher, request)
    corpus.add(result.items)
    return corpus

async def async_gather(platform, urls, author="", **config) -> Corpus:
    """Async entry point — Jupyter with await, async servers."""
    ...
    result = await run_fetcher_async(fetcher, request)
    corpus.add(result.items)
    return corpus
```

### Fetcher Changes

**YtDlpFetcher** — becomes purely sync:

- Implements `def fetch(self, request) -> FetchResult`
- Remove `async def _fetch_async` — inline its logic into `fetch()`
- Remove `run_async` import
- All internal methods become plain `def` (drop `async` from `_enumerate_channel`, `_extract_video_info_and_captions`, `_download_video`)

**BrightDataFetcher** — becomes purely async:

- Implements `async def fetch_async(self, request) -> FetchResult`
- Remove sync `def fetch()` wrapper
- Remove `run_async` import
- Rename `_fetch_async` to `fetch_async` (the protocol method)

**LocalFetcher** — stays sync (already sync-native, just needs protocol conformance check).

### Registry Changes

`registry.py` accepts `Fetcher`:

- `register_fetcher()` validates `isinstance(fetcher, ContentFetcher) or isinstance(fetcher, AsyncContentFetcher)`
- `FETCHER_REGISTRY` type becomes `dict[FetcherKey, Fetcher]`
- `get_fetcher()` return type becomes `Fetcher`

### Public API (`__init__.py`)

- Export `AsyncContentFetcher`, `Fetcher`, `run_fetcher_sync`, `run_fetcher_async`, `async_gather`
- Remove `run_async` export (replaced by `run_fetcher_sync`/`run_fetcher_async`)

### What Gets Deleted

- `run_async()` from `fetcher.py` (replaced by `run_fetcher_sync`/`run_fetcher_async`)
- `async def _fetch_async` from `YtDlpFetcher`
- `def fetch` sync wrapper from `BrightDataFetcher`
- All `run_async` imports from fetcher modules

## File Change Summary

| File                                      | Change                                                                                               |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `syft_ingest/core/fetcher.py`           | Add `AsyncContentFetcher`, `Fetcher`, `run_fetcher_sync()`, `run_fetcher_async()`. Remove `run_async()`. |
| `syft_ingest/core/gather.py`            | Add `async_gather()`. Extract shared request-building to `_build_request()` helper.                |
| `syft_ingest/core/registry.py`          | Accept `Fetcher`. Update type annotations and isinstance check.                                    |
| `syft_ingest/sources/youtube.py`        | Pure sync `fetch()`. Drop all `async def`, `await`, `run_async`.                             |
| `syft_ingest/sources/brightdata.py`     | Pure async `fetch_async()`. Drop sync `fetch()` wrapper, `run_async`.                          |
| `syft_ingest/__init__.py`               | Export new types. Remove `run_async`.                                                              |
| `tests/unit/test_fetcher.py`            | Add `AsyncContentFetcher` protocol tests, `run_fetcher` dispatch tests.                          |
| `tests/unit/sources/test_youtube.py`    | Update to call sync `fetch()` directly.                                                            |
| `tests/unit/sources/test_brightdata.py` | Update to use `pytest-asyncio` for `fetch_async()`.                                              |

## Usage After

```python
import syft_ingest as si

# Sync — scripts, CLI, plain Python
corpus = si.gather("youtube", ["https://youtube.com/watch?v=kCc8FmEb1nY"])

# Async — Jupyter with await, async servers
corpus = await si.async_gather("youtube", ["https://youtube.com/watch?v=kCc8FmEb1nY"])

# Both work with any fetcher, regardless of whether the fetcher is sync or async internally
corpus = await si.async_gather("instagram", ["https://instagram.com/user/"])
```

## Non-Goals

- No changes to `FetchRequest`, `FetchResult`, `FetchConfig`, or error hierarchy
- No changes to the URL router or models
- No concurrent multi-URL fetching within a single `gather` call (future work)
- No changes to export/persistence layer
