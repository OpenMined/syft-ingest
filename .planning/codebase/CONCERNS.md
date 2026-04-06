# Codebase Concerns

**Analysis Date:** 2026-04-06

## Error Handling

**Overly Broad Exception Catching:**
- Issue: Generic `except Exception as e` in `syft_ingest/core/gather.py:43` masks actual errors
- Files: `syft_ingest/core/gather.py` (line 43)
- Impact: Failures in data source plugins (local, youtube, etc.) silently log warnings. Real bugs like ImportError or AttributeError get swallowed with generic "Failed to fetch" message. Debugging becomes difficult.
- Fix approach: Catch specific exceptions (`FileNotFoundError`, `ValueError`, `ImportError`). Let programming errors (AttributeError, KeyError) propagate. Add structured error context to logs.

**Silent Failures on Missing Dependencies:**
- Issue: `ImportError` for optional dependencies caught and converted to RuntimeError with helpful message, but only when code path is executed
- Files: `syft_ingest/rag/embedders/clip_contract.py:28-31`, `syft_ingest/rag/embedders/multimodal_video.py:156-159, 206-209, 243-246`, `syft_ingest/rag/embedders/multimodal_post.py:194-197`
- Impact: If user doesn't have `sentence-transformers`, `opencv-python`, or `Pillow` installed, the CLI will fail at runtime with message asking to install extras. This is correct behavior but means test coverage may miss dependency issues.
- Fix approach: Add smoke test that imports all optional dependencies before running, or document clearly which extras are needed for each pipeline. Consider early validation in CLI entry point.

**JSON Decoding Errors Not Differentiated:**
- Issue: Multiple catch blocks treat `json.JSONDecodeError` and `UnicodeDecodeError` identically
- Files: `syft_ingest/sources/facebook.py:571, 598, 614`, `syft_ingest/sources/instagram.py:541, 570, 637`
- Impact: Malformed JSON and broken file encoding both log "failed to parse JSON" and skip file. Can't distinguish between data corruption and encoding issues. No recovery path.
- Fix approach: Log error type separately. For encoding errors, try alternative encodings before giving up.

**OSError Silent Skip in Image Loading:**
- Issue: `syft_ingest/rag/embedders/multimodal_post.py:206` catches `OSError` when opening images but silently continues
- Files: `syft_ingest/rag/embedders/multimodal_post.py:200-207`
- Impact: Corrupted image files, permission errors, or disk I/O problems silently skip images without warning the user or counting skipped items. Embeddings will have fewer images than expected without explanation.
- Fix approach: Count and log skipped images per record. Provide at least a debug-level log of which images failed.

## Memory & Performance

**No Batch Size Limits on Embedding Operations:**
- Issue: `embed_posts_multimodal` and `embed_records_with_clip` load all text embeddings into memory before processing records
- Files: `syft_ingest/rag/embedders/multimodal_post.py:327`, `syft_ingest/rag/embedders/multimodal_video.py:258-262, 272-277`
- Impact: For large corpus (10k+ posts), all text vectors stay in memory at once. With 384-dim embeddings on 10k posts = ~15MB just for text. When combined with images (3x more data), total memory could exceed 100MB+ for a single batch. No streaming or chunking.
- Scaling limit: Practical limit is ~5-10k posts per run before hitting memory constraints on standard machines.
- Fix approach: Implement streaming batch processing. Process records in chunks of 100-500, write embeddings to disk incrementally. Don't load all text vectors at once.

**Video Frame Extraction Creates Temporary Files:**
- Issue: `syft_ingest/rag/embedders/multimodal_post.py:340-346` creates temporary directories for each post when stable frame root not provided
- Files: `syft_ingest/rag/embedders/multimodal_post.py:339-356`
- Impact: Processing 100 posts = 100 temp directories created. Each frame extraction allocates disk space. For 60fps video at 2.5s intervals = ~240 frames per video = ~50MB per video. With many posts, disk usage explodes. Cleanup is guaranteed by Python's context manager, but if process crashes, temp files linger.
- Fix approach: Require `frames_root` parameter or use centralized temp location with deterministic naming. Add cleanup handler.

**No Timeout on Model Loading:**
- Issue: `load_sentence_transformer(model_name)` in `multimodal_post.py:271` and `multimodal_video.py:249` downloads models from HuggingFace with no timeout
- Files: `syft_ingest/rag/embedders/clip_contract.py` (where loading happens), `syft_ingest/rag/embedders/multimodal_post.py:271`, `syft_ingest/rag/embedders/multimodal_video.py:249`
- Impact: First-time model loading can take 2-10 minutes depending on network. If connection is slow or hangs, process hangs indefinitely with no way to interrupt gracefully.
- Fix approach: Set request timeout in sentence-transformers config. Add progress callback. Document expected first-run latency.

**No Pagination or Streaming for Large JSON Files:**
- Issue: `syft_ingest/sources/facebook.py:536` and `instagram.py:507` load entire JSON file into memory with `json.load()`
- Files: `syft_ingest/sources/facebook.py:536`, `syft_ingest/sources/instagram.py:507`, `syft_ingest/sources/instagram.py:569`
- Impact: For a Facebook export with 10k+ posts (30MB+ JSON), entire file is loaded into memory. With nested attachments and media data, can easily exceed 100MB. Large exports may fail on memory-constrained systems.
- Fix approach: Use JSONL format (one record per line) or implement streaming JSON parser. Process records incrementally.

## Architectural Issues

**Tight Coupling Between Detection and Parsing:**
- Issue: `syft_ingest/sources/local.py` couples export format detection to parser delegation
- Files: `syft_ingest/sources/local.py:34-39`, `syft_ingest/sources/facebook.py:79-80`, `syft_ingest/sources/instagram.py:40-76`
- Impact: `_looks_like_brightdata_row()` is called twice: once during file detection, then again during parsing. For large exports, this means scanning files twice. Adding new formats requires modifying local.py.
- Fix approach: Implement pluggable parser registry. Cache detection results to avoid double-scanning.

**No Deduplication Across Multiple Parsing Runs:**
- Issue: `_dedupe_items()` only dedupes within a single parse call
- Files: `syft_ingest/sources/facebook.py:231-272`, `syft_ingest/sources/instagram.py:323-362`
- Impact: If user runs `gather()` twice (once with Meta export, once with Bright Data export of same posts), duplicates appear in corpus. Cross-source deduplication requires post-processing by caller.
- Fix approach: Add corpus-level deduplication in `Corpus` class. Track content hashes across sources.

**Fallback Hashing is Fragile:**
- Issue: `_fallback_hash_for_media_post()` uses post_id + post_url + sorted media URLs
- Files: `syft_ingest/sources/instagram.py:268-273`, `syft_ingest/sources/facebook.py:409-414`
- Impact: If media URLs change (CDN updates, links expire), fallback hash changes and post is treated as new. Posts without text become hard to dedupe. Bright Data exports with missing post_id fall back to index-based ID which is unreliable across re-exports.
- Fix approach: Use stable URL identifier (shortcode for Instagram, post_id for Facebook) as primary key. Only fall back to media hash for truly media-only posts, and warn in logs.

**Inconsistent Metadata Structure Between Sources:**
- Issue: Meta exports and Bright Data exports produce different metadata structures
- Files: `syft_ingest/sources/facebook.py:317-325` (Meta) vs `syft_ingest/sources/facebook.py:490-502` (Bright Data)
- Impact: Consumers of ContentItem must handle optional `post_representation` key and different `extractor` values. Easy to miss fields. Makes RAG pipeline brittle.
- Fix approach: Define strict schema for `post_representation` and require all sources to populate it uniformly. Add validation in ContentItem initialization.

## Test Coverage Gaps

**No Tests for Large File Handling:**
- Issue: Test files use small synthetic data, don't test real-world file sizes
- Files: `tests/test_facebook.py`, `tests/test_instagram.py` - fixtures are manually created JSON objects, not large exports
- Risk: Memory leaks and performance regressions on large exports go undetected. Streaming/pagination code never exercised.
- Recommendation: Add optional integration test with real large exports (if available). Mock large files in unit tests.

**No Tests for Encoding Edge Cases:**
- Issue: `fix_meta_encoding_recursive()` is tested only for known bug pattern
- Files: `syft_ingest/sources/_meta_utils.py:13-35`, `tests/test_meta_utils.py` (limited coverage)
- Risk: Other Unicode/encoding issues in Meta exports go undetected. Fallback behavior (return text as-is) may mask data corruption.
- Fix approach: Add tests for: emoji, RTL text, invalid UTF-8 bytes, mixed encoding in same file.

**Error Path Testing Missing:**
- Issue: JSON parsing errors, missing files, corrupted images tested only via exception capture
- Files: `tests/` - test structure focused on happy path
- Risk: Error messages and skip counts not verified. Silent failures may persist.
- Fix approach: Add unit tests for each `except` block. Verify log output and return values on error.

**No Tests for Concurrent/Streaming Scenarios:**
- Issue: All tests run single-threaded on small datasets
- Risk: Race conditions, memory corruption, or file handle leaks won't surface until production.
- Fix approach: Add tests with multiple workers (if parallelization is added later). Add stress tests with 1000+ items.

## Fragile Areas

**Timestamp Parsing is Defensive but Inconsistent:**
- Issue: Three different timestamp formats handled (UNIX, ISO 8601, string digits)
- Files: `syft_ingest/sources/facebook.py:365-382`, `syft_ingest/sources/instagram.py:207-224`
- Impact: Each source has its own timestamp extraction logic. Easy to miss a format variant in new Bright Data exports. Max timestamp hardcoded at year 2100 (`_MAX_TIMESTAMP = 4102444800`) without comment on why.
- Fix approach: Extract timestamp parsing to shared utility. Document supported formats. Make year 2100 a named constant with explanation.

**String Type Checking is Verbose but Error-Prone:**
- Issue: Pattern like `isinstance(value, str) and value.strip()` repeated ~40 times across sources
- Files: `syft_ingest/sources/facebook.py`, `syft_ingest/sources/instagram.py`, `syft_ingest/sources/_social_media_common.py`
- Impact: Inconsistent type narrowing. E.g., `value.strip()` in truthy position means empty strings are falsy (intended), but None/int passing `isinstance(value, str)` check would fail at runtime if check order changes.
- Fix approach: Create utility function `is_nonempty_string(value: Any) -> bool` and use consistently.

**Post Representation Building is Inconsistent:**
- Issue: Instagram adds more fields (content_type, content_items, audio, thumbnail_url, latest_comments) than Facebook
- Files: `syft_ingest/sources/instagram.py:276-308` vs `syft_ingest/sources/facebook.py:197-215`
- Impact: RAG pipeline must handle optional fields. Embeddings contract and representation metadata may diverge between platforms without clear intent.
- Fix approach: Define canonical post_representation schema. Either all sources support all fields, or fields are properly marked optional with null defaults.

## Dependencies at Risk

**sentence-transformers Has Large Transitive Dependencies:**
- Risk: `sentence-transformers>=3.0` pulls in PyTorch (200MB+), scikit-learn, transformers library
- Impact: Installation of `uv sync --extra multimodal` takes 5+ minutes and uses 1GB+ disk space. Makes Docker image bloated.
- Migration plan: Evaluate `fastembed` (already in dependencies) as alternative. It's smaller and faster for inference. Would require reimplementing CLIP embedding logic.

**OpenCV is Headless-only but Still Large:**
- Risk: `opencv-python-headless` is 50MB+ and depends on many system libraries
- Impact: Adds complexity to Docker builds. May have conflicts with other X11 dependencies.
- Migration plan: Evaluate `ffmpeg` + `PIL` for frame extraction. Would be smaller and more portable.

**Whisper Can Hang on Bad Audio:**
- Risk: `openai-whisper` doesn't have built-in timeout for transcription
- Impact: Processing corrupted video with bad audio can hang indefinitely
- Fix approach: Wrap whisper calls in timeout. Add early validation of audio streams.

## Security Considerations

**No URL Validation Before Following Links:**
- Issue: URLs extracted from posts are stored but never validated
- Files: `syft_ingest/sources/facebook.py:206`, `syft_ingest/sources/instagram.py:453-456`
- Current mitigation: URLs are only stored, not followed. No network requests made.
- Recommendation: If RAG pipeline ever fetches content from extracted URLs, implement URL whitelist and DNS rebinding protection.

**User-Controlled Author/Name in Metadata:**
- Issue: Author field comes directly from post data without sanitization
- Files: `syft_ingest/sources/instagram.py:386`, `syft_ingest/sources/facebook.py:422`
- Current mitigation: Only used as metadata, not executed or injected into HTML.
- Recommendation: If author field is used in templates or logs, escape properly.

**File Path Injection in Frame Output:**
- Issue: `_collect_video_frame_paths()` uses video_idx to build directory name
- Files: `syft_ingest/rag/embedders/multimodal_post.py:239`
- Current mitigation: Path is constructed with f-string, not user input.
- Recommendation: When moving frames to stable location, validate no `../` traversal in post_id.

## Known Bugs

**Media Type Guessing is Based on URL Extension Only:**
- Symptoms: Video with image extension (e.g., `video.jpg`) or image with ambiguous MIME type will be misclassified
- Files: `syft_ingest/sources/_social_media_common.py` (contains `guess_media_type()`)
- Trigger: Bright Data exports with incorrect file extensions
- Workaround: Pre-process and normalize media URLs before parsing

**Bare URL Detection Doesn't Handle Trailing Whitespace:**
- Symptoms: `"  https://example.com  "` (with spaces) is not detected as bare URL, gets included as text content
- Files: `syft_ingest/sources/instagram.py:392`, `syft_ingest/sources/facebook.py:428`
- Trigger: Posts with only a URL plus surrounding whitespace
- Workaround: Manually filter such posts from corpus
- Fix: Call `.strip()` before checking `is_bare_url()`

**ISO DateTime Parsing Breaks on Milliseconds Without Fractional Seconds:**
- Symptoms: `"2025-08-22T18:04:35.000Z"` (zero milliseconds) parses fine, but `"2025-08-22T18:04:35Z"` (no ms at all) also parses fine. However, a datetime string like `"2025-08-22T18:04:35.0Z"` may behave unexpectedly.
- Files: `syft_ingest/sources/instagram.py:162-174`, `syft_ingest/sources/facebook.py:172-185`
- Trigger: Bright Data exports with inconsistent datetime formatting
- Workaround: Normalize datetime strings before parsing
- Fix: Use `datetime.fromisoformat()` carefully or use `dateutil.parser` for robustness

## Missing Critical Features

**No Incremental/Resumable Ingestion:**
- Problem: If embedding a large corpus fails mid-way, user must start over. No checkpoint system.
- Blocks: Long-running ingestion jobs, restart on failure, progress tracking
- Impact: For corpus with 100k+ items, a failure after 50k items means losing all progress
- Suggested approach: Store processed item IDs in a JSON file. Skip already-processed items on re-run.

**No Source Reconciliation Across Updates:**
- Problem: If user re-exports their Facebook data, syft-ingest can't tell which items are updated vs. new vs. deleted
- Blocks: Keeping RAG index in sync with source of truth
- Impact: Duplicate posts accumulate, deleted posts persist in search results
- Suggested approach: Use post_id + updated_at timestamp. Mark items for deletion if not seen in latest export.

**No Rate Limiting or Backpressure:**
- Problem: If embedding model is slow, pipeline doesn't throttle source processing
- Blocks: Graceful degradation under load
- Impact: Memory builds up if sources feed faster than embeddings consume
- Suggested approach: Add queue-based architecture with configurable batch sizes and rate limits.

**No Retry Logic for Transient Failures:**
- Problem: Network timeouts, temporary file I/O errors cause permanent failure
- Blocks: Reliable ingestion in cloud environments
- Impact: Intermittent outages cause data loss
- Suggested approach: Wrap file I/O and model loading in retry decorators with exponential backoff

---

*Concerns audit: 2026-04-06*
