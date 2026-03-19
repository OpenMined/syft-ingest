# syft-ingest

Content aggregator — person-centric or topic-centric. Scrape, normalize, deliver.

## Setup

```bash
uv sync
```

### Data

Test data lives in a separate repo. Clone it into `./data`:

```bash
git clone https://github.com/OpenMined/syft-influencer-data.git ./data
```

This provides Facebook and Instagram export samples at `data/creators/syft-influencer-test/`.

## What it can do

**Phase 1 (current):** Parse Facebook and Instagram data exports into structured content, export as JSONL.

- Facebook data export parsing (Meta's "Download Your Information" JSON format)
- Instagram data export parsing (same Meta format, different schema)
- Meta encoding bug fix (UTF-8-as-Latin-1 mojibake)
- Hashtag and mention extraction
- Content deduplication (by URL and content hash)
- Context enrichment (`[Facebook post by Author | Published: 2026-03-19]\n\ntext`)
- JSONL, JSON, and text file export

## API

### `gather()` — main entry point

```python
import syft_ingest

corpus = syft_ingest.gather(
    "Creator Name",
    sources=["local"],
    local_dirs=["./data/creators/syft-influencer-test/fb-page-2026-03-18/"],
)
```

Returns a `Corpus` object containing parsed `ContentItem` objects.

### `corpus.export()` — output to file

```python
# JSONL (one JSON object per line — feeds into syft-influencer's ingest.py)
corpus.export("jsonl", output="output.jsonl")

# JSON (single array)
corpus.export("json", output="output.json")

# Text (one .txt file per item)
corpus.export("text", output_dir="./output-texts/")
```

### `corpus.all_items()` — access items in memory

```python
for item in corpus.all_items():
    print(item.title, item.url, item.metadata["platform"])
```

### Multiple sources

```python
corpus = syft_ingest.gather(
    "Creator Name",
    sources=["local"],
    local_dirs=[
        "./data/creators/creator/fb-page-export/",
        "./data/creators/creator/instagram-export/",
    ],
)
```

Facebook and Instagram exports are auto-detected. Adding a new platform parser requires zero changes to the dispatcher.

## JSONL output schema

Each line in the JSONL output:

```json
{
  "text": "[Facebook post by Creator | Published: 2026-03-19]\n\nPost content...",
  "title": "First line of post text",
  "url": "https://example.com/blog-post",
  "source": "local",
  "source_type": "",
  "author": "Creator Name",
  "site": "",
  "tags": ["federatedlearning", "ai", "openmined"],
  "metadata": {
    "platform": "facebook",
    "tags": ["federatedlearning", "ai", "openmined"],
    "mentions": [],
    "content_hash": "abc123..."
  }
}
```

## Tests

```bash
uv run pytest tests/ -v
```

48 tests across 5 files:

| File | Tests | What it covers |
|---|---|---|
| `test_meta_utils.py` | 19 | Encoding fix, hashtag/mention extraction, normalization, content hash, `is_bare_url`, `derive_title` |
| `test_facebook.py` | 8 | FB post text/URL extraction, export detection, integration with real data |
| `test_instagram.py` | 6 | IG post text extraction, export detection, integration with real data, cross-post detection |
| `test_local.py` | 5 | Auto-detection dispatcher, multi-dir, nonexistent/unrecognized dirs |
| `test_e2e.py` | 9 | Full `gather()` -> `export()` pipeline: JSONL/JSON/text formats, dedup, bare-URL filtering, graceful degradation |

Tests require the data repo cloned into `./data` (see Setup above).
