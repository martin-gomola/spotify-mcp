"""Compact routed catalog reads over Spotify's current singular endpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.links import spotify_id, spotify_web_url

CatalogRoute = Literal["track", "artist", "artist_albums"]
AlbumGroup = Literal["album", "single", "appears_on", "compilation"]


class CatalogTrack(BaseModel):
    id: str
    name: str
    uri: str | None = None
    spotify_url: str
    image_url: str | None = None
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    explicit: bool | None = None


class CatalogArtist(BaseModel):
    id: str
    name: str
    uri: str | None = None
    spotify_url: str
    image_url: str | None = None
    genres: list[str] | None = None


class ArtistAlbum(BaseModel):
    id: str
    name: str
    uri: str | None = None
    spotify_url: str
    image_url: str | None = None
    artists: list[str] = Field(default_factory=list)
    album_type: str | None = None
    release_date: str | None = None
    total_tracks: int | None = Field(default=None, ge=0)


class ArtistAlbumsPage(BaseModel):
    artist_id: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    items: list[ArtistAlbum]


class CatalogResult(BaseModel):
    route: CatalogRoute
    track: CatalogTrack | None = None
    artist: CatalogArtist | None = None
    albums: ArtistAlbumsPage | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _image_url(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for raw in value:
        url = _string(_mapping(raw).get("url"))
        if url is not None:
            return url
    return None


def _artist_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for raw in value if (name := _string(_mapping(raw).get("name")))]


def _track(value: Any) -> CatalogTrack:
    data = _mapping(value)
    track_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if track_id is None or name is None:
        raise ValueError("Spotify returned malformed track metadata")
    album = _mapping(data.get("album"))
    external_url = _string(_mapping(data.get("external_urls")).get("spotify"))
    return CatalogTrack(
        id=track_id,
        name=name,
        uri=_string(data.get("uri")),
        spotify_url=spotify_web_url("track", track_id, external_url=external_url),
        image_url=_image_url(album.get("images")),
        artists=_artist_names(data.get("artists")),
        album=_string(album.get("name")),
        duration_ms=_integer(data.get("duration_ms")),
        explicit=data.get("explicit") if isinstance(data.get("explicit"), bool) else None,
    )


def _artist(value: Any) -> CatalogArtist:
    data = _mapping(value)
    artist_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if artist_id is None or name is None:
        raise ValueError("Spotify returned malformed artist metadata")
    genres = data.get("genres")
    external_url = _string(_mapping(data.get("external_urls")).get("spotify"))
    return CatalogArtist(
        id=artist_id,
        name=name,
        uri=_string(data.get("uri")),
        spotify_url=spotify_web_url("artist", artist_id, external_url=external_url),
        image_url=_image_url(data.get("images")),
        genres=[genre for genre in genres if isinstance(genre, str)]
        if isinstance(genres, list)
        else None,
    )


def _album(value: Any) -> ArtistAlbum | None:
    data = _mapping(value)
    album_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if album_id is None or name is None:
        return None
    external_url = _string(_mapping(data.get("external_urls")).get("spotify"))
    return ArtistAlbum(
        id=album_id,
        name=name,
        uri=_string(data.get("uri")),
        spotify_url=spotify_web_url("album", album_id, external_url=external_url),
        image_url=_image_url(data.get("images")),
        artists=_artist_names(data.get("artists")),
        album_type=_string(data.get("album_type")),
        release_date=_string(data.get("release_date")),
        total_tracks=_integer(data.get("total_tracks")),
    )


class CatalogService:
    """Dispatch one compact MCP route to supported singular catalog reads."""

    def __init__(self, spotify: SpotifyGateway) -> None:
        self._spotify = spotify

    async def get(
        self,
        route: CatalogRoute,
        entity_id: str,
        *,
        include_groups: Sequence[AlbumGroup] = ("album", "single"),
        limit: int = 10,
        offset: int = 0,
    ) -> CatalogResult:
        if route == "track":
            exact_id = spotify_id("track", entity_id)
            raw = await self._spotify.request(
                "GET", f"/tracks/{exact_id}", params={"market": "from_token"}
            )
            return CatalogResult(route=route, track=_track(raw))
        if route == "artist":
            exact_id = spotify_id("artist", entity_id)
            raw = await self._spotify.request("GET", f"/artists/{exact_id}")
            return CatalogResult(route=route, artist=_artist(raw))

        exact_id = spotify_id("artist", entity_id)
        groups = list(dict.fromkeys(include_groups))
        if not groups:
            raise ValueError("include_groups must contain at least one album group")
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        page = _mapping(
            await self._spotify.request(
                "GET",
                f"/artists/{exact_id}/albums",
                params={
                    "include_groups": ",".join(groups),
                    "market": "from_token",
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        raw_items = page.get("items")
        albums = (
            [album for raw in raw_items if (album := _album(raw)) is not None]
            if isinstance(raw_items, list)
            else []
        )
        return CatalogResult(
            route=route,
            albums=ArtistAlbumsPage(
                artist_id=exact_id,
                total=_integer(page.get("total")) or len(albums),
                offset=offset,
                items=albums,
            ),
        )
