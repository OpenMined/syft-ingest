"""Facebook data export parser.

Supports:
- Meta "Download Your Information" export format
- Bright Data / crawler-style Facebook post JSON exports

Outputs normalized ``ContentItem`` objects with post-level representation
metadata (text, tags, mentions, media assets, and stable post reference).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
_MEDIA_HOST_HINTS = ("fbcdn.net", "cdninstagram.com")
_HTTP_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _find_meta_post_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("**/posts/profile_posts_*.json"))


def _looks_like_brightdata_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False

    def _nonempty_scalar(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        return isinstance(value, (int, float))

    has_identity = any(
        _nonempty_scalar(row.get(key))
        for key in ("post_id", "url", "post_url", "permalink", "date_posted")
    )
    has_text_payload = any(
        isinstance(row.get(key), str) and row.get(key).strip()
        for key in ("content", "text", "message", "caption", "description", "title")
    )
    attachments = row.get("attachments")
    has_attachment_payload = isinstance(attachments, list) and bool(attachments)
    has_top_level_media_payload = any(
        _is_http_url(row.get(key))
        for key in ("post_image", "post_external_image", "video_url")
    )
    return has_identity and (
        has_text_payload or has_attachment_payload or has_top_level_media_payload
    )


def _is_brightdata_export_file(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, list) or not raw:
        return False
    return any(_looks_like_brightdata_row(item) for item in raw)


def _find_brightdata_files(directory: Path) -> list[Path]:
    json_files = sorted(directory.glob("**/*.json"))
    return [path for path in json_files if _is_brightdata_export_file(path)]


def is_facebook_export(directory: Path) -> bool:
    """Detect if a directory is a Facebook data export."""
    return bool(_find_meta_post_files(directory) or _find_brightdata_files(directory))


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


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse ISO datetime strings safely and normalize timezone."""
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _guess_media_type(url: str, source_field: str) -> str:
    lower_field = source_field.lower()
    if "video_url" in lower_field:
        return "video"
    if any(token in lower_field for token in ("thumbnail", "image", "photo", "picture")):
        return "image"

    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _IMAGE_EXTS:
        return "image"

    host = parsed.netloc.lower()
    if "video-" in host and "fbcdn.net" in host:
        return "video"
    if "scontent-" in host and "fbcdn.net" in host:
        return "image"
    if any(hint in host for hint in _MEDIA_HOST_HINTS):
        return "image"
    return "other"


def _iter_media_urls(obj: Any, path: str = "") -> list[tuple[str, str, str]]:
    """Recursively find media URLs in nested JSON and classify by type."""
    found: list[tuple[str, str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_path = f"{path}.{key}" if path else key
            if _is_http_url(value):
                media_type = _guess_media_type(value, new_path)
                if media_type in {"video", "image"}:
                    found.append((value, media_type, new_path))
            else:
                found.extend(_iter_media_urls(value, new_path))
        return found
    if isinstance(obj, list):
        for index, value in enumerate(obj):
            new_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_iter_media_urls(value, new_path))
    return found


def _normalize_tag(value: str) -> str | None:
    tag = value.strip().lstrip("#").lower()
    return tag or None


def _extract_tags_from_field(raw: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(raw, list):
        for value in raw:
            if isinstance(value, str):
                normalized = _normalize_tag(value)
                if normalized:
                    tags.append(normalized)
    elif isinstance(raw, str):
        normalized = _normalize_tag(raw)
        if normalized:
            tags.append(normalized)
    return tags


def _extract_urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in _HTTP_URL_RE.findall(text):
        if match in seen:
            continue
        seen.add(match)
        urls.append(match)
    return urls


def _media_type_counts(media: list[dict[str, Any]]) -> tuple[int, int]:
    video_count = sum(1 for entry in media if entry.get("media_type") == "video")
    image_count = sum(1 for entry in media if entry.get("media_type") == "image")
    return video_count, image_count


def _build_post_representation(
    *,
    author: str,
    text: str,
    published_at: datetime | None,
    tags: list[str],
    mentions: list[str],
    media: list[dict[str, Any]],
) -> dict[str, Any]:
    links = _extract_urls_from_text(text) if text else []
    return {
        "author": author,
        "published_at": published_at.isoformat() if published_at else None,
        "text": text,
        "tags": tags,
        "mentions": mentions,
        "links": links,
        "media": media,
    }


def _select_better_item(current: ContentItem, candidate: ContentItem) -> ContentItem:
    """Keep richer item when deduplicating by post ID/URL."""
    current_media = len(current.metadata.get("post_representation", {}).get("media", []))
    candidate_media = len(
        candidate.metadata.get("post_representation", {}).get("media", [])
    )
    current_score = (current_media, len(current.text))
    candidate_score = (candidate_media, len(candidate.text))
    return candidate if candidate_score > current_score else current


def _dedupe_items(raw_items: list[ContentItem]) -> list[ContentItem]:
    # Dedup by post_id first (for Bright Data-style exports).
    by_post_id: dict[str, ContentItem] = {}
    without_post_id: list[ContentItem] = []
    for item in raw_items:
        post_ref = item.metadata.get("post_ref", {})
        post_id = ""
        if isinstance(post_ref, dict):
            post_id = str(post_ref.get("post_id") or "").strip()
        if post_id:
            existing = by_post_id.get(post_id)
            by_post_id[post_id] = (
                item if existing is None else _select_better_item(existing, item)
            )
        else:
            without_post_id.append(item)

    # Dedup by URL: keep richer/longer item.
    by_url: dict[str, ContentItem] = {}
    no_url_items: list[ContentItem] = []
    for item in list(by_post_id.values()) + without_post_id:
        if item.url:
            existing = by_url.get(item.url)
            by_url[item.url] = (
                item if existing is None else _select_better_item(existing, item)
            )
        else:
            no_url_items.append(item)

    # Dedup by content hash.
    deduped = list(by_url.values()) + no_url_items
    seen_hashes: set[str] = set()
    final: list[ContentItem] = []
    for item in deduped:
        chash = str(item.metadata.get("content_hash") or "")
        if not chash:
            final.append(item)
            continue
        if chash not in seen_hashes:
            seen_hashes.add(chash)
            final.append(item)
    return final


def _build_meta_content_item(post: dict[str, Any], author: str) -> ContentItem | None:
    text = _extract_post_text(post)
    if not text or is_bare_url(text):
        return None

    url = _extract_post_url(post)
    tags = extract_hashtags(text)
    mentions = extract_mentions(text)
    chash = content_hash(text)
    published_at = _safe_timestamp(post.get("timestamp"))

    date_str = published_at.strftime("%Y-%m-%d") if published_at else "unknown date"
    media_entries = _iter_media_urls(post.get("attachments", []), "attachments")
    media_by_url: dict[str, dict[str, Any]] = {}
    for media_url, media_type, source_field in media_entries:
        entry = media_by_url.get(media_url)
        if entry is None:
            media_by_url[media_url] = {
                "url": media_url,
                "media_type": media_type,
                "source_fields": [source_field],
            }
        elif source_field not in entry["source_fields"]:
            entry["source_fields"].append(source_field)
    media = list(media_by_url.values())

    post_representation = _build_post_representation(
        author=author,
        text=text,
        published_at=published_at,
        tags=tags,
        mentions=mentions,
        media=media,
    )
    enriched_text = f"[Facebook post by {author} | Published: {date_str}]\n\n{text}"
    return ContentItem(
        title=derive_title(text),
        author=author,
        source_type=SourceType.LOCAL,
        url=url,
        text=enriched_text,
        published_at=published_at,
        metadata={
            "platform": "facebook",
            "extractor": "meta_export",
            "tags": tags,
            "mentions": mentions,
            "content_hash": chash,
            "post_ref": {"platform": "facebook", "post_id": "", "url": url or ""},
            "post_representation": post_representation,
        },
    )


def _extract_brightdata_post_text(post: dict[str, Any]) -> str:
    for key in ("content", "text", "message", "caption", "description", "title"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    attachments = post.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            for key in ("description", "title", "caption", "text"):
                value = attachment.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            data_items = attachment.get("data")
            if isinstance(data_items, list):
                for data_item in data_items:
                    if not isinstance(data_item, dict):
                        continue
                    media = data_item.get("media")
                    if isinstance(media, dict):
                        value = media.get("description")
                        if isinstance(value, str) and value.strip():
                            return value.strip()
    return ""


def _extract_brightdata_post_url(post: dict[str, Any]) -> str:
    for key in ("url", "post_url", "permalink"):
        value = post.get(key)
        if _is_http_url(value):
            return value.strip()
    return ""


def _extract_brightdata_published_at(post: dict[str, Any]) -> datetime | None:
    date_posted = post.get("date_posted")
    if isinstance(date_posted, str):
        parsed = _parse_iso_datetime(date_posted)
        if parsed:
            return parsed

    for key in ("timestamp", "created_time", "created_timestamp"):
        value = post.get(key)
        if isinstance(value, (int, float)):
            parsed = _safe_timestamp(value)
            if parsed:
                return parsed
        if isinstance(value, str) and value.isdigit():
            parsed = _safe_timestamp(int(value))
            if parsed:
                return parsed
    return None


def _collect_brightdata_media(post: dict[str, Any]) -> list[dict[str, Any]]:
    media_by_url: dict[str, dict[str, Any]] = {}
    media_entries = _iter_media_urls(post.get("attachments", []), "attachments")
    for key in ("post_image", "post_external_image", "video_url"):
        value = post.get(key)
        if _is_http_url(value):
            media_type = _guess_media_type(value, key)
            if media_type in {"video", "image"}:
                media_entries.append((value, media_type, key))

    for media_url, media_type, source_field in media_entries:
        entry = media_by_url.get(media_url)
        if entry is None:
            media_by_url[media_url] = {
                "url": media_url,
                "media_type": media_type,
                "source_fields": [source_field],
            }
            continue
        if source_field not in entry["source_fields"]:
            entry["source_fields"].append(source_field)
    return list(media_by_url.values())


def _fallback_hash_for_media_post(
    *, post_id: str, post_url: str, media: list[dict[str, Any]]
) -> str:
    media_urls = sorted(item["url"] for item in media)
    key = f"{post_id}|{post_url}|{'|'.join(media_urls)}"
    return sha256(key.encode("utf-8")).hexdigest()


def _build_brightdata_content_item(
    post: dict[str, Any], *, author: str, fallback_post_id: str
) -> ContentItem | None:
    post_id = str(post.get("post_id") or "").strip() or fallback_post_id
    post_url = _extract_brightdata_post_url(post)
    page_name = str(post.get("page_name") or "").strip() or author
    text = _extract_brightdata_post_text(post)
    media = _collect_brightdata_media(post)

    if not text and not media:
        return None
    if text and is_bare_url(text) and not media:
        return None

    tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in extract_hashtags(text):
        if tag not in seen_tags:
            seen_tags.add(tag)
            tags.append(tag)
    for field_name in ("hashtags", "tags"):
        for tag in _extract_tags_from_field(post.get(field_name)):
            if tag not in seen_tags:
                seen_tags.add(tag)
                tags.append(tag)

    mentions = extract_mentions(text)
    published_at = _extract_brightdata_published_at(post)
    date_str = published_at.strftime("%Y-%m-%d") if published_at else "unknown date"
    post_representation = _build_post_representation(
        author=page_name,
        text=text,
        published_at=published_at,
        tags=tags,
        mentions=mentions,
        media=media,
    )
    video_count, image_count = _media_type_counts(media)

    if text:
        content_for_hash = text
        body_lines = [text]
    else:
        content_for_hash = ""
        body_lines = [
            "Media-only Facebook post.",
            f"Videos: {video_count}, Images: {image_count}",
        ]

    if tags:
        body_lines.append("Tags: " + " ".join(f"#{tag}" for tag in tags))

    enriched_text = (
        f"[Facebook post by {page_name} | Published: {date_str}]\n\n"
        + "\n".join(body_lines)
    )
    stable_hash = (
        content_hash(content_for_hash)
        if content_for_hash
        else _fallback_hash_for_media_post(
            post_id=post_id,
            post_url=post_url,
            media=media,
        )
    )

    return ContentItem(
        title=derive_title(text) if text else f"Facebook post {post_id}",
        author=page_name or author,
        source_type=SourceType.LOCAL,
        url=post_url or None,
        text=enriched_text,
        published_at=published_at,
        metadata={
            "platform": "facebook",
            "extractor": "brightdata",
            "source_type_label": "social_media_post",
            "tags": tags,
            "mentions": mentions,
            "content_hash": stable_hash,
            "post_ref": {
                "platform": "facebook",
                "post_id": post_id,
                "url": post_url,
            },
            "post_representation": post_representation,
        },
    )


def _parse_meta_export_file(post_file: Path, *, author: str) -> tuple[list[ContentItem], int, int]:
    with post_file.open("r", encoding="utf-8") as f:
        posts = json.load(f)
    posts = fix_meta_encoding_recursive(posts)

    items: list[ContentItem] = []
    skipped_no_text = 0
    skipped_bare_url = 0
    for post in posts:
        if not isinstance(post, dict):
            continue
        text = _extract_post_text(post)
        if not text:
            skipped_no_text += 1
            continue
        if is_bare_url(text):
            skipped_bare_url += 1
            continue
        item = _build_meta_content_item(post, author)
        if item is not None:
            items.append(item)
    return items, skipped_no_text, skipped_bare_url


def _parse_brightdata_export_file(post_file: Path, *, author: str) -> tuple[list[ContentItem], int]:
    with post_file.open("r", encoding="utf-8") as f:
        posts = json.load(f)
    posts = fix_meta_encoding_recursive(posts)
    if not isinstance(posts, list):
        logger.warning(f"Skipping {post_file}: expected top-level list")
        return [], 0

    items: list[ContentItem] = []
    skipped_empty = 0
    file_token = sha256(str(post_file).encode("utf-8")).hexdigest()[:12]
    for index, post in enumerate(posts, start=1):
        if not isinstance(post, dict):
            continue
        item = _build_brightdata_content_item(
            post,
            author=author,
            fallback_post_id=f"brightdata-{file_token}-{index}",
        )
        if item is None:
            skipped_empty += 1
            continue
        items.append(item)
    return items, skipped_empty


def parse_facebook_brightdata_file(path: Path, *, author: str) -> list[ContentItem]:
    """Parse a single Bright Data-style Facebook JSON file into ContentItem objects."""
    if not path.is_file():
        logger.warning(f"Bright Data file not found: {path}")
        return []
    if not _is_brightdata_export_file(path):
        logger.warning(f"Not a supported Bright Data Facebook JSON file: {path}")
        return []
    try:
        items, skipped_empty = _parse_brightdata_export_file(path, author=author)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Skipping {path}: failed to parse JSON: {e}")
        return []
    final = _dedupe_items(items)
    logger.info(
        f"Facebook Bright Data ({path.name}): {len(items)} raw → {len(final)} after dedup "
        f"(skipped_empty={skipped_empty})"
    )
    return final


def parse_facebook_export(export_dir: Path, *, author: str) -> list[ContentItem]:
    """Parse Facebook exports (Meta and Bright Data) into ContentItem objects."""
    meta_files = _find_meta_post_files(export_dir)
    brightdata_files = _find_brightdata_files(export_dir)
    if not meta_files and not brightdata_files:
        logger.warning(f"No Facebook export files found in {export_dir}")
        return []

    raw_items: list[ContentItem] = []

    for post_file in meta_files:
        logger.info(f"Parsing {post_file.name}")
        try:
            items, skipped_no_text, skipped_bare_url = _parse_meta_export_file(
                post_file, author=author
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Skipping {post_file}: failed to parse JSON: {e}")
            continue
        raw_items.extend(items)
        if skipped_no_text or skipped_bare_url:
            logger.info(
                f"{post_file.name}: skipped {skipped_no_text} posts without text, "
                f"{skipped_bare_url} bare-URL posts"
            )

    for post_file in brightdata_files:
        logger.info(f"Parsing {post_file.name} (Bright Data)")
        try:
            items, skipped_empty = _parse_brightdata_export_file(post_file, author=author)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Skipping {post_file}: failed to parse JSON: {e}")
            continue
        raw_items.extend(items)
        if skipped_empty:
            logger.info(
                f"{post_file.name}: skipped {skipped_empty} posts with no text/media"
            )

    final = _dedupe_items(raw_items)

    logger.info(f"Facebook: {len(raw_items)} raw → {len(final)} after dedup")
    return final
