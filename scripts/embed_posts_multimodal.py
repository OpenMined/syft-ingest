#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from syft_ingest.rag.embedders.multimodal_post import embed_posts_multimodal
from syft_ingest.sources._meta_utils import (
    derive_title,
    extract_hashtags,
    extract_mentions,
)

DEFAULT_MANIFEST = Path(
    "../syft-influencer/data/creators/jen-lazzari/paintedwildflower-fbpage/local-sync/manifests/posts_local_manifest.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed Facebook posts with text + images + sampled video frames."
    )
    parser.add_argument(
        "--manifest-jsonl",
        default=str(DEFAULT_MANIFEST),
        help="Path to posts_local_manifest.jsonl",
    )
    parser.add_argument(
        "--output",
        default="output/post_embeddings_multimodal.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Optional cap on number of posts to embed",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Start offset in the manifest",
    )
    parser.add_argument(
        "--clip-model",
        default="clip-ViT-B-32",
        help="CLIP model name for text+image embeddings",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Embedding batch size",
    )
    parser.add_argument(
        "--text-weight",
        type=float,
        default=0.75,
        help="Fusion weight for text modality",
    )
    parser.add_argument(
        "--image-weight",
        type=float,
        default=0.125,
        help="Fusion weight for image modality",
    )
    parser.add_argument(
        "--video-weight",
        type=float,
        default=0.125,
        help="Fusion weight for video modality",
    )
    parser.add_argument(
        "--video-interval-seconds",
        type=float,
        default=2.5,
        help="Seconds between sampled video frames",
    )
    parser.add_argument(
        "--video-max-frames",
        type=int,
        default=8,
        help="Max sampled frames per video",
    )
    parser.add_argument(
        "--frames-root",
        default=None,
        help=(
            "Optional persistent frame extraction directory. "
            "If omitted, temporary directories are used."
        ),
    )
    parser.add_argument(
        "--summarize-long-text",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable simple summary for long post text",
    )
    parser.add_argument(
        "--include-tags-in-embedding-text",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include tags in embedding text (off by default; tags stay metadata)",
    )
    parser.add_argument(
        "--summary-min-chars",
        type=int,
        default=900,
        help="Minimum post length before summarization is applied",
    )
    parser.add_argument(
        "--summary-max-chars",
        type=int,
        default=420,
        help="Target max summary length",
    )
    return parser.parse_args()


def _normalize_tags(raw_tags: Any, text: str) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []

    if isinstance(raw_tags, list):
        candidates = raw_tags
    else:
        candidates = []

    for raw in candidates + extract_hashtags(text):
        value = str(raw).strip().lower().lstrip("#")
        if not value or value in seen:
            continue
        seen.add(value)
        tags.append(value)
    return tags


def _paths_from_media(media: list[dict[str, Any]], media_type: str) -> list[str]:
    paths: list[str] = []
    for entry in media:
        if not isinstance(entry, dict):
            continue
        if entry.get("media_type") != media_type:
            continue
        if entry.get("status") not in {"downloaded", "skipped_existing"}:
            continue
        path = str(entry.get("local_path") or "").strip()
        if path:
            paths.append(path)
    return paths


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue

            post_id = str(row.get("post_id") or "").strip()
            text = str(row.get("content") or "").strip()
            media = row.get("media") if isinstance(row.get("media"), list) else []
            image_paths = _paths_from_media(media, "image")
            video_paths = _paths_from_media(media, "video")
            if not text and not image_paths and not video_paths:
                continue

            author = str(row.get("page_name") or "").strip()
            title = derive_title(text) if text else f"Facebook post {post_id or 'unknown'}"
            tags = _normalize_tags(row.get("tags"), text)
            mentions = extract_mentions(text)
            published_at = str(row.get("date_posted") or "").strip()
            url = str(row.get("post_url") or "").strip()

            records.append(
                {
                    "post_id": post_id,
                    "url": url,
                    "author": author,
                    "title": title,
                    "text": text,
                    "published_at": published_at,
                    "tags": tags,
                    "mentions": mentions,
                    "image_paths": image_paths,
                    "video_paths": video_paths,
                    "source_media_count": len(media),
                }
            )
    return records


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    manifest = Path(args.manifest_jsonl).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not manifest.is_file():
        raise SystemExit(f"Manifest not found: {manifest}")

    records = load_records(manifest)
    start = max(0, args.offset)
    selected = records[start:]
    if args.max_posts is not None:
        selected = selected[: max(0, args.max_posts)]
    if not selected:
        raise SystemExit("No posts selected for embedding.")

    print(f"Loaded {len(records)} records; embedding {len(selected)} post(s)")
    embedded = embed_posts_multimodal(
        selected,
        model_name=args.clip_model,
        batch_size=args.batch_size,
        summarize_long_text=args.summarize_long_text,
        summary_min_chars=args.summary_min_chars,
        summary_max_chars=args.summary_max_chars,
        text_weight=args.text_weight,
        image_weight=args.image_weight,
        video_weight=args.video_weight,
        video_interval_seconds=args.video_interval_seconds,
        video_max_frames=args.video_max_frames,
        frames_root=args.frames_root,
        include_tags_in_embedding_text=args.include_tags_in_embedding_text,
    )
    write_jsonl(output, embedded)

    total_frames = sum(int(row.get("video_frames_used", 0)) for row in embedded)
    summary_used = sum(1 for row in embedded if row.get("summary_used"))
    print(
        "Wrote embeddings: "
        f"{output} | posts={len(embedded)} | "
        f"summaries={summary_used} | sampled_video_frames={total_frames}"
    )


if __name__ == "__main__":
    main()
