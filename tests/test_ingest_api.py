import json

import pytest

from syft_ingest import (
    ChunkingSpec,
    EmbeddingSpec,
    NoDocumentsError,
    QdrantDestination,
    SocialProfileSource,
    gather,
    ingest_corpus,
    ingest_jsonl,
)
from syft_ingest.core.models import Corpus


class _FakeCollectionInfo:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCollections:
    def __init__(self, names: list[str]) -> None:
        self.collections = [_FakeCollectionInfo(name) for name in names]


class _FakeQdrantClient:
    def __init__(self, *args, **kwargs) -> None:
        self.created: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.delete_calls: list[tuple[str, list[str]]] = []
        self.upserts: list[tuple[str, list[dict]]] = []
        self._collections = _FakeCollections([])

    def get_collections(self):
        return self._collections

    def delete_collection(self, collection_name: str):
        self.deleted.append(collection_name)
        self._collections = _FakeCollections(
            [c.name for c in self._collections.collections if c.name != collection_name]
        )

    def create_collection(self, collection_name: str, vectors_config):
        self.created.append((collection_name, vectors_config.size))
        self._collections = _FakeCollections(
            [c.name for c in self._collections.collections] + [collection_name]
        )

    def upsert(self, collection_name: str, points: list[dict]):
        self.upserts.append((collection_name, points))

    def delete(self, collection_name: str, points_selector: list[str]):
        self.delete_calls.append((collection_name, list(points_selector)))


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


class _FakeEmbedder:
    def embed(self, texts):
        values = []
        for idx, _ in enumerate(list(texts)):
            values.append([float(idx + 1), 0.5, 0.25])
        return iter(values)


@pytest.fixture
def patch_ingest_runtime(monkeypatch):
    monkeypatch.setattr(
        "syft_ingest.core.ingest.build_text_embedder", lambda *a, **k: _FakeEmbedder()
    )
    monkeypatch.setattr(
        "syft_ingest.core.ingest._import_qdrant",
        lambda: (
            _FakeQdrantClient,
            _FakeDistance,
            _FakePointStruct,
            _FakeVectorParams,
        ),
    )


def test_ingest_jsonl_upserts_points(tmp_path, patch_ingest_runtime):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "title": "Carousel post",
                "author": "Katy Stevens",
                "url": "https://www.instagram.com/p/abc123/",
                "text": "[Instagram post by Katy Stevens]\\n\\nHello world",
                "site": "instagram.com",
                "source_type": "social_media_post",
                "metadata": {"platform": "instagram", "extractor": "brightdata"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = ingest_jsonl(
        manifest,
        destination=QdrantDestination(
            collection_name="katy-stevens", reset_collection=True
        ),
        embedding=EmbeddingSpec(),
        chunking=ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0),
    )

    assert report.collection_name == "katy-stevens"
    assert report.documents_total == 1
    assert report.chunks_total == 1
    assert len(report.point_ids) == 1
    assert report.embedding_contract["embedding_backend"] == "fastembed"


def test_ingest_corpus_supports_source_spec_metadata(tmp_path, patch_ingest_runtime):
    brightdata_dir = tmp_path / "brightdata-ig"
    brightdata_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "url": "https://www.instagram.com/p/DIWPWGpsUQX/",
            "shortcode": "DIWPWGpsUQX",
            "user_posted": "paintedwildflower",
            "description": "Carousel caption #watercolor",
            "date_posted": "2025-04-12T13:03:14.000Z",
            "photos": ["https://cdninstagram.com/example/photo-1.jpg"],
        }
    ]
    (brightdata_dir / "brightdata-instagram.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    corpus = gather(
        "Painted Wildflower",
        source_specs=[
            SocialProfileSource(
                platform="instagram",
                extractor="brightdata",
                handle="paintedwildflower",
                profile_url="https://www.instagram.com/paintedwildflower/",
                raw_dirs=[str(brightdata_dir)],
            )
        ],
    )

    report = ingest_corpus(
        corpus,
        destination=QdrantDestination(collection_name="paintedwildflower"),
        embedding=EmbeddingSpec(),
        chunking=ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0),
    )

    assert report.documents_total == 1
    assert report.chunks_total == 1


def test_ingest_jsonl_rolls_back_partial_upserts(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "title": "Post one",
                "author": "Katy Stevens",
                "url": "https://www.instagram.com/p/abc123/",
                "text": "first document",
                "site": "instagram.com",
                "source_type": "social_media_post",
                "metadata": {"platform": "instagram", "extractor": "brightdata"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "title": "Post two",
                "author": "Katy Stevens",
                "url": "https://www.instagram.com/p/def456/",
                "text": "second document",
                "site": "instagram.com",
                "source_type": "social_media_post",
                "metadata": {"platform": "instagram", "extractor": "brightdata"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FailingQdrantClient(_FakeQdrantClient):
        last_instance = None

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.upsert_calls = 0
            FailingQdrantClient.last_instance = self

        def upsert(self, collection_name: str, points: list[dict]):
            self.upsert_calls += 1
            super().upsert(collection_name, points)
            if self.upsert_calls == 2:
                raise RuntimeError("transient qdrant failure")

    monkeypatch.setattr(
        "syft_ingest.core.ingest.build_text_embedder", lambda *a, **k: _FakeEmbedder()
    )
    monkeypatch.setattr(
        "syft_ingest.core.ingest._import_qdrant",
        lambda: (
            FailingQdrantClient,
            _FakeDistance,
            _FakePointStruct,
            _FakeVectorParams,
        ),
    )

    with pytest.raises(RuntimeError, match="transient qdrant failure"):
        ingest_jsonl(
            manifest,
            destination=QdrantDestination(
                collection_name="katy-stevens",
                reset_collection=True,
                batch_size=1,
            ),
            embedding=EmbeddingSpec(),
            chunking=ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0),
        )

    client = FailingQdrantClient.last_instance
    assert client is not None
    assert client.delete_calls == [("katy-stevens", [client.upserts[0][1][0].id])]


def test_ingest_empty_corpus_raises_no_documents(patch_ingest_runtime):
    """Empty corpus should raise NoDocumentsError, not a generic RuntimeError."""
    corpus = Corpus(person="Nobody")
    with pytest.raises(NoDocumentsError, match="No documents"):
        ingest_corpus(
            corpus,
            destination=QdrantDestination(collection_name="empty-test"),
        )


def test_ingest_jsonl_skips_malformed_lines(tmp_path, patch_ingest_runtime):
    """Malformed JSONL lines should be skipped, not crash the entire ingest."""
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "this is not json\n"
        + json.dumps(
            {
                "title": "Good post",
                "author": "Test Author",
                "url": "https://example.com/post",
                "text": "This is valid content",
                "source_type": "social_media_post",
                "metadata": {},
            }
        )
        + "\n"
        + "{broken json\n",
        encoding="utf-8",
    )

    report = ingest_jsonl(
        manifest,
        destination=QdrantDestination(collection_name="malformed-test"),
        embedding=EmbeddingSpec(),
        chunking=ChunkingSpec(chunk_size=500, chunk_overlap=0, min_chunk_size=0),
    )

    # Only the valid line should be ingested
    assert report.documents_total == 1
    assert report.chunks_total == 1


def test_chunking_spec_rejects_invalid_values():
    """ChunkingSpec should reject invalid values at the boundary."""
    with pytest.raises(ValueError):
        ChunkingSpec(chunk_size=0)
    with pytest.raises(ValueError):
        ChunkingSpec(chunk_size=-1)


def test_qdrant_destination_rejects_empty_collection():
    """QdrantDestination should reject empty collection name."""
    with pytest.raises(ValueError):
        QdrantDestination(collection_name="")
