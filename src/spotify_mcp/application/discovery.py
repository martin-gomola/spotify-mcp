"""Read-only Spotify discovery use cases over current Web API endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.links import SpotifyEntityType, spotify_web_url

SearchType = Literal["track", "album", "artist", "playlist", "episode", "show"]
TimeRange = Literal["short_term", "medium_term", "long_term"]


class Model(BaseModel):
    """Strictly typed output while tolerating Spotify response additions."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class Track(Model):
    id: str
    name: str
    uri: str | None = None
    spotify_url: str | None = None
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    popularity: int | None = None


class Artist(Model):
    id: str
    name: str
    uri: str | None = None
    spotify_url: str | None = None
    genres: list[str] | None = None
    popularity: int | None = None


class SearchItem(Model):
    type: SearchType
    id: str
    name: str
    uri: str | None = None
    spotify_url: str | None = None
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    owner: str | None = None
    description: str | None = None
    publisher: str | None = None
    duration_ms: int | None = None
    release_date: str | None = None
    total_episodes: int | None = None
    item_count: int | None = None
    genres: list[str] | None = None
    popularity: int | None = None


class SearchResults(Model):
    query: str
    type: SearchType
    total: int
    offset: int
    items: list[SearchItem]


class RecentTrack(Track):
    played_at: str | None = None


class RecentTracks(Model):
    tracks: list[RecentTrack]


class TopTracks(Model):
    time_range: TimeRange
    tracks: list[Track]


class TopArtists(Model):
    time_range: TimeRange
    artists: list[Artist]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    raw = _mapping(value).get("items")
    return list(raw) if isinstance(raw, list) else []


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _artist_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for item in value if (name := _string(_mapping(item).get("name")))]


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]


def _spotify_url(item: Mapping[str, Any], item_type: SpotifyEntityType, item_id: str) -> str:
    external_url = _string(_mapping(item.get("external_urls")).get("spotify"))
    return spotify_web_url(item_type, item_id, external_url=external_url)


def _track(value: Any) -> Track | None:
    item = _mapping(value)
    track_id = _string(item.get("id"))
    name = _string(item.get("name"))
    if track_id is None or name is None:
        return None
    return Track(
        id=track_id,
        name=name,
        uri=_string(item.get("uri")),
        spotify_url=_spotify_url(item, "track", track_id),
        artists=_artist_names(item.get("artists")),
        album=_string(_mapping(item.get("album")).get("name")),
        duration_ms=_integer(item.get("duration_ms")),
        explicit=_boolean(item.get("explicit")),
        popularity=_integer(item.get("popularity")),
    )


def _artist(value: Any) -> Artist | None:
    item = _mapping(value)
    artist_id = _string(item.get("id"))
    name = _string(item.get("name"))
    if artist_id is None or name is None:
        return None
    return Artist(
        id=artist_id,
        name=name,
        uri=_string(item.get("uri")),
        spotify_url=_spotify_url(item, "artist", artist_id),
        genres=_string_list(item.get("genres")),
        popularity=_integer(item.get("popularity")),
    )


class DiscoveryService:
    """Discovery operations with transport-independent typed results."""

    def __init__(self, spotify: SpotifyGateway) -> None:
        self._spotify = spotify

    async def search(
        self,
        query: str,
        item_type: SearchType,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResults:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        payload = _mapping(
            await self._spotify.request(
                "GET",
                "/search",
                params={
                    "q": query,
                    "type": item_type,
                    "limit": limit,
                    "offset": offset,
                    "market": "from_token",
                },
            )
        )
        page = _mapping(payload.get(f"{item_type}s"))
        items = [
            parsed
            for raw in _items(page)
            if (parsed := self._search_item(item_type, raw)) is not None
        ]
        total = _integer(page.get("total"))
        return SearchResults(
            query=query,
            type=item_type,
            total=total if total is not None else len(items),
            offset=offset,
            items=items,
        )

    async def recently_played(self, *, limit: int = 20) -> RecentTracks:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        payload = await self._spotify.request(
            "GET", "/me/player/recently-played", params={"limit": limit}
        )
        tracks: list[RecentTrack] = []
        for entry_value in _items(payload):
            entry = _mapping(entry_value)
            track = _track(entry.get("track"))
            if track is not None:
                tracks.append(
                    RecentTrack(**track.model_dump(), played_at=_string(entry.get("played_at")))
                )
        return RecentTracks(tracks=tracks)

    async def top_tracks(
        self, *, time_range: TimeRange = "medium_term", limit: int = 20
    ) -> TopTracks:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        payload = await self._spotify.request(
            "GET",
            "/me/top/tracks",
            params={"time_range": time_range, "limit": limit},
        )
        tracks = [track for item in _items(payload) if (track := _track(item)) is not None]
        return TopTracks(time_range=time_range, tracks=tracks)

    async def top_artists(
        self, *, time_range: TimeRange = "medium_term", limit: int = 20
    ) -> TopArtists:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        payload = await self._spotify.request(
            "GET",
            "/me/top/artists",
            params={"time_range": time_range, "limit": limit},
        )
        artists = [artist for item in _items(payload) if (artist := _artist(item)) is not None]
        return TopArtists(time_range=time_range, artists=artists)

    @staticmethod
    def _search_item(item_type: SearchType, value: Any) -> SearchItem | None:
        item = _mapping(value)
        item_id = _string(item.get("id"))
        name = _string(item.get("name"))
        if item_id is None or name is None:
            return None

        item_count = _integer(_mapping(item.get("items")).get("total"))
        if item_count is None:
            item_count = _integer(_mapping(item.get("tracks")).get("total"))
        return SearchItem(
            type=item_type,
            id=item_id,
            name=name,
            uri=_string(item.get("uri")),
            spotify_url=_spotify_url(item, item_type, item_id),
            artists=_artist_names(item.get("artists")),
            album=_string(_mapping(item.get("album")).get("name")),
            owner=_string(_mapping(item.get("owner")).get("display_name")),
            description=_string(item.get("description")),
            publisher=_string(item.get("publisher")),
            duration_ms=_integer(item.get("duration_ms")),
            release_date=_string(item.get("release_date")),
            total_episodes=_integer(item.get("total_episodes")),
            item_count=item_count,
            genres=_string_list(item.get("genres")),
            popularity=_integer(item.get("popularity")),
        )
