from __future__ import annotations

from loguru import logger

from syft_ingest.core.models import Corpus


def gather(
    name: str,
    *,
    sources: list[str] | None = None,
    local_dirs: list[str] | None = None,
    **kwargs,
) -> Corpus:
    """Gather content from multiple sources into a Corpus."""
    corpus = Corpus(person=name)
    sources = sources or []

    for source in sources:
        try:
            if source == "local":
                if not local_dirs:
                    logger.warning(
                        "Source 'local' specified but no local_dirs provided"
                    )
                    continue
                from syft_ingest.sources.local import fetch_local

                items = fetch_local(local_dirs, author=name)
                corpus.add(items)
            elif source == "youtube":
                logger.warning("YouTube source not yet implemented")
            elif source == "web":
                logger.warning("Web source not yet implemented")
            elif source == "arxiv":
                logger.warning("arXiv source not yet implemented")
            elif source == "podcast":
                logger.warning("Podcast source not yet implemented")
            elif source == "tiktok":
                logger.warning("TikTok source not yet implemented")
            else:
                logger.warning(f"Unknown source: {source!r}")
        except Exception as e:
            logger.error(f"Failed to fetch from source {source!r}: {e}")

    logger.info(f"Gathered {len(corpus.all_items())} items for {name!r}")
    return corpus
