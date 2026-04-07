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
            logger.warning(
                "Parsed platform %r does not match source spec platform %r for %s",
                parser_platform,
                spec.platform,
                spec.raw_dirs,
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
    **kwargs,
) -> Corpus:
    """Gather content from multiple sources into a Corpus."""
    corpus = Corpus(person=name)
    sources = sources or []
    source_specs = source_specs or []

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

    logger.info(f"Gathered {len(corpus.all_items())} items for {name!r}")
    return corpus
