from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from syft_ingest.core.models import ContentItem, Corpus

# Map platform metadata to site domains
_PLATFORM_SITES = {
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "threads": "threads.net",
}

# Map platform metadata to source_type labels
_PLATFORM_SOURCE_TYPES = {
    "facebook": "social_media_post",
    "instagram": "social_media_post",
}


def _stable_id(item: ContentItem) -> str:
    """Generate a stable ID from URL + source + content hash."""
    content_hash = item.metadata.get("content_hash", "")
    key = f"{item.url or ''}:{item.source_type.value}:{content_hash}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _item_to_dict(item: ContentItem) -> dict:
    """Map ContentItem to JSONL-compatible dict matching syft-influencer schema."""
    platform = item.metadata.get("platform", "")
    published_at_str = item.published_at.isoformat() if item.published_at else ""
    excerpt = item.text.split("\n\n", 1)[-1][:240] if item.text else ""

    return {
        "id": _stable_id(item),
        "text": item.text,
        "title": item.title,
        "url": item.url or "",
        "source": item.source_type.value,
        "source_type": item.metadata.get(
            "source_type_label", _PLATFORM_SOURCE_TYPES.get(platform, "")
        ),
        "author": item.author,
        "site": item.metadata.get("site", _PLATFORM_SITES.get(platform, "")),
        "published_at": published_at_str,
        "tags": item.metadata.get("tags", []),
        "excerpt": excerpt,
        "ingested_at": datetime.now(UTC).isoformat(),
        "metadata": item.metadata,
    }


def _export_jsonl(items: list[ContentItem], output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(_item_to_dict(item), ensure_ascii=False) + "\n")
    logger.info(f"Exported {len(items)} items to {path}")


def _export_json(items: list[ContentItem], output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [_item_to_dict(item) for item in items]
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Exported {len(items)} items to {path}")


def _export_text(items: list[ContentItem], output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(items):
        slug = re.sub(r"[^\w\-]", "_", item.title[:60]) if item.title else "item"
        filepath = out / f"{i:04d}_{slug}.txt"
        filepath.write_text(item.text, encoding="utf-8")
    logger.info(f"Exported {len(items)} items to {out}/")


def export(corpus: Corpus, fmt: str, **kwargs) -> None:
    items = corpus.all_items()
    if not items:
        logger.warning("No items to export")
        return

    if fmt == "jsonl":
        _export_jsonl(items, kwargs["output"])
    elif fmt == "json":
        _export_json(items, kwargs["output"])
    elif fmt == "text":
        _export_text(items, kwargs["output_dir"])
    else:
        raise ValueError(
            f"Unknown export format: {fmt!r}. Supported: jsonl, json, text"
        )
