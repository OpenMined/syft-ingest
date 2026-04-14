# syft-ingest — Project Guidelines

## What this project is

A general-purpose, person-centric content aggregator. Scrape → normalize → deliver. See `.docs/arch.md` for architecture and `.docs/plans.md` for implementation plan.

## Confidentiality rules

**CRITICAL: This is a personal open-source project. Never expose private information from any employer, client, or organization.**

- **No company names** in code, comments, commit messages, README, or any public-facing file. No references to specific organizations, their products, internal tools, or internal script paths.
- **No real person names** of customers, trial users, or business contacts. Use generic examples like `"Andrej Karpathy"` or `"Kenji López-Alt"` (public figures only).
- **No internal architecture details** of any employer's systems — no endpoint URLs, API keys, database schemas, embedding model configs tied to a specific company's pipeline, or internal script paths.
- **No business strategy** — no customer validation data, revenue figures, pricing, pipeline details, or competitive positioning that came from employer work.
- **Private notes stay private.** The `.docs/` directory is gitignored and must NEVER be committed. If referencing `.docs/` content in code or public files, generalize it first.
- **Commit messages must be clean.** No references to any employer, their products, or internal systems in git history.

When in doubt: would this line make sense to a stranger with no knowledge of any specific company? If not, generalize it.

## Python standards

- **Package manager**: `uv` (never pip)
- **Logging**: `loguru`
- **Paths**: `pathlib.Path`
- **Models**: Pydantic with type hints at boundaries
- **Tests**: Plain `test_` prefix functions, `conftest.py` for shared fixtures
- **Validation**: Never trust unvalidated data across boundaries

## Architecture principles

- **Scope**: Scrape → normalize → deliver. No query engines, no LLM generation, no messaging, no analytics.
- **YAGNI**: Don't build sources, adapters, or features until they're needed.
- **Dual sync/async protocols**: `ContentFetcher` (sync) and `AsyncContentFetcher` (async). Fetcher authors implement whichever is natural. Framework bridges via `run_fetcher_sync`/`run_fetcher_async`.
- **Two gather functions**: `gather()` (sync) and `async_gather()` (async). Follows httpx Client/AsyncClient convention. Never use a flag to switch return types.
- **Protocols over concrete types**: `VectorStore` and `Embedder` are protocols. Depend on abstractions.
- **Chunking ownership**: `to_rag()` chunks. `export()` does NOT chunk. This is non-negotiable.
- **Embedding model match**: Always document which embedding model is being used. Default is `BAAI/bge-small-en-v1.5` but users must be able to swap it.

## Workflow

1. **Research** → read arch.md, existing code, related context before planning
2. **Plan** → write what files to modify, function signatures, data flow
3. **Implement** → execute the plan, one file/function at a time
4. **Test** → write and run tests, verify outputs
5. Gate: "Does this conform to the plan?" → "Would a stranger understand this code?" → "Did I leak any private info?"
