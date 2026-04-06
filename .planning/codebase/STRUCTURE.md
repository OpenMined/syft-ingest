# Codebase Structure

**Analysis Date:** 2026-04-06

## Directory Layout

```
syft-ingest/
├── syft_ingest/              # Main package
│   ├── __init__.py           # Exports gather()
│   ├── cli.py                # CLI entry point
│   ├── core/                 # Core aggregation and export
│   │   ├── __init__.py
│   │   ├── models.py         # Pydantic data contracts (ContentItem, Corpus)
│   │   ├── gather.py         # gather() orchestrator
│   │   └── exporters.py      # Export strategies (JSONL, JSON, text)
│   ├── sources/              # Platform-specific parsers
│   │   ├── __init__.py
│   │   ├── local.py          # Directory dispatcher (registry pattern)
│   │   ├── facebook.py       # Facebook Meta + Bright Data parser
│   │   ├── instagram.py      # Instagram Meta + Bright Data parser
│   │   ├── _meta_utils.py    # Shared Meta platform utilities
│   │   └── _social_media_common.py  # Shared social media utilities
│   └── rag/                  # Multimodal embeddings (optional)
│       ├── __init__.py
│       ├── embedders/        # Embedding generators
│       │   ├── __init__.py
│       │   ├── clip_contract.py     # CLIP embedding metadata contract
│       │   ├── multimodal_post.py   # Post embeddings (text + media)
│       │   └── multimodal_video.py  # Video embeddings (frames + transcript)
│       └── stores/           # Vector store integrations (placeholder)
│           └── __init__.py
├── tests/                    # Test suite
│   ├── conftest.py           # Pytest fixtures
│   ├── test_meta_utils.py    # Meta encoding, extraction utils
│   ├── test_facebook.py      # Facebook parser
│   ├── test_instagram.py     # Instagram parser
│   ├── test_local.py         # Local dispatcher
│   ├── test_e2e.py           # gather() → export() pipeline
│   ├── test_clip_contract.py # Embedding contract
│   ├── test_multimodal_post.py   # Post embedding
│   └── test_multimodal_video.py  # Video embedding
├── scripts/                  # Standalone utilities
│   ├── embed_posts_multimodal.py   # Post embedding script
│   └── embed_video_multimodal.py   # Video embedding script
├── docs/                     # Documentation
├── pyproject.toml            # Project metadata, dependencies, extras
├── uv.lock                   # Lock file
├── README.md                 # User-facing documentation
├── LICENSE                   # MIT
├── .gitignore                # Version control exclusions
├── .pre-commit-config.yaml   # Pre-commit hooks
└── justfile                  # Task commands
```

## Directory Purposes

**syft_ingest/:**
- Purpose: Main package containing all production code
- Contains: Subpackages for core, sources, rag; CLI module
- Key files: `__init__.py` (public API via `gather`), `cli.py` (entry point)

**syft_ingest/core/:**
- Purpose: Core aggregation, data models, and export logic
- Contains: Pydantic models, gather orchestrator, export strategies
- Key files: `models.py` (data contracts), `gather.py` (orchestration), `exporters.py` (output formats)

**syft_ingest/sources/:**
- Purpose: Platform-specific parsers and auto-detection
- Contains: Parsers for Facebook, Instagram; dispatcher; shared utilities
- Key files: `local.py` (registry-based dispatcher), `facebook.py` (20KB parser), `instagram.py` (20KB parser)
- Special: `_meta_utils.py` and `_social_media_common.py` are private helpers (underscore prefix)

**syft_ingest/rag/:**
- Purpose: Optional multimodal embedding generation
- Contains: CLIP embedding contract, post/video embedding generators, vector store stubs
- Key files: `embedders/clip_contract.py` (metadata schema), `embedders/multimodal_post.py`, `embedders/multimodal_video.py`
- Status: `stores/` is placeholder, not implemented

**tests/:**
- Purpose: pytest-based unit and integration test suite
- Contains: Test files for each module, shared fixtures
- Key files: `conftest.py` (fixtures), `test_e2e.py` (pipeline tests), `test_facebook.py` and `test_instagram.py` (parser tests)
- Coverage: 48 tests across 8 files

**scripts/:**
- Purpose: Standalone executable scripts for embedding generation
- Contains: `embed_posts_multimodal.py`, `embed_video_multimodal.py`
- Invocation: `uv run python scripts/embed_*.py --help`

## Key File Locations

**Entry Points:**
- `syft_ingest/__init__.py`: Public API, exports `gather()`
- `syft_ingest/cli.py`: Command-line interface, `main()` function
- `scripts/embed_posts_multimodal.py`: Post embedding standalone entry point
- `scripts/embed_video_multimodal.py`: Video embedding standalone entry point

**Configuration:**
- `pyproject.toml`: Project metadata, dependencies (core + optional extras for web, arxiv, rag, multimodal, stores)
- `uv.lock`: Dependency lock file
- `.pre-commit-config.yaml`: Pre-commit hooks (ruff, prettier, etc.)
- `justfile`: Common commands (format, lint, test)

**Core Logic:**
- `syft_ingest/core/models.py`: Data model definitions (ContentItem, Corpus, SourceType)
- `syft_ingest/core/gather.py`: Main orchestrator, calls sources
- `syft_ingest/core/exporters.py`: Serialization to JSONL/JSON/text
- `syft_ingest/sources/local.py`: Dispatcher with registry pattern
- `syft_ingest/sources/facebook.py`: Facebook parser (~330 lines)
- `syft_ingest/sources/instagram.py`: Instagram parser (~340 lines)

**Testing:**
- `tests/conftest.py`: Fixtures (fb_export_path, ig_export_path)
- `tests/test_e2e.py`: Full pipeline tests (gather + export)
- `tests/test_facebook.py`: Facebook parser unit tests
- `tests/test_instagram.py`: Instagram parser unit tests
- `tests/test_local.py`: Dispatcher tests
- `tests/test_meta_utils.py`: Encoding and extraction utilities tests
- `tests/test_clip_contract.py`: Embedding contract tests
- `tests/test_multimodal_post.py`: Post embedding tests
- `tests/test_multimodal_video.py`: Video embedding tests

## Naming Conventions

**Files:**
- `models.py`: Pydantic data classes
- `gather.py`: Orchestration/main logic
- `exporters.py`: Format-specific output logic
- `_private.py`: Shared internal utilities (underscore prefix)
- `test_*.py`: Test files, one per module being tested
- `embed_*.py` in scripts/: Standalone executable scripts

**Directories:**
- `core/`: Core aggregation, models, export (no platform-specific logic)
- `sources/`: Platform-specific parsers
- `rag/`: Optional multimodal embedding features
- `embedders/`: Embedding generators (subdir of rag/)
- `stores/`: Vector store backends (subdir of rag/, currently empty)
- `tests/`: All test files at same level, not nested per module
- `scripts/`: Executable Python scripts meant to be run directly

**Functions and Classes:**
- `gather()`: Main public function (no underscore)
- `parse_facebook_export()`: Platform-specific parse function
- `fetch_local()`: Source-specific fetch function
- `_extract_post_text()`: Private helper (underscore prefix)
- `_item_to_dict()`: Private helper (underscore prefix)
- `ContentItem`: Public data class (PascalCase)
- `Corpus`: Public data class (PascalCase)
- `SourceType`: Public enum (PascalCase)

**Constants:**
- `DEFAULT_CLIP_MODEL`: Module-level constant (UPPER_SNAKE_CASE)
- `_MAX_TIMESTAMP`: Private constant (underscore + UPPER_SNAKE_CASE)
- `_PLATFORM_SITES`: Module-level mapping (underscore + UPPER_SNAKE_CASE)

## Where to Add New Code

**New Content Source (e.g., TikTok, YouTube):**
1. Create `syft_ingest/sources/tiktok.py` with functions:
   - `is_tiktok_export(directory: Path) -> bool`: Detection logic
   - `parse_tiktok_export(directory: Path, author: str) -> list[ContentItem]`: Parser
2. Add `SourceType.TIKTOK = "tiktok"` to `syft_ingest/core/models.py` if needed
3. Add field `tiktok: list[VideoResult] = Field(default_factory=list)` to `Corpus` model
4. Append `(is_tiktok_export, parse_tiktok_export)` to `PARSERS` list in `syft_ingest/sources/local.py`
5. Write tests in `tests/test_tiktok.py` following pattern of `test_facebook.py` and `test_instagram.py`

**New Export Format (e.g., CSV):**
1. Add function `_export_csv(items: list[ContentItem], output: str) -> None` to `syft_ingest/core/exporters.py`
2. Add format case in `export()` function (line 102–111)
3. Add tests to `tests/test_e2e.py` for new format

**New Embedder:**
1. Create `syft_ingest/rag/embedders/new_model.py` with function:
   - `embed_new_model(...) -> dict | list[dict]`: Embedding generator
2. Export from `syft_ingest/rag/embedders/__init__.py`
3. Create standalone script `scripts/embed_new_model.py` if standalone execution needed
4. Add tests to `tests/test_embedding_new.py`

**Shared Utility:**
- Platform-specific helpers: `syft_ingest/sources/_platform_utils.py`
- General-purpose helpers: Consider if it fits in existing `_meta_utils.py` or `_social_media_common.py`, or create new utility module

**Test Fixtures:**
- Add to `tests/conftest.py` as `@pytest.fixture` functions
- Reference test data from `./data/` directory (must clone from `syft-influencer-data` repo)

## Special Directories

**data/ (Not Committed):**
- Purpose: Test data (Facebook, Instagram exports)
- Generated: Manual clone from `https://github.com/OpenMined/syft-influencer-data.git`
- Committed: No, listed in `.gitignore`
- Access: `tests/conftest.py` mounts as `DATA_DIR`

**.planning/ (Not Committed):**
- Purpose: Local planning artifacts
- Generated: By GSD orchestrator
- Committed: No, must add to `.gitignore` if not already
- Contents: ARCHITECTURE.md, STRUCTURE.md, etc. (ephemeral)

**docs/:**
- Purpose: User/developer documentation (currently minimal)
- Committed: Yes
- Contents: Markdown files (if any)

---

*Structure analysis: 2026-04-06*
