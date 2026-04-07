# syft-ingest: Data Acquisition

## What This Is

syft-ingest is a multi-platform content ingestion pipeline that fetches social media content, normalizes it into structured models, and feeds it through embedding pipelines for vector search. This milestone focuses on expanding acquisition capabilities — adding programmatic Bright Data API scraping, YouTube ingestion via yt-dlp, TikTok support, and a URL router to unify platform dispatch.

## Core Value

Given a creator URL from any supported platform, syft-ingest fetches their content, normalizes it, and makes it searchable — without manual export steps.

## Requirements

### Validated

- ✓ Facebook content parsing from Meta exports and Bright Data crawler exports — existing
- ✓ Instagram content parsing from Meta exports and Bright Data crawler exports — existing
- ✓ Pydantic data models: ContentItem, VideoResult, PaperResult, ArticleResult, PodcastResult, Corpus — existing
- ✓ Multimodal embedding pipeline (CLIP + Whisper) for posts and videos — existing
- ✓ Export to JSONL/JSON/text formats — existing
- ✓ CLI interface for local export processing — existing
- ✓ Registry-based source auto-detection via pluggable (detect_fn, parse_fn) tuples — existing

### Active

- [ ] Bright Data API client that triggers scrapes programmatically for FB/IG/TikTok
- [ ] YouTube source via yt-dlp: metadata + thumbnails always, full video download optional
- [ ] URL router that detects platform from creator URL and dispatches to correct source
- [ ] TikTok data model and Bright Data response parser

### Out of Scope

- PR #8 fixes (ingest → Qdrant + library API) — separate effort, not part of this milestone
- Twitter/X support — no immediate need
- Rate limiting / queue system — scale is small (1-10 creators per run)
- Continuous/scheduled scraping — manual trigger is sufficient for now

## Context

- **Existing codebase**: Python 3.12+, Pydantic v2, loguru, uv package manager
- **yt-dlp is already a dependency** but unused — wiring to VideoResult model is the work
- **Bright Data credentials exist** but API endpoints need research
- **Architecture is plugin-based**: PARSERS registry in `syft_ingest/sources/local.py` makes adding new sources straightforward
- **Embedding pipeline already handles video**: CLIP for frames + Whisper for audio transcription, just needs content fed to it
- **Scale**: Small batch processing (1-10 creators per run), no need for async/queue infrastructure

## Constraints

- **Package manager**: Must use `uv` (project convention)
- **Data models**: Must use Pydantic v2 (existing pattern)
- **Source pattern**: New sources must follow the existing `(detect_fn, parse_fn)` registry pattern
- **API research needed**: Bright Data API endpoints and response formats need investigation before implementation
- **No secrets in code**: Bright Data API credentials must come from environment variables

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| YouTube via yt-dlp (not Bright Data) | Free, no API dependency, yt-dlp already installed | — Pending |
| Bright Data API for FB/IG/TikTok | Programmatic scraping vs manual file exports | — Pending |
| PR #8 out of scope | Separate effort, keeps this milestone focused on acquisition | — Pending |
| Metadata-first, video-optional for YouTube | Thumbnails always available; full download is expensive | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-07 after initialization*
