"""Local directory dispatcher with registry-based auto-detection.

Adding a new export format = add one (detect, parse) tuple to PARSERS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger

from syft_ingest.core.fetcher import FetchRequest, FetchResult
from syft_ingest.core.models import ContentItem
from syft_ingest.sources.facebook import is_facebook_export, parse_facebook_export
from syft_ingest.sources.instagram import is_instagram_export, parse_instagram_export

PARSERS: list[tuple[Callable[[Path], bool], Callable[..., list[ContentItem]]]] = [
    (is_facebook_export, parse_facebook_export),
    (is_instagram_export, parse_instagram_export),
]


def fetch_local(dirs: list[str], *, author: str = "") -> list[ContentItem]:
    """Walk directories, auto-detect export type, delegate to parser."""
    items: list[ContentItem] = []

    for d in dirs:
        path = Path(d)
        if not path.is_dir():
            logger.warning(f"Skipping non-existent directory: {d}")
            continue

        matched = False
        for detect, parse in PARSERS:
            if detect(path):
                result = parse(path, author=author)
                items.extend(result)
                matched = True
                break

        if not matched:
            logger.warning(f"Could not detect export type for: {d}")

    return items


class LocalFetcher:
    """Fetcher for local directory exports (Facebook, Instagram, etc.).

    Implements ContentFetcher protocol to allow "local" to be dispatched
    through the same registry as remote platforms (YouTube, Instagram, etc.).
    """

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch content from local directory exports.

        Args:
            request: FetchRequest with urls as directory paths.
                     Author can be passed in request.config if needed.

        Returns:
            FetchResult with parsed items from the local export.
        """
        # Extract author from config if provided
        author = ""
        if isinstance(request.config, dict):
            author = request.config.get("author", "")

        items = fetch_local(request.urls, author=author)
        return FetchResult(items=items, rows_fetched=len(items))
