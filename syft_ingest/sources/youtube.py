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

import asyncio
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

    The fetch() method is synchronous (matching the ContentFetcher protocol),
    but internally uses async/await via asyncio.run().

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
            "socket_timeout": 30,
            "playlistend": 50,
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
        """Synchronous wrapper for async _fetch_async.

        Runs the async method using asyncio.run(). This bridges the
        ContentFetcher protocol (sync) with the async implementation.

        Args:
            request: Fetch request with platform, URLs, and config.

        Returns:
            FetchResult with items and optional artifact_paths.

        Raises:
            FetchAuthError: Age-restricted or private video.
            FetchEmptyResultError: Video not found.
            FetchTimeoutError: Request timeout exceeded.
            FetchError: Generic extraction failure.
        """
        return asyncio.run(self._fetch_async(request))

    async def _fetch_async(self, request: FetchRequest) -> FetchResult:
        """Fetch and extract metadata for YouTube videos or channels.

        Detects channel/playlist URLs and enumerates videos, or processes single videos.
        Optionally downloads videos if config['download_full_video'] and output_dir set.

        Steps:
        1. Check if first URL is channel/playlist (heuristic: /channel/, /@, /playlist, /c/)
        2. If channel: enumerate videos, extract metadata for each
        3. If single video: extract metadata for all provided URLs
        4. Optionally download if enabled and output_dir provided
        5. Return FetchResult with items and artifact_paths

        Args:
            request: FetchRequest with urls, output_dir, and config.

        Returns:
            FetchResult with extracted VideoResult items and artifact_paths.

        Raises:
            FetchAuthError, FetchEmptyResultError, FetchError as appropriate.
        """
        items: list[VideoResult] = []
        artifact_paths: dict[str, Path] = {}
        output_dir = request.output_dir
        download_enabled = self._config.get("download_full_video", False)

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
                video_urls = await self._enumerate_channel(
                    first_url, limit=self._config.get("playlistend", 50)
                )
                logger.info("Enumerated {n} videos from channel", n=len(video_urls))

                # Extract metadata for each video
                for video_url in video_urls:
                    try:
                        video_result = await self._extract_video_info(
                            video_url, download=download_enabled
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
            else:
                logger.info(
                    "Single video URL(s): processing {n} URLs", n=len(request.urls)
                )
                # Single video: extract metadata for each URL
                for video_url in request.urls:
                    try:
                        video_result = await self._extract_video_info(
                            video_url, download=download_enabled
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
            logger.error("Unexpected error in _fetch_async: {error}", error=e)
            raise FetchError(f"Unexpected error: {str(e)}", platform="youtube") from e

        # Raise FetchEmptyResultError if no items extracted
        if not items:
            raise FetchEmptyResultError(
                "No content items found for URL(s)",
                platform="youtube",
            )

        # Build response with content hashes
        content_hashes = {
            item.url or item.title: hashlib.sha256(item.title.encode()).hexdigest()
            for item in items
        }

        return FetchResult(
            items=items,
            rows_fetched=len(items),
            artifact_paths=artifact_paths,
            fetched_at=datetime.now(UTC),
            content_hashes=content_hashes,
        )

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

    async def _enumerate_channel(self, channel_url: str, limit: int = 50) -> list[str]:
        """Enumerate video URLs from a channel/playlist using extract_flat.

        Uses yt-dlp's extract_flat=True for fast enumeration without downloading.
        Respects playlistend config for limiting results.

        Args:
            channel_url: YouTube channel or playlist URL
            limit: Max videos to enumerate (default 50)

        Returns:
            List of full video URLs

        Raises:
            FetchError: If enumeration fails
        """
        logger.debug(
            "Enumerating channel with limit={limit}",
            limit=limit,
        )

        try:
            ydl_opts = {
                "socket_timeout": self._config.get("socket_timeout", 30),
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

            video_urls = []
            for entry in info["entries"]:
                if entry and "url" in entry:
                    video_urls.append(entry["url"])
                elif entry and "id" in entry:
                    # Fallback: construct URL from ID
                    video_urls.append(f"https://www.youtube.com/watch?v={entry['id']}")

            logger.info(
                "Enumerated {n} videos from channel",
                n=len(video_urls),
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

    async def _extract_video_info(
        self, video_url: str, download: bool = False
    ) -> VideoResult | None:
        """Extract metadata from a single YouTube video.

        Uses yt-dlp to extract structured metadata from the video,
        then maps it to a VideoResult model. Optionally downloads the video
        if download=True and config['download_full_video']=True.

        Args:
            video_url: YouTube video URL.
            download: If True and config['download_full_video']=True, attempt download.

        Returns:
            VideoResult with extracted metadata, or None if not found.

        Raises:
            FetchAuthError: Age-restricted or private video.
            FetchEmptyResultError: Video not found.
            FetchTimeoutError: Request timeout.
            FetchError: Generic extraction failure.
        """
        logger.debug("Extracting metadata for {url}", url=video_url)

        try:
            # Configure yt-dlp options
            ydl_opts = {
                "socket_timeout": self._config.get("socket_timeout", 30),
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
            }

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

            # Build metadata dict
            metadata = {
                "source_id": source_id,
                "like_count": like_count,
                "thumbnail_url": thumbnail_url,
            }

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
            )

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

    async def _download_video(self, video_url: str, output_dir: Path) -> Path:
        """Download a video with best video+audio combo.

        Creates output_dir if it doesn't exist. Uses yt-dlp's format selection
        to get the best quality video+audio combination.

        Args:
            video_url: YouTube video URL
            output_dir: Directory to save video file

        Returns:
            Path to downloaded file

        Raises:
            FetchError: If download fails
        """
        logger.info("Downloading video: {url}", url=video_url)

        try:
            # Create output directory if needed
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.debug("Output directory ready: {path}", path=output_dir)

            ydl_opts = {
                "socket_timeout": self._config.get("socket_timeout", 30),
                "format": "bestvideo+bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            # Construct expected output path
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                extracted = ydl.extract_info(video_url, download=False)
                video_id = extracted.get("id")
                ext = extracted.get("ext", "mp4")

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
