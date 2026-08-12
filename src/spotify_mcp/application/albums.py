"""Album catalog and saved-album use cases over Spotify's current API."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.errors import SpotifyRequestError
from spotify_mcp.domain.links import spotify_web_url

MAX_ALBUM_LOOKUPS = 20
MAX_PAGE_SIZE = 50
LOOKUP_CONCURRENCY = 5


class Album(BaseModel):
    id: str
    uri: str | None = None
    spotify_url: str | None = None
    name: str
    artists: list[str] = Field(default_factory=list)
    album_type: str | None = None
    release_date: str | None = None
    total_tracks: int | None = Field(default=None, ge=0)
    external_url: str | None = None


class AlbumsResult(BaseModel):
    requested_ids: list[str]
    albums: list[Album]
    missing_ids: list[str]


class AlbumTrack(BaseModel):
    id: str
    uri: str | None = None
    spotify_url: str | None = None
    name: str
    artists: list[str] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)
    disc_number: int | None = Field(default=None, ge=1)
    track_number: int | None = Field(default=None, ge=1)
    explicit: bool | None = None


class AlbumTracksPage(BaseModel):
    album_id: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    tracks: list[AlbumTrack]


class SavedAlbum(BaseModel):
    added_at: str | None = None
    album: Album


class SavedAlbumsPage(BaseModel):
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    albums: list[SavedAlbum]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _artist_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for raw in value if (name := _string(_mapping(raw).get("name"))) is not None]


def _normalise_ids(values: Iterable[str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = value.strip().removeprefix("spotify:album:")
        if candidate and candidate not in seen:
            ids.append(candidate)
            seen.add(candidate)
    return ids


def _validated_ids(values: Iterable[str], *, maximum: int) -> list[str]:
    ids = _normalise_ids(values)
    if not ids:
        raise ValueError("at least one album ID is required")
    if len(ids) > maximum:
        raise ValueError(f"at most {maximum} album IDs are allowed")
    return ids


def _album(value: Any) -> Album | None:
    data = _mapping(value)
    album_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if album_id is None or name is None:
        return None
    total_tracks = _integer(data.get("total_tracks"))
    external_urls = _mapping(data.get("external_urls"))
    return Album(
        id=album_id,
        uri=_string(data.get("uri")),
        spotify_url=spotify_web_url(
            "album", album_id, external_url=_string(external_urls.get("spotify"))
        ),
        name=name,
        artists=_artist_names(data.get("artists")),
        album_type=_string(data.get("album_type")),
        release_date=_string(data.get("release_date")),
        total_tracks=total_tracks if total_tracks is None or total_tracks >= 0 else None,
        external_url=_string(external_urls.get("spotify")),
    )


def _album_track(value: Any) -> AlbumTrack | None:
    data = _mapping(value)
    track_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if track_id is None or name is None:
        return None
    duration_ms = _integer(data.get("duration_ms"))
    disc_number = _integer(data.get("disc_number"))
    track_number = _integer(data.get("track_number"))
    explicit = data.get("explicit")
    external_urls = _mapping(data.get("external_urls"))
    return AlbumTrack(
        id=track_id,
        uri=_string(data.get("uri")),
        spotify_url=spotify_web_url(
            "track", track_id, external_url=_string(external_urls.get("spotify"))
        ),
        name=name,
        artists=_artist_names(data.get("artists")),
        duration_ms=duration_ms if duration_ms is None or duration_ms >= 0 else None,
        disc_number=disc_number if disc_number is not None and disc_number >= 1 else None,
        track_number=track_number if track_number is not None and track_number >= 1 else None,
        explicit=explicit if isinstance(explicit, bool) else None,
    )


async def get_albums(spotify: SpotifyGateway, album_ids: Sequence[str]) -> AlbumsResult:
    """Fetch albums individually because Spotify removed the batch endpoint."""

    ids = _validated_ids(album_ids, maximum=MAX_ALBUM_LOOKUPS)
    semaphore = asyncio.Semaphore(LOOKUP_CONCURRENCY)

    async def read(album_id: str) -> tuple[str, Album | None]:
        async with semaphore:
            try:
                raw = await spotify.request("GET", f"/albums/{album_id}")
            except SpotifyRequestError as exc:
                if exc.status_code == 404:
                    return album_id, None
                raise
        return album_id, _album(raw)

    responses = await asyncio.gather(*(read(album_id) for album_id in ids))
    albums = [album for _, album in responses if album is not None]
    missing = [album_id for album_id, album in responses if album is None]
    return AlbumsResult(requested_ids=ids, albums=albums, missing_ids=missing)


async def get_album_tracks(
    spotify: SpotifyGateway,
    album_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> AlbumTracksPage:
    ids = _validated_ids([album_id], maximum=1)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    exact_id = ids[0]
    page = _mapping(
        await spotify.request(
            "GET", f"/albums/{exact_id}/tracks", params={"limit": limit, "offset": offset}
        )
    )
    raw_items = page.get("items")
    tracks = (
        [track for raw in raw_items if (track := _album_track(raw)) is not None]
        if isinstance(raw_items, list)
        else []
    )
    raw_total = _integer(page.get("total"))
    return AlbumTracksPage(
        album_id=exact_id,
        total=raw_total if raw_total is not None and raw_total >= 0 else len(tracks),
        offset=offset,
        tracks=tracks,
    )


async def get_saved_albums(
    spotify: SpotifyGateway, *, limit: int = 20, offset: int = 0
) -> SavedAlbumsPage:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    page = _mapping(
        await spotify.request("GET", "/me/albums", params={"limit": limit, "offset": offset})
    )
    raw_items = page.get("items")
    albums: list[SavedAlbum] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            entry = _mapping(raw)
            album = _album(entry.get("album"))
            if album is not None:
                albums.append(SavedAlbum(added_at=_string(entry.get("added_at")), album=album))
    raw_total = _integer(page.get("total"))
    return SavedAlbumsPage(
        total=raw_total if raw_total is not None and raw_total >= 0 else len(albums),
        offset=offset,
        albums=albums,
    )
