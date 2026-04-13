from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    ARXIV = "arxiv"
    WEB = "web"
    PODCAST = "podcast"
    LOCAL = "local"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class ContentItem(BaseModel):
    """Unified content item across all sources."""

    title: str
    author: str
    source_type: SourceType
    url: str | None = None
    text: str
    published_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class VideoResult(ContentItem):
    source_type: SourceType = SourceType.YOUTUBE
    view_count: int | None = None
    transcript: str | None = None
    duration_seconds: int | None = None


class PaperResult(ContentItem):
    source_type: SourceType = SourceType.ARXIV
    abstract: str = ""
    pdf_text: str | None = None
    categories: list[str] = Field(default_factory=list)


class ArticleResult(ContentItem):
    source_type: SourceType = SourceType.WEB
    site_name: str | None = None


class PodcastResult(ContentItem):
    source_type: SourceType = SourceType.PODCAST
    episode_title: str | None = None
    show_name: str | None = None
    transcript: str | None = None
    duration_seconds: int | None = None


class ProfileResult(ContentItem):
    """User profile from social platforms (Instagram, Facebook, TikTok)."""

    source_type: SourceType
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    profile_picture_url: str | None = None
    verified: bool = False
    bio: str = ""


class SocialPostResult(ContentItem):
    """Text or image post from social platforms (Instagram, Facebook)."""

    source_type: SourceType
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    media_urls: list[str] = Field(default_factory=list)
    engagement_rate: float | None = None


class ReelResult(ContentItem):
    """Video content (Reels, Shorts, TikTok videos) from social platforms."""

    source_type: SourceType
    duration_seconds: int | None = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    view_count: int = 0
    media_urls: list[str] = Field(default_factory=list)
    engagement_rate: float | None = None


class Corpus(BaseModel):
    """Collection of content items from multiple sources."""

    person: str
    youtube: list[VideoResult] = Field(default_factory=list)
    tiktok: list[ReelResult] = Field(default_factory=list)
    arxiv: list[PaperResult] = Field(default_factory=list)
    web: list[ArticleResult] = Field(default_factory=list)
    podcast: list[PodcastResult] = Field(default_factory=list)
    facebook: list[SocialPostResult | ReelResult] = Field(default_factory=list)
    instagram: list[ProfileResult | SocialPostResult | ReelResult] = Field(
        default_factory=list
    )
    local: list[ContentItem] = Field(default_factory=list)

    def all_items(self) -> list[ContentItem]:
        return (
            self.youtube
            + self.tiktok
            + self.arxiv
            + self.web
            + self.podcast
            + self.facebook
            + self.instagram
            + self.local
        )

    def add(self, items: list[ContentItem]):
        for item in items:
            getattr(self, item.source_type.value).append(item)

    def export(self, fmt: str, **kwargs):
        from syft_ingest.core.exporters import export

        export(self, fmt, **kwargs)
