"""Discrete BrightData snapshot lifecycle.

Today only ``download_snapshot`` + ``cancel`` are implemented.
``trigger`` / ``poll_status`` / ``attach`` are signposts: a future
orchestrating caller (a windowed ingestion loop, or the ingestion service)
will drive the steps separately — persist the ``snapshot_id`` before any long
wait so a crash mid-collection is resumable. ``gather()`` / ``async_gather()``
remain the all-in-one trigger→poll→download path.

Design: the *download* step (``GET /datasets/v3/snapshot/{id}``) is platform-
and dataset-agnostic, so ``download_snapshot`` re-attaches to a snapshot from
any BrightData source the same way. The *trigger* is the only per-platform
piece; poll / download / cancel are shared. Adding a new source (X, TikTok, …)
means writing its trigger — resume + cancel + chunked download come for free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from syft_ingest.core.models import Corpus

# Platforms whose snapshots BrightData parses today. The download endpoint is
# platform-agnostic, but normalization (_parse_response) is per-platform, so a
# resume only makes sense for a platform we can parse back into ContentItems.
_DOWNLOADABLE_PLATFORMS: frozenset[str] = frozenset({"facebook", "instagram"})


@dataclass(frozen=True)
class SnapshotHandle:
    """An addressable, persisted snapshot: ``(platform, snapshot_id)``.

    A value object a caller can store and later pass to the lifecycle steps to
    re-drive a snapshot without re-triggering it.
    """

    platform: str
    snapshot_id: str


async def download_snapshot(
    platform: str,
    snapshot_id: str,
    *,
    cancel_callback: Callable[[], bool] | None = None,
    status_callback: Callable[[str, str], None] | None = None,
) -> Corpus:
    """Re-attach to an already-collected snapshot and download it.

    No re-trigger, no re-collection, no re-bill: streams the snapshot's data by
    id and normalizes it into the same ``Corpus`` a fresh fetch would produce.
    Waits past a still-collecting (HTTP 202) snapshot until ready, so a resume
    works even when the snapshot we re-attach to has not finished. Checks
    ``cancel_callback`` between chunks (raising ``FetchCancelled`` and
    best-effort cancelling upstream) and emits ``status_callback`` as it
    progresses.

    Args:
        platform: ``"facebook"`` or ``"instagram"`` (the platforms whose
            snapshots can be normalized today).
        snapshot_id: The BrightData snapshot id to re-attach to.
        cancel_callback: Optional ``() -> bool`` consulted between chunks.
        status_callback: Optional ``(snapshot_id, status)`` observability hook.

    Returns:
        A ``Corpus`` containing the normalized content items.

    Raises:
        ValueError: ``platform`` is not a downloadable platform.
        FetchAuthError: No ``BRIGHTDATA_API_TOKEN`` available.
        FetchCancelled: ``cancel_callback`` returned True mid-download.
        SnapshotNotFoundError: Snapshot expired / not found (caller should fall
            back to a fresh trigger).
        FetchEmptyResultError: Snapshot downloaded but contained no items.
        FetchBotChallengeError / FetchScrapeFailedError: Snapshot carried an
            upstream error_code (bot challenge / scrape failure).
    """
    platform = platform.lower()
    if platform not in _DOWNLOADABLE_PLATFORMS:
        raise ValueError(
            f"download_snapshot supports {sorted(_DOWNLOADABLE_PLATFORMS)}; "
            f"got {platform!r}"
        )

    # Imported lazily: brightdata imports the SDK at module load, and the
    # lifecycle API should be importable (for the signposts) even where the SDK
    # or a token is not configured.
    from syft_ingest.core.fetcher import FetchEmptyResultError
    from syft_ingest.sources.brightdata import (
        BrightDataFetcher,
        _classify_brightdata_error,
        _download_snapshot_data,
    )

    raw_data = await _download_snapshot_data(
        snapshot_id,
        platform_name=platform,
        cancel_callback=cancel_callback,
        status_callback=status_callback,
        wait_for_ready=True,
    )

    # Error-shaped responses look enough like posts to slip past the permissive
    # parsers — classify before parsing so a bot challenge / scrape failure
    # surfaces as a typed error, not a nonsense one-item Corpus.
    _classify_brightdata_error(
        raw_data, platform_name=platform, snapshot_id=snapshot_id
    )

    # _parse_response is stateless; the token was already required by the
    # download above, so constructing the fetcher here cannot fail for auth.
    items = BrightDataFetcher()._parse_response(raw_data, platform, {})
    if not items:
        raise FetchEmptyResultError(
            f"Snapshot {snapshot_id} downloaded but contained no content items",
            platform=platform,
        )

    corpus = Corpus(person="")
    corpus.add(items)
    return corpus


async def cancel(snapshot_id: str, platform: str | None = None) -> None:
    """Cancel a running snapshot upstream. Thin wrapper over ``_cancel_snapshot``.

    Best-effort and idempotent: cancelling an already-terminal snapshot is a
    no-op upstream and never raises (the underlying helper logs and swallows
    HTTP errors). ``platform`` is accepted for call-site symmetry with
    ``download_snapshot`` / ``attach`` but is unused — BrightData's cancel
    endpoint is keyed only by snapshot id.
    """
    from syft_ingest.sources.brightdata import _cancel_snapshot

    await _cancel_snapshot(snapshot_id)


# --- Signposts: planned lifecycle steps. Raise loudly so nobody half-uses them. ---


async def trigger(platform: str, urls: list[str], **config) -> SnapshotHandle:
    """Create a snapshot and return its id immediately, without polling/downloading.

    Future: lets a caller persist ``snapshot_id`` before any long wait, so a
    crash mid-collection is resumable. Use ``gather()`` until this lands.
    """
    raise NotImplementedError(
        "trigger() is a planned lifecycle step; use gather()/async_gather() for now"
    )


async def poll_status(handle: SnapshotHandle) -> str:
    """Return remote status ('collecting'|'digesting'|'ready'|'failed') without
    downloading. Future: lets the caller own the poll loop + heartbeat cadence.
    """
    raise NotImplementedError(
        "poll_status() is a planned lifecycle step; gather() polls internally for now"
    )


async def attach(platform: str, snapshot_id: str) -> SnapshotHandle:
    """Rebuild a handle from a persisted snapshot_id (sugar over passing raw ids).

    Future: pairs with poll_status()/download_snapshot() for full step-by-step drive.
    """
    raise NotImplementedError(
        "attach() is a planned lifecycle step; pass (platform, snapshot_id) to "
        "download_snapshot() directly for now"
    )
