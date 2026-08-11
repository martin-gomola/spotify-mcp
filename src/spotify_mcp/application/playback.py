"""Spotify Connect playback use cases over current Web API endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.ports import SpotifyGateway

PlayableType = Literal["track", "album", "artist", "playlist"]
QueueableType = Literal["track", "episode"]
PlaybackItemType = Literal["track", "episode", "unknown"]
PlaybackOperation = Literal[
    "play", "resume", "pause", "next", "previous", "add_to_queue", "set_volume"
]


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
    device: Device | None = None
    item: PlaybackItem | None = None


class PlaybackQueue(Model):
    currently_playing: PlaybackItem | None = None
    queue: list[PlaybackItem]


class PlaybackResult(Model):
    operation: PlaybackOperation
    status: Literal["accepted"] = "accepted"
    device_id: str | None = None
    uri: str | None = None
    volume_percent: int | None = None


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
    return PlaybackItem(
        type=item_type,
        id=_string(item.get("id")),
        uri=_string(item.get("uri")),
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
        uri: str | None = None,
        item_type: PlayableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
        offset: int | None = None,
    ) -> PlaybackResult:
        resolved_uri = self._resolve_uri(uri, item_type, item_id)
        resolved_type = resolved_uri.split(":", maxsplit=2)[1]
        if offset is not None and offset < 0:
            raise ValueError("offset must be non-negative")
        device = await self._ensure_active_device(device_id)
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
            "PUT", "/me/player/play", params={"device_id": device}, json=body
        )
        return PlaybackResult(operation="play", device_id=device, uri=resolved_uri)

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
        return PlaybackResult(operation="add_to_queue", device_id=device, uri=resolved_uri)

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
        selected = preferred or next(
            (device for device in available if device.is_active), available[0]
        )
        if selected.id is None:
            raise ValueError(f"Spotify device has no usable ID: {selected.name}")

        if not selected.is_active:
            await self._spotify.request(
                "PUT", "/me/player", json={"device_ids": [selected.id], "play": False}
            )
            await anyio.sleep(0.6)
        return selected

    @staticmethod
    def _resolve_uri(uri: str | None, item_type: PlayableType | None, item_id: str | None) -> str:
        resolved = uri or (
            f"spotify:{item_type}:{item_id}" if item_type is not None and item_id else None
        )
        if resolved is None:
            raise ValueError("provide uri or both item_type and item_id")
        parts = resolved.split(":", maxsplit=2)
        if (
            len(parts) != 3
            or parts[0] != "spotify"
            or parts[1]
            not in {
                "track",
                "album",
                "artist",
                "playlist",
            }
        ):
            raise ValueError("uri must be a Spotify track, album, artist, or playlist URI")
        return resolved

    @staticmethod
    def _resolve_queue_uri(
        uri: str | None, item_type: QueueableType | None, item_id: str | None
    ) -> str:
        resolved = uri or (
            f"spotify:{item_type}:{item_id}" if item_type is not None and item_id else None
        )
        if resolved is None:
            raise ValueError("provide uri or both item_type and item_id")
        parts = resolved.split(":", maxsplit=2)
        if len(parts) != 3 or parts[0] != "spotify" or parts[1] not in {"track", "episode"}:
            raise ValueError("queue uri must be a Spotify track or episode URI")
        return resolved
