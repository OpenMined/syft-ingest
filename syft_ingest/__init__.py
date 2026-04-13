from syft_ingest.core.fetcher import (
    ContentFetcher,
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
)
from syft_ingest.core.gather import gather
from syft_ingest.core.ingest import (
    ChunkingSpec,
    Embedder,
    EmbeddingSpec,
    IngestError,
    IngestReport,
    MissingDependencyError,
    NoDocumentsError,
    QdrantDestination,
    UnsupportedBackendError,
    ingest_corpus,
    ingest_jsonl,
)
from syft_ingest.core.registry import FetcherKey, get_fetcher, register_fetcher
from syft_ingest.core.source_specs import SocialProfileSource, SourceSpec
from syft_ingest.setup import register_fetchers

__all__ = [
    "ChunkingSpec",
    "ContentFetcher",
    "Embedder",
    "EmbeddingSpec",
    "FetchAuthError",
    "FetchEmptyResultError",
    "FetchError",
    "FetcherKey",
    "FetchRequest",
    "FetchResult",
    "FetchTimeoutError",
    "IngestError",
    "IngestReport",
    "MissingDependencyError",
    "NoDocumentsError",
    "QdrantDestination",
    "SocialProfileSource",
    "SourceSpec",
    "UnsupportedBackendError",
    "gather",
    "get_fetcher",
    "ingest_corpus",
    "ingest_jsonl",
    "register_fetcher",
]

# Register all available fetchers on library import
register_fetchers()
