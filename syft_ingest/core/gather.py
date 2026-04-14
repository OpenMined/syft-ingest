from __future__ import annotations

from loguru import logger

from syft_ingest.core.fetcher import FetchRequest, run_fetcher_async, run_fetcher_sync
from syft_ingest.core.models import Corpus

_fetchers_registered = False


def _ensure_fetchers() -> None:
    """Register fetchers on first use, not at import time."""
    global _fetchers_registered
    if not _fetchers_registered:
        from syft_ingest.setup import register_fetchers

        register_fetchers()
        _fetchers_registered = True


def _build_request(
    platform: str,
    urls: list[str] | None,
    author: str,
    **config,
):
    """Validate inputs, build FetchRequest, and resolve fetcher. Shared by gather/async_gather."""
    from syft_ingest.core.registry import get_fetcher
    from syft_ingest.core.url_router import Platform

    if not urls:
        raise ValueError(f"Platform '{platform}' requires urls list")

    p = Platform(platform)

    # Extract top-level FetchRequest fields from config kwargs so they are not
    # silently buried in the opaque config dict.
    start_date = config.pop("start_date", None)
    end_date = config.pop("end_date", None)

    request_config = dict(config)
    if author:
        request_config["author"] = author

    request = FetchRequest(
        platform=p,
        urls=urls,
        start_date=start_date,
        end_date=end_date,
        config=request_config,
    )
    fetcher = get_fetcher(p, request.extractor)
    return fetcher, request


def gather(
    platform: str,
    urls: list[str] | None = None,
    author: str = "",
    **config,
) -> Corpus:
    """Gather content from a platform — sync entry point.

    Usage:
        corpus = gather("youtube", ["https://youtube.com/watch?v=..."])
        corpus = gather("instagram", ["https://instagram.com/user/"])
        corpus = gather("local", ["/path/to/export"], author="Andrej Karpathy")

    Args:
        platform: Platform name ("youtube", "facebook", "instagram", "tiktok", "local")
        urls: List of URLs or local directory paths to fetch from
        author: Optional author/person name for metadata
        **config: Fetcher-specific config options

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    _ensure_fetchers()
    corpus = Corpus(person=author)

    try:
        fetcher, request = _build_request(platform, urls, author, **config)
        result = run_fetcher_sync(fetcher, request)
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


async def async_gather(
    platform: str,
    urls: list[str] | None = None,
    author: str = "",
    **config,
) -> Corpus:
    """Gather content from a platform — async entry point.

    Usage:
        corpus = await async_gather("youtube", ["https://youtube.com/watch?v=..."])
        corpus = await async_gather("instagram", ["https://instagram.com/user/"])

    Args:
        platform: Platform name ("youtube", "facebook", "instagram", "tiktok", "local")
        urls: List of URLs or local directory paths to fetch from
        author: Optional author/person name for metadata
        **config: Fetcher-specific config options

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    _ensure_fetchers()
    corpus = Corpus(person=author)

    try:
        fetcher, request = _build_request(platform, urls, author, **config)
        result = await run_fetcher_async(fetcher, request)
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
