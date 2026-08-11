"""Validated value objects shared by Spotify application use cases."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DomainModel(BaseModel):
    """Base configuration for immutable, forward-compatible domain values."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class Artist(DomainModel):
    """Artist data used by discovery and library workflows."""

    id: NonEmptyStr | None = None
    name: NonEmptyStr
    uri: NonEmptyStr | None = None
    genres: tuple[str, ...] = ()
    popularity: int | None = Field(default=None, ge=0, le=100)


class Track(DomainModel):
    """A playable track, including fields that Spotify may omit by market."""

    id: NonEmptyStr | None = None
    name: NonEmptyStr
    artists: tuple[Artist, ...] = ()
    album_name: str | None = None
    uri: NonEmptyStr | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    explicit: bool | None = None
    popularity: int | None = Field(default=None, ge=0, le=100)
    is_local: bool = False
    is_playable: bool | None = None


class SavedTrack(DomainModel):
    """A track together with its library timestamp."""

    track: Track
    added_at: NonEmptyStr | None = None


class PlaylistOwner(DomainModel):
    """The Spotify account that owns a playlist."""

    id: NonEmptyStr
    display_name: str | None = None


class Playlist(DomainModel):
    """Playlist metadata without coupling to a particular API response shape."""

    id: NonEmptyStr
    name: NonEmptyStr
    description: str = ""
    owner: PlaylistOwner | None = None
    public: bool | None = None
    collaborative: bool = False
    snapshot_id: NonEmptyStr | None = None
    track_count: int | None = Field(default=None, ge=0)
    uri: NonEmptyStr | None = None
    url: NonEmptyStr | None = None


ItemT = TypeVar("ItemT")


class Page(DomainModel, Generic[ItemT]):
    """A normalized offset-based Spotify result page."""

    items: tuple[ItemT, ...] = ()
    total: int = Field(ge=0)
    limit: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_url: str | None = Field(default=None, alias="next")
    previous_url: str | None = Field(default=None, alias="previous")

    @model_validator(mode="after")
    def page_size_fits_limit(self) -> Page[ItemT]:
        if len(self.items) > self.limit:
            raise ValueError("items cannot exceed the declared page limit")
        return self


class WriteState(StrEnum):
    """How confidently a mutating operation reached its intended state."""

    VERIFIED = "verified"
    UNCHANGED = "unchanged"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class WriteStatus(DomainModel):
    """Transport-independent result of a Spotify write and its verification."""

    operation: NonEmptyStr
    state: WriteState
    resource_id: NonEmptyStr | None = None
    snapshot_id: NonEmptyStr | None = None
    changed: bool = False
    mismatches: tuple[str, ...] = ()
    warning: str | None = None

    @model_validator(mode="after")
    def mismatch_has_evidence(self) -> WriteStatus:
        if self.state is WriteState.MISMATCH and not self.mismatches:
            raise ValueError("mismatch results must describe at least one mismatch")
        return self
