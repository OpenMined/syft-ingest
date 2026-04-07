# syft-ingest

Content aggregator — person-centric or topic-centric. Scrape, normalize, deliver.

## Setup

```bash
uv sync
```

For multimodal video embeddings (frame + transcript), install extras:

```bash
uv sync --extra multimodal
```

For reusable text ingest into Qdrant:

```bash
uv sync --extra qdrant
```

Optional auto-transcription with Whisper:

```bash
uv sync --extra podcast
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
- Facebook crawler export parsing (Bright Data / similar JSON exports)
- Instagram data export parsing (same Meta format, different schema)
- Instagram crawler export parsing (Bright Data / similar JSON exports)
- Meta encoding bug fix (UTF-8-as-Latin-1 mojibake)
- Hashtag and mention extraction
- Post-level representation extraction for Facebook (`post_ref` + `post_representation`):
  text, tags, mentions, videos, images, and media provenance fields
- Content deduplication (by URL and content hash)
- Context enrichment (`[Facebook post by Author | Published: 2026-03-19]\n\ntext`)
- JSONL, JSON, and text file export
- Reusable text ingest API for Qdrant (remote URL or local on-disk path)
- Multimodal video embedding script for local video files (sample frames + transcript fusion)

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

The older `sources=["local"], local_dirs=[...]` API remains supported, but
for app-to-library integrations the preferred entry point is a typed source spec:

```python
import syft_ingest

corpus = syft_ingest.gather(
    "Katy Stevens",
    source_specs=[
        syft_ingest.SocialProfileSource(
            platform="instagram",
            extractor="brightdata",
            handle="katykicker",
            profile_url="https://www.instagram.com/katykicker/",
            raw_dirs=["./runs/20260403T093140Z/"],
            start_date="2026-03-01",
            source_slug="katykicker-instagram",
        )
    ],
)
```

`SocialProfileSource` carries the creator/platform/source identity explicitly
while still parsing local raw export directories.

### `corpus.export()` — output to file

```python
# JSONL (one JSON object per line — feeds into syft-influencer's ingest.py)
corpus.export("jsonl", output="output.jsonl")

# JSON (single array)
corpus.export("json", output="output.json")

# Text (one .txt file per item)
corpus.export("text", output_dir="./output-texts/")
```

### CLI

```bash
uv run syft-ingest local-export \
  --author "Creator Name" \
  --input-dir ./data/creators/creator/facebook-brightdata \
  --input-dir ./data/creators/creator/instagram-brightdata \
  --format jsonl \
  --output ./output/creator_social_posts.jsonl
```

The CLI is a thin wrapper over the same library seam and is useful for manual
runs, but application code should prefer importing `gather(...)` directly.

### `ingest_jsonl()` — ingest a normalized manifest into Qdrant

```python
import syft_ingest

report = syft_ingest.ingest_jsonl(
    "./output/creator_social_posts.jsonl",
    destination=syft_ingest.QdrantDestination(
        collection_name="katy-stevens",
        url="http://127.0.0.1:6333",
    ),
    embedding=syft_ingest.EmbeddingSpec(
        backend="fastembed",
        model="BAAI/bge-small-en-v1.5",
    ),
    chunking=syft_ingest.ChunkingSpec(
        chunk_size=1000,
        chunk_overlap=250,
    ),
)
```

For local smoke tests without a separate Qdrant service:

```python
destination = syft_ingest.QdrantDestination(
    collection_name="katy-stevens-smoke",
    path="/tmp/qdrant-katy-smoke",
)
```

`IngestReport` returns:
- `collection_name`
- `documents_total`
- `chunks_total`
- `point_ids`
- `embedding_contract`

### `ingest_corpus()` — gather and ingest without writing JSONL first

```python
import syft_ingest

corpus = syft_ingest.gather(
    "Katy Stevens",
    source_specs=[
        syft_ingest.SocialProfileSource(
            platform="instagram",
            extractor="brightdata",
            handle="katykicker",
            profile_url="https://www.instagram.com/katykicker/",
            raw_dirs=["./runs/20260403T093140Z/"],
        )
    ],
)

report = syft_ingest.ingest_corpus(
    corpus,
    destination=syft_ingest.QdrantDestination(
        collection_name="katy-stevens",
        url="http://127.0.0.1:6333",
    ),
)
```

### `corpus.all_items()` — access items in memory

```python
for item in corpus.all_items():
    print(item.title, item.url, item.metadata["platform"])
```

### Direct Bright Data Facebook parsing

```python
from pathlib import Path
from syft_ingest.sources.facebook import parse_facebook_brightdata_file

items = parse_facebook_brightdata_file(
    Path("data/creators/jen-lazzari/paintedwildflower-fbpage/brightdata-sd_...json"),
    author="Jen Lazzari",
)
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

## Multimodal Video Embeddings

Embed non-YouTube videos by combining sampled frame embeddings with nearby transcript text.

Embedding contract:
- backend: `sentence-transformers`
- default model: `clip-ViT-B-32`
- output vectors are L2-normalized
- output rows include `embedding_backend`, `embedding_family`, `embedding_model`,
  `embedding_space`, and `embedding_normalized`

Consumers such as `syft-influencer` should use the same query embedding backend/model
when searching a collection produced by these scripts.

Run:

```bash
uv run python scripts/embed_video_multimodal.py ./data/videos/example.mp4 \
  --output ./output/video_embeddings.jsonl \
  --interval-seconds 2 \
  --clip-model clip-ViT-B-32
```

With transcript file (`.json` or `.jsonl` segments):

```bash
uv run python scripts/embed_video_multimodal.py ./data/videos/example.mp4 \
  --transcript-json ./data/videos/example_transcript.json \
  --output ./output/video_embeddings.jsonl
```

With automatic Whisper transcription:

```bash
uv run python scripts/embed_video_multimodal.py ./data/videos/example.mp4 \
  --whisper-model base \
  --output ./output/video_embeddings.jsonl
```

Transcript segment schema:

```json
[
  {"start": 0.0, "end": 2.4, "text": "Intro scene"},
  {"start": 2.4, "end": 6.8, "text": "Speaker explains the setup"}
]
```

## Multimodal Post Embeddings

Embed Facebook posts as one vector per post using:
- post text (no chunking),
- local image files from the post, and
- sampled frames from local post videos.

Optional summarization for long text is available but disabled by default.

These embeddings use the same explicit CLIP contract as the video pipeline:
`sentence-transformers` + `clip-ViT-B-32` by default, with alignment metadata
stored on each output row so downstream retrieval can verify compatibility.

```bash
uv run python scripts/embed_posts_multimodal.py \
  --manifest-jsonl ../syft-influencer/data/creators/jen-lazzari/paintedwildflower-fbpage/local-sync/manifests/posts_local_manifest.jsonl \
  --output ./output/post_embeddings_multimodal.jsonl \
  --max-posts 5
```

Enable summarization only when needed:

```bash
uv run python scripts/embed_posts_multimodal.py \
  --manifest-jsonl ../syft-influencer/data/creators/jen-lazzari/paintedwildflower-fbpage/local-sync/manifests/posts_local_manifest.jsonl \
  --summarize-long-text \
  --summary-min-chars 900 \
  --summary-max-chars 420

# Optional: include tags directly in embedding text (default is metadata-only tags)
uv run python scripts/embed_posts_multimodal.py \
  --manifest-jsonl ../syft-influencer/data/creators/jen-lazzari/paintedwildflower-fbpage/local-sync/manifests/posts_local_manifest.jsonl \
  --include-tags-in-embedding-text
```

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
    "extractor": "brightdata",
    "content_hash": "abc123...",
    "post_ref": {
      "platform": "facebook",
      "post_id": "122243006504090679",
      "url": "https://www.facebook.com/reel/1378171301018195/"
    },
    "post_representation": {
      "author": "Creator Name",
      "published_at": "2026-03-19T12:00:00+00:00",
      "text": "Easy flower tutorial #watercolor",
      "tags": ["watercolor"],
      "mentions": [],
      "links": [],
      "media": [
        {
          "url": "https://video-...mp4",
          "media_type": "video",
          "source_fields": ["attachments[0].video_url"]
        },
        {
          "url": "https://scontent-...jpg",
          "media_type": "image",
          "source_fields": ["attachments[0].thumbnail_url"]
        }
      ]
    }
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
