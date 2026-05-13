# Graph + Vector RAG Research

## The Problem with Plain Vector RAG

Current syft-influencer DM pipeline: `query -> embed -> cosine similarity -> top-K chunks -> LLM -> answer`

Chunks are isolated -- no relationships between them. A fan asking "What does Kenji think about wok hei vs regular stir fry?" gets 25 chunks mentioning "wok" or "stir fry" with no structural connection between the concepts.

---

## GraphRAG: Graph-Enhanced Retrieval

**Source**: DeepLearning.AI "Knowledge Graphs for RAG" course (Andrew Ng + Neo4j)

Instead of replacing RAG, use graph structure to make RAG smarter. Combine graph traversal (structured relationships) with vector similarity (semantic matching).

### How it works

1. **Extract** entities + relationships from text (person, technique, ingredient, recipe, video...)
2. **Store** in Neo4j as a knowledge graph (nodes = entities, edges = relationships)
3. **Query** with Cypher (graph queries) + vector similarity together
4. **LLM** gets structured relational context, not just flat chunks

### Plain RAG vs GraphRAG

| Approach                            | What gets retrieved                                                                                                                | Weakness                                                        |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **Vector RAG** (Qdrant only)  | 25 chunks with high cosine similarity to query                                                                                     | Chunks are isolated; no relationships; multi-hop questions fail |
| **GraphRAG** (Neo4j + Qdrant) | Entity "wok hei" -> connected to "carbon steel wok" -> connected to "stir fry technique" -> connected to specific video timestamps | More complex infrastructure                                     |

### Why graph + vectors > either alone

- **Vector search** excels at: semantic similarity, fuzzy matching, finding relevant passages even with different wording
- **Graph traversal** excels at: multi-hop reasoning, entity relationships, structured facts (job title, start date, ingredients list), temporal connections
- **Combined**: vector finds the neighborhood, graph provides the structure

---

## Relevant Tools & Frameworks

### Microsoft GraphRAG

- **Source**: [microsoft.github.io/graphrag](https://microsoft.github.io/graphrag/)
- Extracts knowledge graph from text, builds community hierarchy (Leiden clustering), generates community summaries
- Best for global queries across large document sets
- 90% hallucination reduction vs plain RAG
- Expensive to build (many LLM calls), no incremental updates
- **Maturity**: Production-grade, Microsoft-backed

### LightRAG

- **Source**: [github.com/hkuds/lightrag](https://github.com/hkuds/lightrag) (20k+ stars)
- Lightweight alternative to GraphRAG: dual-level retrieval (entity + relationship level)
- 10x cheaper than GraphRAG, ~30% lower query latency
- **Supports incremental updates** -- no full rebuild when new data arrives
- Published at EMNLP 2025
- **Best fit for syft stack** -- practical, peer-reviewed, incremental

### Graphiti (by Zep)

- **Source**: [github.com/getzep/graphiti](https://github.com/getzep/graphiti)
- Temporally-aware knowledge graph -- tracks when facts were true
- Bi-temporal model: event time vs ingestion time
- Hybrid search: semantic + BM25 + graph traversal
- Good for evolving knowledge (creator changes opinions, updates techniques)
- **Maturity**: Production-grade, backed by Zep

### Neo4j LLM Knowledge Graph Builder

- **Source**: [github.com/neo4j-labs/llm-graph-builder](https://github.com/neo4j-labs/llm-graph-builder)
- Web app: ingest PDFs, docs, YouTube transcripts -> extract entities/relationships -> Neo4j
- Multiple query modes: GraphRAG, vector, Text2Cypher (natural language -> graph queries)
- **Maturity**: Production infra (Neo4j is battle-tested), extraction layer more experimental

### graphify

- **Source**: https://github.com/Graphitti/graphify
- Already has `--neo4j` export (Cypher export or direct push)
- Two-pass extraction: deterministic AST + Claude semantic extraction
- Confidence labels: EXTRACTED / INFERRED / AMBIGUOUS
- Leiden community detection, wiki export, Obsidian vault export
- **Key advantage:** understands code + docs + images

---

## Architecture for syft-influencer + syft-ingest

### Data flow

```
Content -> syft-ingest fetchers (Phases 1-5)
    |
    +-> graphify extract() -> Neo4j (entities + relationships)
    |      graphify already has --neo4j export
    |
    +-> Qdrant (vector embeddings, current path)
    |
    +-> Wiki compilation (Obsidian, creator-facing)

Fan DM -> Neo4j graph traversal + Qdrant vector search -> combined context -> Claude -> answer
```

### Layer assessment

| Layer                                   | DM pipeline              | Creator frontend | Notes                                         |
| --------------------------------------- | ------------------------ | ---------------- | --------------------------------------------- |
| **Content fetching** (Phases 1-5) | Yes                      | Yes              | Foundation                                    |
| **Graph extraction** (graphify)   | Yes -- GraphRAG          | Yes              | Entities + relationships -> Neo4j             |
| **Neo4j**                         | Yes -- graph queries     | Yes              | Structured traversal for multi-hop questions  |
| **Qdrant**                        | Yes -- vector similarity | No               | Complements graph with semantic search        |
| **Wiki compilation**              | No                       | Yes              | Creator-facing Obsidian view                  |
| **Fan query heat map**            | No                       | Yes              | Overlay DM cluster frequency onto graph nodes |
| **LLM health checks** (lint)      | Yes                      | Yes              | Keep graph accurate                           |
| **Delta tracking** (SHA256)       | Yes                      | Yes              | Incremental graph updates                     |

### Same data, multiple frontends

| Frontend                   | User     | Purpose                                    | Backed by                     |
| -------------------------- | -------- | ------------------------------------------ | ----------------------------- |
| Instagram DM pipeline      | Fans     | Automated Q&A via GraphRAG                 | Neo4j + Qdrant                |
| Obsidian wiki + graph view | Creators | Explore and curate their knowledge base    | graphify wiki/obsidian export |
| Admin dashboard            | Ops      | Monitor routing, policies, logs, analytics | SQLite + clustering data      |

---

## Concrete Improvements Over Current System

### 1. Graph layer between raw content and vectors

Currently syft-ingest goes `raw -> chunks -> Qdrant` directly. Adding a graph layer:

- Makes RAG answers auditable (trace to an entity/relationship, not an opaque chunk)
- Enables multi-hop questions (connect concepts across videos/articles)
- Provides structured context alongside semantic matches

### 2. LLM health checks on the knowledge graph

Run periodic audits to flag:

- Stale content (old recipes, updated techniques)
- Contradictions across sources
- Coverage gaps (topics with few entity connections)
- AMBIGUOUS edges from graphify that need human review

### 3. Delta tracking (SHA256 cache)

Adopt graphify's SHA256 cache pattern in syft-ingest `gather()`:

- Skip already-processed content
- Incremental graph updates when new content arrives
- No full rebuild on each run

### 4. Fan query heat map on graph

Overlay DM cluster frequency from syft-influencer onto the knowledge graph:

- Creators see which parts of their content fans engage with most
- Enables data-driven content strategy
- Clustering infrastructure already exists in syft-influencer

---

## YouTube Data Tools (for Phases 1-5)

### Recommended stack

| Layer                                   | Primary tool                                                                          | Fallback                                            | Notes                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------- |
| **Discovery** (find videos)       | [scrapetube](https://github.com/dermasmid/scrapetube) (499 stars)                        | YouTube API v3 `playlistItems.list` (1 unit/page) | No API key needed                               |
| **Metadata** (full details)       | [yt-dlp](https://github.com/yt-dlp/yt-dlp) (156k stars) `extract_info(download=False)` | YouTube API v3 `videos.list` (1 unit)             | Most comprehensive metadata                     |
| **Transcripts** (with timestamps) | [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) (6.8k stars) | yt-dlp subtitle extraction                          | Returns `{text, start, duration}` per segment |

### Transcription for videos without captions

| Tool                                                                 | Type        | Speed          | Timestamps              | Best for                                  |
| -------------------------------------------------------------------- | ----------- | -------------- | ----------------------- | ----------------------------------------- |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (22k stars) | Self-hosted | 4x Whisper     | Word-level              | Primary -- fast, free, accurate           |
| [WhisperX](https://github.com/m-bain/whisperX) (21.2k stars)            | Self-hosted | 70x realtime   | Word-level + speaker ID | Podcasts/interviews (speaker diarization) |
| [AssemblyAI](https://www.assemblyai.com/)                               | API         | Near real-time | Word-level              | Scale without GPU ($0.0025/min)           |

---

## Social Media Data Tools

**Decision: Bright Data for all social media platforms** (FB, IG, TikTok, Twitter/X).

Already implemented in syft-influencer (`scripts/ingestion/brightdata_social_ingest.py`, `app/social_ingestion.py`). Roadmap Phase 2 builds the `BrightDataFetcher` for syft-ingest. API key via `BRIGHTDATA_API_KEY` env var.

Why Bright Data over per-platform scrapers:
- **Single vendor** for FB/IG/TikTok/Twitter — no maintaining 4 fragile scrapers
- **Handles anti-bot** — proxy rotation, browser fingerprinting, CAPTCHA solving managed by Bright Data
- **Trigger/poll/fetch lifecycle** — async scraping with snapshot polling (already proven in syft-influencer)
- **Lower legal risk** — Bright Data operates the scraping infrastructure, not us
- Per-platform tools (twscrape, instagrapi, TikTok-Api) are fragile, break every 2-4 weeks with platform changes, and carry higher TOS risk

| Platform | Acquisition | Notes |
|----------|------------|-------|
| Facebook | Bright Data (Phase 2) | Posts, videos, metadata |
| Instagram | Bright Data (Phase 2) | Reels, IGTV, posts, captions |
| TikTok | Bright Data (Phase 2) | Videos, metadata, captions |
| Twitter/X | Bright Data (Phase 2) | Tweets with video, metadata |
| YouTube | yt-dlp + youtube-transcript-api (Phase 3) | Metadata + timestamped transcripts |
| Blogs/websites | trafilatura (Phase 5) | Article extraction |
| Podcasts | PodcastIndex API + RSS (future) | RSS is designed for programmatic use |

For videos without captions (IG Reels, TikTok), download via yt-dlp then transcribe with faster-whisper.

---

## Karpathy's LLM Wiki Pattern (Background)

**Source**: [Karpathy gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (April 2026)

The insight that informed this research: use LLMs to pre-compile raw research into structured, interlinked markdown wikis. Three operations: ingest (LLM updates 10-15 wiki pages per source), query (synthesize answers with citations), lint (health-check for contradictions and stale content).

For syft stack, this pattern applies to the **creator frontend** (Obsidian wiki) while **GraphRAG** applies to the **DM pipeline** (Neo4j + Qdrant). Both consume the same underlying content from syft-ingest fetchers.

### Tier 1 implementations (Karpathy-inspired)

- [nvk/llm-wiki](https://github.com/nvk/llm-wiki) -- Claude Code plugin, full pipeline
- [second-brain](https://github.com/NicholasSpisak/second-brain) -- best lint implementation
- [obsidian-wiki](https://github.com/Ar9av/obsidian-wiki) -- provenance tracking, graph analysis
- [sage-wiki](https://github.com/xoai/sage-wiki) -- single Go binary, hybrid search
- [llmwiki](https://github.com/lucasastorian/llmwiki) -- web app + MCP

All very early stage (born April 2026). graphify is more mature and already in the codebase.

---

## Priority Order

1. **Phases 1-5** -- content fetching (foundation for everything)
2. **Delta tracking** -- adopt graphify's SHA256 cache in `gather()` (quick win)
3. **graphify integration** -- `import graphify` in syft-ingest, extract entities/relationships
4. **Neo4j setup** -- graphify `--neo4j` export, hybrid query layer
5. **Wiki compilation** -- Obsidian vault per creator (creator frontend)
6. **Fan query heat map** -- overlay cluster frequency onto graph
7. **LLM health checks** -- periodic lint on graph + wiki
