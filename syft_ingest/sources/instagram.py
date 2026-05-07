"""Instagram data export parser.

Supports:
- Meta "Download Your Information" export format
- Bright Data / crawler-style Instagram post JSON exports
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

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
from syft_ingest.sources._social_media_common import (
    extract_tags_from_field,
    guess_media_type,
    is_http_url,
    iter_media_urls,
    media_type_counts,
)

# Max reasonable timestamp: year 2100
_MAX_TIMESTAMP = 4102444800


def _looks_like_brightdata_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False

    def _nonempty_scalar(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        return isinstance(value, (int, float))

    has_identity = any(
        _nonempty_scalar(row.get(key))
        for key in (
            "url",
            "post_url",
            "shortcode",
            "content_id",
            "pk",
            "date_posted",
        )
    )
    has_author = any(
        isinstance(row.get(key), str) and row.get(key).strip()
        for key in ("user_posted", "username", "owner_username", "profile_name")
    )
    has_text_payload = any(
        isinstance(row.get(key), str) and row.get(key).strip()
        for key in ("description", "caption", "text", "title", "content")
    )
    has_media_payload = any(
        isinstance(row.get(key), list) and bool(row.get(key))
        for key in ("photos", "videos", "images", "post_content", "carousel_media")
    ) or any(
        isinstance(row.get(key), str)
        and row.get(key).startswith(("http://", "https://"))
        for key in ("video_url", "thumbnail_url", "thumbnail", "image_url")
    )
    return has_identity and (has_author or has_text_payload or has_media_payload)


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


def is_instagram_export(directory: Path) -> bool:
    """Detect if a directory is an Instagram data export.

    Checks for modern format (media/posts_*.json) and legacy format (content/posts_*.json).
    """
    modern = list(directory.glob("**/media/posts_*.json"))
    legacy = list(directory.glob("**/content/posts_*.json"))
    return bool(modern or legacy or _find_brightdata_files(directory))


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


def _parse_iso_datetime(value: str) -> datetime | None:
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


def _extract_brightdata_post_text(post: dict[str, Any]) -> str:
    for key in ("description", "caption", "text", "title", "content"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            # BrightData sometimes puts the numeric post ID in "title" — skip it
            if stripped.isdigit():
                continue
            return stripped

    post_content = post.get("post_content")
    if isinstance(post_content, list):
        for entry in post_content:
            if not isinstance(entry, dict):
                continue
            for key in ("caption", "description", "alt_text", "accessibility_caption"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _extract_brightdata_post_url(post: dict[str, Any]) -> str:
    for key in ("url", "post_url", "permalink"):
        value = post.get(key)
        if is_http_url(value):
            return value.strip()

    shortcode = str(post.get("shortcode") or post.get("content_id") or "").strip()
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    return ""


def _extract_brightdata_published_at(post: dict[str, Any]) -> datetime | None:
    date_posted = post.get("date_posted")
    if isinstance(date_posted, str):
        parsed = _parse_iso_datetime(date_posted)
        if parsed:
            return parsed

    for key in ("timestamp", "taken_at_timestamp", "created_timestamp"):
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

    def add(url: str, source_field: str) -> None:
        if not is_http_url(url):
            return
        media_type = guess_media_type(url, source_field)
        if media_type not in {"video", "image"}:
            return
        entry = media_by_url.get(url)
        if entry is None:
            media_by_url[url] = {
                "url": url,
                "media_type": media_type,
                "source_fields": [source_field],
            }
            return
        if source_field not in entry["source_fields"]:
            entry["source_fields"].append(source_field)

    for key in ("photos", "videos", "images"):
        values = post.get(key)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if isinstance(value, str):
                add(value, f"{key}[{index}]")

    for key in ("video_url", "thumbnail_url", "thumbnail", "image_url"):
        value = post.get(key)
        if isinstance(value, str):
            add(value, key)

    post_content = post.get("post_content")
    if isinstance(post_content, list):
        for media_url, _, source_field in iter_media_urls(post_content, "post_content"):
            add(media_url, source_field)

    return list(media_by_url.values())


def _fallback_hash_for_media_post(
    *, post_id: str, post_url: str, media: list[dict[str, Any]]
) -> str:
    media_urls = sorted(item["url"] for item in media)
    key = f"{post_id}|{post_url}|{'|'.join(media_urls)}"
    return sha256(key.encode("utf-8")).hexdigest()


def _build_post_representation(
    *,
    author: str,
    text: str,
    published_at: datetime | None,
    tags: list[str],
    mentions: list[str],
    media: list[dict[str, Any]],
    content_type: str | None,
    content_items: list[dict[str, Any]],
    audio: dict[str, Any] | None,
    thumbnail_url: str | None,
    latest_comments: list[dict[str, Any]],
) -> dict[str, Any]:
    post_representation = {
        "author": author,
        "published_at": published_at.isoformat() if published_at else None,
        "text": text,
        "tags": tags,
        "mentions": mentions,
        "media": media,
    }
    if content_type:
        post_representation["content_type"] = content_type
    if content_items:
        post_representation["content_items"] = content_items
    if audio:
        post_representation["audio"] = audio
    if thumbnail_url:
        post_representation["thumbnail_url"] = thumbnail_url
    if latest_comments:
        post_representation["latest_comments"] = latest_comments
    return post_representation


def _select_better_item(current: ContentItem, candidate: ContentItem) -> ContentItem:
    current_media = len(
        current.metadata.get("post_representation", {}).get("media", [])
    )
    candidate_media = len(
        candidate.metadata.get("post_representation", {}).get("media", [])
    )
    current_score = (current_media, len(current.text))
    candidate_score = (candidate_media, len(candidate.text))
    return candidate if candidate_score > current_score else current


def _dedupe_items(raw_items: list[ContentItem]) -> list[ContentItem]:
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

    deduped = list(by_url.values()) + no_url_items
    seen_hashes: set[str] = set()
    final: list[ContentItem] = []
    for item in deduped:
        chash = str(item.metadata.get("content_hash") or "")
        if not chash:
            final.append(item)
            continue
        if chash in seen_hashes:
            continue
        seen_hashes.add(chash)
        final.append(item)
    return final


def _build_brightdata_content_item(
    post: dict[str, Any], *, author: str, fallback_post_id: str
) -> ContentItem | None:
    post_url = _extract_brightdata_post_url(post)
    post_id = (
        str(
            post.get("pk")
            or post.get("content_id")
            or post.get("shortcode")
            or post.get("user_posted_id")
            or ""
        ).strip()
        or fallback_post_id
    )
    account_name = str(
        post.get("user_posted")
        or post.get("username")
        or post.get("owner_username")
        or post.get("profile_name")
        or ""
    ).strip()
    item_author = account_name or author
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
        for tag in extract_tags_from_field(post.get(field_name)):
            if tag not in seen_tags:
                seen_tags.add(tag)
                tags.append(tag)

    mentions = extract_mentions(text)
    published_at = _extract_brightdata_published_at(post)
    date_str = published_at.strftime("%Y-%m-%d") if published_at else "unknown date"
    content_type = post.get("content_type")
    if not isinstance(content_type, str) or not content_type.strip():
        content_type = None
    thumbnail_url = post.get("thumbnail") or post.get("thumbnail_url")
    if not isinstance(thumbnail_url, str) or not thumbnail_url.strip():
        thumbnail_url = None
    audio = post.get("audio") if isinstance(post.get("audio"), dict) else None
    content_items = [
        entry for entry in (post.get("post_content") or []) if isinstance(entry, dict)
    ]
    latest_comments = [
        entry
        for entry in (post.get("latest_comments") or [])
        if isinstance(entry, dict)
    ]
    post_representation = _build_post_representation(
        author=item_author,
        text=text,
        published_at=published_at,
        tags=tags,
        mentions=mentions,
        media=media,
        content_type=content_type,
        content_items=content_items,
        audio=audio,
        thumbnail_url=thumbnail_url,
        latest_comments=latest_comments,
    )
    video_count, image_count = media_type_counts(media)

    if text:
        content_for_hash = text
        body_lines = [text]
    else:
        content_for_hash = ""
        body_lines = [
            "Media-only Instagram post.",
            f"Videos: {video_count}, Images: {image_count}",
        ]

    if tags:
        body_lines.append("Tags: " + " ".join(f"#{tag}" for tag in tags))

    enriched_text = (
        f"[Instagram post by {item_author} | Published: {date_str}]\n\n"
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

    metadata = {
        "platform": "instagram",
        "extractor": "brightdata",
        "source_type_label": "social_media_post",
        "tags": tags,
        "mentions": mentions,
        "content_hash": stable_hash,
        "post_ref": {
            "platform": "instagram",
            "post_id": post_id,
            "shortcode": str(post.get("shortcode") or "").strip(),
            "url": post_url,
        },
        "post_representation": post_representation,
    }

    profile_url = str(
        post.get("profile_url")
        or post.get("owner_profile_url")
        or post.get("user_posted_url")
        or ""
    ).strip()
    if profile_url:
        metadata["profile_url"] = profile_url

    return ContentItem(
        title=derive_title(text) if text else f"Instagram post {post_id}",
        author=item_author,
        source_type=SourceType.LOCAL,
        url=post_url or None,
        text=enriched_text,
        published_at=published_at,
        metadata=metadata,
    )


def _parse_brightdata_export_file(
    post_file: Path, *, author: str
) -> tuple[list[ContentItem], int]:
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
            fallback_post_id=f"brightdata-instagram-{file_token}-{index}",
        )
        if item is None:
            skipped_empty += 1
            continue
        items.append(item)
    return items, skipped_empty


def parse_instagram_brightdata_file(path: Path, *, author: str) -> list[ContentItem]:
    """Parse a single Bright Data-style Instagram JSON file into ContentItem objects."""
    if not path.is_file():
        logger.warning(f"Bright Data file not found: {path}")
        return []
    if not _is_brightdata_export_file(path):
        logger.warning(f"Not a supported Bright Data Instagram JSON file: {path}")
        return []
    try:
        items, skipped_empty = _parse_brightdata_export_file(path, author=author)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Skipping {path}: failed to parse JSON: {e}")
        return []
    final = _dedupe_items(items)
    logger.info(
        f"Instagram Bright Data ({path.name}): {len(items)} raw → {len(final)} after dedup "
        f"(skipped_empty={skipped_empty})"
    )
    return final


def parse_instagram_export(export_dir: Path, *, author: str) -> list[ContentItem]:
    """Parse an Instagram data export directory into ContentItem objects."""
    post_files = sorted(
        list(export_dir.glob("**/media/posts_*.json"))
        + list(export_dir.glob("**/content/posts_*.json"))
    )
    brightdata_files = _find_brightdata_files(export_dir)
    if not post_files and not brightdata_files:
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

    for post_file in brightdata_files:
        logger.info(f"Parsing {post_file.name} (Bright Data)")
        try:
            items, skipped_empty = _parse_brightdata_export_file(
                post_file, author=author
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Skipping {post_file}: failed to parse JSON: {e}")
            continue
        raw_items.extend(items)
        if skipped_empty:
            logger.info(
                f"{post_file.name}: skipped {skipped_empty} posts with no text/media"
            )

    final = _dedupe_items(raw_items)
    logger.info(f"Instagram: {len(raw_items)} raw → {len(final)} after dedup")
    return final
