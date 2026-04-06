# Coding Conventions

**Analysis Date:** 2026-04-06

## Naming Patterns

**Files:**
- Snake case: `_meta_utils.py`, `_social_media_common.py`
- Private/internal utilities prefixed with underscore: `_meta_utils.py`, `_social_media_common.py`
- Source modules by platform: `facebook.py`, `instagram.py`, `local.py`
- Examples: `syft_ingest/sources/facebook.py`, `syft_ingest/rag/embedders/multimodal_post.py`

**Functions:**
- Snake case for all functions: `extract_post_text()`, `fix_meta_encoding()`, `derive_title()`
- Private functions prefixed with underscore: `_extract_post_text()`, `_looks_like_brightdata_row()`
- Helper functions with clear intent: `_safe_timestamp()`, `_parse_iso_datetime()`, `_dedupe_items()`

**Variables:**
- Snake case consistently: `raw_items`, `published_at`, `post_representation`
- Boolean flags with `is_` or `has_` prefix: `is_bare_url()`, `has_text_payload`
- Abbreviations avoided except for standard conventions: `tmp_path` (test fixture), `exc` (exception)

**Types:**
- Pydantic model names in PascalCase: `ContentItem`, `VideoResult`, `PaperResult`, `SourceType`
- Enum members in UPPERCASE_CONSTANT: `SourceType.YOUTUBE`, `SourceType.LOCAL`
- Dictionary keys as snake_case: `post_id`, `page_name`, `content_hash`

**Constants:**
- All caps with underscores: `_MAX_TIMESTAMP`, `DEFAULT_CLIP_MODEL`, `EMBEDDING_BACKEND`
- Module-level constants clearly defined: `_HASHTAG_RE`, `_MENTION_RE`, `_HTTP_URL_RE`

## Code Style

**Formatting:**
- Tool: `ruff` with `ruff-format`
- Config: `pyproject.toml` at `[tool.ruff.lint]`
- Line length: No explicit limit set; follows ruff defaults (~88 chars)
- Import sorting: Enabled with `extend-select = ["I"]`

**Linting:**
- Tool: `ruff`
- Key rule: Import sorting enabled via config
- Per-file ignores: `"**/__init__.py" = ["F401"]` (unused imports allowed in `__init__.py`)
- Pre-commit hooks: `ruff` and `ruff-format` configured in `.pre-commit-config.yaml`

**Trailing whitespace and line endings:**
- Pre-commit checks for trailing whitespace
- Mixed line endings fixed to LF via pre-commit hook

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first)
2. Standard library imports: `import json`, `from datetime import UTC, datetime`
3. Third-party packages: `from pydantic import BaseModel`, `from loguru import logger`
4. Local imports: `from syft_ingest.core.models import ContentItem`

**Path Aliases:**
- No aliases used; absolute imports from package root
- Pattern: `from syft_ingest.sources._meta_utils import extract_hashtags`
- Example: `syft_ingest/sources/facebook.py` → `from syft_ingest.core.models import ContentItem`

**Grouping:**
- Blank line between each import group
- Imports within groups sorted alphabetically by `ruff`
- Single-line imports preferred; multi-import acceptable for closely related items

## Error Handling

**Patterns:**
- Broad exception catching in entry points with graceful degradation
  - `gather()` function catches `Exception` and logs error, continues processing
  - File parsers catch `json.JSONDecodeError`, `UnicodeDecodeError` specifically
- Domain-specific exceptions raised for API boundary violations
  - `ValueError("interval_seconds must be > 0")` in `multimodal_video.py`
  - `ImportError` re-raised as `RuntimeError` with helpful message
- Safe conversion functions return `None` on invalid input
  - `_safe_timestamp()` returns `None` for invalid timestamps
  - `_parse_iso_datetime()` returns `None` for unparseable strings
- Type validation before processing with guard clauses
  - `if not isinstance(row, dict): return False`
  - `if not isinstance(raw, list) or not raw: return False`

**Defense at boundaries:**
- JSON parsing wrapped in try/except to catch decode errors
- File I/O wrapped with OSError handling
- Import guards for optional dependencies raise helpful RuntimeError with installation instructions

## Logging

**Framework:** `loguru`

**Patterns:**
- Import: `from loguru import logger` (module level)
- Used for informational events and error reporting
- Levels employed:
  - `logger.info()` for significant pipeline events: `"Gathered {count} items for {name}"`
  - `logger.warning()` for skipped data or unimplemented features: `"Source 'local' specified but no local_dirs provided"`
  - `logger.error()` for failures to process: `"Failed to fetch from source {source!r}: {e}"`
- Format style: Using f-strings with `!r` for repr formatting
- Example from `facebook.py`:
  ```python
  logger.info(f"Facebook Bright Data ({path.name}): {len(items)} raw → {len(final)} after dedup")
  ```

## Comments

**When to Comment:**
- Module docstrings describe purpose and design decisions: See `facebook.py` docstring explaining Meta export support
- Function docstrings for complex behavior: `_extract_post_text()` documents extraction strategy
- Inline comments explain why, not what: "blog post link typically last" in `_extract_post_url()`
- Magic numbers documented: `_MAX_TIMESTAMP = 4102444800  # Max reasonable timestamp: year 2100`

**JSDoc/TSDoc:**
- Docstrings follow Google style
- Triple quotes used: `"""..."""`
- Include summary + description for non-trivial functions
- Example from `_extract_post_text()`:
  ```python
  """Extract text content from a Facebook post.

  Primary: data[0].post
  Fallback: first media description in attachments
  """
  ```

## Function Design

**Size:**
- Prefer focused, single-responsibility functions
- Longest functions (200+ lines) are data extraction with multiple fallback paths
- Typical utility functions 10-50 lines

**Parameters:**
- Positional parameters first, keyword-only for optional configuration
- Example: `gather(name, *, sources=None, local_dirs=None, **kwargs)`
- Type hints on all parameters and return values
- Example: `def build_embedding_contract(model_name: str) -> dict[str, Any]`

**Return Values:**
- Consistent return types (don't mix `list` and `None` without reason)
- Safe extraction functions return `None` on failure, not empty list
- Tuple returns for multi-value extraction with logging: `(items, skipped_count)`

**Type hints:**
- Used throughout: functions have full type annotations
- Union types via `|` syntax (Python 3.10+): `str | None`, `dict[str, Any]`
- Example: `def _safe_timestamp(timestamp) -> datetime | None:`

## Module Design

**Exports:**
- Core public API in `__init__.py` files for easy discovery
- `syft_ingest/__init__.py` exports: `gather`, `Corpus`, `ContentItem`, `SourceType`
- Private implementation details prefixed with underscore: `_meta_utils`, `_social_media_common`

**Barrel Files:**
- `syft_ingest/rag/embedders/__init__.py` lists exports for clarity
- `syft_ingest/sources/__init__.py` marks module boundaries

**Layering:**
- Core models/contracts: `syft_ingest/core/`
- Platform-specific parsers: `syft_ingest/sources/`
- Feature extraction: `syft_ingest/rag/embedders/`

---

*Convention analysis: 2026-04-06*
