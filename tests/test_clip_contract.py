from syft_ingest.rag.embedders.clip_contract import (
    DEFAULT_CLIP_MODEL,
    build_embedding_contract,
    embedding_space,
)


def test_embedding_space_uses_backend_and_model() -> None:
    assert embedding_space("clip-ViT-B-32") == "sentence-transformers:clip-ViT-B-32"


def test_build_embedding_contract_contains_alignment_metadata() -> None:
    contract = build_embedding_contract(DEFAULT_CLIP_MODEL)
    assert contract == {
        "embedding_backend": "sentence-transformers",
        "embedding_family": "clip",
        "embedding_model": DEFAULT_CLIP_MODEL,
        "embedding_space": f"sentence-transformers:{DEFAULT_CLIP_MODEL}",
        "embedding_normalized": True,
    }
