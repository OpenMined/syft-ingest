"""Facebook data export parser.

Parses Meta's "Download Your Information" JSON export into ContentItem objects.
Handles the encoding bug, pagination, deduplication, and context enrichment.
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
    extract_hashtags,
    extract_last_url,
    extract_mentions,
    fix_meta_encoding_recursive,
    is_bare_url,
)

# Max reasonable timestamp: year 2100
_MAX_TIMESTAMP = 4102444800


def is_facebook_export(directory: Path) -> bool:
    """Detect if a directory is a Facebook data export."""
    return bool(list(directory.glob("**/posts/profile_posts_*.json")))


def _extract_post_text(post: dict) -> str | None:
    """Extract text content from a Facebook post.

    Primary: data[0].post
    Fallback: first media description in attachments
    """
    data_list = post.get("data", [])
    for entry in data_list:
        if "post" in entry:
            return entry["post"]

    for attachment in post.get("attachments", []):
        for data_item in attachment.get("data", []):
            media = data_item.get("media", {})
            if "description" in media:
                return media["description"]

    return None


def _extract_post_url(post: dict) -> str | None:
    """Extract URL from a Facebook post.

    Primary: external_context.url from attachments
    Fallback: last URL found in post text (the blog post link is typically last,
    while mid-text URLs like program links are shared across posts)
    """
    for attachment in post.get("attachments", []):
        for data_item in attachment.get("data", []):
            ext = data_item.get("external_context", {})
            if "url" in ext:
                return ext["url"]

    text = _extract_post_text(post)
    if text:
        return extract_last_url(text)

    return None


def _safe_timestamp(timestamp) -> datetime | None:
    """Safely convert a timestamp from untrusted JSON to datetime."""
    if not isinstance(timestamp, (int, float)):
        return None
    if timestamp < 0 or timestamp > _MAX_TIMESTAMP:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def parse_facebook_export(export_dir: Path, *, author: str) -> list[ContentItem]:
    """Parse a Facebook data export directory into ContentItem objects."""
    post_files = sorted(export_dir.glob("**/posts/profile_posts_*.json"))
    if not post_files:
        logger.warning(f"No profile_posts files found in {export_dir}")
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

            url = _extract_post_url(post)
            tags = extract_hashtags(text)
            mentions = extract_mentions(text)
            chash = content_hash(text)

            published_at = _safe_timestamp(post.get("timestamp"))

            date_str = (
                published_at.strftime("%Y-%m-%d") if published_at else "unknown date"
            )
            enriched_text = (
                f"[Facebook post by {author} | Published: {date_str}]\n\n{text}"
            )

            item = ContentItem(
                title=derive_title(text),
                author=author,
                source_type=SourceType.LOCAL,
                url=url,
                text=enriched_text,
                published_at=published_at,
                metadata={
                    "platform": "facebook",
                    "tags": tags,
                    "mentions": mentions,
                    "content_hash": chash,
                },
            )
            raw_items.append(item)

        if skipped_no_text or skipped_bare_url:
            logger.info(
                f"{post_file.name}: skipped {skipped_no_text} posts without text, "
                f"{skipped_bare_url} bare-URL posts"
            )

    # Dedup by URL: keep the version with longest text
    url_map: dict[str, ContentItem] = {}
    no_url_items: list[ContentItem] = []
    for item in raw_items:
        if item.url:
            existing = url_map.get(item.url)
            if existing is None or len(item.text) > len(existing.text):
                url_map[item.url] = item
        else:
            no_url_items.append(item)

    deduped = list(url_map.values()) + no_url_items

    # Dedup by content hash
    seen_hashes: set[str] = set()
    final: list[ContentItem] = []
    for item in deduped:
        chash = item.metadata["content_hash"]
        if chash not in seen_hashes:
            seen_hashes.add(chash)
            final.append(item)

    logger.info(f"Facebook: {len(raw_items)} raw → {len(final)} after dedup")
    return final
