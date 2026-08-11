from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.playback import PlaybackService
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.playback import register

ACTIVE_DEVICES = {
    "devices": [
        {
            "id": "device-1",
            "name": "Desk",
            "type": "Computer",
            "is_active": True,
            "is_restricted": False,
            "volume_percent": 42,
        }
    ]
}


class FakeSpotify:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Mapping[str, Any] | None, Any]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        self.calls.append((method, path, params, json))
        return self.responses.pop(0) if self.responses else None


@pytest.mark.anyio
async def test_now_playing_handles_episode_and_missing_optional_fields() -> None:
    spotify = FakeSpotify(
        [
            {
                "is_playing": False,
                "item": {
                    "type": "episode",
                    "id": "episode-1",
                    "uri": "spotify:episode:episode-1",
                    "name": "The Long Drive",
                    "show": {"name": "Road Stories"},
                    "external_urls": {"spotify": "https://open.spotify.com/episode/episode-1"},
                },
            }
        ]
    )

    result = await PlaybackService(spotify).now_playing()

    assert result.is_playing is False
    assert result.device is None
    assert result.item is not None
    assert result.item.type == "episode"
    assert result.item.show == "Road Stories"
    assert result.item.spotify_url == "https://open.spotify.com/episode/episode-1"
    assert spotify.calls == [("GET", "/me/player", None, None)]


@pytest.mark.anyio
async def test_devices_and_queue_use_current_endpoints_and_limit_queue() -> None:
    spotify = FakeSpotify(
        [
            ACTIVE_DEVICES,
            {
                "currently_playing": {"type": "track", "id": "now", "name": "Now"},
                "queue": [
                    {"type": "track", "id": "one", "name": "One"},
                    {"type": "episode", "id": "two", "name": "Two"},
                ],
            },
        ]
    )
    service = PlaybackService(spotify)

    devices = await service.devices()
    queue = await service.queue(limit=1)

    assert devices.devices[0].volume_percent == 42
    assert [item.id for item in queue.queue] == ["one"]
    assert [call[1] for call in spotify.calls] == ["/me/player/devices", "/me/player/queue"]


@pytest.mark.anyio
async def test_play_track_targets_active_device_with_current_request_shape() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, None])

    result = await PlaybackService(spotify).play(item_type="track", item_id="track-1", offset=1250)

    assert result.operation == "play"
    assert result.device_id == "device-1"
    assert result.spotify_url == "https://open.spotify.com/track/track-1"
    assert spotify.calls[-1] == (
        "PUT",
        "/me/player/play",
        {"device_id": "device-1"},
        {"uris": ["spotify:track:track-1"], "position_ms": 1250},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "operation"),
    [
        ("resume", "PUT", "/me/player/play", "resume"),
        ("pause", "PUT", "/me/player/pause", "pause"),
        ("next", "POST", "/me/player/next", "next"),
        ("previous", "POST", "/me/player/previous", "previous"),
    ],
)
async def test_playback_controls_use_current_endpoints(
    method_name: str, http_method: str, path: str, operation: str
) -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, None])
    service = PlaybackService(spotify)

    result = await getattr(service, method_name)()

    assert result.operation == operation
    assert spotify.calls[-1] == (http_method, path, {"device_id": "device-1"}, None)


@pytest.mark.anyio
async def test_queue_and_volume_send_typed_current_requests() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, None, ACTIVE_DEVICES, None])
    service = PlaybackService(spotify)

    queued = await service.add_to_queue(item_type="episode", item_id="episode-1")
    volume = await service.set_volume(65)

    assert queued.uri == "spotify:episode:episode-1"
    assert queued.spotify_url == "https://open.spotify.com/episode/episode-1"
    assert volume.volume_percent == 65
    assert spotify.calls[1] == (
        "POST",
        "/me/player/queue",
        {"uri": "spotify:episode:episode-1", "device_id": "device-1"},
        None,
    )
    assert spotify.calls[3] == (
        "PUT",
        "/me/player/volume",
        {"volume_percent": 65, "device_id": "device-1"},
        None,
    )


@pytest.mark.anyio
async def test_adjust_volume_uses_selected_device_volume_and_returns_typed_result() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, None])

    result = await PlaybackService(spotify).adjust_volume(15)

    assert result.operation == "adjust_volume"
    assert result.device_id == "device-1"
    assert result.adjustment == 15
    assert result.previous_volume_percent == 42
    assert result.volume_percent == 57
    assert result.clamped is False
    assert spotify.calls == [
        ("GET", "/me/player/devices", None, None),
        (
            "PUT",
            "/me/player/volume",
            {"volume_percent": 57, "device_id": "device-1"},
            None,
        ),
    ]


@pytest.mark.anyio
async def test_adjust_volume_clamps_and_targets_preferred_device() -> None:
    devices = {
        "devices": [
            ACTIVE_DEVICES["devices"][0],
            {
                "id": "device-2",
                "name": "Kitchen",
                "type": "Speaker",
                "is_active": False,
                "is_restricted": False,
                "volume_percent": 95,
            },
        ]
    }
    spotify = FakeSpotify([devices, None, None])

    result = await PlaybackService(spotify).adjust_volume(10, device_id="device-2")

    assert result.previous_volume_percent == 95
    assert result.volume_percent == 100
    assert result.clamped is True
    assert spotify.calls == [
        ("GET", "/me/player/devices", None, None),
        ("PUT", "/me/player", None, {"device_ids": ["device-2"], "play": False}),
        (
            "PUT",
            "/me/player/volume",
            {"volume_percent": 100, "device_id": "device-2"},
            None,
        ),
    ]


@pytest.mark.anyio
async def test_adjust_volume_clamps_at_zero() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, None])

    result = await PlaybackService(spotify).adjust_volume(-100)

    assert result.previous_volume_percent == 42
    assert result.volume_percent == 0
    assert result.clamped is True
    assert spotify.calls[-1] == (
        "PUT",
        "/me/player/volume",
        {"volume_percent": 0, "device_id": "device-1"},
        None,
    )


@pytest.mark.anyio
async def test_adjust_volume_rejects_unknown_current_volume_without_write() -> None:
    devices = {
        "devices": [
            {
                **ACTIVE_DEVICES["devices"][0],
                "volume_percent": None,
            }
        ]
    }
    spotify = FakeSpotify([devices])

    with pytest.raises(ValueError, match="current volume"):
        await PlaybackService(spotify).adjust_volume(-10)

    assert spotify.calls == [("GET", "/me/player/devices", None, None)]


@pytest.mark.anyio
async def test_playback_validation_prevents_invalid_writes() -> None:
    spotify = FakeSpotify([])
    service = PlaybackService(spotify)

    with pytest.raises(ValueError, match="track or episode"):
        await service.add_to_queue(uri="spotify:playlist:not-queueable")
    with pytest.raises(ValueError, match="between 0 and 100"):
        await service.set_volume(101)

    assert spotify.calls == []


@pytest.mark.anyio
async def test_play_rejects_episode_with_queue_and_open_url_guidance() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match=r"add_to_queue.*open\.spotify\.com/episode/episode-1"):
        await PlaybackService(spotify).play(uri="spotify:episode:episode-1")

    assert spotify.calls == []


@pytest.mark.anyio
async def test_playback_tools_have_spotify_names_outputs_and_annotations() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_now_playing",
        "spotify_devices",
        "spotify_queue",
        "spotify_play",
        "spotify_resume",
        "spotify_pause",
        "spotify_next",
        "spotify_previous",
        "spotify_add_to_queue",
        "spotify_set_volume",
        "spotify_adjust_volume",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert tools["spotify_now_playing"].annotations.read_only_hint is True
    assert tools["spotify_play"].annotations.read_only_hint is False
    assert tools["spotify_pause"].annotations.idempotent_hint is True
    assert tools["spotify_adjust_volume"].annotations.read_only_hint is False
    assert tools["spotify_adjust_volume"].annotations.idempotent_hint is False
