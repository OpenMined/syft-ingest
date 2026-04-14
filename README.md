# syft-ingest

Content aggregator — person-centric or topic-centric. Scrape, normalize, deliver.

## Setup

```bash
uv sync
```

For reusable text ingest into Qdrant:

```bash
uv sync --extra qdrant
```

### Data

Test data lives in a separate repo. Clone it into `./data`:

```bash
git clone https://github.com/OpenMined/syft-influencer-data.git ./data
```

This provides Facebook and Instagram export samples at `data/creators/syft-influencer-test/`.

## What it can do

Fetch content from YouTube, Facebook, and Instagram. Normalize to a unified `Corpus` of `ContentItem` objects. Export as JSONL. Optionally ingest into a vector store (Qdrant) for RAG.

**Supported platforms:**

| Platform | Fetcher | How it works |
|---|---|---|
| YouTube | `YtDlpFetcher` (sync) | yt-dlp: video metadata, captions, optional download |
| Facebook | `BrightDataFetcher` (async) | BrightData SDK: trigger/poll/fetch scrape jobs |
| Instagram | `BrightDataFetcher` (async) | BrightData SDK: search scraper with server-side post limiting |
| Local | `LocalFetcher` (sync) | Parse Facebook/Instagram data exports from disk |

## API

### `gather()` / `async_gather()` — main entry points

Two functions, one return type each. Pick the one that matches your runtime context.

```python
import syft_ingest as si

# Sync — scripts, CLI, plain Python
corpus = si.gather("youtube", ["https://www.youtube.com/watch?v=zY2dAK-pMPI"])

# Async — Jupyter with await, async servers
corpus = await si.async_gather("youtube", ["https://www.youtube.com/watch?v=zY2dAK-pMPI"])
```

Both return a `Corpus` object. Pass platform-specific config as keyword arguments:

```python
# YouTube: channel enumeration with post limit
corpus = si.gather(
    "youtube",
    ["https://www.youtube.com/@iamtrask"],
    playlistend=5,
    socket_timeout=60,
)

# Facebook: BrightData scrape with server-side post limit
corpus = await si.async_gather(
    "facebook",
    ["https://www.facebook.com/profile.php?id=61583734012155"],
    author="Andrew Trask",
    posts_limit=10,
    timeout=300,
)

# Instagram: BrightData search with server-side post limit
corpus = await si.async_gather(
    "instagram",
    ["https://www.instagram.com/iamtrask/"],
    author="Andrew Trask",
    posts_limit=5,
    timeout=300,
)

# Local: parse data exports from disk
corpus = si.gather(
    "local",
    ["./data/creators/syft-influencer-test/fb-page-2026-03-18/"],
    author="Andrew Trask",
)
```

### Delta fetching with `start_date`

Only fetch content published after a given date. Saves BrightData credits on daily re-scrapes.

```python
# YouTube: only videos after April 1 (filtered post-extraction via upload_date)
corpus = si.gather("youtube", ["https://youtube.com/@creator"], start_date="2026-04-01")

# Facebook: only posts after April 1 (filtered server-side by BrightData)
corpus = await si.async_gather("facebook", ["https://facebook.com/..."], start_date="2026-04-01")

# Instagram: same
corpus = await si.async_gather("instagram", ["https://instagram.com/..."], start_date="2026-04-01")
```

Format: `YYYY-MM-DD`. When omitted, all content is fetched (backwards compatible).

### Concurrent fetching

The async API enables concurrent scraping — total time equals the slowest scrape, not the sum:

```python
import asyncio

corpus_yt, corpus_fb, corpus_ig = await asyncio.gather(
    si.async_gather("youtube", ["https://www.youtube.com/@iamtrask"], playlistend=3),
    si.async_gather("facebook", ["https://facebook.com/..."], posts_limit=5, timeout=300),
    si.async_gather("instagram", ["https://instagram.com/..."], posts_limit=5, timeout=300),
)
```

### `corpus.export()` — output to file

```python
corpus.export("./output.jsonl")      # JSONL (one JSON object per line)
corpus.export("./output.json")       # JSON (single array)
corpus.export("./output/", fmt="text")  # Text (one .txt per item)
```

### `corpus.all_items()` — access items in memory

```python
for item in corpus.all_items():
    print(item.title, item.url, item.source_type)
    print(item.metadata)  # platform-specific raw data
```

### `ingest_jsonl()` — ingest normalized JSONL into Qdrant

```python
report = si.ingest_jsonl(
    "./output.jsonl",
    destination=si.QdrantDestination(
        collection_name="my-collection",
        url="http://127.0.0.1:6333",
    ),
    embedding=si.EmbeddingSpec(
        backend="fastembed",
        model="BAAI/bge-small-en-v1.5",
    ),
    chunking=si.ChunkingSpec(
        chunk_size=1000,
        chunk_overlap=250,
    ),
)
```

### CLI

```bash
uv run syft-ingest local-export \
  --author "Creator Name" \
  --input-dir ./data/creators/creator/facebook-brightdata \
  --format jsonl \
  --output ./output/creator_social_posts.jsonl
```

## Architecture

### Dual sync/async protocol system

Fetcher authors implement whichever I/O model is natural for their underlying library. The framework bridges between them automatically.

```
ContentFetcher (sync)          AsyncContentFetcher (async)
  def fetch(request)             async def fetch_async(request)
       │                                  │
       └──── run_fetcher_sync ────────────┘  (sync callers)
       └──── run_fetcher_async ───────────┘  (async callers)
                    │
              gather() / async_gather()
```

- **Sync fetchers** (yt-dlp, local): implement `fetch()`. When called from async context, the framework wraps them in `asyncio.to_thread()`.
- **Async fetchers** (BrightData SDK): implement `fetch_async()`. When called from sync context, the framework bridges via `asyncio.run()` (Jupyter-safe).
- **Registry**: maps `(platform, extractor)` pairs to fetcher instances. Accepts both protocol types.

### Config options

| Option | Platform | Description |
|---|---|---|
| `socket_timeout` | YouTube | Network timeout in seconds (default: 30) |
| `playlistend` | YouTube | Max videos from channel/playlist (default: 50) |
| `download_full_video` | YouTube | Enable full video download (default: false) |
| `timeout` | Facebook/Instagram | Scrape job timeout in seconds (default: 180) |
| `poll_interval` | Facebook | Job status check interval in seconds (default: 5) |
| `posts_limit` | Facebook/Instagram | Limit posts fetched, server-side for FB/IG (default: no limit) |

## Tests

```bash
uv run pytest tests/ -v
```

271 tests across unit and integration suites. 15 tests skip if test data is not available (clone the data repo to run them).

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `BRIGHTDATA_API_TOKEN` | For Facebook/Instagram | BrightData API token |
