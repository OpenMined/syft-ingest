# External Integrations

**Analysis Date:** 2026-04-06

## APIs & External Services

**YouTube:**
- Service: YouTube (via yt-dlp)
  - SDK/Client: `yt-dlp>=2024.0`
  - Status: Built-in dependency, source placeholder in codebase (not yet implemented)
  - Usage: `syft_ingest/core/gather.py` routes to `"youtube"` source (currently logs warning: "YouTube source not yet implemented")

**arXiv:**
- Service: arXiv API
  - SDK/Client: `arxiv>=2.0`
  - Auth: None (public API)
  - Status: Optional extra (`uv sync --extra arxiv`)
  - Usage: Parsing academic papers (implementation pending, source in `gather()` logs warning)

**OpenAI:**
- Service: OpenAI API (embeddings and other models)
  - SDK/Client: `openai>=1.0`
  - Auth: `OPENAI_API_KEY` environment variable (convention, not validated in codebase)
  - Status: Optional extra (`uv sync --extra openai-embeddings`)
  - Usage: Embedding models (prepared but not actively used in current phase)

**NotebookLM:**
- Service: NotebookLM (third-party integration)
  - SDK/Client: `notebooklm-py>=0.1`
  - Auth: API key (environment-dependent)
  - Status: Optional extra (`uv sync --extra notebooklm`)
  - Usage: Prepared for integration, not currently active

## Data Storage

**Databases:**
- None required for core functionality
- File-based storage only

**Vector Databases (Optional):**
- Qdrant
  - Client: `qdrant-client>=1.9`
  - Status: Optional extra (`uv sync --extra qdrant`)
  - Config: Connection URL (environment-dependent, not configured)
  - Usage: Not active in codebase (prepared for future)

- Weaviate
  - Client: `weaviate-client>=4.0`
  - Status: Optional extra (`uv sync --extra weaviate`)
  - Config: Connection URL (environment-dependent)
  - Usage: Not active in codebase (prepared for future)

- Chroma
  - Client: `chromadb>=0.4`
  - Status: Optional extra (`uv sync --extra chroma`)
  - Config: Local or remote instance (environment-dependent)
  - Usage: Not active in codebase (prepared for future)

**File Storage:**
- Local filesystem only
- Input: JSON files (Facebook/Instagram exports, Bright Data crawler exports)
- Output: JSONL, JSON, or text files (configured via `corpus.export()` in `syft_ingest/core/exporters.py`)

**Caching:**
- None (stateless processing)
- Frame extraction writes temporary files to output directory

## Authentication & Identity

**Auth Provider:**
- Custom or OAuth via third-party SDKs (optional, not configured)
- YouTube: yt-dlp handles authentication internally if needed
- OpenAI: Uses API key (not validated in code)
- Bright Data: Input data already exported locally, no API integration

## Monitoring & Observability

**Error Tracking:**
- None configured (not integrated)

**Logs:**
- loguru library configured for structured logging
- Logs written to stdout/stderr (format configurable by consumer)
- Key log locations:
  - `syft_ingest/sources/facebook.py`: Logs post parsing, encoding fixes, export detection
  - `syft_ingest/sources/instagram.py`: Logs IG post extraction
  - `syft_ingest/sources/local.py`: Logs source auto-detection
  - `syft_ingest/core/gather.py`: Logs source routing and item counts
  - `syft_ingest/core/exporters.py`: Logs export operations
  - `syft_ingest/rag/embedders/multimodal_video.py`: Logs frame extraction, transcription, embedding

## CI/CD & Deployment

**Hosting:**
- Not configured (application is library + CLI)
- Intended deployment: Local scripts, containerized workflows, or CI pipelines

**CI Pipeline:**
- pre-commit hooks via `.pre-commit-config.yaml` (enforces ruff lint/format)
- Tests via pytest (run locally or in CI)
- No GitHub Actions or similar configured in codebase

## Environment Configuration

**Required env vars:**
- None for core functionality
- Optional (if using OpenAI embeddings): `OPENAI_API_KEY`
- Optional (if using NotebookLM): Service-specific API key
- Optional (if using vector DBs): Connection strings (Qdrant URL, Weaviate URL, Chroma path)

**Secrets location:**
- Not stored in codebase
- Expected to be injected at runtime (container env vars, CI secrets, etc.)

## Webhooks & Callbacks

**Incoming:**
- None (polling/batch-based model)

**Outgoing:**
- None (file output only)

## Content Sources Currently Integrated

**Bright Data:**
- Export Format: JSON files containing crawled Facebook/Instagram posts
- Parser: `syft_ingest/sources/facebook.py:parse_facebook_brightdata_file()`
- Fields: `page_name`, `page_category`, `attachments`, `post_content`, `videos`, `shortcode`, etc.
- Validation: `_looks_like_brightdata_row()` detects Bright Data JSON schema

**Meta Native Export:**
- Export Format: "Download Your Information" JSON from Facebook/Instagram
- Parser: `syft_ingest/sources/facebook.py:parse_facebook_export()` and `syft_ingest/sources/instagram.py:parse_instagram_export()`
- Fields: Posts, photos, videos, comments (schema differs from Bright Data)
- Auto-detection: `is_facebook_export()`, `is_instagram_export()`

**Local Files:**
- Input: Facebook and Instagram JSON exports (auto-detected)
- Parser: `syft_ingest/sources/local.py:fetch_local()`
- Multi-directory support: Accepts list of local directories, recursively auto-detects format

## Embedding & Vector Storage Workflow

**CLIP Embedding Contract:**
- Backend: `sentence-transformers`
- Default Model: `clip-ViT-B-32`
- Output: L2-normalized vectors (normalized dimension included in output)
- Metadata: Each embedding row includes alignment fields:
  - `embedding_backend: "sentence-transformers"`
  - `embedding_family: "clip"`
  - `embedding_model: "clip-ViT-B-32"` (configurable)
  - `embedding_space: "sentence-transformers:clip-ViT-B-32"`
  - `embedding_normalized: true`
- Purpose: Ensures downstream consumers (syft-influencer retrieval) can verify compatibility

**Multimodal Video Embedding:**
- Input: Video file + optional transcript (JSON/JSONL)
- Process: Frame extraction → Optional Whisper transcription → CLIP embedding → Fusion (frame + transcript weighted average)
- Config: `syft_ingest/rag/embedders/multimodal_video.py`
- Transcript Format: JSON or JSONL with `{"start": float, "end": float, "text": string}`
- Fusion Weights: `text_weight=0.35` (image 65%, text 35%, default)
- Output: JSONL with embedding vectors + contract metadata

**Multimodal Post Embedding:**
- Input: Facebook posts manifest (JSONL) with local image/video paths
- Process: Text + images + sampled video frames → Embedding fusion
- Config: `syft_ingest/rag/embedders/multimodal_post.py`
- Text Handling: Optional summarization (disabled by default)
- Output: JSONL with post embeddings + contract metadata

## Data Pipeline & Output Schema

**Gather → Export:**
1. `gather()` orchestrates source routing (`syft_ingest/core/gather.py`)
2. Each source parser returns list of `ContentItem` objects
3. Items deduplicated by content hash and URL
4. `corpus.export()` normalizes to downstream schema (`syft_ingest/core/exporters.py`)

**Output JSONL Schema (Compatible with syft-influencer):**
```json
{
  "id": "stable_hash_of_url_plus_content",
  "text": "[Facebook post by Author | Published: 2026-03-19]\n\nPost content...",
  "title": "First line of post",
  "url": "https://facebook.com/...",
  "source": "local",
  "source_type": "social_media_post",
  "author": "Creator Name",
  "site": "facebook.com",
  "published_at": "2026-03-19T12:00:00+00:00",
  "tags": ["hashtag1", "hashtag2"],
  "metadata": {
    "platform": "facebook",
    "extractor": "brightdata",
    "content_hash": "sha256_hash",
    "post_ref": { "platform": "facebook", "post_id": "...", "url": "..." },
    "post_representation": {
      "author": "...",
      "published_at": "...",
      "text": "...",
      "tags": [],
      "mentions": [],
      "links": [],
      "media": [{ "url": "...", "media_type": "video", "source_fields": [...] }]
    }
  }
}
```

---

*Integration audit: 2026-04-06*
