"""Tests for internal functions of syft_ingest.core.ingest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from syft_ingest.core.gather import gather
from syft_ingest.core.ingest import (
    ChunkingSpec,
    IngestError,
    QdrantDestination,
    UnsupportedBackendError,
    _chunk_text,
    _create_qdrant_client,
    _Doc,
    _enrich_text,
    _merge_embedding_contract,
    build_embedding_contract,
    build_text_embedder,
    normalize_embedding_backend,
    to_rag,
)

# ---------------------------------------------------------------------------
# Shared fake Qdrant runtime (reused from test_ingest_api.py pattern)
# ---------------------------------------------------------------------------


class _FakeQdrantClient:
    def __init__(self, *args, **kwargs) -> None:
        pass


class _FakeDistance:
    COSINE = "cosine"


class _FakeVectorParams:
    def __init__(self, size: int, distance: str) -> None:
        self.size = size
        self.distance = distance


class _FakePointStruct:
    def __init__(self, id, vector, payload) -> None:
        self.id = id
        self.vector = vector
        self.payload = payload


@pytest.fixture
def patch_qdrant_import(monkeypatch):
    """Monkeypatch _import_qdrant so tests don't need a real qdrant-client."""
    monkeypatch.setattr(
        "syft_ingest.core.ingest._import_qdrant",
        lambda: (_FakeQdrantClient, _FakeDistance, _FakePointStruct, _FakeVectorParams),
    )


# ---------------------------------------------------------------------------
# 1. test_to_rag_produces_stable_deterministic_chunk_ids
# ---------------------------------------------------------------------------


def test_to_rag_produces_stable_deterministic_chunk_ids():
    doc = _Doc(
        text="Hello world, this is a test document with enough text.",
        payload={"url": "https://example.com/page1", "source": "test"},
    )
    spec = ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0)

    result_a = to_rag([doc], spec)
    result_b = to_rag([doc], spec)

    assert len(result_a) > 0
    ids_a = [d.payload["_raw_doc_id"] for d in result_a]
    ids_b = [d.payload["_raw_doc_id"] for d in result_b]
    assert ids_a == ids_b, "Identical inputs must produce identical _raw_doc_id values"

    different_doc = _Doc(
        text="Completely different content here.",
        payload={"url": "https://example.com/page2", "source": "test"},
    )
    result_c = to_rag([different_doc], spec)
    ids_c = [d.payload["_raw_doc_id"] for d in result_c]
    assert ids_a != ids_c, "Different docs must produce different _raw_doc_id values"


# ---------------------------------------------------------------------------
# 2. test_to_rag_chunk_metadata_fields
# ---------------------------------------------------------------------------


def test_to_rag_chunk_metadata_fields(monkeypatch):
    # Mock RecursiveCharacterTextSplitter since langchain_text_splitters may
    # not be installed.  The mock splits text into fixed-size pieces.
    class _FakeSplitter:
        def __init__(self, **kwargs):
            self._size = kwargs.get("chunk_size", 500)

        def split_text(self, text: str) -> list[str]:
            return [text[i : i + self._size] for i in range(0, len(text), self._size)]

    monkeypatch.setattr(
        "syft_ingest.core.ingest.RecursiveCharacterTextSplitter", _FakeSplitter
    )

    raw_text = ("word " * 400).strip()  # ~2000 chars
    doc = _Doc(
        text=raw_text,
        payload={"url": "https://example.com/long", "source": "test"},
    )
    spec = ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0)
    chunks = to_rag([doc], spec)

    assert len(chunks) > 1, "Expected multiple chunks for a 2000-char document"

    for idx, chunk_doc in enumerate(chunks):
        p = chunk_doc.payload
        assert p["chunk_index"] == idx
        assert p["chunk_count"] == len(chunks)
        assert p["text"] == chunk_doc.text
        assert p["raw_text"] == raw_text, "raw_text must be the original doc text"
        assert p["excerpt"] == chunk_doc.text[:240]
        assert "_raw_doc_id" in p


# ---------------------------------------------------------------------------
# 3. test_build_text_embedder_rejects_unknown_backend
# ---------------------------------------------------------------------------


def test_build_text_embedder_rejects_unknown_backend():
    with pytest.raises(UnsupportedBackendError):
        build_text_embedder("some-model", "unknown_backend")


# ---------------------------------------------------------------------------
# 4. test_create_qdrant_client_requires_url_or_path
# ---------------------------------------------------------------------------


def test_create_qdrant_client_requires_url_or_path(patch_qdrant_import):
    dest = QdrantDestination(collection_name="test", url=None, path=None)
    with pytest.raises(IngestError, match="requires url or path"):
        _create_qdrant_client(dest)


# ---------------------------------------------------------------------------
# 5. test_enrich_text_with_source_type_labels
# ---------------------------------------------------------------------------


def test_enrich_text_known_source_type():
    doc = _Doc(
        text="My video content here.",
        payload={
            "source_type": "youtube_caption_chunk",
            "title": "How to Cook Pasta",
            "published_at": "2025-06-15T12:00:00Z",
        },
    )
    enriched = _enrich_text(doc)
    assert "[Video: How to Cook Pasta | Published: 2025-06-15]" in enriched
    assert "My video content here." in enriched


def test_enrich_text_unknown_source_type_title_cases():
    doc = _Doc(
        text="Post body.",
        payload={
            "source_type": "social_media_post",
            "title": "My Post",
        },
    )
    enriched = _enrich_text(doc)
    assert "Social Media Post: My Post" in enriched


def test_enrich_text_no_title_no_source_type_returns_raw():
    doc = _Doc(
        text="Just raw text.",
        payload={},
    )
    enriched = _enrich_text(doc)
    assert enriched == "Just raw text."


# ---------------------------------------------------------------------------
# 6. test_chunk_text_min_chunk_merging
# ---------------------------------------------------------------------------


def test_chunk_text_min_chunk_merging():
    # Build text where last segment is short enough to be merged
    long_part = "A" * 800
    short_tail = "B" * 50
    text = f"{long_part} {short_tail}"

    spec_with_merge = ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=200)
    chunks_merged = _chunk_text(text, spec_with_merge)
    # With merging, short trailing chunk should be folded into previous
    for chunk in chunks_merged:
        assert len(chunk) >= 200 or len(chunks_merged) == 1

    spec_no_merge = ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0)
    chunks_no_merge = _chunk_text(text, spec_no_merge)
    # Without merging, may have a short trailing chunk
    assert len(chunks_no_merge) >= len(chunks_merged)


def test_chunk_text_empty_returns_empty():
    spec = ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0)
    assert _chunk_text("", spec) == []


def test_to_rag_without_chunking_emits_single_doc():
    doc = _Doc(
        text="Hello world, this is a test document with enough text.",
        payload={"url": "https://example.com/page1", "source": "test"},
    )

    result = to_rag([doc], None)

    assert len(result) == 1
    payload = result[0].payload
    assert payload["chunk_index"] == 0
    assert payload["chunk_count"] == 1
    assert payload["raw_text"] == doc.text
    assert result[0].text


# ---------------------------------------------------------------------------
# 7. test_gather_unsupported_source_spec_kind
# ---------------------------------------------------------------------------


def test_gather_unsupported_source_spec_kind():
    @dataclass
    class _UnknownSpec:
        kind: str = "unknown_kind"
        raw_dirs: list[str] = None

        def __post_init__(self):
            if self.raw_dirs is None:
                self.raw_dirs = ["/tmp"]

    corpus = gather(name="test", source_specs=[_UnknownSpec()])
    assert len(corpus.all_items()) == 0


# ---------------------------------------------------------------------------
# 8. test_merge_embedding_contract_handles_edge_cases
# ---------------------------------------------------------------------------


def test_merge_embedding_contract_metadata_missing():
    payload: dict[str, Any] = {"text": "hello"}
    _merge_embedding_contract(payload, {"embedding_model": "bge"})
    assert payload["metadata"]["embedding_model"] == "bge"


def test_merge_embedding_contract_metadata_not_dict():
    payload: dict[str, Any] = {"metadata": "not-a-dict"}
    _merge_embedding_contract(payload, {"embedding_model": "bge"})
    assert isinstance(payload["metadata"], dict)
    assert payload["metadata"]["embedding_model"] == "bge"


def test_merge_embedding_contract_preserves_existing_keys():
    payload: dict[str, Any] = {"metadata": {"custom_key": "keep_me"}}
    _merge_embedding_contract(payload, {"embedding_model": "bge"})
    assert payload["metadata"]["custom_key"] == "keep_me"
    assert payload["metadata"]["embedding_model"] == "bge"


# ---------------------------------------------------------------------------
# 9. test_build_embedding_contract_backends
# ---------------------------------------------------------------------------


def test_build_embedding_contract_fastembed_bge():
    contract = build_embedding_contract("BAAI/bge-small-en-v1.5", "fastembed")
    assert contract["embedding_family"] == "bge"
    assert "embedding_normalized" not in contract


def test_build_embedding_contract_fastembed_text_family():
    contract = build_embedding_contract("some-text-model", "fastembed")
    assert contract["embedding_family"] == "text"
    assert "embedding_normalized" not in contract


def test_build_embedding_contract_sentence_transformers():
    contract = build_embedding_contract(
        "BAAI/bge-small-en-v1.5", "sentence-transformers"
    )
    assert contract["embedding_normalized"] is True


def test_build_embedding_contract_clip_family():
    contract = build_embedding_contract("openai/clip-vit-base-patch32", "fastembed")
    assert contract["embedding_family"] == "clip"


# ---------------------------------------------------------------------------
# 10. test_normalize_embedding_backend_aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("fast-embed", "fastembed"),
        ("sentence_transformers", "sentence-transformers"),
        (None, "fastembed"),
        ("unknown", "unknown"),
    ],
)
def test_normalize_embedding_backend_aliases(input_val, expected):
    assert normalize_embedding_backend(input_val) == expected
