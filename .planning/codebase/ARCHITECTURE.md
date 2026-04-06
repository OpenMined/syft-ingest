# Architecture

**Analysis Date:** 2026-04-06

## Pattern Overview

**Overall:** Modular pipeline with layered composition (source detection → normalization → export).

**Key Characteristics:**
- **Registry-based source detection**: Auto-detection via pluggable `(detect_fn, parse_fn)` tuples in `PARSERS` list
- **Unified data model**: All platform-specific content normalizes to `ContentItem` + metadata
- **Lazy deduplication**: Item deduplication happens at parse time, not post-collection
- **Pluggable export formats**: JSONL, JSON, text formats via strategy functions
- **Optional embeddings layer**: Multimodal embedding for posts and videos, separate from core ingestion

## Layers

**CLI Entry Point:**
- Purpose: Command-line interface for local export processing
- Location: `syft_ingest/cli.py`
- Contains: Argument parsing (`build_parser`), command dispatchers (`_cmd_local_export`)
- Depends on: `gather()` from core, standard library
- Used by: End users via `syft-ingest` command

**Core Aggregation Layer:**
- Purpose: Orchestrate content collection across sources, marshal into unified `Corpus`
- Location: `syft_ingest/core/gather.py`
- Contains: `gather()` function (tries each source, logs failures, aggregates)
- Depends on: Source implementations, models
- Used by: CLI, direct library usage

**Core Models:**
- Purpose: Pydantic-based data contracts for content and metadata
- Location: `syft_ingest/core/models.py`
- Contains: `SourceType` enum, `ContentItem` base class, `VideoResult`, `PaperResult`, `ArticleResult`, `PodcastResult`, `Corpus`
- Depends on: Pydantic v2
- Used by: All source parsers, exporters

**Source Detection & Parsing Layer:**
- Purpose: Detect and normalize platform-specific exports to `ContentItem` lists
- Location: `syft_ingest/sources/`
- Contains:
  - `local.py`: Dispatcher that walks directories, auto-detects platform, delegates to parser
  - `facebook.py`: Facebook Meta export + Bright Data crawler export parser
  - `instagram.py`: Instagram Meta export + Bright Data crawler export parser
  - `_meta_utils.py`: Shared UTF-8 encoding fix, hashtag/mention extraction, URL parsing
  - `_social_media_common.py`: Media type detection, URL classification, tag normalization
- Depends on: Models, Pydantic, loguru
- Used by: `gather()`, local source handler

**Export Layer:**
- Purpose: Serialize `Corpus` to file formats matching downstream consumer schema
- Location: `syft_ingest/core/exporters.py`
- Contains: Format-specific functions (`_export_jsonl`, `_export_json`, `_export_text`), schema mapping (`_item_to_dict`)
- Depends on: Models, pathlib
- Used by: `Corpus.export()` method

**RAG/Embedding Layer (Optional):**
- Purpose: Generate multimodal embeddings for posts and videos
- Location: `syft_ingest/rag/`
- Contains:
  - `embedders/clip_contract.py`: Embedding metadata contract (backend, model, normalization info)
  - `embedders/multimodal_post.py`: Post embedding (text + sampled frames + images → single vector)
  - `embedders/multimodal_video.py`: Video embedding (frames + transcript → chunked vectors)
- Depends on: `sentence-transformers`, OpenCV, models (optional extras)
- Used by: Standalone scripts in `scripts/`

## Data Flow

**Gather Pipeline:**

1. **CLI invocation** → `main()` parses args (author, input_dirs, format, output)
2. **gather()** called with `sources=["local"]`, `local_dirs=input_dirs`
3. **fetch_local()** walks each directory:
   - For each path, tries `PARSERS` tuple list in order
   - First matching `detect_fn` → calls corresponding `parse_fn(path, author=author)`
4. **parse_facebook_export() or parse_instagram_export()** (whichever matched):
   - Loads JSON files (Meta format) or Bright Data JSON arrays
   - Applies `fix_meta_encoding_recursive()` (UTF-8-as-Latin-1 bug)
   - Extracts text, URL, published_at, media URLs from nested JSON
   - Deduplicates by `post_id` (Bright Data), then by URL + content_hash
   - Builds post-level representation (text, tags, mentions, links, media array)
   - Creates `ContentItem` + metadata with `post_representation` dict
   - Returns deduplicated list
5. **Corpus.add()** merges items by `source_type` field (youtube, facebook, instagram, etc.)
6. **corpus.export()** called with format and output path:
   - Retrieves all items via `all_items()`
   - Calls `_export_jsonl()` / `_export_json()` / `_export_text()` based on format
   - Each item mapped via `_item_to_dict()` to output schema
   - Written to file(s)

**Multimodal Embedding Pipeline** (separate from gather):

1. Script reads manifest JSONL (post metadata) or video path
2. Loads post JSON or video file, extracts local media file paths
3. For videos: samples frames at intervals, runs frame → CLIP embeddings, loads transcript segments
4. For posts: finds local image/video files referenced in metadata, samples frames, processes text
5. Pools embeddings (mean or chunking) based on media presence
6. Outputs JSONL with one row per embedding, including `embedding_contract` metadata

**State Management:**

- No shared mutable state; all processing is functional
- Deduplication happens eagerly within parsers (in-memory dict)
- Corpus is built incrementally via `add()` method but doesn't perform dedup (parser responsibility)
- Export is read-only (no mutations to corpus)

## Key Abstractions

**ContentItem:**
- Purpose: Unified interface for all content sources
- Examples: `syft_ingest/core/models.py` lines 18–28
- Pattern: Pydantic `BaseModel` with required fields (title, author, source_type, text) and optional fields (url, published_at, metadata dict)
- Subclasses override `source_type` default: `VideoResult` (YouTube), `PaperResult` (arXiv), `ArticleResult` (web), `PodcastResult` (podcast)

**Corpus:**
- Purpose: Typed collection of content items grouped by source
- Examples: `syft_ingest/core/models.py` lines 57–86
- Pattern: Pydantic model with source-specific fields (youtube, tiktok, arxiv, web, podcast, local)
- Behavior: `all_items()` flattens to single list, `add()` routes by source_type, `export()` delegates to exporters module

**Registry Pattern (PARSERS):**
- Purpose: Extensible source detection without conditionals
- Examples: `syft_ingest/sources/local.py` lines 17–20
- Pattern: List of `(detect_fn, parse_fn)` tuples; iterate in order, call detect on path, first match wins
- Adding new platform: append new tuple (no changes to dispatcher)

**Post Representation Metadata:**
- Purpose: Preserve platform-specific structure (text, tags, mentions, media, links) alongside normalized item
- Examples: `syft_ingest/sources/facebook.py` lines 197–215, exporters output at schema line 230–249 (README)
- Pattern: Nested dict in `metadata["post_representation"]` with keys: author, published_at, text, tags, mentions, links, media
- Benefit: Downstream consumers (syft-influencer) can access rich platform-aware content without re-parsing

**Embedding Contract:**
- Purpose: Make embedding model/backend explicit so retrieval can verify compatibility
- Examples: `syft_ingest/rag/embedders/clip_contract.py` lines 15–22
- Pattern: Dict with keys `embedding_backend`, `embedding_family`, `embedding_model`, `embedding_space`, `embedding_normalized`
- Used by: Multimodal scripts to stamp each output row

## Entry Points

**CLI Entry Point:**
- Location: `syft_ingest/cli.py` `main()`
- Triggers: `syft-ingest local-export --author ... --input-dir ... --format ... --output ...`
- Responsibilities: Parse CLI args, call `gather()`, call `corpus.export()`, return exit code

**Library Entry Point:**
- Location: `syft_ingest/__init__.py` exports `gather()`
- Triggers: `import syft_ingest; syft_ingest.gather(...)`
- Responsibilities: Collect items from sources, return Corpus object

**Embedding Entry Points:**
- Location: `scripts/embed_video_multimodal.py` and `scripts/embed_posts_multimodal.py`
- Triggers: `uv run python scripts/embed_*.py --manifest-jsonl ... --output ...` (with optional flags)
- Responsibilities: Load manifests/videos, extract local media, generate embeddings, write JSONL with contract metadata

## Error Handling

**Strategy:** Graceful degradation with logging. Failures in one source don't stop collection from others.

**Patterns:**

- **Source fetch failures** (gather.py lines 43–44): Try-except wraps each source, logs error, continues to next
- **Missing optional data** (facebook.py, instagram.py): Return `None` from extraction functions, callers check before use
- **Encoding errors** (facebook.py lines 104–107): Safely try JSON decode, return False if malformed; if load succeeds, parse may still fix encoding
- **Timestamp validation** (facebook.py lines 163–169): Range-check timestamps (0 to year 2100), return None if out of bounds
- **Directory validation** (local.py lines 29–31): Check `is_dir()` before processing, warn and skip if missing
- **Format validation** (exporters.py lines 109–111): Raise ValueError for unknown export format (not graceful, by design)

## Cross-Cutting Concerns

**Logging:**
- Framework: `loguru`
- Pattern: Explicit log levels at key points: `logger.info()` for progress, `logger.warning()` for skipped/unimplemented features, `logger.error()` for exceptions
- Examples: gather.py line 46 (items gathered), local.py line 42 (unrecognized dir), exporters.py line 74 (items exported)

**Validation:**
- Pydantic models enforce type and required fields at collection boundaries (ContentItem, Corpus)
- Extraction functions return typed values (str | None) and callers check
- No raw dict passing; metadata is always dict but stored under `ContentItem.metadata` field

**Content Deduplication:**
- By `post_id` (Bright Data exports have explicit post_id)
- By URL + normalized text hash (Meta exports may have same URL across different files)
- Selection logic: Keep item with more media or longer text (facebook.py lines 218–228)
- Happens per-parser, not globally (dedup within parse_facebook_export, separate from parse_instagram_export)

**Encoding Fixes:**
- Meta platform bug: UTF-8 encoded as Latin-1 in JSON (each UTF-8 byte becomes separate \\u00XX)
- Applied recursively to all strings in post dicts before extraction (facebook.py, instagram.py)
- Test coverage: test_meta_utils.py tests fix behavior

---

*Architecture analysis: 2026-04-06*
