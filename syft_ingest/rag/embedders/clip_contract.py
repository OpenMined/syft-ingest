from __future__ import annotations

from typing import Any

DEFAULT_CLIP_MODEL = "clip-ViT-B-32"
EMBEDDING_BACKEND = "sentence-transformers"
EMBEDDING_FAMILY = "clip"
EMBEDDING_NORMALIZED = True


def embedding_space(model_name: str) -> str:
    return f"{EMBEDDING_BACKEND}:{model_name}"


def build_embedding_contract(model_name: str) -> dict[str, Any]:
    return {
        "embedding_backend": EMBEDDING_BACKEND,
        "embedding_family": EMBEDDING_FAMILY,
        "embedding_model": model_name,
        "embedding_space": embedding_space(model_name),
        "embedding_normalized": EMBEDDING_NORMALIZED,
    }


def load_sentence_transformer(model_name: str = DEFAULT_CLIP_MODEL):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for CLIP embeddings. "
            "Install with: `uv sync --extra multimodal`"
        ) from exc
    return SentenceTransformer(model_name)
