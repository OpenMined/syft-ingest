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

    # Validate URLs are provided for all platforms
    if not urls:
        raise ValueError(f"Platform '{platform}' requires urls list")

    try:
        from syft_ingest.core.fetcher import FetchRequest
        from syft_ingest.core.registry import get_fetcher
        from syft_ingest.core.url_router import Platform

        # Convert to Platform enum (validates platform name)
        p = Platform(platform)

        # Create request (auto-detects extractor from platform)
        # Include author in config if provided (for LocalFetcher and other fetchers that need it)
        request_config = dict(config)
        if author:
            request_config["author"] = author

        request = FetchRequest(
            platform=p,
            urls=urls,
            config=request_config,
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
