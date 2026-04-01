from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
_MEDIA_HOST_HINTS = ("fbcdn.net", "cdninstagram.com")


def is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def guess_media_type(url: str, source_field: str) -> str:
    lower_field = source_field.lower()
    if "video" in lower_field:
        return "video"
    if any(
        token in lower_field
        for token in ("thumbnail", "image", "photo", "picture", "display")
    ):
        return "image"

    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _IMAGE_EXTS:
        return "image"

    host = parsed.netloc.lower()
    if "video" in host and any(hint in host for hint in _MEDIA_HOST_HINTS):
        return "video"
    if any(hint in host for hint in _MEDIA_HOST_HINTS):
        return "image"
    return "other"


def iter_media_urls(obj: Any, path: str = "") -> list[tuple[str, str, str]]:
    """Recursively find media URLs in nested JSON and classify by type."""
    found: list[tuple[str, str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_path = f"{path}.{key}" if path else key
            if is_http_url(value):
                media_type = guess_media_type(value, new_path)
                if media_type in {"video", "image"}:
                    found.append((value, media_type, new_path))
            else:
                found.extend(iter_media_urls(value, new_path))
        return found
    if isinstance(obj, list):
        for index, value in enumerate(obj):
            new_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(iter_media_urls(value, new_path))
    return found


def extract_tags_from_field(raw: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(raw, list):
        for value in raw:
            normalized = _normalize_tag(value)
            if normalized:
                tags.append(normalized)
    elif isinstance(raw, str):
        normalized = _normalize_tag(raw)
        if normalized:
            tags.append(normalized)
    return tags


def media_type_counts(media: list[dict[str, Any]]) -> tuple[int, int]:
    video_count = sum(1 for entry in media if entry.get("media_type") == "video")
    image_count = sum(1 for entry in media if entry.get("media_type") == "image")
    return video_count, image_count


def _normalize_tag(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    tag = raw.strip().lstrip("#").lower()
    return tag or None
