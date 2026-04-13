from __future__ import annotations

from loguru import logger

from syft_ingest.core.models import Corpus
from syft_ingest.core.source_specs import SocialProfileSource, SourceSpec


def _apply_social_profile_metadata(
    spec: SocialProfileSource,
    corpus: Corpus,
) -> None:
    for item in corpus.local:
        metadata = dict(item.metadata or {})
        parser_platform = str(metadata.get("platform") or "").strip().lower()
        if parser_platform and parser_platform != spec.platform:
            raise RuntimeError(
                "Parsed platform "
                f"{parser_platform!r} does not match source spec platform "
                f"{spec.platform!r} for {spec.raw_dirs}"
            )
        metadata.setdefault("platform", spec.platform)
        metadata.setdefault("extractor", spec.extractor)
        metadata["source_profile"] = {
            "platform": spec.platform,
            "extractor": spec.extractor,
            "handle": spec.handle,
            "profile_url": spec.profile_url,
            "start_date": spec.start_date,
            "end_date": spec.end_date,
            "external_account_id": spec.external_account_id,
            "display_name": spec.display_name,
            "source_slug": spec.source_slug,
        }
        item.metadata = metadata


def _gather_from_source_spec(name: str, spec: SourceSpec) -> Corpus:
    corpus = Corpus(person=name)
    if not isinstance(spec, SourceSpec):
        logger.warning("Object does not satisfy SourceSpec protocol: {!r}", spec)
        return corpus

    kind = getattr(spec, "kind", None)
    if kind == "social_profile":
        from syft_ingest.sources.local import fetch_local

        corpus.add(fetch_local(spec.raw_dirs, author=name))
        # Apply social-specific metadata if the spec has the fields
        if isinstance(spec, SocialProfileSource):
            _apply_social_profile_metadata(spec, corpus)
        return corpus

    logger.warning("Unsupported source spec kind: {!r}", kind)
    return corpus


def gather(
    name: str,
    *,
    source_specs: list[SourceSpec] | None = None,
    sources: list[str] | None = None,
    local_dirs: list[str] | None = None,
    url_sources: list[str] | None = None,
    **kwargs,
) -> Corpus:
    """Gather content from multiple sources into a Corpus.

    Args:
        name: Person/creator identifier
        source_specs: List of SourceSpec objects (social profile exports)
        sources: List of source type strings ('local', 'youtube', etc.) - deprecated in favor of url_sources
        local_dirs: List of local export directory paths
        url_sources: List of creator URLs (YouTube, Instagram, Facebook) - NEW
        **kwargs: Additional options

    Returns:
        Corpus: Unified collection of content items from all sources
    """
    corpus = Corpus(person=name)
    sources = sources or []
    source_specs = source_specs or []
    url_sources = url_sources or []

    for spec in source_specs:
        source_corpus = _gather_from_source_spec(name, spec)
        corpus.add(source_corpus.all_items())

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

    # URL sources dispatch via url_router and fetcher registry
    for url in url_sources:
        try:
            from syft_ingest.core.fetcher import (
                FetchEmptyResultError,
                FetchError,
                FetchRequest,
            )
            from syft_ingest.core.url_router import (
                _PLATFORM_ACQUISITION,
                AcquisitionMethod,
                get_fetcher_for_url,
                resolve_url,
            )

            logger.info(f"Fetching from URL: {url}")

            # Resolve URL to get platform and acquisition method
            route_result = resolve_url(url)
            platform = route_result.platform

            # Map acquisition method to extractor name
            method_mapping = {
                AcquisitionMethod.YT_DLP: "yt-dlp",
                AcquisitionMethod.BRIGHT_DATA: "brightdata",
            }
            acquisition_method = _PLATFORM_ACQUISITION[platform]
            extractor = method_mapping.get(acquisition_method)

            if not extractor:
                logger.warning(f"No extractor configured for {platform.value}")
                continue

            # Dispatch URL to fetcher via registry
            fetcher = get_fetcher_for_url(url)

            # Create fetch request with resolved platform and extractor
            request = FetchRequest(
                platform=platform,
                extractor=extractor,
                urls=[url],
            )

            # Fetch content
            result = fetcher.fetch(request)

            # Add items to corpus
            if result and result.items:
                corpus.add(result.items)
                logger.info(f"Fetched {len(result.items)} items from {url}")
            else:
                logger.warning(f"No items returned from {url}")

        except FetchEmptyResultError as e:
            logger.info(f"Empty result from {url}: {e}")
        except FetchError as e:
            logger.warning(f"Fetch error for {url}: {e}")
        except ValueError as e:
            logger.warning(f"Invalid URL {url}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")

    logger.info(f"Gathered {len(corpus.all_items())} items for {name!r}")
    return corpus
