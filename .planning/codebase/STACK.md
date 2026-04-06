# Technology Stack

**Analysis Date:** 2026-04-06

## Languages

**Primary:**
- Python 3.12+ - All application code, scripts, and tooling
- JSON - Data serialization format for content and embeddings

## Runtime

**Environment:**
- Python 3.12 (minimum requirement)
- Runs on macOS, Linux (tested), Windows (assumed compatible)

**Package Manager:**
- `uv` - Modern, fast Python package manager
- Lockfile: `uv.lock` (present, tracks all transitive dependencies)

## Frameworks & Core Libraries

**Data Validation:**
- Pydantic >= 2.0 - Type validation and data models (`syft_ingest/core/models.py` defines `ContentItem`, `Corpus`, `VideoResult`, `PaperResult`, `ArticleResult`, `PodcastResult`)

**Logging:**
- loguru >= 0.7 - Structured logging throughout codebase (`from loguru import logger` in `syft_ingest/sources/facebook.py`, `instagram.py`, `local.py`)

**Content Download:**
- yt-dlp >= 2024.0 - YouTube video downloading and metadata extraction

## Key Dependencies by Feature

### Core Social Media Parsing
- **Facebook/Instagram Processing:**
  - No external dependencies required for Meta export parsing
  - Parses native "Download Your Information" JSON format
  - Parses Bright Data crawler JSON exports
  - Custom encoding normalization for UTF-8-as-Latin-1 mojibake

### Optional Feature: Web Content Extraction
- trafilatura >= 1.0 - HTML content extraction
- beautifulsoup4 >= 4.12 - HTML parsing
- Install: `uv sync --extra web`

### Optional Feature: Academic Papers (arXiv)
- arxiv >= 2.0 - arXiv API client
- pymupdf >= 1.23 - PDF text extraction
- Install: `uv sync --extra arxiv`

### Optional Feature: Podcast Audio Transcription
- openai-whisper >= 20230918 - Speech-to-text for audio files
- Install: `uv sync --extra podcast`

### Optional Feature: RAG/Embeddings Foundation
- fastembed >= 0.3 - Lightweight embedding models
- langchain-text-splitters >= 0.2 - Text chunking for embeddings
- Install: `uv sync --extra rag`

### Optional Feature: Multimodal Video/Image Embeddings
- opencv-python-headless >= 4.10 - Video frame extraction (no GUI dependency)
- Pillow >= 10.0 - Image loading and processing
- sentence-transformers >= 3.0 - CLIP model inference for embeddings
- Install: `uv sync --extra multimodal`

**Note:** Frame extraction happens in `syft_ingest/rag/embedders/multimodal_video.py:extract_frames_with_opencv()`, embedding in `syft_ingest/rag/embedders/clip_contract.py:load_sentence_transformer()`.

### Vector Database Support (Optional)
All optional, layered on top of `rag` extra:
- qdrant-client >= 1.9 - Qdrant vector database
  - Install: `uv sync --extra qdrant`
- weaviate-client >= 4.0 - Weaviate vector database
  - Install: `uv sync --extra weaviate`
- chromadb >= 0.4 - Chroma vector database
  - Install: `uv sync --extra chroma`

**Status:** Installed but not actively used in current codebase. Preparation for future integration.

### Optional Feature: OpenAI Embeddings
- openai >= 1.0 - OpenAI API client for embedding models
- Install: `uv sync --extra openai-embeddings`
- Not currently used; prepared for integration

### Optional Feature: NotebookLM Integration
- notebooklm-py >= 0.1 - NotebookLM API wrapper (third-party)
- Install: `uv sync --extra notebooklm`
- Status: Optional integration, not actively used

### Install All Extras
```bash
uv sync --extra all
```
Installs every optional dependency for development/testing of all features.

## Development Tools

**Build System:**
- hatchling - Python project builder

**Code Quality:**
- ruff >= 0.12.0 - Fast Python linter and formatter
  - Config: `pyproject.toml [tool.ruff.lint]`
  - Extends selection with import sorting (`extend-select = ["I"]`)
  - Per-file ignores: `__init__.py` ignores `F401` (unused imports)

**Pre-commit Hooks:**
- pre-commit >= 4.0 - Git hook framework
- Config: `.pre-commit-config.yaml`
- Active hooks:
  - Standard checks (AST, trailing whitespace, YAML, merge conflicts, shebangs, debug statements)
  - Mixed line ending fix (normalize to LF)
  - ruff format and lint with auto-fix

**Testing:**
- pytest >= 9.0.2 - Test runner
- Tests run via: `uv run pytest tests/ -v`

## Configuration

**Environment:**
- No `.env` file required (configuration-less design)
- Project uses local file paths and command-line arguments
- Suitable for CI/CD and containerized deployments

**Build Configuration:**
- `pyproject.toml` - Single source of truth for project metadata, dependencies, and tool config
- `uv.lock` - Locked dependency versions for reproducible installs

**Runtime Configuration:**
- CLI: `syft_ingest` command with argparse-based flags (`syft_ingest/cli.py`)
- Python API: Keyword arguments to `gather()` function in `syft_ingest/core/gather.py`

## Platform Requirements

**Development:**
- Python 3.12+
- `uv` package manager
- For multimodal features: ffmpeg (implicit dependency of opencv for video processing)

**Production:**
- Python 3.12+ runtime
- Deployment target: Local filesystem or containerized environment
- No database server required (works with file-based data)
- Optional: Vector database (Qdrant, Weaviate, Chroma) if using embeddings

## Integration Points

**Incoming Data:**
- Local filesystem: Facebook/Instagram JSON exports, video files
- YouTube: via yt-dlp (when YouTube source enabled)

**Outgoing Data:**
- JSONL files (compatible with syft-influencer ingest pipeline)
- JSON files
- Text files (one per content item)

---

*Stack analysis: 2026-04-06*
