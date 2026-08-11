"""Playlist use cases independent of the MCP transport."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.errors import AmbiguousWrite, SpotifyRequestError
from spotify_mcp.domain.links import SpotifyEntityType, spotify_web_url

MAX_PLAYLIST_ITEMS_PER_WRITE = 100
MAX_PAGE_SIZE = 50
PlaylistUpdateField = Literal["name", "description", "public", "collaborative"]


class PlaylistSummary(BaseModel):
    id: str
    name: str
    spotify_url: str | None = None
    item_count: int | None = Field(default=None, ge=0)
    public: bool | None = None
    collaborative: bool = False


class PlaylistsPage(BaseModel):
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    playlists: list[PlaylistSummary]


class PlaylistOwner(BaseModel):
    id: str
    name: str


class PlaylistDetails(BaseModel):
    id: str
    name: str
    spotify_url: str | None = None
    description: str
    owner: PlaylistOwner
    item_count: int | None = Field(default=None, ge=0)
    public: bool | None = None
    collaborative: bool = False
    snapshot_id: str | None = None
    url: str


class PlaylistItem(BaseModel):
    position: int = Field(ge=1)
    type: Literal["track", "episode", "unknown"]
    id: str | None = None
    uri: str | None = None
    spotify_url: str | None = None
    name: str
    artists: list[str] = Field(default_factory=list)
    show: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class PlaylistItemsPage(BaseModel):
    playlist_id: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    items: list[PlaylistItem]


class PlaylistCreateResult(BaseModel):
    operation: Literal["create"] = "create"
    status: Literal["verified", "mismatch", "accepted", "ambiguous"]
    playlist_id: str | None = None
    playlist_url: str | None = None
    spotify_url: str | None = None
    requested_public: bool
    observed_public: bool | None = None
    visibility_status: Literal["verified", "mismatch", "unknown"]
    warning: str | None = None


class PlaylistUpdateResult(BaseModel):
    playlist_id: str
    spotify_url: str | None = None
    updated_fields: list[PlaylistUpdateField]
    status: Literal["verified", "mismatch", "ambiguous"]
    mismatches: list[str]
    observed: PlaylistDetails | None = None
    warning: str | None = None


class PlaylistSnapshotResult(BaseModel):
    operation: Literal["add-items", "remove-items", "reorder-items"]
    playlist_id: str
    spotify_url: str | None = None
    item_count: int = Field(ge=1)
    status: Literal["accepted", "ambiguous"]
    snapshot_id: str | None = None
    position: int | None = Field(default=None, ge=0)
    range_start: int | None = Field(default=None, ge=0)
    insert_before: int | None = Field(default=None, ge=0)


class PlaylistUnfollowResult(BaseModel):
    playlist_id: str
    spotify_url: str | None = None
    status: Literal["verified", "mismatch", "ambiguous"]
    still_saved: bool | None = None
    warning: str | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _normalise_id(value: str, item_type: str) -> str:
    candidate = value.strip()
    prefix = f"spotify:{item_type}:"
    if candidate.startswith(prefix):
        candidate = candidate.removeprefix(prefix)
    if not candidate:
        raise ValueError(f"{item_type} ID must not be empty")
    return candidate


def _normalise_item_uris(values: Iterable[str]) -> list[str]:
    uris: list[str] = []
    for value in values:
        candidate = value.strip()
        if not candidate:
            continue
        uris.append(candidate if candidate.startswith("spotify:") else f"spotify:track:{candidate}")
    return uris


def _entity_url(data: Mapping[str, Any], item_type: SpotifyEntityType, value: str) -> str:
    external_urls = _mapping(data.get("external_urls"))
    external_url = external_urls.get("spotify")
    return spotify_web_url(
        item_type,
        value,
        external_url=external_url if isinstance(external_url, str) else None,
    )


def _optional_entity_url(
    data: Mapping[str, Any], item_type: SpotifyEntityType, value: str | None
) -> str | None:
    return _entity_url(data, item_type, value) if value is not None else None


def _metadata(raw: Any, requested_id: str) -> tuple[PlaylistDetails, set[str]]:
    data = _mapping(raw)
    owner = _mapping(data.get("owner"))
    current_items = _mapping(data.get("items"))
    legacy_tracks = _mapping(data.get("tracks"))
    item_count = current_items.get("total", legacy_tracks.get("total"))
    playlist_id = _string(data.get("id"), requested_id)
    resolved_url = _entity_url(data, "playlist", playlist_id)
    available = {
        field for field in ("name", "description", "public", "collaborative") if field in data
    }
    owner_id = _string(owner.get("id"), "unknown")
    return (
        PlaylistDetails(
            id=playlist_id,
            name=_string(data.get("name"), requested_id),
            spotify_url=resolved_url,
            description=_string(data.get("description")),
            owner=PlaylistOwner(
                id=owner_id,
                name=_string(owner.get("display_name"), owner_id),
            ),
            item_count=item_count if isinstance(item_count, int) and item_count >= 0 else None,
            public=data.get("public") if isinstance(data.get("public"), bool) else None,
            collaborative=data.get("collaborative") is True,
            snapshot_id=data.get("snapshot_id")
            if isinstance(data.get("snapshot_id"), str)
            else None,
            url=resolved_url,
        ),
        available,
    )


def _playlist_item(raw: Any, position: int) -> PlaylistItem:
    entry = _mapping(raw)
    data = _mapping(entry.get("item") or entry.get("track"))
    item_type = data.get("type")
    if item_type == "track":
        item_id = data.get("id") if isinstance(data.get("id"), str) else None
        uri = data.get("uri") if isinstance(data.get("uri"), str) else None
        artists = [
            artist["name"]
            for value in data.get("artists", [])
            if isinstance(value, Mapping) and isinstance((artist := value).get("name"), str)
        ]
        return PlaylistItem(
            position=position,
            type="track",
            id=item_id,
            uri=uri,
            spotify_url=_optional_entity_url(data, "track", uri or item_id),
            name=_string(data.get("name"), "Unknown track"),
            artists=artists,
            duration_ms=data.get("duration_ms")
            if isinstance(data.get("duration_ms"), int) and data["duration_ms"] >= 0
            else None,
        )
    if item_type == "episode":
        show = _mapping(data.get("show"))
        item_id = data.get("id") if isinstance(data.get("id"), str) else None
        uri = data.get("uri") if isinstance(data.get("uri"), str) else None
        return PlaylistItem(
            position=position,
            type="episode",
            id=item_id,
            uri=uri,
            spotify_url=_optional_entity_url(data, "episode", uri or item_id),
            name=_string(data.get("name"), "Unknown episode"),
            show=show.get("name") if isinstance(show.get("name"), str) else None,
            duration_ms=data.get("duration_ms")
            if isinstance(data.get("duration_ms"), int) and data["duration_ms"] >= 0
            else None,
        )
    return PlaylistItem(position=position, type="unknown", name="[Removed item]")


async def list_playlists(
    spotify: SpotifyGateway, *, limit: int = MAX_PAGE_SIZE, offset: int = 0
) -> PlaylistsPage:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    page = _mapping(
        await spotify.request("GET", "/me/playlists", params={"limit": limit, "offset": offset})
    )
    raw_items = page.get("items")
    playlists: list[PlaylistSummary] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            data = _mapping(raw)
            playlist_id = data.get("id")
            name = data.get("name")
            if not isinstance(playlist_id, str) or not isinstance(name, str):
                continue
            current_items = _mapping(data.get("items"))
            legacy_tracks = _mapping(data.get("tracks"))
            count = current_items.get("total", legacy_tracks.get("total"))
            playlists.append(
                PlaylistSummary(
                    id=playlist_id,
                    name=name,
                    spotify_url=_entity_url(data, "playlist", playlist_id),
                    item_count=count if isinstance(count, int) and count >= 0 else None,
                    public=data.get("public") if isinstance(data.get("public"), bool) else None,
                    collaborative=data.get("collaborative") is True,
                )
            )
    total = page.get("total")
    return PlaylistsPage(
        total=total if isinstance(total, int) and total >= 0 else len(playlists),
        offset=offset,
        playlists=playlists,
    )


async def get_playlist(spotify: SpotifyGateway, playlist_id: str) -> PlaylistDetails:
    exact_id = _normalise_id(playlist_id, "playlist")
    details, _ = _metadata(await spotify.request("GET", f"/playlists/{exact_id}"), exact_id)
    return details


async def get_playlist_items(
    spotify: SpotifyGateway,
    playlist_id: str,
    *,
    limit: int = MAX_PAGE_SIZE,
    offset: int = 0,
) -> PlaylistItemsPage:
    exact_id = _normalise_id(playlist_id, "playlist")
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    page = _mapping(
        await spotify.request(
            "GET",
            f"/playlists/{exact_id}/items",
            params={"limit": limit, "offset": offset, "additional_types": "track,episode"},
        )
    )
    raw_items = page.get("items")
    entries = raw_items if isinstance(raw_items, list) else []
    items = [_playlist_item(item, offset + index + 1) for index, item in enumerate(entries)]
    total = page.get("total")
    return PlaylistItemsPage(
        playlist_id=exact_id,
        total=total if isinstance(total, int) and total >= 0 else len(items),
        offset=offset,
        items=items,
    )


async def create_playlist(
    spotify: SpotifyGateway,
    *,
    name: str,
    description: str = "",
    public: bool = False,
) -> PlaylistCreateResult:
    if not name.strip():
        raise ValueError("playlist name must not be empty")
    try:
        created = _mapping(
            await spotify.request(
                "POST",
                "/me/playlists",
                json={"name": name.strip(), "description": description, "public": public},
            )
        )
    except AmbiguousWrite as exc:
        return PlaylistCreateResult(
            status="ambiguous",
            requested_public=public,
            visibility_status="unknown",
            warning=str(exc),
        )
    playlist_id = created.get("id")
    if not isinstance(playlist_id, str) or not playlist_id:
        return PlaylistCreateResult(
            status="ambiguous",
            requested_public=public,
            visibility_status="unknown",
            warning="Spotify returned success without a playlist ID; verify the playlist list",
        )
    playlist_url = _entity_url(created, "playlist", playlist_id)
    try:
        raw_observed = await spotify.request("GET", f"/playlists/{playlist_id}")
        observed, available = _metadata(raw_observed, playlist_id)
    except Exception as exc:  # The creation may already have succeeded; preserve that fact.
        return PlaylistCreateResult(
            status="accepted",
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            spotify_url=playlist_url,
            requested_public=public,
            visibility_status="unknown",
            warning=f"Playlist was created, but visibility verification failed: {exc}",
        )
    if "public" not in available:
        return PlaylistCreateResult(
            status="accepted",
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            spotify_url=playlist_url,
            requested_public=public,
            visibility_status="unknown",
            warning="Playlist was created, but Spotify omitted visibility during verification",
        )
    matches = observed.public is public
    return PlaylistCreateResult(
        status="verified" if matches else "mismatch",
        playlist_id=playlist_id,
        playlist_url=playlist_url,
        spotify_url=playlist_url,
        requested_public=public,
        observed_public=observed.public,
        visibility_status="verified" if matches else "mismatch",
        warning=None
        if matches
        else f"Requested public={public}, but Spotify reports public={observed.public}",
    )


async def update_playlist(
    spotify: SpotifyGateway,
    playlist_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    collaborative: bool | None = None,
) -> PlaylistUpdateResult:
    exact_id = _normalise_id(playlist_id, "playlist")
    changes: dict[str, str | bool] = {}
    if name is not None:
        if not name.strip():
            raise ValueError("playlist name must not be empty")
        changes["name"] = name.strip()
    if description is not None:
        changes["description"] = description
    if public is not None:
        changes["public"] = public
    if collaborative is not None:
        changes["collaborative"] = collaborative
    if not changes:
        raise ValueError("at least one playlist field must be provided")
    if changes.get("public") is True and changes.get("collaborative") is True:
        raise ValueError("a collaborative playlist cannot be public")

    updated_fields = cast(list[PlaylistUpdateField], list(changes))
    try:
        await spotify.request("PUT", f"/playlists/{exact_id}", json=changes)
    except AmbiguousWrite as exc:
        return PlaylistUpdateResult(
            playlist_id=exact_id,
            spotify_url=spotify_web_url("playlist", exact_id),
            updated_fields=updated_fields,
            status="ambiguous",
            mismatches=[],
            warning=str(exc),
        )
    try:
        observed, available = _metadata(
            await spotify.request("GET", f"/playlists/{exact_id}"), exact_id
        )
    except Exception as exc:  # The update may already have succeeded; never retry it blindly.
        return PlaylistUpdateResult(
            playlist_id=exact_id,
            spotify_url=spotify_web_url("playlist", exact_id),
            updated_fields=updated_fields,
            status="ambiguous",
            mismatches=[],
            warning=f"Spotify accepted the update, but verification failed: {exc}",
        )
    mismatches: list[str] = []
    for field, expected in changes.items():
        if field not in available:
            mismatches.append(f"{field}: Spotify omitted this field during verification")
            continue
        actual = getattr(observed, field)
        if actual != expected:
            mismatches.append(f"{field}: requested {expected!r}, observed {actual!r}")
    return PlaylistUpdateResult(
        playlist_id=exact_id,
        spotify_url=observed.spotify_url,
        updated_fields=updated_fields,
        status="mismatch" if mismatches else "verified",
        mismatches=mismatches,
        observed=observed,
    )


def _snapshot_result(
    *,
    operation: Literal["add-items", "remove-items", "reorder-items"],
    playlist_id: str,
    item_count: int,
    response: Any,
    position: int | None = None,
    range_start: int | None = None,
    insert_before: int | None = None,
) -> PlaylistSnapshotResult:
    snapshot = _mapping(response).get("snapshot_id")
    snapshot_id = snapshot if isinstance(snapshot, str) and snapshot else None
    return PlaylistSnapshotResult(
        operation=operation,
        playlist_id=playlist_id,
        spotify_url=spotify_web_url("playlist", playlist_id),
        item_count=item_count,
        status="accepted" if snapshot_id else "ambiguous",
        snapshot_id=snapshot_id,
        position=position,
        range_start=range_start,
        insert_before=insert_before,
    )


async def add_playlist_items(
    spotify: SpotifyGateway,
    playlist_id: str,
    item_ids_or_uris: Sequence[str],
    *,
    position: int | None = None,
) -> PlaylistSnapshotResult:
    exact_id = _normalise_id(playlist_id, "playlist")
    uris = _normalise_item_uris(item_ids_or_uris)
    if not uris:
        raise ValueError("at least one item ID or URI is required")
    if len(uris) > MAX_PLAYLIST_ITEMS_PER_WRITE:
        raise ValueError(f"at most {MAX_PLAYLIST_ITEMS_PER_WRITE} items are allowed")
    if position is not None and position < 0:
        raise ValueError("position must be non-negative")
    body: dict[str, Any] = {"uris": uris}
    if position is not None:
        body["position"] = position
    try:
        response = await spotify.request("POST", f"/playlists/{exact_id}/items", json=body)
    except AmbiguousWrite:
        response = None
    return _snapshot_result(
        operation="add-items",
        playlist_id=exact_id,
        item_count=len(uris),
        response=response,
        position=position,
    )


async def remove_playlist_items(
    spotify: SpotifyGateway,
    playlist_id: str,
    item_ids_or_uris: Sequence[str],
    *,
    snapshot_id: str | None = None,
) -> PlaylistSnapshotResult:
    exact_id = _normalise_id(playlist_id, "playlist")
    uris = _normalise_item_uris(item_ids_or_uris)
    if not uris:
        raise ValueError("at least one item ID or URI is required")
    if len(uris) > MAX_PLAYLIST_ITEMS_PER_WRITE:
        raise ValueError(f"at most {MAX_PLAYLIST_ITEMS_PER_WRITE} items are allowed")
    body: dict[str, Any] = {"items": [{"uri": uri} for uri in uris]}
    if snapshot_id:
        body["snapshot_id"] = snapshot_id
    try:
        response = await spotify.request("DELETE", f"/playlists/{exact_id}/items", json=body)
    except AmbiguousWrite:
        response = None
    return _snapshot_result(
        operation="remove-items",
        playlist_id=exact_id,
        item_count=len(uris),
        response=response,
    )


async def reorder_playlist_items(
    spotify: SpotifyGateway,
    playlist_id: str,
    *,
    range_start: int,
    insert_before: int,
    range_length: int = 1,
    snapshot_id: str | None = None,
) -> PlaylistSnapshotResult:
    exact_id = _normalise_id(playlist_id, "playlist")
    if range_start < 0 or insert_before < 0:
        raise ValueError("playlist positions must be non-negative")
    if range_length < 1:
        raise ValueError("range_length must be at least 1")
    body: dict[str, Any] = {
        "range_start": range_start,
        "insert_before": insert_before,
        "range_length": range_length,
    }
    if snapshot_id:
        body["snapshot_id"] = snapshot_id
    try:
        response = await spotify.request("PUT", f"/playlists/{exact_id}/items", json=body)
    except AmbiguousWrite:
        response = None
    return _snapshot_result(
        operation="reorder-items",
        playlist_id=exact_id,
        item_count=range_length,
        response=response,
        range_start=range_start,
        insert_before=insert_before,
    )


async def unfollow_playlist(spotify: SpotifyGateway, playlist_id: str) -> PlaylistUnfollowResult:
    exact_id = _normalise_id(playlist_id, "playlist")
    uri = f"spotify:playlist:{exact_id}"
    try:
        await spotify.request("DELETE", "/me/library", params={"uris": uri})
    except AmbiguousWrite as exc:
        return PlaylistUnfollowResult(
            playlist_id=exact_id,
            spotify_url=spotify_web_url("playlist", exact_id),
            status="ambiguous",
            warning=str(exc),
        )
    try:
        response = await spotify.request("GET", "/me/library/contains", params={"uris": uri})
        if (
            not isinstance(response, list)
            or len(response) != 1
            or not isinstance(response[0], bool)
        ):
            raise SpotifyRequestError("Spotify returned malformed playlist membership evidence")
        still_saved = response[0]
    except Exception as exc:  # The unfollow may already have succeeded.
        return PlaylistUnfollowResult(
            playlist_id=exact_id,
            spotify_url=spotify_web_url("playlist", exact_id),
            status="ambiguous",
            warning=f"Spotify accepted the unfollow, but verification failed: {exc}",
        )
    return PlaylistUnfollowResult(
        playlist_id=exact_id,
        spotify_url=spotify_web_url("playlist", exact_id),
        status="mismatch" if still_saved else "verified",
        still_saved=still_saved,
    )
