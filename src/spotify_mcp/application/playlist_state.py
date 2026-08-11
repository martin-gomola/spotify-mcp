"""Snapshot-consistent reads of observable Spotify playlist positions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.dj import occurrence_tokens
from spotify_mcp.domain.playlist import PlaylistItemType, PlaylistPosition


@dataclass(frozen=True, slots=True)
class PlaylistState:
    """Every observable playlist position bound to one stable snapshot."""

    playlist_id: str
    name: str
    snapshot_id: str
    positions: tuple[PlaylistPosition, ...]

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(position.position_token for position in self.positions)


async def read_playlist_state(
    spotify: SpotifyGateway,
    playlist_id: str,
) -> PlaylistState:
    """Read fresh metadata and every item, rejecting a snapshot that changes mid-read."""

    metadata = _mapping(await spotify.request("GET", f"playlists/{playlist_id}"), "playlist")
    name = str(metadata.get("name") or "Untitled playlist")
    snapshot_id = _required_string(metadata, "snapshot_id")
    raw_items: list[Mapping[str, Any]] = []
    offset = 0
    while True:
        page = _mapping(
            await spotify.request(
                "GET",
                f"playlists/{playlist_id}/items",
                params={"limit": 50, "offset": offset},
            ),
            "playlist items",
        )
        page_items = page.get("items", [])
        if not isinstance(page_items, list):
            raise ValueError("Spotify playlist items response has invalid items")
        raw_items.extend(_mapping(item, "playlist item") for item in page_items)
        offset += len(page_items)
        total = int(page.get("total", offset))
        if not page_items or offset >= total:
            break

    verified_metadata = _mapping(
        await spotify.request("GET", f"playlists/{playlist_id}"),
        "playlist",
    )
    if _required_string(verified_metadata, "snapshot_id") != snapshot_id:
        raise ValueError("playlist changed while its items were being read")

    identities = tuple(_playlist_identity(item, index) for index, item in enumerate(raw_items))
    tokens = occurrence_tokens(identities)
    positions = tuple(
        _playlist_position(item, index, identities[index], tokens[index])
        for index, item in enumerate(raw_items)
    )
    return PlaylistState(playlist_id, name, snapshot_id, positions)


async def verify_playlist_snapshot(
    spotify: SpotifyGateway,
    playlist_id: str,
    expected_snapshot_id: str,
) -> None:
    """Reject work derived from a playlist snapshot that is no longer current."""

    metadata = _mapping(await spotify.request("GET", f"playlists/{playlist_id}"), "playlist")
    if _required_string(metadata, "snapshot_id") != expected_snapshot_id:
        raise ValueError("playlist changed after its stable state was read")


def _playlist_identity(item: Mapping[str, Any], position: int) -> str:
    subject = _playlist_subject(item)
    return str(subject.get("uri") or subject.get("id") or f"unavailable:{position}")


def _playlist_position(
    item: Mapping[str, Any],
    position: int,
    identity: str,
    token: str,
) -> PlaylistPosition:
    subject = _playlist_subject(item)
    raw_artists = subject.get("artists", [])
    artists = raw_artists if isinstance(raw_artists, list) else []
    item_type = _playlist_item_type(subject)
    track_id = _optional_string(subject.get("id")) if item_type == "track" else None
    return PlaylistPosition(
        position_token=token,
        identity=identity,
        original_position=position,
        track_id=track_id,
        uri=_optional_string(subject.get("uri")),
        name=str(subject.get("name") or "Unknown"),
        artists=tuple(str(artist.get("name")) for artist in artists if isinstance(artist, Mapping)),
        artist_ids=tuple(
            str(artist.get("id"))
            for artist in artists
            if isinstance(artist, Mapping) and artist.get("id")
        ),
        duration_ms=_optional_non_negative_int(subject.get("duration_ms")),
        item_type=item_type,
        fixed=item_type != "track" or track_id is None,
    )


def _playlist_subject(item: Mapping[str, Any]) -> Mapping[str, Any]:
    subject = item.get("item", item.get("track", item))
    return _mapping(subject, "playlist subject")


def _playlist_item_type(subject: Mapping[str, Any]) -> PlaylistItemType:
    uri = _optional_string(subject.get("uri"))
    if subject.get("is_local") is True or (uri is not None and uri.startswith("spotify:local:")):
        return "local"
    raw_type = subject.get("type")
    if raw_type == "episode" or (uri is not None and uri.startswith("spotify:episode:")):
        return "episode"
    if raw_type == "track" or (uri is not None and uri.startswith("spotify:track:")):
        return "track"
    if not uri and not subject.get("id"):
        return "unavailable"
    return "unknown"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Spotify {label} response is invalid")
    return value


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"missing required string: {key}")
    return result


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
