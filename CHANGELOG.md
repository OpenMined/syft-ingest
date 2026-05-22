# Changelog

All notable changes to `syft-ingest` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0]

### Added

- **Snapshot lifecycle entry points** (import from `syft_ingest`):
  - `download_snapshot(platform, snapshot_id, *, cancel_callback=None, status_callback=None)`
    — re-attach to an already-collected BrightData snapshot by id and download
    it into a `Corpus`, with no re-trigger / re-collection / re-bill. Waits past
    a still-collecting snapshot, checks `cancel_callback` between chunks, and
    emits `status_callback` as it progresses.
  - `cancel(snapshot_id, platform=None)` — cancel a running snapshot upstream
    (thin, best-effort, idempotent wrapper over the cancel endpoint).
  - `SnapshotHandle` — a `(platform, snapshot_id)` value object.
  - `trigger` / `poll_status` / `attach` — documented signposts for the full
    step-by-step lifecycle; they raise `NotImplementedError` with guidance until
    a real consumer arrives (use `gather()` / `async_gather()` for now).
- **`SnapshotNotFoundError`** — typed `FetchError` raised when a snapshot id no
  longer exists upstream (expired retention), distinct from
  `FetchEmptyResultError`, so a re-attaching caller can fall back to a fresh
  trigger.

### Changed

- The **initial download** is now cancellable mid-stream for both Facebook and
  Instagram, not just during the poll phase. Both platforms route their download
  through one shared streaming seam (`GET /datasets/v3/snapshot/{id}`, checked
  between chunks); the per-platform trigger is the only platform-specific step,
  so new BrightData sources inherit cancel + resume + chunked download for free.
- Instagram fetching was split from the SDK's opaque combined discovery call
  into trigger → poll → download, matching Facebook. As a result, Instagram now
  also fires `status_callback` transitions during collection.

### Unchanged

- `gather()` / `async_gather()` keep the same signature and trigger→poll→download
  behavior. The empty-vs-error classification (`FetchBotChallengeError` /
  `FetchScrapeFailedError`) is unchanged.

## [0.2.0]

- Prior release (baseline before the snapshot lifecycle work).
