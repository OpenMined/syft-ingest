from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from loguru import logger
from pydantic import BaseModel, Field

from syft_ingest.core.models import Corpus

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - optional dependency
    RecursiveCharacterTextSplitter = None


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class IngestError(Exception):
    """Base exception for ingestion errors."""


class MissingDependencyError(IngestError):
    """A required optional dependency is not installed."""


class NoDocumentsError(IngestError):
    """No documents available for ingestion."""


class UnsupportedBackendError(IngestError):
    """The requested embedding backend is not supported."""


# ---------------------------------------------------------------------------
# Embedder protocol
# ---------------------------------------------------------------------------

DEFAULT_TEXT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_EMBEDDING_BACKEND = "fastembed"


@runtime_checkable
class Embedder(Protocol):
    """Protocol for text embedding backends."""

    def embed(self, texts: Iterable[str]) -> Iterable[list[float]]: ...


# ---------------------------------------------------------------------------
# Public config models (Pydantic at boundaries)
# ---------------------------------------------------------------------------


class EmbeddingSpec(BaseModel, frozen=True):
    backend: str = DEFAULT_EMBEDDING_BACKEND
    model: str = DEFAULT_TEXT_MODEL


class ChunkingSpec(BaseModel, frozen=True):
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=250, ge=0)
    min_chunk_size: int = Field(default=200, ge=0)


class QdrantDestination(BaseModel, frozen=True):
    collection_name: str = Field(min_length=1)
    url: str | None = "http://127.0.0.1:6333"
    path: str | None = None
    timeout: float = Field(default=60.0, gt=0)
    batch_size: int = Field(default=500, gt=0)
    reset_collection: bool = False


class IngestReport(BaseModel, frozen=True):
    collection_name: str
    documents_total: int
    chunks_total: int
    point_ids: list[str]
    embedding_contract: dict[str, Any]


# ---------------------------------------------------------------------------
# Internal doc representation
# ---------------------------------------------------------------------------


class _Doc:
    __slots__ = ("text", "payload")

    def __init__(self, text: str, payload: dict[str, Any]) -> None:
        self.text = text
        self.payload = payload


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def normalize_embedding_backend(backend: str | None) -> str:
    value = (backend or DEFAULT_EMBEDDING_BACKEND).strip().lower()
    if value in {"fastembed", "fast-embed"}:
        return "fastembed"
    if value in {"sentence-transformers", "sentence_transformers"}:
        return "sentence-transformers"
    return value


def build_embedding_space(model_name: str, backend: str | None = None) -> str:
    normalized_backend = normalize_embedding_backend(backend)
    return f"{normalized_backend}:{model_name}"


def _infer_embedding_family(model_name: str, backend: str | None = None) -> str | None:
    normalized_backend = normalize_embedding_backend(backend)
    lower_name = model_name.strip().lower()
    if "clip" in lower_name:
        return "clip"
    if "bge" in lower_name:
        return "bge"
    if normalized_backend == "fastembed":
        return "text"
    return None


def build_embedding_contract(
    model_name: str,
    backend: str | None = None,
    *,
    embedding_dim: int | None = None,
) -> dict[str, Any]:
    normalized_backend = normalize_embedding_backend(backend)
    contract: dict[str, Any] = {
        "embedding_backend": normalized_backend,
        "embedding_model": model_name,
        "embedding_space": build_embedding_space(model_name, normalized_backend),
    }
    family = _infer_embedding_family(model_name, normalized_backend)
    if family:
        contract["embedding_family"] = family
    if normalized_backend == "sentence-transformers":
        contract["embedding_normalized"] = True
    if embedding_dim is not None:
        contract["embedding_dim"] = int(embedding_dim)
    return contract


def build_text_embedder(model_name: str, backend: str | None = None) -> Embedder:
    normalized_backend = normalize_embedding_backend(backend)
    if normalized_backend == "fastembed":
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - dependency failure
            raise MissingDependencyError(
                "fastembed is required for backend='fastembed'. Install with: `uv sync --extra rag`"
            ) from exc
        return TextEmbedding(model_name=model_name)
    if normalized_backend == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency failure
            raise MissingDependencyError(
                "sentence-transformers is required for backend='sentence-transformers'. "
                "Install with: `uv sync --extra multimodal`"
            ) from exc

        class SentenceTransformersTextEmbedder:
            def __init__(self, model: str) -> None:
                self._model = SentenceTransformer(model)

            def embed(self, texts: Iterable[str]) -> Iterable[list[float]]:
                text_list = list(texts)
                if not text_list:
                    return iter(())
                vectors = self._model.encode(
                    text_list,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                return iter(
                    [
                        vector.tolist() if hasattr(vector, "tolist") else list(vector)
                        for vector in vectors
                    ]
                )

        return SentenceTransformersTextEmbedder(model_name)
    raise UnsupportedBackendError(f"Unsupported embedding backend: {backend!r}")


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _import_qdrant():
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Distance, PointStruct, VectorParams
    except ImportError as exc:  # pragma: no cover - dependency failure
        raise MissingDependencyError(
            "qdrant-client is required for Qdrant ingestion. Install with: `uv sync --extra qdrant`"
        ) from exc
    return QdrantClient, Distance, PointStruct, VectorParams


def _merge_embedding_contract(
    payload: dict[str, Any], contract: dict[str, Any]
) -> None:
    metadata = payload.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata.update(contract)
    payload["metadata"] = metadata


# ---------------------------------------------------------------------------
# Chunking — to_rag() owns chunking per CLAUDE.md
# ---------------------------------------------------------------------------


def _chunk_text(text: str, spec: ChunkingSpec) -> list[str]:
    if not text:
        return []
    if RecursiveCharacterTextSplitter is None:
        return [text[: spec.chunk_size]]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=spec.chunk_size,
        chunk_overlap=spec.chunk_overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
        keep_separator=True,
        length_function=len,
    )
    chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
    if spec.min_chunk_size <= 0:
        return chunks
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < spec.min_chunk_size:
            merged[-1] = f"{merged[-1]} {chunk}".strip()
        else:
            merged.append(chunk)
    return merged


_SOURCE_TYPE_LABELS: dict[str, str] = {
    "youtube_caption_chunk": "Video",
    "youtube_video_metadata": "Video",
    "recipe": "Recipe",
    "recipe_page": "Recipe",
}


def _enrich_text(doc: _Doc) -> str:
    source_type = str(doc.payload.get("source_type") or "").strip()
    label = _SOURCE_TYPE_LABELS.get(
        source_type, source_type.replace("_", " ").title() if source_type else ""
    )
    title = str(doc.payload.get("title") or "").strip()
    published_at = str(doc.payload.get("published_at") or "").strip()

    if not title and not label:
        return doc.text

    header_parts: list[str] = []
    if label and title:
        header_parts.append(f"{label}: {title}")
    elif title:
        header_parts.append(title)
    elif label:
        header_parts.append(label)
    if published_at:
        date_str = published_at[:10] if len(published_at) >= 10 else published_at
        header_parts.append(f"Published: {date_str}")

    header = f"[{' | '.join(header_parts)}]"
    metadata = doc.payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    description = str(metadata.get("video_description") or "").strip()
    desc_line = ""
    if description:
        truncated = (
            description[:200].rsplit(" ", 1)[0].rstrip()
            if len(description) > 200
            else description
        )
        desc_line = f"\n{truncated}"
    return f"{header}{desc_line}\n\n{doc.text}"


def to_rag(docs: list[_Doc], chunking: ChunkingSpec) -> list[_Doc]:
    """Chunk documents for RAG ingestion.

    This is the single place where chunking happens, per architecture rule:
    'to_rag() chunks. export() does NOT chunk.'
    """
    chunked: list[_Doc] = []
    for doc in docs:
        enriched = _enrich_text(doc)
        chunks = _chunk_text(enriched, chunking)
        raw_hash = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
        source_id = doc.payload.get("url") or doc.payload.get("title") or "doc"
        stable_doc_key = f"{source_id}::{doc.payload.get('source', '')}::{raw_hash}"
        raw_doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, stable_doc_key))

        for idx, chunk in enumerate(chunks):
            payload = dict(doc.payload)
            payload.update(
                {
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "text": chunk,
                    "raw_text": doc.text,
                    "excerpt": chunk[:240],
                    "_raw_doc_id": raw_doc_id,
                }
            )
            chunked.append(_Doc(text=chunk, payload=payload))
    return chunked


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------


def _doc_from_record(obj: dict[str, Any]) -> _Doc | None:
    text = obj.get("text") or obj.get("content") or ""
    if not text:
        return None
    metadata = obj.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    payload = {
        "source": obj.get("source", metadata.get("source")),
        "source_type": obj.get("source_type", metadata.get("source_type")),
        "author": obj.get("author", metadata.get("author")),
        "title": obj.get("title", metadata.get("title")),
        "url": obj.get("url", metadata.get("url")),
        "published_at": obj.get("published_at", metadata.get("published_at")),
        "tags": obj.get("tags", metadata.get("tags", [])),
        "site": obj.get("site", metadata.get("site")),
        "ingested_at": obj.get("ingested_at", metadata.get("ingested_at")),
        "metadata": metadata,
    }
    payload["excerpt"] = obj.get(
        "excerpt", obj.get("summary", payload.get("excerpt", text[:240]))
    )
    return _Doc(text=text, payload=payload)


def _iter_docs_from_jsonl(manifest_jsonl: str | Path) -> list[_Doc]:
    path = Path(manifest_jsonl).expanduser().resolve()
    docs: list[_Doc] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Skipping malformed JSONL at line {}: {}", line_number, exc
                )
                continue
            if not isinstance(record, dict):
                continue
            doc = _doc_from_record(record)
            if doc is not None:
                docs.append(doc)
    return docs


def _iter_docs_from_corpus(corpus: Corpus) -> list[_Doc]:
    docs: list[_Doc] = []
    for item in corpus.all_items():
        metadata = dict(item.metadata or {})
        payload = {
            "source": metadata.get("source"),
            "source_type": metadata.get("source_type"),
            "author": item.author,
            "title": item.title,
            "url": item.url,
            "published_at": item.published_at.isoformat()
            if item.published_at
            else None,
            "tags": metadata.get("tags", []),
            "site": metadata.get("site"),
            "ingested_at": metadata.get("ingested_at"),
            "metadata": metadata,
            "excerpt": item.text[:240],
        }
        docs.append(_Doc(text=item.text, payload=payload))
    return docs


# ---------------------------------------------------------------------------
# Qdrant upsert with rollback
# ---------------------------------------------------------------------------


def _upsert_qdrant_points(
    client, destination: QdrantDestination, points: list[dict]
) -> list[str]:
    inserted_ids: list[str] = []
    if not points:
        return inserted_ids
    batch_size = max(1, destination.batch_size)
    _, _, PointStruct, _ = _import_qdrant()
    try:
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            point_structs = [
                PointStruct(
                    id=point["id"], vector=point["vector"], payload=point["payload"]
                )
                for point in batch
            ]
            client.upsert(
                collection_name=destination.collection_name, points=point_structs
            )
            inserted_ids.extend(point["id"] for point in batch)
    except Exception:
        if inserted_ids:
            try:
                client.delete(
                    collection_name=destination.collection_name,
                    points_selector=inserted_ids,
                )
            except Exception as rollback_exc:
                logger.error(
                    "Rollback failed for collection {!r}: could not delete {} orphaned points. "
                    "Manual cleanup may be required. Error: {}",
                    destination.collection_name,
                    len(inserted_ids),
                    rollback_exc,
                )
        raise
    return inserted_ids


def _create_qdrant_client(destination: QdrantDestination):
    QdrantClient, Distance, _, VectorParams = _import_qdrant()
    kwargs: dict[str, Any] = {"timeout": destination.timeout}
    if destination.path:
        kwargs["path"] = destination.path
    elif destination.url:
        kwargs["url"] = destination.url
    else:
        raise IngestError("QdrantDestination requires url or path")
    return QdrantClient(**kwargs), Distance, VectorParams


# ---------------------------------------------------------------------------
# Core ingest pipeline
# ---------------------------------------------------------------------------


def _ingest_docs(
    docs: list[_Doc],
    *,
    destination: QdrantDestination,
    embedding: EmbeddingSpec,
    chunking: ChunkingSpec,
) -> IngestReport:
    if not docs:
        raise NoDocumentsError("No documents available for ingestion")

    embedder = build_text_embedder(embedding.model, embedding.backend)
    sample_vector = next(embedder.embed(["sample"]))
    embedding_contract = build_embedding_contract(
        embedding.model,
        embedding.backend,
        embedding_dim=len(sample_vector),
    )

    client, Distance, VectorParams = _create_qdrant_client(destination)
    existing = [c.name for c in client.get_collections().collections]
    if destination.reset_collection and destination.collection_name in existing:
        client.delete_collection(collection_name=destination.collection_name)
        existing.remove(destination.collection_name)
    if destination.collection_name not in existing:
        client.create_collection(
            collection_name=destination.collection_name,
            vectors_config=VectorParams(
                size=len(sample_vector), distance=Distance.COSINE
            ),
        )

    # Chunking happens in to_rag(), not here.
    rag_docs = to_rag(docs, chunking)

    points: list[dict[str, Any]] = []
    for doc in rag_docs:
        vectors = list(embedder.embed([doc.text]))
        if not vectors:
            continue
        vector = vectors[0]
        vector = vector.tolist() if hasattr(vector, "tolist") else list(vector)

        payload = dict(doc.payload)
        _merge_embedding_contract(payload, embedding_contract)

        raw_doc_id = payload.pop("_raw_doc_id", "doc")
        chunk_hash = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
        chunk_index = payload.get("chunk_index", 0)
        stable_key = f"{raw_doc_id}::{chunk_index}::{chunk_hash}"
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, stable_key))
        points.append({"id": point_id, "vector": vector, "payload": payload})

    point_ids = _upsert_qdrant_points(client, destination, points)
    return IngestReport(
        collection_name=destination.collection_name,
        documents_total=len(docs),
        chunks_total=len(points),
        point_ids=point_ids,
        embedding_contract=embedding_contract,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_jsonl(
    manifest_jsonl: str | Path,
    *,
    destination: QdrantDestination,
    embedding: EmbeddingSpec | None = None,
    chunking: ChunkingSpec | None = None,
) -> IngestReport:
    return _ingest_docs(
        _iter_docs_from_jsonl(manifest_jsonl),
        destination=destination,
        embedding=embedding or EmbeddingSpec(),
        chunking=chunking or ChunkingSpec(),
    )


def ingest_corpus(
    corpus: Corpus,
    *,
    destination: QdrantDestination,
    embedding: EmbeddingSpec | None = None,
    chunking: ChunkingSpec | None = None,
) -> IngestReport:
    return _ingest_docs(
        _iter_docs_from_corpus(corpus),
        destination=destination,
        embedding=embedding or EmbeddingSpec(),
        chunking=chunking or ChunkingSpec(),
    )
