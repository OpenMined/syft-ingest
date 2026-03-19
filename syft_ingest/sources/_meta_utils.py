"""Shared utilities for Meta platform data exports (Facebook, Instagram, Threads).

All Meta exports share the same UTF-8-as-Latin-1 encoding bug, the same
pagination pattern (_1, _2 suffixed files), and the same omitted-field behavior.
"""

from __future__ import annotations

import hashlib
import re


def fix_meta_encoding(text: str) -> str:
    """Fix Meta's broken UTF-8-as-Latin-1 encoding.

    Meta's JSON serializer encodes each UTF-8 byte as a separate \\u00XX escape.
    Example: 'ą' (U+0105, UTF-8 bytes 0xC4 0x85) is stored as \\u00c4\\u0085.

    The fix: encode back to Latin-1 (recovers original UTF-8 bytes), then decode as UTF-8.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def fix_meta_encoding_recursive(obj):
    """Apply fix_meta_encoding to all strings in a nested dict/list structure."""
    if isinstance(obj, str):
        return fix_meta_encoding(obj)
    if isinstance(obj, dict):
        return {k: fix_meta_encoding_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fix_meta_encoding_recursive(item) for item in obj]
    return obj


_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
_MENTION_RE = re.compile(r"@(\w+)", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)


def extract_hashtags(text: str) -> list[str]:
    """Extract #hashtags from text, deduplicated, lowercased."""
    seen = set()
    result = []
    for match in _HASHTAG_RE.finditer(text):
        tag = match.group(1).lower()
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def extract_mentions(text: str) -> list[str]:
    """Extract @mentions from text, deduplicated, lowercased."""
    seen = set()
    result = []
    for match in _MENTION_RE.finditer(text):
        mention = match.group(1).lower()
        if mention not in seen:
            seen.add(mention)
            result.append(mention)
    return result


def extract_first_url(text: str) -> str | None:
    """Extract the first URL from text, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def extract_last_url(text: str) -> str | None:
    """Extract the last URL from text, or None.

    Useful for FB posts where the blog post link is typically the last URL,
    while mid-text URLs (e.g., co-design program links) are shared across posts.
    """
    matches = _URL_RE.findall(text)
    return matches[-1] if matches else None


def normalize_text(text: str) -> str:
    """Normalize text for deduplication comparison.

    Strips hashtags and mentions but keeps URLs (they differentiate posts
    that share prose but link to different content). Collapses whitespace, lowercases.
    """
    normalized = _HASHTAG_RE.sub("", text)
    normalized = _MENTION_RE.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def content_hash(text: str) -> str:
    """SHA-256 hash of normalized text for cross-platform deduplication."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def is_bare_url(text: str) -> bool:
    """Check if text is just a URL with no meaningful content."""
    return bool(_BARE_URL_RE.match(text))


def derive_title(text: str, max_length: int = 80) -> str:
    """Derive a title from the first line of post text."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_length:
        return first_line
    truncated = first_line[:max_length]
    parts = truncated.rsplit(" ", 1)
    if len(parts) > 1:
        return parts[0] + "..."
    return truncated[: max_length - 3] + "..."
