"""Instagram data export parser.

Parses Meta's "Download Your Information" JSON export for Instagram
into ContentItem objects. Shares encoding fix and utilities with Facebook
via _meta_utils.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from syft_ingest.core.models import ContentItem, SourceType
from syft_ingest.sources._meta_utils import (
    content_hash,
    derive_title,
    extract_first_url,
    extract_hashtags,
    extract_mentions,
    fix_meta_encoding_recursive,
    is_bare_url,
)

# Max reasonable timestamp: year 2100
_MAX_TIMESTAMP = 4102444800


def is_instagram_export(directory: Path) -> bool:
    """Detect if a directory is an Instagram data export.

    Checks for modern format (media/posts_*.json) and legacy format (content/posts_*.json).
    """
    modern = list(directory.glob("**/media/posts_*.json"))
    legacy = list(directory.glob("**/content/posts_*.json"))
    return bool(modern or legacy)


def _extract_post_text(post: dict) -> str | None:
    """Extract text content from an Instagram post.

    IG uses 'title' for the caption text (confusingly named).
    Check post-level title first, then media[0].title for carousel posts.
    """
    title = post.get("title")
    if title:
        return title

    media_list = post.get("media", [])
    if media_list:
        first_media = media_list[0]
        title = first_media.get("title")
        if title:
            return title

    return None


def _extract_timestamp(post: dict) -> int | None:
    """Extract creation timestamp from an Instagram post.

    Check post-level creation_timestamp, then media[0].creation_timestamp.
    """
    ts = post.get("creation_timestamp")
    if ts:
        return ts

    media_list = post.get("media", [])
    if media_list:
        ts = media_list[0].get("creation_timestamp")
        if ts:
            return ts

    return None


def _extract_cross_post_source(post: dict) -> str | None:
    """Extract cross-post source app if present (e.g., 'FB')."""
    media_list = post.get("media", [])
    if media_list:
        cps = media_list[0].get("cross_post_source", {})
        return cps.get("source_app")
    return None


def _safe_timestamp(timestamp) -> datetime | None:
    """Safely convert a timestamp from untrusted JSON to datetime."""
    if not isinstance(timestamp, (int, float)):
        return None
    if timestamp < 0 or timestamp > _MAX_TIMESTAMP:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def parse_instagram_export(export_dir: Path, *, author: str) -> list[ContentItem]:
    """Parse an Instagram data export directory into ContentItem objects."""
    post_files = sorted(
        list(export_dir.glob("**/media/posts_*.json"))
        + list(export_dir.glob("**/content/posts_*.json"))
    )
    if not post_files:
        logger.warning(f"No Instagram post files found in {export_dir}")
        return []

    raw_items: list[ContentItem] = []

    for post_file in post_files:
        logger.info(f"Parsing {post_file.name}")
        try:
            with post_file.open("r", encoding="utf-8") as f:
                posts = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Skipping {post_file}: failed to parse JSON: {e}")
            continue

        posts = fix_meta_encoding_recursive(posts)

        skipped_no_text = 0
        skipped_bare_url = 0

        for post in posts:
            text = _extract_post_text(post)
            if not text:
                skipped_no_text += 1
                continue
            if is_bare_url(text):
                skipped_bare_url += 1
                continue

            url = extract_first_url(text)
            tags = extract_hashtags(text)
            mentions = extract_mentions(text)
            chash = content_hash(text)

            timestamp = _extract_timestamp(post)
            published_at = _safe_timestamp(timestamp)

            date_str = (
                published_at.strftime("%Y-%m-%d") if published_at else "unknown date"
            )
            enriched_text = (
                f"[Instagram post by {author} | Published: {date_str}]\n\n{text}"
            )

            metadata = {
                "platform": "instagram",
                "tags": tags,
                "mentions": mentions,
                "content_hash": chash,
            }

            cross_post = _extract_cross_post_source(post)
            if cross_post:
                metadata["cross_post_source"] = cross_post

            item = ContentItem(
                title=derive_title(text),
                author=author,
                source_type=SourceType.LOCAL,
                url=url,
                text=enriched_text,
                published_at=published_at,
                metadata=metadata,
            )
            raw_items.append(item)

        if skipped_no_text or skipped_bare_url:
            logger.info(
                f"{post_file.name}: skipped {skipped_no_text} posts without text, "
                f"{skipped_bare_url} bare-URL posts"
            )

    # Dedup by content hash
    seen_hashes: set[str] = set()
    final: list[ContentItem] = []
    for item in raw_items:
        chash = item.metadata["content_hash"]
        if chash not in seen_hashes:
            seen_hashes.add(chash)
            final.append(item)

    logger.info(f"Instagram: {len(raw_items)} raw → {len(final)} after dedup")
    return final
