"""Spotify Connect playback use cases over current Web API endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

import anyio
from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.discovery import DiscoveryService, SearchItem
from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.links import spotify_uri, spotify_url_from_uri, spotify_web_url

PlayableType = Literal["track", "album", "artist", "playlist"]
QueueableType = Literal["track", "episode"]
PlaybackItemType = Literal["track", "episode", "unknown"]
RepeatState = Literal["track", "context", "off"]
PlaybackOperation = Literal[
    "play",
    "resume",
    "pause",
    "next",
    "previous",
    "add_to_queue",
    "set_volume",
    "seek",
    "set_shuffle",
    "set_repeat",
    "transfer_playback",
]
_PLAYBACK_OBSERVATION_DELAYS = (0.0, 0.2, 0.4)


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Device(Model):
    id: str | None = None
    name: str
    type: str
    is_active: bool = False
    is_restricted: bool = False
    volume_percent: int | None = None


class Devices(Model):
    devices: list[Device]


class PlaybackItem(Model):
    type: PlaybackItemType
    id: str | None = None
    uri: str | None = None
    spotify_url: str | None = None
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    show: str | None = None
    duration_ms: int | None = None


class NowPlaying(Model):
    is_playing: bool
    progress_ms: int | None = None
    shuffle_state: bool | None = None
    repeat_state: str | None = None
    context_uri: str | None = None
    device: Device | None = None
    item: PlaybackItem | None = None


class PlaybackQueue(Model):
    currently_playing: PlaybackItem | None = None
    queue: list[PlaybackItem]


class PlaybackResult(Model):
    operation: PlaybackOperation
    status: Literal["accepted", "needs_selection", "no_match"] = "accepted"
    device_id: str | None = None
    uri: str | None = None
    spotify_url: str | None = None
    volume_percent: int | None = None
    position_ms: int | None = None
    shuffle_state: bool | None = None
    repeat_state: RepeatState | None = None
    play: bool | None = None
    query: str | None = None
    query_type: PlayableType | None = None
    resolved_entity: SearchItem | None = None
    candidates: list[SearchItem] = Field(default_factory=list)


class ObservedPlaybackResult(Model):
    operation: Literal["play"] = "play"
    status: Literal["verified", "unverified"]
    requested_uri: str
    device_id: str
    observed: NowPlaying


class VolumeAdjustmentResult(Model):
    operation: Literal["adjust_volume"] = "adjust_volume"
    status: Literal["accepted"] = "accepted"
    device_id: str
    adjustment: int
    previous_volume_percent: int
    volume_percent: int
    clamped: bool


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _artist_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for raw in value if (name := _string(_mapping(raw).get("name"))) is not None]


def _device(value: Any) -> Device | None:
    item = _mapping(value)
    if not item:
        return None
    return Device(
        id=_string(item.get("id")),
        name=_string(item.get("name")) or "Unknown device",
        type=_string(item.get("type")) or "Unknown",
        is_active=_boolean(item.get("is_active")) or False,
        is_restricted=_boolean(item.get("is_restricted")) or False,
        volume_percent=_integer(item.get("volume_percent")),
    )


def _playback_item(value: Any) -> PlaybackItem | None:
    item = _mapping(value)
    if not item:
        return None
    raw_type = _string(item.get("type"))
    item_type: PlaybackItemType
    if raw_type == "track":
        item_type = "track"
    elif raw_type == "episode":
        item_type = "episode"
    else:
        item_type = "unknown"
    item_id = _string(item.get("id"))
    uri = _string(item.get("uri"))
    external_url = _string(_mapping(item.get("external_urls")).get("spotify"))
    linked_type = item_type if item_type != "unknown" else None
    linked_value = uri or item_id
    return PlaybackItem(
        type=item_type,
        id=item_id,
        uri=uri,
        spotify_url=spotify_web_url(linked_type, linked_value, external_url=external_url)
        if linked_type is not None and linked_value is not None
        else None,
        name=_string(item.get("name")) or "Unknown item",
        artists=_artist_names(item.get("artists")),
        album=_string(_mapping(item.get("album")).get("name")),
        show=_string(_mapping(item.get("show")).get("name")),
        duration_ms=_integer(item.get("duration_ms")),
    )


class PlaybackService:
    """Read and control Spotify playback without SDK wrapper indirection."""

    def __init__(self, spotify: SpotifyGateway) -> None:
        self._spotify = spotify

    async def now_playing(self) -> NowPlaying:
        payload = _mapping(await self._spotify.request("GET", "/me/player"))
        return NowPlaying(
            is_playing=_boolean(payload.get("is_playing")) or False,
            progress_ms=_integer(payload.get("progress_ms")),
            shuffle_state=_boolean(payload.get("shuffle_state")),
            repeat_state=_string(payload.get("repeat_state")),
            context_uri=_string(_mapping(payload.get("context")).get("uri")),
            device=_device(payload.get("device")),
            item=_playback_item(payload.get("item")),
        )

    async def devices(self) -> Devices:
        payload = _mapping(await self._spotify.request("GET", "/me/player/devices"))
        raw_devices = payload.get("devices")
        devices = (
            [parsed for raw in raw_devices if (parsed := _device(raw)) is not None]
            if isinstance(raw_devices, list)
            else []
        )
        return Devices(devices=devices)

    async def queue(self, *, limit: int = 10) -> PlaybackQueue:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        payload = _mapping(await self._spotify.request("GET", "/me/player/queue"))
        raw_queue = payload.get("queue")
        queue = (
            [parsed for raw in raw_queue[:limit] if (parsed := _playback_item(raw)) is not None]
            if isinstance(raw_queue, list)
            else []
        )
        return PlaybackQueue(
            currently_playing=_playback_item(payload.get("currently_playing")),
            queue=queue,
        )

    async def play(
        self,
        *,
        query: str | None = None,
        uri: str | None = None,
        item_type: PlayableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
        offset: int | None = None,
    ) -> PlaybackResult:
        if query is not None:
            if uri is not None or item_id is not None:
                raise ValueError("query cannot be combined with uri or item_id")
            if item_type is None:
                raise ValueError("item_type is required with query")
            return await self._play_query(
                query=query,
                item_type=item_type,
                device_id=device_id,
                offset=offset,
            )
        resolved_uri = self._resolve_uri(uri, item_type, item_id)
        if offset is not None and offset < 0:
            raise ValueError("offset must be non-negative")
        device = await self._ensure_active_device(device_id)
        await self._start_playback(resolved_uri, device_id=device, offset=offset)
        return PlaybackResult(
            operation="play",
            device_id=device,
            uri=resolved_uri,
            spotify_url=spotify_url_from_uri(resolved_uri),
        )

    async def _play_query(
        self,
        *,
        query: str,
        item_type: PlayableType,
        device_id: str | None,
        offset: int | None,
    ) -> PlaybackResult:
        if offset is not None and offset < 0:
            raise ValueError("offset must be non-negative")
        normalized_query = " ".join(query.split())
        results = await DiscoveryService(self._spotify).search(
            normalized_query, item_type, limit=10
        )
        candidates = [
            item.model_copy(
                update={
                    "uri": spotify_uri(item_type, item.uri or item.id),
                    "spotify_url": spotify_web_url(
                        item_type,
                        item.uri or item.id,
                        external_url=item.spotify_url,
                    ),
                }
            )
            for item in results.items
        ]
        exact_matches = [
            item for item in candidates if self._query_matches_item(normalized_query, item)
        ]
        if len(exact_matches) != 1:
            return PlaybackResult(
                operation="play",
                status="no_match" if not candidates else "needs_selection",
                query=normalized_query,
                query_type=item_type,
                candidates=candidates,
            )

        resolved = exact_matches[0]
        assert resolved.uri is not None
        played = await self.play(
            uri=resolved.uri,
            device_id=device_id,
            offset=offset,
        )
        return played.model_copy(
            update={
                "query": normalized_query,
                "query_type": item_type,
                "resolved_entity": resolved,
            }
        )

    async def play_and_observe(
        self,
        *,
        uri: str,
        device_id: str | None,
    ) -> ObservedPlaybackResult:
        """Start one exact entity and observe bounded fresh state without retrying the write."""

        if device_id is None:
            raise ValueError("device_id is required for direct play")
        resolved_uri = self._resolve_uri(uri, None, None)
        devices = (await self.devices()).devices
        selected = next((device for device in devices if device.id == device_id), None)
        if selected is None:
            raise ValueError(f"Spotify device not found: {device_id}")
        if selected.is_restricted:
            raise ValueError(f"Spotify device cannot be controlled: {selected.name}")

        await self._start_playback(resolved_uri, device_id=device_id)
        resolved_type = resolved_uri.split(":", maxsplit=2)[1]
        observed: NowPlaying | None = None
        for delay in _PLAYBACK_OBSERVATION_DELAYS:
            if delay:
                await anyio.sleep(delay)
            observed = await self.now_playing()
            observed_matches = (
                observed.item is not None and observed.item.uri == resolved_uri
                if resolved_type == "track"
                else observed.context_uri == resolved_uri
            )
            device_matches = observed.device is not None and observed.device.id == device_id
            if observed.is_playing and device_matches and observed_matches:
                return ObservedPlaybackResult(
                    status="verified",
                    requested_uri=resolved_uri,
                    device_id=device_id,
                    observed=observed,
                )

        assert observed is not None
        return ObservedPlaybackResult(
            status="unverified",
            requested_uri=resolved_uri,
            device_id=device_id,
            observed=observed,
        )

    async def _start_playback(
        self,
        resolved_uri: str,
        *,
        device_id: str,
        offset: int | None = None,
    ) -> None:
        resolved_type = resolved_uri.split(":", maxsplit=2)[1]
        body: dict[str, Any]
        if resolved_type == "track":
            body = {"uris": [resolved_uri]}
            if offset is not None:
                body["position_ms"] = offset
        else:
            body = {"context_uri": resolved_uri}
            if offset is not None:
                body["offset"] = {"position": offset}
        await self._spotify.request(
            "PUT", "/me/player/play", params={"device_id": device_id}, json=body
        )

    async def resume(self, *, device_id: str | None = None) -> PlaybackResult:
        device = await self._ensure_active_device(device_id)
        await self._spotify.request("PUT", "/me/player/play", params={"device_id": device})
        return PlaybackResult(operation="resume", device_id=device)

    async def pause(self, *, device_id: str | None = None) -> PlaybackResult:
        device = await self._ensure_active_device(device_id)
        await self._spotify.request("PUT", "/me/player/pause", params={"device_id": device})
        return PlaybackResult(operation="pause", device_id=device)

    async def next(self, *, device_id: str | None = None) -> PlaybackResult:
        device = await self._ensure_active_device(device_id)
        await self._spotify.request("POST", "/me/player/next", params={"device_id": device})
        return PlaybackResult(operation="next", device_id=device)

    async def previous(self, *, device_id: str | None = None) -> PlaybackResult:
        device = await self._ensure_active_device(device_id)
        await self._spotify.request("POST", "/me/player/previous", params={"device_id": device})
        return PlaybackResult(operation="previous", device_id=device)

    async def add_to_queue(
        self,
        *,
        uri: str | None = None,
        item_type: QueueableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
    ) -> PlaybackResult:
        resolved_uri = self._resolve_queue_uri(uri, item_type, item_id)
        device = await self._ensure_active_device(device_id)
        await self._spotify.request(
            "POST",
            "/me/player/queue",
            params={"uri": resolved_uri, "device_id": device},
        )
        return PlaybackResult(
            operation="add_to_queue",
            device_id=device,
            uri=resolved_uri,
            spotify_url=spotify_url_from_uri(resolved_uri),
        )

    async def set_volume(
        self, volume_percent: int, *, device_id: str | None = None
    ) -> PlaybackResult:
        if not 0 <= volume_percent <= 100:
            raise ValueError("volume_percent must be between 0 and 100")
        device = await self._ensure_active_device(device_id)
        await self._spotify.request(
            "PUT",
            "/me/player/volume",
            params={"volume_percent": volume_percent, "device_id": device},
        )
        return PlaybackResult(
            operation="set_volume", device_id=device, volume_percent=volume_percent
        )

    async def seek(self, position_ms: int, *, device_id: str | None = None) -> PlaybackResult:
        if position_ms < 0:
            raise ValueError("position_ms must be non-negative")
        device = await self._ensure_active_device(device_id)
        await self._spotify.request(
            "PUT",
            "/me/player/seek",
            params={"position_ms": position_ms, "device_id": device},
        )
        return PlaybackResult(operation="seek", device_id=device, position_ms=position_ms)

    async def set_shuffle(self, state: bool, *, device_id: str | None = None) -> PlaybackResult:
        device = await self._ensure_active_device(device_id)
        await self._spotify.request(
            "PUT",
            "/me/player/shuffle",
            params={"state": state, "device_id": device},
        )
        return PlaybackResult(operation="set_shuffle", device_id=device, shuffle_state=state)

    async def set_repeat(
        self, repeat_state: RepeatState, *, device_id: str | None = None
    ) -> PlaybackResult:
        if repeat_state not in {"track", "context", "off"}:
            raise ValueError("repeat_state must be track, context, or off")
        device = await self._ensure_active_device(device_id)
        await self._spotify.request(
            "PUT",
            "/me/player/repeat",
            params={"state": repeat_state, "device_id": device},
        )
        return PlaybackResult(operation="set_repeat", device_id=device, repeat_state=repeat_state)

    async def transfer_playback(self, device_id: str, *, play: bool = False) -> PlaybackResult:
        devices = (await self.devices()).devices
        selected = next((device for device in devices if device.id == device_id), None)
        if selected is None:
            raise ValueError(f"Spotify device not found: {device_id}")
        if selected.is_restricted:
            raise ValueError(f"Spotify device cannot be controlled: {selected.name}")
        await self._spotify.request(
            "PUT",
            "/me/player",
            json={"device_ids": [device_id], "play": play},
        )
        return PlaybackResult(operation="transfer_playback", device_id=device_id, play=play)

    async def adjust_volume(
        self, adjustment: int, *, device_id: str | None = None
    ) -> VolumeAdjustmentResult:
        if not -100 <= adjustment <= 100:
            raise ValueError("adjustment must be between -100 and 100")

        device = await self._select_device(device_id)
        assert device.id is not None
        if device.volume_percent is None:
            raise ValueError(f"Unable to get current volume from device: {device.name}")

        unclamped_volume = device.volume_percent + adjustment
        target_volume = min(100, max(0, unclamped_volume))
        await self._spotify.request(
            "PUT",
            "/me/player/volume",
            params={"volume_percent": target_volume, "device_id": device.id},
        )
        return VolumeAdjustmentResult(
            device_id=device.id,
            adjustment=adjustment,
            previous_volume_percent=device.volume_percent,
            volume_percent=target_volume,
            clamped=target_volume != unclamped_volume,
        )

    async def _ensure_active_device(self, preferred_id: str | None) -> str:
        selected = await self._select_device(preferred_id)
        assert selected.id is not None
        return selected.id

    async def _select_device(self, preferred_id: str | None) -> Device:
        available = (await self.devices()).devices
        if not available:
            raise ValueError("No Spotify devices found. Open Spotify on a device first.")

        preferred = (
            next((device for device in available if device.id == preferred_id), None)
            if preferred_id is not None
            else None
        )
        if preferred_id is not None and preferred is None:
            raise ValueError(f"Spotify device not found: {preferred_id}")
        if preferred is not None and preferred.is_restricted:
            raise ValueError(f"Spotify device cannot be controlled: {preferred.name}")

        usable = [
            device for device in available if device.id is not None and not device.is_restricted
        ]
        if not usable:
            raise ValueError(
                "No controllable Spotify devices found. Open Spotify on a device first."
            )
        active = next((device for device in usable if device.is_active), None)
        if preferred is not None:
            selected = preferred
        elif active is not None:
            selected = active
        elif len(usable) == 1:
            selected = usable[0]
        else:
            choices = ", ".join(f"{device.name} ({device.id})" for device in usable)
            raise ValueError(
                "Multiple Spotify devices are available; provide device_id to choose one. "
                f"Available: {choices}."
            )
        assert selected.id is not None

        if not selected.is_active:
            await self._spotify.request(
                "PUT", "/me/player", json={"device_ids": [selected.id], "play": False}
            )
            await anyio.sleep(0.6)
        return selected

    @staticmethod
    def _normalized_name(value: str) -> str:
        return " ".join(value.casefold().split())

    @classmethod
    def _query_matches_item(cls, query: str, item: SearchItem) -> bool:
        normalized_query = cls._normalized_name(query)
        normalized_name = cls._normalized_name(item.name)
        accepted_queries = {normalized_name}
        for artist in item.artists:
            normalized_artist = cls._normalized_name(artist)
            accepted_queries.add(f"{normalized_name} {normalized_artist}")
            accepted_queries.add(f"{normalized_name} by {normalized_artist}")
        return normalized_query in accepted_queries

    @staticmethod
    def _resolve_uri(uri: str | None, item_type: PlayableType | None, item_id: str | None) -> str:
        if uri is not None and uri.strip().startswith("spotify:episode:"):
            episode_url = spotify_web_url("episode", uri)
            raise ValueError(
                "spotify_play does not support direct episode playback; use "
                f"spotify_add_to_queue or open {episode_url}"
            )
        resolved = uri or (
            spotify_uri(item_type, item_id) if item_type is not None and item_id else None
        )
        if resolved is None:
            raise ValueError("provide uri or both item_type and item_id")
        parts = resolved.split(":", maxsplit=2)
        if (
            len(parts) != 3
            or parts[0] != "spotify"
            or parts[1] not in {"track", "album", "artist", "playlist"}
        ):
            raise ValueError("uri must be a Spotify track, album, artist, or playlist URI")
        return spotify_uri(cast(PlayableType, parts[1]), resolved)

    @staticmethod
    def _resolve_queue_uri(
        uri: str | None, item_type: QueueableType | None, item_id: str | None
    ) -> str:
        resolved = uri or (
            spotify_uri(item_type, item_id) if item_type is not None and item_id else None
        )
        if resolved is None:
            raise ValueError("provide uri or both item_type and item_id")
        parts = resolved.split(":", maxsplit=2)
        if len(parts) != 3 or parts[0] != "spotify" or parts[1] not in {"track", "episode"}:
            raise ValueError("queue uri must be a Spotify track or episode URI")
        return spotify_uri(cast(QueueableType, parts[1]), resolved)
