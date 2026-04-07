from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


@runtime_checkable
class SourceSpec(Protocol):
    """Protocol for all source specifications.

    Any new source kind (e.g. YouTube channel, podcast RSS) must satisfy this
    protocol so that ``gather()`` can dispatch on it without isinstance checks
    against concrete types.
    """

    kind: str
    raw_dirs: list[str]


class SocialProfileSource(BaseModel):
    """Typed source spec for a creator-owned social profile export."""

    kind: Literal["social_profile"] = "social_profile"
    platform: Literal["facebook", "instagram"]
    extractor: str = "brightdata"
    raw_dirs: list[str] = Field(min_length=1)
    handle: str | None = None
    profile_url: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    external_account_id: str | None = None
    display_name: str | None = None
    source_slug: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "SocialProfileSource":
        if not self.handle and not self.profile_url:
            raise ValueError("SocialProfileSource requires handle or profile_url")
        return self
