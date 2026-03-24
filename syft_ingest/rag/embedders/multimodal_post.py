from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from syft_ingest.rag.embedders.multimodal_video import extract_frames_with_opencv

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _l2_normalize(vector: list[float]) -> list[float]:
    squared_norm = sum(v * v for v in vector)
    if squared_norm <= 0:
        return vector
    inv_norm = squared_norm**-0.5
    return [v * inv_norm for v in vector]


def _mean_pool(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    dim = len(vectors[0])
    if dim == 0:
        return None
    for vector in vectors:
        if len(vector) != dim:
            raise ValueError("All vectors must share the same dimension")

    pooled = [0.0] * dim
    for vector in vectors:
        for idx, value in enumerate(vector):
            pooled[idx] += value
    scale = 1.0 / len(vectors)
    return [value * scale for value in pooled]


def simple_summarize_text(
    text: str,
    *,
    max_chars: int = 420,
    max_sentences: int = 4,
) -> str:
    """Heuristic summarizer for long text (extractive + deterministic)."""
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized

    parts = [
        part.strip() for part in _SENTENCE_SPLIT_RE.split(normalized) if part.strip()
    ]
    if not parts:
        return normalized[:max_chars].rstrip()

    selected: list[str] = [parts[0]]
    selected_set = {parts[0]}

    # Prioritize salient social signals for short-form posts.
    for part in parts[1:]:
        if len(selected) >= max_sentences:
            break
        if "#" in part or "@" in part or "http" in part:
            if part not in selected_set:
                selected.append(part)
                selected_set.add(part)

    for part in parts[1:]:
        if len(selected) >= max_sentences:
            break
        if part not in selected_set:
            selected.append(part)
            selected_set.add(part)

    summary = " ".join(selected).strip()
    if len(summary) <= max_chars:
        return summary
    truncated = summary[: max_chars - 3].rstrip()
    return f"{truncated}..."


def build_post_embedding_text(
    *,
    author: str,
    title: str,
    text: str,
    tags: list[str],
    mentions: list[str],
    published_at: str,
    image_count: int,
    video_count: int,
    summary: str | None,
    include_tags_in_text: bool = False,
    include_mentions_in_text: bool = True,
) -> str:
    """Build concise text context for post-level embedding."""
    lines: list[str] = []
    if author:
        lines.append(f"Author: {author}")
    if title:
        lines.append(f"Title: {title}")
    if published_at:
        lines.append(f"Published: {published_at[:10]}")
    if include_tags_in_text and tags:
        lines.append("Tags: " + " ".join(f"#{tag}" for tag in tags))
    if include_mentions_in_text and mentions:
        lines.append("Mentions: " + " ".join(f"@{mention}" for mention in mentions))
    if image_count or video_count:
        media_bits: list[str] = []
        if image_count:
            media_bits.append(f"{image_count} image(s)")
        if video_count:
            media_bits.append(f"{video_count} video(s)")
        lines.append("Media: " + ", ".join(media_bits))

    body = summary if summary else text
    if body:
        lines.append("Post: " + body)

    return "\n".join(lines).strip()


def fuse_modality_embeddings(
    *,
    text_embedding: list[float] | None,
    image_embedding: list[float] | None,
    video_embedding: list[float] | None,
    text_weight: float = 0.75,
    image_weight: float = 0.125,
    video_weight: float = 0.125,
) -> list[float]:
    """Fuse available modality vectors with normalized active weights."""
    raw_modalities = [
        ("text", text_embedding, text_weight),
        ("image", image_embedding, image_weight),
        ("video", video_embedding, video_weight),
    ]
    active = [
        (name, vector, weight)
        for name, vector, weight in raw_modalities
        if vector is not None
    ]
    if not active:
        raise ValueError("No modality embeddings provided")

    dim = len(active[0][1])  # type: ignore[index]
    for _, vector, _ in active:
        if len(vector) != dim:
            raise ValueError("All modality embeddings must have same dimension")

    positive_weight_sum = sum(max(weight, 0.0) for _, _, weight in active)
    if positive_weight_sum <= 0:
        effective = [(1.0 / len(active))] * len(active)
    else:
        effective = [max(weight, 0.0) / positive_weight_sum for _, _, weight in active]

    fused = [0.0] * dim
    for (_, vector, _), weight in zip(active, effective, strict=True):
        for idx, value in enumerate(vector):
            fused[idx] += weight * value
    return _l2_normalize(fused)


def _encode_texts(
    model: Any,
    texts: list[str],
    *,
    batch_size: int,
) -> list[list[float]]:
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return [vector.tolist() for vector in vectors]


def _encode_images(
    model: Any,
    image_paths: list[Path],
    *,
    batch_size: int,
) -> list[list[float]]:
    if not image_paths:
        return []
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required for image loading. Install with: "
            "`uv sync --extra multimodal`"
        ) from e

    loaded = []
    for path in image_paths:
        if not path.is_file():
            continue
        try:
            loaded.append(Image.open(path).convert("RGB"))
        except OSError:
            continue
    if not loaded:
        return []

    try:
        vectors = model.encode(
            loaded,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [vector.tolist() for vector in vectors]
    finally:
        for image in loaded:
            image.close()


def _collect_video_frame_paths(
    *,
    video_paths: list[Path],
    frame_root: Path,
    interval_seconds: float,
    max_frames_per_video: int,
) -> list[Path]:
    frame_paths: list[Path] = []
    if not video_paths:
        return frame_paths

    frame_root.mkdir(parents=True, exist_ok=True)
    for video_idx, video_path in enumerate(video_paths):
        if not video_path.is_file():
            continue
        video_frame_dir = frame_root / f"video_{video_idx:03d}"
        samples = extract_frames_with_opencv(
            video_path,
            output_dir=video_frame_dir,
            interval_seconds=interval_seconds,
            max_frames=max_frames_per_video,
        )
        frame_paths.extend(sample.image_path for sample in samples)
    return [path for path in frame_paths if path.is_file()]


def embed_posts_multimodal(
    records: list[dict[str, Any]],
    *,
    model_name: str = "clip-ViT-B-32",
    batch_size: int = 16,
    summarize_long_text: bool = False,
    summary_min_chars: int = 900,
    summary_max_chars: int = 420,
    text_weight: float = 0.75,
    image_weight: float = 0.125,
    video_weight: float = 0.125,
    video_interval_seconds: float = 2.5,
    video_max_frames: int = 8,
    frames_root: str | Path | None = None,
    include_tags_in_embedding_text: bool = False,
    include_mentions_in_embedding_text: bool = True,
) -> list[dict[str, Any]]:
    """Embed post records using text + images + sampled video frames."""
    if not records:
        return []

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers is required for multimodal post embeddings. "
            "Install with: `uv sync --extra multimodal`"
        ) from e

    model = SentenceTransformer(model_name)
    stable_frames_root = Path(frames_root) if frames_root else None

    text_inputs: list[str] = []
    summaries: list[str | None] = []
    image_paths_by_record: list[list[Path]] = []
    video_paths_by_record: list[list[Path]] = []

    for record in records:
        text = str(record.get("text") or "").strip()
        title = str(record.get("title") or "").strip()
        author = str(record.get("author") or "").strip()
        published_at = str(record.get("published_at") or "").strip()
        tags = record.get("tags") if isinstance(record.get("tags"), list) else []
        mentions = (
            record.get("mentions") if isinstance(record.get("mentions"), list) else []
        )

        image_paths = [
            Path(str(path))
            for path in (record.get("image_paths") or [])
            if str(path).strip()
        ]
        video_paths = [
            Path(str(path))
            for path in (record.get("video_paths") or [])
            if str(path).strip()
        ]

        summary: str | None = None
        if summarize_long_text and len(text) >= summary_min_chars and text:
            summary = simple_summarize_text(text, max_chars=summary_max_chars)
        summaries.append(summary)
        text_inputs.append(
            build_post_embedding_text(
                author=author,
                title=title,
                text=text,
                tags=[str(tag).lower().lstrip("#") for tag in tags if str(tag).strip()],
                mentions=[
                    str(mention).lower().lstrip("@")
                    for mention in mentions
                    if str(mention).strip()
                ],
                published_at=published_at,
                image_count=len(image_paths),
                video_count=len(video_paths),
                summary=summary,
                include_tags_in_text=include_tags_in_embedding_text,
                include_mentions_in_text=include_mentions_in_embedding_text,
            )
        )
        image_paths_by_record.append(image_paths)
        video_paths_by_record.append(video_paths)

    text_vectors = _encode_texts(model, text_inputs, batch_size=batch_size)
    outputs: list[dict[str, Any]] = []

    for idx, record in enumerate(records):
        image_vectors = _encode_images(
            model,
            image_paths_by_record[idx],
            batch_size=batch_size,
        )
        image_embedding = _mean_pool(image_vectors)

        post_id = str(record.get("post_id") or f"post_{idx:05d}")
        temp_frames_dir: tempfile.TemporaryDirectory[str] | None = None
        if stable_frames_root is None:
            temp_frames_dir = tempfile.TemporaryDirectory(
                prefix=f"post_frames_{post_id}_"
            )
            frame_root = Path(temp_frames_dir.name)
        else:
            frame_root = stable_frames_root / post_id

        frame_paths = _collect_video_frame_paths(
            video_paths=video_paths_by_record[idx],
            frame_root=frame_root,
            interval_seconds=video_interval_seconds,
            max_frames_per_video=video_max_frames,
        )
        video_vectors = _encode_images(model, frame_paths, batch_size=batch_size)
        if temp_frames_dir is not None:
            temp_frames_dir.cleanup()
        video_embedding = _mean_pool(video_vectors)

        embedding = fuse_modality_embeddings(
            text_embedding=text_vectors[idx],
            image_embedding=image_embedding,
            video_embedding=video_embedding,
            text_weight=text_weight,
            image_weight=image_weight,
            video_weight=video_weight,
        )

        outputs.append(
            {
                **record,
                "embedding": embedding,
                "embedding_dim": len(embedding),
                "embedding_model": model_name,
                "embedding_text": text_inputs[idx],
                "summary_used": summaries[idx] is not None,
                "summary_text": summaries[idx],
                "image_count_used": len(image_vectors),
                "video_count_used": len(video_paths_by_record[idx]),
                "video_frames_used": len(video_vectors),
            }
        )

    return outputs
