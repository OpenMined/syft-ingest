# Requirements: syft-ingest Data Acquisition

**Defined:** 2026-04-08
**Core Value:** Given a creator URL, fetch their content programmatically without manual export steps.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Content Fetcher Abstraction

- [x] **CP-01**: Define `ContentFetcher` protocol/ABC with methods: `fetch(platform, urls) -> list[ContentItem]` — Strategy pattern
- [x] **CP-02**: Fetcher registry allows swapping implementations (Bright Data, Apify, AI agents) without changing callers
- [x] **CP-03**: Each fetcher encapsulates its own auth, polling, error handling — callers see only `ContentItem` output
- [x] **CP-04**: Fetcher selection configurable per-platform (e.g., YouTube=yt-dlp, FB=BrightData, IG=Apify)

### Bright Data Fetcher (first ContentFetcher implementation)

- [ ] **BD-01**: Implements ContentFetcher — triggers scrape via Bright Data API given platform + input URLs
- [ ] **BD-02**: Polls snapshot status with timeout and exponential backoff
- [ ] **BD-03**: Fetches completed snapshot results as structured data
- [ ] **BD-04**: Classifies errors: empty results vs. failed scrape vs. timeout vs. rate-limited
- [ ] **BD-05**: API credentials (token, dataset IDs) loaded from environment variables

### yt-dlp Fetcher (second ContentFetcher implementation)

- [ ] **YT-01**: Implements ContentFetcher — extracts video metadata (title, description, stats, thumbnail, tags, upload date) via yt-dlp library API
- [ ] **YT-02**: Maps yt-dlp metadata to existing VideoResult model
- [ ] **YT-03**: Enumerates videos from a channel URL using `extract_flat` with `playlistend` cap
- [ ] **YT-04**: Optionally downloads full video + audio when explicitly requested (configurable flag)
- [ ] **YT-05**: Registered in fetcher registry as default fetcher for YouTube platform

### Integration & Wiring

- [ ] **INT-01**: Wire YouTube source into existing URL router for dispatch from YouTube URLs
- [ ] **INT-02**: Wire Bright Data client into URL router for FB/IG URL dispatch
- [ ] **INT-03**: `gather()` function supports URL-based source alongside existing local export source

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### TikTok

- **TT-01**: Parse Bright Data TikTok response to ContentItem/VideoResult
- **TT-02**: Immediate media download on fetch (CDN URLs expire in hours)
- **TT-03**: Register TikTok in PARSERS for local export processing

### Additional Fetchers

- **PRV-01**: Apify ContentFetcher implementation
- **PRV-02**: AI agentic ContentFetcher implementation (browser automation via LLM)

### Additional Platforms

- **PLT-01**: X/Twitter parser via Bright Data API
- **PLT-02**: Slack ingestion (requires different approach — not web-scrapable)
- **PLT-03**: WhatsApp/Telegram/Zalo content ingestion

### Data Freshness & Updates

- **DATA-01**: ContentFetcher accepts `since_date` param for incremental fetches (only new posts)
- **DATA-02**: Scheduled/cron-based re-fetching for tracked creators (e.g., daily stock market influencer updates)
- **DATA-03**: Deduplication across incremental runs — don't re-ingest content already in Qdrant

### Stale Data & Cleanup

- **STALE-01**: Detect inactive creators (no new posts in configurable window)
- **STALE-02**: Purge deleted/removed content from Qdrant when source confirms removal
- **STALE-03**: Mark creators as inactive in content_sources when they stop posting on a platform

### URL Router Enhancements

- **URL-01**: Resolve short-link redirects (vm.tiktok.com, youtu.be, fb.watch)
- **URL-02**: Extract content ID from URL path for direct content fetch

## Out of Scope

| Feature | Reason |
|---------|--------|
| PR #8 fixes (Qdrant ingest + library API) | Separate effort |
| Async/queue infrastructure | Scale is small (1-10 creators), sync is sufficient |
| Webhook callbacks from Bright Data | Polling is simpler for small scale |
| Scheduled/continuous scraping | Manual trigger is sufficient |
| Browser automation / Puppeteer | Bright Data handles anti-bot |
| Auto-transcription via Whisper in YouTube source | Existing embedding pipeline handles this downstream |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CP-01 | Phase 1 | Complete |
| CP-02 | Phase 1 | Complete |
| CP-03 | Phase 1 | Complete |
| CP-04 | Phase 1 | Complete |
| BD-01 | Phase 2 | Pending |
| BD-02 | Phase 2 | Pending |
| BD-03 | Phase 2 | Pending |
| BD-04 | Phase 2 | Pending |
| BD-05 | Phase 2 | Pending |
| YT-01 | Phase 3 | Pending |
| YT-02 | Phase 3 | Pending |
| YT-03 | Phase 3 | Pending |
| YT-04 | Phase 3 | Pending |
| YT-05 | Phase 3 | Pending |
| INT-01 | Phase 4 | Pending |
| INT-02 | Phase 4 | Pending |
| INT-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-04-08*
*Last updated: 2026-04-06 after roadmap creation*
