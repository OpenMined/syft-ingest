from __future__ import annotations

from loguru import logger

from syft_ingest.core.models import Corpus


def gather(
    platform: str,
    urls: list[str] | None = None,
    author: str = "",
    **config,
) -> Corpus:
    """Gather content from a platform or local sources into a Corpus.

    Simplified API (Phase 4):
        gather("youtube", ["https://youtube.com/watch?v=..."])
        gather("facebook", ["https://facebook.com/user"])
        gather("instagram", ["https://instagram.com/user/"])
        gather("local", ["/path/to/export"], author="Andrej Karpathy")

    Args:
        platform: Platform name ("youtube", "facebook", "instagram", "tiktok", "local")
        urls: List of URLs or local directory paths to fetch from
        author: Optional author/person name for metadata
        **config: Fetcher-specific config options (socket_timeout, timeout, posts_limit, etc.)

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    corpus = Corpus(person=author)

    # Handle "local" specially (existing behavior)
    if platform == "local":
        if not urls:
            raise ValueError("'local' platform requires urls (list of directory paths)")
        from syft_ingest.sources.local import fetch_local

        items = fetch_local(urls, author=author)
        corpus.add(items)
        logger.info(f"Gathered {len(items)} items from local directories")
        return corpus

    # Handle remote platforms via fetcher registry
    if not urls:
        raise ValueError(f"Platform '{platform}' requires urls list")

    try:
        from syft_ingest.core.fetcher import FetchRequest
        from syft_ingest.core.registry import get_fetcher
        from syft_ingest.core.url_router import Platform

        # Convert to Platform enum (validates platform name)
        p = Platform(platform)

        # Create request (auto-detects extractor from platform)
        request = FetchRequest(
            platform=p,
            urls=urls,
            config=config,
        )

        # Get fetcher from registry
        fetcher = get_fetcher(p, request.extractor)

        # Fetch and add to corpus
        result = fetcher.fetch(request)
        corpus.add(result.items)
        logger.info(f"Gathered {len(result.items)} items from {platform}")

    except ValueError as e:
        logger.error(f"Invalid platform: {e}")
        raise
    except KeyError as e:
        logger.error(f"No fetcher registered for {platform}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to fetch from {platform}: {e}")
        raise

    return corpus
