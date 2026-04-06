# Testing Patterns

**Analysis Date:** 2026-04-06

## Test Framework

**Runner:**
- `pytest` (version >=9.0.2 from `pyproject.toml`)
- Config: No explicit `pytest.ini`; uses pyproject.toml or defaults

**Assertion Library:**
- pytest's built-in assertions: `assert condition`
- `pytest.approx()` for floating-point comparisons: `assert fused == pytest.approx([0.970143, 0.242536], abs=1e-5)`

**Run Commands:**
```bash
pytest                           # Run all tests
pytest -xvs                      # Run with verbose output, stop on first failure
pytest tests/test_facebook.py   # Run single test file
pytest tests/test_facebook.py::test_extract_post_text_from_data  # Run specific test
pytest --cov=syft_ingest        # Run with coverage (if coverage installed)
```

## Test File Organization

**Location:**
- Co-located in `tests/` directory at repository root
- Separate from source code; `tests/` parallel to `syft_ingest/`
- Pattern: `tests/test_<module>.py` mirrors source module names

**Naming:**
- Test files: `test_*.py` pattern
- Test functions: `test_<description>()` snake_case
- Examples: `test_extract_post_text_from_data()`, `test_is_bare_url_true()`

**Structure:**
```
tests/
├── conftest.py                          # Shared fixtures
├── test_facebook.py                     # Tests for facebook.py parser
├── test_instagram.py                    # Tests for instagram.py parser
├── test_local.py                        # Tests for local.py loader
├── test_cli.py                          # CLI integration tests
├── test_e2e.py                          # End-to-end pipeline tests
├── test_meta_utils.py                   # Tests for shared _meta_utils
├── test_clip_contract.py                # CLIP embedding contract tests
├── test_multimodal_post.py              # Multimodal embedding tests
├── test_multimodal_video.py             # Video extraction tests
└── __init__.py
```

## Test Structure

**Suite Organization:**
```python
# Unit test: single function behavior
def test_extract_post_text_from_data():
    post = {"data": [{"post": "Hello world"}]}
    assert _extract_post_text(post) == "Hello world"

# Parametric behavior with fixtures
def test_is_facebook_export(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")
    assert is_facebook_export(fb_export_path)

# Integration test with multiple components
def test_e2e_facebook_gather_and_export_jsonl(fb_export_path, output_dir):
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(fb_export_path)],
    )
    corpus.export("jsonl", output=str(output_file))
    assert output_file.exists()
```

**Patterns:**
- **Setup**: Create fixtures or inline test data (avoid side effects)
- **Teardown**: Implicit via pytest fixtures with cleanup (e.g., `tmp_path` is auto-cleaned)
- **Assertion**: Direct `assert` statements; no verbose assertion libraries

## Mocking

**Framework:**
- No explicit mocking framework used (no `unittest.mock` or `pytest-mock` imports)
- Real I/O used for integration tests; `tmp_path` fixture for file operations

**Patterns:**
- Prefer integration over mocking: tests call actual parsers with real JSON
- Fixtures for test data: `conftest.py` provides `fb_export_path`, `ig_export_path`
- Temporary directories for file operations: `tmp_path` pytest builtin
  ```python
  def test_cli_local_export_jsonl(tmp_path):
      brightdata_dir = tmp_path / "brightdata-ig"
      brightdata_dir.mkdir(parents=True, exist_ok=True)
      (brightdata_dir / "brightdata-instagram.json").write_text(...)
  ```

**What to Mock:**
- External I/O that's slow or has side effects (not done in current codebase)
- Optional dependencies with helpful error messages (tested via try/except boundaries)

**What NOT to Mock:**
- File I/O (use `tmp_path` instead)
- JSON parsing (test with real JSON structures)
- Data transformation functions (call actual implementations)
- Platform-specific parsers (Facebook, Instagram)

## Fixtures and Factories

**Test Data:**
```python
# From conftest.py - fixtures for test data paths
@pytest.fixture
def fb_export_path():
    return DATA_DIR / "fb-page-2026-03-18"

@pytest.fixture
def ig_export_path():
    return DATA_DIR / "instagram-2026-03-18"

@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "output"

# Inline factories in test_e2e.py
def test_e2e_brightdata_facebook_gather_and_export_jsonl(tmp_path, output_dir):
    brightdata_dir = tmp_path / "brightdata-fb"
    brightdata_payload = [
        {
            "post_id": "122243006504090679",
            "url": "https://www.facebook.com/reel/1378171301018195/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "Easy flower tutorial #watercolor",
            "attachments": [...],
        }
    ]
    (brightdata_dir / "brightdata-sample.json").write_text(
        json.dumps(brightdata_payload), encoding="utf-8"
    )
```

**Location:**
- Shared fixtures: `tests/conftest.py`
- Test-specific fixtures: Inline in test files
- Test data paths: `DATA_DIR = Path(__file__).parent.parent / "data" / "creators" / "syft-influencer-test"`

## Coverage

**Requirements:**
- Not explicitly enforced (no coverage threshold in config)
- Coverage tool not in dev dependencies by default

**View Coverage:**
```bash
# Install coverage tools first (not in standard dev dependencies)
uv pip install pytest-cov
pytest --cov=syft_ingest --cov-report=html
```

**Current Coverage:**
- Core parsing logic well-covered: `test_facebook.py` (28 tests), `test_instagram.py` (multiple tests)
- E2E pipeline: 10 integration tests in `test_e2e.py`
- Total test count: ~1412 lines across 10 test files

## Test Types

**Unit Tests:**
- Scope: Individual function behavior, edge cases
- Approach: Test single function in isolation with known inputs
- Examples:
  - `test_extract_post_text_from_data()` - tests extraction from specific dict structure
  - `test_fix_meta_encoding_curly_apostrophe()` - tests character encoding fix
  - `test_simple_summarize_text_noop_for_short_text()` - tests truncation logic
- Location: `tests/test_*.py` files with prefix `test_`

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Call parsers with real JSON, verify output structure
- Examples:
  - `test_parse_instagram_export_brightdata_extracts_post_representation()` - parser + dedup
  - `test_cli_local_export_jsonl()` - CLI + parser + exporter
- Location: `tests/test_e2e.py` for pipeline tests; module-specific tests

**E2E Tests:**
- Framework: pytest with fixtures and real file I/O
- Pattern: `gather()` → `export()` pipeline with verification
- Examples from `test_e2e.py`:
  ```python
  def test_e2e_facebook_gather_and_export_jsonl(fb_export_path, output_dir):
      corpus = syft_ingest.gather(
          "Syft Influencer Test",
          sources=["local"],
          local_dirs=[str(fb_export_path)],
      )
      corpus.export("jsonl", output=str(output_file))
      lines = output_file.read_text().strip().splitlines()
      assert len(lines) == len(corpus.all_items())
      for line in lines:
          record = json.loads(line)
          assert record["metadata"]["platform"] == "facebook"
          assert record["metadata"]["content_hash"]
  ```

## Common Patterns

**Async Testing:**
- Not used; codebase is synchronous

**Error Testing:**
```python
# Test with pytest.skip for conditional test data
def test_is_facebook_export(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")
    assert is_facebook_export(fb_export_path)

# Test error conditions
def test_is_bare_url_true():
    assert is_bare_url("https://openmined.org/")
    assert is_bare_url("  https://example.com  ")

def test_is_bare_url_false():
    assert not is_bare_url("Blog post\nhttps://example.com")
    assert not is_bare_url("Hello world")

# Test ValueError boundaries
from syft_ingest.rag.embedders.multimodal_video import fuse_modality_embeddings
# Function raises ValueError for invalid parameters
```

**Determinism Testing:**
```python
def test_e2e_stable_ids_are_deterministic_and_unique(fb_export_path, output_dir):
    # Export twice, IDs should be identical
    file1 = output_dir / "run1.jsonl"
    file2 = output_dir / "run2.jsonl"
    for f in [file1, file2]:
        corpus = syft_ingest.gather(...)
        corpus.export("jsonl", output=str(f))

    ids1 = [json.loads(line)["id"] for line in file1.read_text().strip().splitlines()]
    ids2 = [json.loads(line)["id"] for line in file2.read_text().strip().splitlines()]
    assert ids1 == ids2, "IDs should be deterministic across runs"
    assert len(ids1) == len(set(ids1)), "IDs should be unique"
```

**Boundary Testing:**
```python
# Test with empty input
def test_e2e_empty_local_dirs():
    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=["/nonexistent/path"]
    )
    assert len(corpus.all_items()) == 0

# Test with unknown source
def test_e2e_unknown_source_does_not_crash():
    corpus = syft_ingest.gather("Test", sources=["nonexistent"])
    assert len(corpus.all_items()) == 0

# Test with multiple inputs
def test_fetch_local_multiple_dirs(fb_export_path, ig_export_path):
    items = fetch_local(
        [str(fb_export_path), str(ig_export_path)],
        author="Test Author",
    )
    assert len(items) > 0
    platforms = {item.metadata.get("platform") for item in items}
    assert "facebook" in platforms
    assert "instagram" in platforms
```

**Floating-point Comparisons:**
```python
def test_fuse_modality_embeddings_reweights_missing_modalities():
    fused = fuse_modality_embeddings(
        text_embedding=[1.0, 0.0],
        image_embedding=[0.0, 1.0],
        video_embedding=None,
        text_weight=0.8,
        image_weight=0.2,
        video_weight=0.0,
    )
    assert fused == pytest.approx([0.970143, 0.242536], abs=1e-5)
```

---

*Testing analysis: 2026-04-06*
