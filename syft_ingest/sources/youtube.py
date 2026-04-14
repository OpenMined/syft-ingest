"""yt-dlp based YouTube content fetcher for single-video and channel extraction.

Implements ContentFetcher for YouTube videos and channels via the yt-dlp library.
Handles single-video metadata extraction, channel enumeration, and optional download.

Supports:
- Single video metadata extraction (Plan 03-01)
- Channel/playlist enumeration with configurable limits (Plan 03-02)
- Optional full video+audio download (Plan 03-02)

Exceptions from yt-dlp are wrapped in domain-specific FetchError subclasses:
- FetchAuthError: Age-restricted or private videos
- FetchEmptyResultError: Video not found
- FetchTimeoutError: Request timeout exceeded
"""

from __future__ import annotations

import hashlib
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from syft_ingest.core.fetcher import (
    FetchAuthError,
    FetchEmptyResultError,
    FetchError,
    FetchRequest,
    FetchResult,
    FetchTimeoutError,
)
from syft_ingest.core.models import SourceType, VideoResult

# Constants
DEFAULT_SOCKET_TIMEOUT = 30
DEFAULT_PLAYLIST_LIMIT = 50

# Import yt-dlp
try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError as e:
    raise ImportError("yt-dlp SDK not installed.") from e


class YtDlpFetcher:
    """Strategy fetcher for YouTube videos via yt-dlp.

    Implements the ContentFetcher protocol. Handles:
    1. Single video metadata extraction (Plan 03-01)
    2. Channel/playlist enumeration (Plan 03-02)
    3. Optional full video+audio download (Plan 03-02)

    All methods are synchronous — yt-dlp is a sync-native library.
    Async callers should use asyncio.to_thread(fetcher.fetch, request).

    Attributes:
        _config: Configuration dict with socket_timeout, playlistend, download_full_video.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the fetcher with optional configuration.

        Args:
            config: Optional configuration dict with keys like socket_timeout (int, default 30).
                   Any provided config is merged with defaults.
        """
        # Default config
        defaults = {
            "socket_timeout": DEFAULT_SOCKET_TIMEOUT,
            "playlistend": DEFAULT_PLAYLIST_LIMIT,
            "download_full_video": False,
        }

        # Merge user config into defaults
        if config:
            defaults.update(config)

        self._config = defaults
        logger.debug(
            "YtDlpFetcher initialized with config: {config}", config=self._config
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch and extract metadata for YouTube videos or channels.

        Detects channel/playlist URLs and enumerates videos, or processes single videos.
        Optionally downloads videos if config['download_full_video'] and output_dir set.

        Steps:
        1. Merge request.config into effective config (per-request overrides)
        2. Check if first URL is channel/playlist (heuristic: /channel/, /@, /playlist, /c/)
        3. If channel: enumerate videos, extract metadata for each
        4. If single video: extract metadata for all provided URLs
        5. Optionally download if enabled and output_dir provided
        6. Return FetchResult with items and artifact_paths

        Args:
            request: FetchRequest with urls, output_dir, and config.

        Returns:
            FetchResult with extracted VideoResult items and artifact_paths.

        Raises:
            FetchAuthError: Age-restricted or private video.
            FetchEmptyResultError: Video not found.
            FetchTimeoutError: Request timeout exceeded.
            FetchError: Generic extraction failure.
        """
        items: list[VideoResult] = []
        artifact_paths: dict[str, Path] = {}
        output_dir = request.output_dir
        first_error: FetchError | None = (
            None  # Track first error for later re-raise if needed
        )

        # Merge request.config into effective config (per-request overrides take precedence)
        effective_config = {**self._config, **request.config}
        download_enabled = effective_config.get("download_full_video", False)

        logger.info(
            "Fetching {n} YouTube URL(s)",
            n=len(request.urls),
        )

        # Check if first URL is a channel/playlist
        first_url = request.urls[0]
        is_channel = self._is_channel_url(first_url)

        try:
            if is_channel:
                logger.info("Detected channel/playlist URL: {url}", url=first_url)
                # Enumerate videos from channel
                video_urls = self._enumerate_channel(
                    first_url,
                    limit=effective_config.get("playlistend", DEFAULT_PLAYLIST_LIMIT),
                    config=effective_config,
                    start_date=request.start_date,
                )
                logger.info("Enumerated {n} videos from channel", n=len(video_urls))

                # Extract metadata for each video
                for video_url in video_urls:
                    try:
                        video_result = self._extract_video_info_and_captions(
                            video_url,
                            download=download_enabled,
                            output_dir=output_dir,
                            config=effective_config,
                        )
                        if video_result:
                            items.append(video_result)

                            # Track downloaded files
                            if (
                                download_enabled
                                and output_dir
                                and "video_file_path" in video_result.metadata
                            ):
                                file_path = Path(
                                    video_result.metadata["video_file_path"]
                                )
                                video_id = video_result.metadata.get("source_id", "")
                                artifact_paths[video_id] = file_path

                    except FetchAuthError as e:
                        # Some videos may be unavailable (age-restricted, private)
                        if not first_error:
                            first_error = e
                        logger.warning(
                            "Skipping video {url}: {error}",
                            url=video_url,
                            error=e,
                        )
                    except FetchEmptyResultError as e:
                        if not first_error:
                            first_error = e
                        logger.warning(
                            "Video not found {url}: {error}",
                            url=video_url,
                            error=e,
                        )
                    except FetchError as e:
                        if not first_error:
                            first_error = e
                        logger.warning(
                            "Error fetching {url}: {error}",
                            url=video_url,
                            error=e,
                        )
            else:
                logger.info(
                    "Single video URL(s): processing {n} URLs", n=len(request.urls)
                )
                # Single video: extract metadata for each URL
                for video_url in request.urls:
                    try:
                        video_result = self._extract_video_info_and_captions(
                            video_url,
                            download=download_enabled,
                            output_dir=output_dir,
                            config=effective_config,
                        )
                        if video_result:
                            items.append(video_result)

                            # Track downloaded file if applicable
                            if (
                                download_enabled
                                and output_dir
                                and "video_file_path" in video_result.metadata
                            ):
                                file_path = Path(
                                    video_result.metadata["video_file_path"]
                                )
                                video_id = video_result.metadata.get("source_id", "")
                                artifact_paths[video_id] = file_path

                    except FetchAuthError as e:
                        logger.warning(
                            "Skipping video {url}: {error}",
                            url=video_url,
                            error=e,
                        )
                    except FetchEmptyResultError as e:
                        logger.warning(
                            "Video not found {url}: {error}",
                            url=video_url,
                            error=e,
                        )
                    except FetchError as e:
                        logger.warning(
                            "Error fetching {url}: {error}",
                            url=video_url,
                            error=e,
                        )

        except FetchError:
            # Re-raise our domain errors
            raise
        except Exception as e:
            # Log unexpected errors
            logger.error("Unexpected error in fetch: {error}", error=e)
            raise FetchError(f"Unexpected error: {str(e)}", platform="youtube") from e

        # Raise FetchEmptyResultError if no items extracted
        if not items:
            raise FetchEmptyResultError(
                "No content items found for URL(s)",
                platform="youtube",
            )

        # Build response with proper content hashes (Phase 6 deduplication)
        # Hash includes video ID + title + text to prevent false-positive deduplication
        content_hashes = {}
        for item in items:
            video_id = item.metadata.get("source_id", "unknown")
            hash_input = f"{video_id}:{item.title}:{item.text}"
            content_hashes[item.url or item.title] = hashlib.sha256(
                hash_input.encode()
            ).hexdigest()

        return FetchResult(
            items=items,
            rows_fetched=len(items),
            artifact_paths=artifact_paths,
            fetched_at=datetime.now(UTC),
            content_hashes=content_hashes,
        )

    @staticmethod
    def _to_ytdlp_date(date_str: str | None) -> str | None:
        """Convert ISO 8601 date string to yt-dlp dateafter format.

        yt-dlp's dateafter option expects YYYYMMDD (no dashes).

        Args:
            date_str: Date in "YYYY-MM-DD" format, or None.

        Returns:
            Date in "YYYYMMDD" format, or None if input is None.

        Raises:
            ValueError: If date_str is not valid YYYY-MM-DD format.
        """
        if date_str is None:
            return None
        from datetime import datetime as dt

        # Validate strict YYYY-MM-DD format
        dt.strptime(date_str, "%Y-%m-%d")
        return date_str.replace("-", "")

    def _is_channel_url(self, url: str) -> bool:
        """Detect if URL is a channel/playlist (not a single video).

        Heuristics:
        - Contains /channel/ → channel URL
        - Contains /@ → handle URL
        - Contains /playlist → playlist URL
        - Contains /c/ → custom URL

        Args:
            url: YouTube URL to check

        Returns:
            True if channel/playlist, False if single video
        """
        return any(
            pattern in url for pattern in ["/channel/", "/@", "/playlist", "/c/"]
        )

    def _enumerate_channel(
        self,
        channel_url: str,
        limit: int = DEFAULT_PLAYLIST_LIMIT,
        config: dict | None = None,
        start_date: str | None = None,
    ) -> list[str]:
        """Enumerate video URLs from a channel/playlist using extract_flat.

        Uses yt-dlp's extract_flat=True for fast enumeration without downloading.
        Respects playlistend config for limiting results.

        Args:
            channel_url: YouTube channel or playlist URL
            limit: Max videos to enumerate (default DEFAULT_PLAYLIST_LIMIT)
            config: Optional config dict (uses self._config if not provided)
            start_date: ISO 8601 date string ("YYYY-MM-DD"). When provided,
                only videos published on or after this date are enumerated.

        Returns:
            List of full video URLs

        Raises:
            FetchError: If enumeration fails
        """
        logger.debug(
            "Enumerating channel with limit={limit}, start_date={start_date}",
            limit=limit,
            start_date=start_date,
        )

        # Use provided config or fall back to instance config
        effective_config = config or self._config

        try:
            ydl_opts = {
                "socket_timeout": effective_config.get(
                    "socket_timeout", DEFAULT_SOCKET_TIMEOUT
                ),
                "extract_flat": True,
                "quiet": True,
                "no_warnings": True,
                "playlistend": limit,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            # Extract video URLs from entries
            if not info or "entries" not in info:
                raise FetchError(
                    "No entries found in channel response",
                    platform="youtube",
                )

            # Filter by start_date in our code (yt-dlp's dateafter
            # doesn't work with extract_flat/download=False)
            cutoff = self._to_ytdlp_date(start_date)  # "YYYYMMDD" or None

            video_urls = []
            for entry in info["entries"]:
                if not entry:
                    continue

                # Skip videos older than start_date
                if cutoff and entry.get("upload_date"):
                    if entry["upload_date"] < cutoff:
                        continue

                if "url" in entry:
                    video_urls.append(entry["url"])
                elif "id" in entry:
                    video_urls.append(f"https://www.youtube.com/watch?v={entry['id']}")

            logger.info(
                "Enumerated {n} videos from channel{filter_msg}",
                n=len(video_urls),
                filter_msg=f" (after {start_date})" if start_date else "",
            )
            return video_urls

        except FetchError:
            raise
        except Exception as e:
            logger.error(
                "Failed to enumerate channel: {error}",
                error=e,
            )
            raise FetchError(
                f"Failed to enumerate channel: {str(e)}",
                platform="youtube",
            ) from e

    def _extract_video_info_and_captions(
        self,
        video_url: str,
        download: bool = False,
        output_dir: Path | None = None,
        config: dict | None = None,
    ) -> VideoResult | None:
        """Extract video metadata and captions from a single YouTube video.

        PRIMARY ACQUISITION METHOD: Extracts captions/subtitles with timestamps from the video.
        Uses yt-dlp to fetch structured metadata (title, description, duration, view count, etc.),
        then extracts available captions with precise timestamps. Maps all extracted content to
        a VideoResult model.

        Reuses subtitles from initial metadata extraction to avoid redundant API calls and ensure
        timestamp accuracy (captions extracted during metadata fetch are most reliable).

        OPTIONAL: Downloads the full video+audio if download=True and
        config['download_full_video']=True (advanced feature, off by default).

        Args:
            video_url: YouTube video URL.
            download: If True and config['download_full_video']=True, attempt download.
            output_dir: Directory to save downloaded video (required if download=True).
            config: Optional config dict (uses self._config if not provided).

        Returns:
            VideoResult with video metadata + extracted captions (with timestamps), or None if not found.

        Raises:
            FetchAuthError: Age-restricted or private video.
            FetchEmptyResultError: Video not found.
            FetchTimeoutError: Request timeout.
            FetchError: Generic extraction failure.
        """
        logger.debug("Extracting metadata for {url}", url=video_url)

        # Use provided config or fall back to instance config
        effective_config = config or self._config

        try:
            # Configure yt-dlp options for metadata + subtitle extraction
            ydl_opts = {
                "socket_timeout": effective_config.get(
                    "socket_timeout", DEFAULT_SOCKET_TIMEOUT
                ),
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitlesformat": "vtt",
                "subtitleslangs": effective_config.get("subtitleslangs", ["en"]),
                "extractor_args": {
                    "youtube": {"player_client": ["android", "web"]},
                },
            }

            # NOTE: dateafter doesn't work with download=False.
            # Date filtering is done in _enumerate_channel() instead.

            # Extract metadata using yt-dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)

            # Extract fields from info dict
            title = info.get("title", "Unknown")
            description = info.get("description", "")
            author = info.get("uploader", "Unknown")
            duration_seconds = info.get("duration")
            view_count = info.get("view_count")
            like_count = info.get("like_count")
            thumbnail_url = info.get("thumbnail")
            source_id = info.get("id", "unknown")

            # Parse upload date if available
            upload_date_str = info.get("upload_date")
            published_at = None
            if upload_date_str:
                try:
                    # Format: YYYYMMDD
                    published_at = datetime.strptime(upload_date_str, "%Y%m%d").replace(
                        tzinfo=UTC
                    )
                except (ValueError, AttributeError):
                    logger.debug(
                        "Could not parse upload date {date}", date=upload_date_str
                    )

            # Build metadata dict with rich video fields
            metadata = {
                "source_id": source_id,
                "duration_seconds": duration_seconds,
                "view_count": view_count,
                "like_count": like_count,
                "comment_count": info.get("comment_count"),
                "thumbnail_url": thumbnail_url,
                "channel_id": info.get("channel_id"),
                "channel_url": info.get("channel_url"),
                "uploader_id": info.get("uploader_id"),
                "categories": info.get("categories", []),
                "tags": info.get("tags", []),
                "description": (description[:500] if description else ""),
                "language": info.get("language"),
                "availability": info.get("availability"),
                "live_status": info.get("live_status"),
                "age_limit": info.get("age_limit"),
            }

            # Extract captions/subtitles with timestamps.
            # With download=False, yt-dlp returns caption URLs (not text).
            # We fetch the json3 format URL and parse it into segments.
            # Priority: user-created subtitles > automatic captions.
            captions = {}
            caption_langs = effective_config.get("subtitleslangs", ["en"])
            subtitle_sources = info.get("subtitles", {})
            auto_sources = info.get("automatic_captions", {})

            for lang in caption_langs:
                # Try user-created first, then auto-generated
                tracks = subtitle_sources.get(lang, []) or auto_sources.get(lang, [])
                if not tracks:
                    continue
                json3_url = next(
                    (t["url"] for t in tracks if t.get("ext") == "json3"), None
                )
                if json3_url:
                    try:
                        parsed = self._fetch_and_parse_json3(json3_url)
                        if parsed:
                            captions[lang] = parsed
                            logger.debug(
                                "Extracted {n} caption segments for {lang}",
                                n=len(parsed),
                                lang=lang,
                            )
                    except Exception as e:
                        logger.debug(
                            "Could not fetch captions for {lang}: {error}",
                            lang=lang,
                            error=e,
                        )

            # Store captions in metadata
            metadata["captions"] = captions

            # Create VideoResult
            video_result = VideoResult(
                title=title,
                author=author,
                text=description,
                url=video_url,
                source_type=SourceType.YOUTUBE,
                published_at=published_at,
                duration_seconds=duration_seconds,
                view_count=view_count,
                metadata=metadata,
                raw_data=info,
            )

            # Optionally download video if enabled (advanced feature)
            # Note: video download is opt-in, not called by default
            if (
                download
                and effective_config.get("download_full_video", False)
                and output_dir
            ):
                try:
                    file_path = self._download_video(
                        video_url, output_dir, config=effective_config
                    )
                    video_result.metadata["video_file_path"] = str(file_path)
                    logger.info("Downloaded video to {path}", path=file_path)
                except FetchError:
                    raise
                except Exception as e:
                    logger.error(
                        "Download failed for {url}: {error}", url=video_url, error=e
                    )
                    raise FetchError(
                        f"Video download failed: {str(e)}", platform="youtube"
                    ) from e

            logger.debug("Extracted metadata for {title}", title=title)
            return video_result

        except DownloadError as e:
            error_msg = str(e).lower()

            # Age-restricted or private video
            if "not available for users" in error_msg or "age restricted" in error_msg:
                logger.warning("Age-restricted or private video: {url}", url=video_url)
                raise FetchAuthError(
                    f"Age-restricted or private video: {str(e)}", platform="youtube"
                ) from e

            # Video not found
            if "not found" in error_msg:
                logger.warning("Video not found: {url}", url=video_url)
                raise FetchEmptyResultError(
                    f"Video not found: {str(e)}", platform="youtube"
                ) from e

            # Timeout
            if "timeout" in error_msg:
                logger.warning("Timeout fetching {url}", url=video_url)
                raise FetchTimeoutError(
                    f"Timeout fetching video: {str(e)}", platform="youtube"
                ) from e

            # Generic DownloadError
            logger.warning("Download error for {url}: {error}", url=video_url, error=e)
            raise FetchError(f"Download error: {str(e)}", platform="youtube") from e

        except socket.timeout as e:
            logger.warning("Socket timeout for {url}", url=video_url)
            raise FetchTimeoutError(
                f"Socket timeout: {str(e)}", platform="youtube"
            ) from e

        except Exception as e:
            logger.error(
                "Unexpected error extracting {url}: {error}",
                url=video_url,
                error=e,
                exc_info=True,
            )
            raise FetchError(f"Unexpected error: {str(e)}", platform="youtube") from e

    def _fetch_and_parse_json3(self, json3_url: str) -> list[dict]:
        """Fetch a json3 caption URL and parse into segments.

        YouTube's json3 format contains events with segments. Each event has
        tStartMs (start milliseconds) and dDurationMs (duration), with text
        in the segs array.

        Returns:
            List of {"text": str, "start": float, "end": float} dicts.
        """
        import json
        import urllib.request

        data = json.loads(urllib.request.urlopen(json3_url, timeout=15).read())
        segments = []

        for event in data.get("events", []):
            segs = event.get("segs")
            if not segs:
                continue
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if not text:
                continue
            start_ms = event.get("tStartMs", 0)
            dur_ms = event.get("dDurationMs", 0)
            segments.append(
                {
                    "text": text,
                    "start": start_ms / 1000.0,
                    "end": (start_ms + dur_ms) / 1000.0,
                }
            )

        return segments

    def _download_video(
        self, video_url: str, output_dir: Path, config: dict | None = None
    ) -> Path:
        """Download a video with best video+audio combo.

        Creates output_dir if it doesn't exist. Uses yt-dlp's format selection
        to get the best quality video+audio combination.

        Args:
            video_url: YouTube video URL
            output_dir: Directory to save video file
            config: Optional config dict (uses self._config if not provided).

        Returns:
            Path to downloaded file

        Raises:
            FetchError: If download fails
        """
        logger.info("Downloading video: {url}", url=video_url)

        # Use provided config or fall back to instance config
        effective_config = config or self._config

        try:
            # Create output directory if needed
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.debug("Output directory ready: {path}", path=output_dir)

            socket_timeout = effective_config.get(
                "socket_timeout", DEFAULT_SOCKET_TIMEOUT
            )

            # Extract metadata first (respecting socket_timeout) to determine expected filename
            extract_opts = {
                "socket_timeout": socket_timeout,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                extracted = ydl.extract_info(video_url, download=False)
                video_id = extracted.get("id")
                ext = extracted.get("ext", "mp4")

            # Download with the same socket_timeout configuration
            ydl_opts = {
                "socket_timeout": socket_timeout,
                "format": "bestvideo+bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            file_path = output_dir / f"{video_id}.{ext}"

            if file_path.exists():
                logger.info("Download completed: {path}", path=file_path)
                return file_path
            else:
                # Try common extensions
                for ext_try in ["mp4", "mkv", "webm", "flv", "avi"]:
                    alt_path = output_dir / f"{video_id}.{ext_try}"
                    if alt_path.exists():
                        logger.info("Download completed: {path}", path=alt_path)
                        return alt_path

                raise FetchError(
                    f"Downloaded file not found for video {video_id}",
                    platform="youtube",
                )

        except FetchError:
            raise
        except Exception as e:
            logger.error("Download error: {error}", error=e)
            raise FetchError(
                f"Failed to download video: {str(e)}",
                platform="youtube",
            ) from e
