# Roadmap: syft-ingest Data Acquisition

## Overview

This milestone replaces the manual "download export, drop in directory" workflow with programmatic content fetching. We rebase onto the merged PR #8 library API, define a ContentFetcher abstraction, build three implementations (Bright Data for FB/IG, yt-dlp for YouTube, web scraper for blog/article sites), and wire them into the existing URL router and gather() function so that a creator URL is all you need.

## Architecture

```
                        ┌─────────────────────┐
                        │    Creator URL       │
                        │ (FB/IG/YT/TikTok/Web│
                        └─────────┬───────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │   url_router.py       │
                      │   resolve_url()       │
                      │                       │
                      │  URL → Platform enum  │
                      │  Platform → Method    │
                      └───────┬───────────────┘
                              │
                  ┌───────────┼──────────────────────┐
                  │ AcquisitionMethod                 │
                  ▼           ▼                       ▼
    ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
    │  BRIGHT_DATA     │ │  YT_DLP          │ │ ░░ WEB_SCRAPE ░░ │
    │  (FB/IG/TikTok)  │ │  (YouTube)       │ │ ░░ (blogs/sites)░│
    └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
             │                    │                     │
             ▼                    ▼                     ▼
  ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
  │░░ BrightData     ░░│ │░░ YtDlp          ░░│ │░░ WebArticle     ░░│
  │░░ Fetcher        ░░│ │░░ Fetcher        ░░│ │░░ Fetcher        ░░│
  │░░ (Phase 2)      ░░│ │░░ (Phase 3)      ░░│ │░░ (Phase 5)      ░░│
  │░░                ░░│ │░░                ░░│ │░░                ░░│
  │░░ trigger→poll→  ░░│ │░░ yt-dlp metadata░░│ │░░ trafilatura /  ░░│
  │░░ fetch lifecycle░░│ │░░ channel enum   ░░│ │░░ article extract░░│
  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
           │                     │                      │
           └─────────────┬───────┴──────────────────────┘
                          │
                          ▼
  ┌───────────────────────────────────────────────────┐
  │              ░░ ContentFetcher ABC ░░              │
  │              ░░ (Phase 1)         ░░              │
  │                                                   │
  │  fetch(platform, urls) → list[ContentItem]        │
  │  ░░ Fetcher Registry: platform → implementation ░░│
  └───────────────────────┬───────────────────────────┘
                          │
     ┌────────────────────┼─────────────────────┐
     │                    │                     │
     ▼                    ▼                     ▼
┌──────────┐     ┌──────────────┐      ┌──────────────┐
│ PARSERS  │     │ ContentItem  │      │ Corpus       │
│ Registry │     │ VideoResult  │      │ all_items()  │
│          │     │ PaperResult  │      │ add()        │
│ (detect, │     │ ArticleResult│      │ export()     │
│  parse)  │     │ PodcastResult│      └──────┬───────┘
│          │     └──────────────┘             │
│ facebook │            ▲              ┌─────┴──────┐
│ instagram│            │              │            │
└────┬─────┘            │              ▼            ▼
     │                  │     ┌────────────┐ ┌───────────┐
     └──────────────────┘     │  export()  │ │ ingest()  │
     local exports            │ jsonl/json │ │ chunk →   │
     (existing)               │ /text      │ │ embed →   │
                              └────────────┘ │ Qdrant    │
                                             └───────────┘
                                                  │
                                                  ▼
                                          ┌──────────────┐
                                          │  RAG / CLIP  │
                                          │  embedders   │
                                          │  (post+video)│
                                          └──────────────┘

  ░░ = new (this milestone) ░░
  ── = existing
```

**Data flow**: URL → `resolve_url()` → platform + method → ContentFetcher dispatch → `list[ContentItem]` → Corpus → export or embed into Qdrant.

**Existing**: PARSERS registry (local file parsing), models, exporters, embedding pipeline, url_router.
**New (this milestone)**: ContentFetcher ABC + registry (Phase 1), BrightDataFetcher (Phase 2), YtDlpFetcher (Phase 3), wiring into gather() (Phase 4), WebArticleFetcher for blogs/articles (Phase 5).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Rebase & ContentFetcher Abstraction** - Rebase onto main, define ContentFetcher ABC and fetcher registry
- [ ] **Phase 2: Bright Data Fetcher** - First ContentFetcher implementation: trigger/poll/fetch lifecycle for FB/IG
- [ ] **Phase 3: YouTube Fetcher** - Second ContentFetcher implementation: yt-dlp metadata extraction and channel enumeration
- [ ] **Phase 4: Integration & Wiring** - Wire fetchers into URL router dispatch and gather() function
- [ ] **Phase 5: Web Article Fetcher** - Third ContentFetcher implementation: extract blog posts and articles from creator websites

## Phase Details

### Phase 1: Rebase & ContentFetcher Abstraction
**Goal**: Branch is current with main and the ContentFetcher contract is defined so implementations can be built independently
**Depends on**: Nothing (first phase)
**Requirements**: CP-01, CP-02, CP-03, CP-04
**Success Criteria** (what must be TRUE):
  1. Branch rebased onto main with no conflicts; all existing tests pass
  2. A ContentFetcher ABC exists with a `fetch(platform, urls)` method that returns `list[ContentItem]`
  3. A fetcher registry maps platform identifiers to ContentFetcher implementations and allows runtime swapping
  4. Each registered fetcher encapsulates its own auth and error handling -- callers interact only with the registry and receive ContentItem output
**Plans:** 2 plans

Plans:
- [x] 01-01-PLAN.md — ContentFetcher Protocol + FetchError hierarchy (CP-01, CP-03)
- [ ] 01-02-PLAN.md — Fetcher registry with register/get/swap (CP-02, CP-04)

### Phase 2: Bright Data Fetcher
**Goal**: Callers can programmatically fetch FB/IG content through Bright Data without manual exports
**Depends on**: Phase 1
**Requirements**: BD-01, BD-02, BD-03, BD-04, BD-05
**Success Criteria** (what must be TRUE):
  1. Calling `BrightDataFetcher.fetch("facebook", urls)` triggers a Bright Data scrape and returns ContentItem results
  2. Polling uses exponential backoff with a configurable timeout -- a hung scrape does not hang the caller
  3. Errors are classified into distinct categories (empty results, failed scrape, timeout, rate-limited) with appropriate exceptions
  4. API credentials are loaded exclusively from environment variables -- no secrets in code
**Plans**: TBD

### Phase 3: YouTube Fetcher
**Goal**: Callers can extract YouTube video metadata and enumerate channels without manual steps
**Depends on**: Phase 1
**Requirements**: YT-01, YT-02, YT-03, YT-04, YT-05
**Success Criteria** (what must be TRUE):
  1. Calling `YtDlpFetcher.fetch("youtube", urls)` returns VideoResult objects with title, description, stats, thumbnail URL, tags, and upload date
  2. A channel URL produces an enumerated list of videos (capped via `playlistend`) without downloading video files
  3. Full video+audio download is available only when explicitly requested via a configuration flag
  4. YtDlpFetcher is registered in the fetcher registry as the default fetcher for YouTube
**Plans**: TBD

### Phase 4: Integration & Wiring
**Goal**: A creator URL from any supported platform flows through URL router to the correct fetcher and into gather() seamlessly
**Depends on**: Phase 2, Phase 3
**Requirements**: INT-01, INT-02, INT-03
**Success Criteria** (what must be TRUE):
  1. A YouTube URL passed to the URL router dispatches to YtDlpFetcher and returns content
  2. A Facebook or Instagram URL passed to the URL router dispatches to BrightDataFetcher and returns content
  3. `gather()` accepts URL-based sources alongside existing local export sources and produces the same output format
**Plans**: TBD

### Phase 5: Web Article Fetcher
**Goal**: Callers can extract blog posts and articles from creator websites (e.g., seriouseats.com/j-kenji-lopez-alt) without manual steps
**Depends on**: Phase 1
**Requirements**: WEB-01, WEB-02, WEB-03, WEB-04
**Success Criteria** (what must be TRUE):
  1. Calling `WebArticleFetcher.fetch("web", urls)` returns ArticleResult objects with title, author, text, published date, and site name
  2. Given an author/archive page URL, the fetcher discovers and extracts individual article URLs (pagination-aware)
  3. Article extraction handles diverse site layouts via trafilatura or similar library -- no per-site selectors required
  4. WebArticleFetcher is registered in the fetcher registry and url_router maps non-social URLs to WEB_SCRAPE acquisition method
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5
Note: Phases 2, 3, and 5 are independent (all depend only on Phase 1) and could execute in any order.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Rebase & ContentFetcher Abstraction | 0/2 | Planning complete | - |
| 2. Bright Data Fetcher | 0/0 | Not started | - |
| 3. YouTube Fetcher | 0/0 | Not started | - |
| 4. Integration & Wiring | 0/0 | Not started | - |
| 5. Web Article Fetcher | 0/0 | Not started | - |
