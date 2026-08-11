from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.playback import PlaybackService
from spotify_mcp.domain.errors import AmbiguousWrite
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
        response = self.responses.pop(0) if self.responses else None
        if isinstance(response, Exception):
            raise response
        return response


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
async def test_play_uses_only_usable_inactive_device_and_transfers_once() -> None:
    devices = {
        "devices": [
            {
                "id": "restricted",
                "name": "TV",
                "type": "TV",
                "is_active": True,
                "is_restricted": True,
            },
            {
                "id": "device-2",
                "name": "Kitchen",
                "type": "Speaker",
                "is_active": False,
                "is_restricted": False,
            },
        ]
    }
    spotify = FakeSpotify([devices, None, None])

    result = await PlaybackService(spotify).play(uri="spotify:track:track-1")

    assert result.device_id == "device-2"
    assert spotify.calls == [
        ("GET", "/me/player/devices", None, None),
        ("PUT", "/me/player", None, {"device_ids": ["device-2"], "play": False}),
        (
            "PUT",
            "/me/player/play",
            {"device_id": "device-2"},
            {"uris": ["spotify:track:track-1"]},
        ),
    ]


@pytest.mark.anyio
async def test_play_requires_device_choice_for_multiple_usable_inactive_devices() -> None:
    devices = {
        "devices": [
            {
                "id": "device-1",
                "name": "Desk",
                "type": "Computer",
                "is_active": False,
                "is_restricted": False,
            },
            {
                "id": "device-2",
                "name": "Kitchen",
                "type": "Speaker",
                "is_active": False,
                "is_restricted": False,
            },
        ]
    }
    spotify = FakeSpotify([devices])

    with pytest.raises(ValueError, match=r"Multiple Spotify devices are available.*device_id"):
        await PlaybackService(spotify).play(uri="spotify:track:track-1")

    assert spotify.calls == [("GET", "/me/player/devices", None, None)]


@pytest.mark.anyio
async def test_play_query_auto_plays_one_exact_name_match_and_reports_entity() -> None:
    search_response = {
        "tracks": {
            "total": 2,
            "items": [
                {
                    "id": "exact",
                    "uri": "spotify:track:exact",
                    "name": "Road Song",
                    "artists": [{"name": "Driver"}],
                    "album": {"name": "Miles"},
                },
                {
                    "id": "other",
                    "uri": "spotify:track:other",
                    "name": "Road Song (Live)",
                    "artists": [{"name": "Driver"}],
                },
            ],
        }
    }
    spotify = FakeSpotify([search_response, ACTIVE_DEVICES, None])

    result = await PlaybackService(spotify).play(query=" road song ", item_type="track")

    assert result.status == "accepted"
    assert result.query == "road song"
    assert result.resolved_entity is not None
    assert result.resolved_entity.uri == "spotify:track:exact"
    assert result.candidates == []
    assert spotify.calls[-1] == (
        "PUT",
        "/me/player/play",
        {"device_id": "device-1"},
        {"uris": ["spotify:track:exact"]},
    )


@pytest.mark.anyio
async def test_play_query_returns_ambiguous_candidates_without_write() -> None:
    search_response = {
        "tracks": {
            "total": 2,
            "items": [
                {
                    "id": "original",
                    "uri": "spotify:track:original",
                    "name": "Road Song",
                    "artists": [{"name": "Driver"}],
                },
                {
                    "id": "remaster",
                    "uri": "spotify:track:remaster",
                    "name": "Road Song",
                    "artists": [{"name": "Driver"}],
                },
            ],
        }
    }
    spotify = FakeSpotify([search_response])

    result = await PlaybackService(spotify).play(query="Road Song", item_type="track")

    assert result.status == "needs_selection"
    assert result.uri is None
    assert result.resolved_entity is None
    assert [candidate.uri for candidate in result.candidates] == [
        "spotify:track:original",
        "spotify:track:remaster",
    ]
    assert [call for call in spotify.calls if call[0] != "GET"] == []


@pytest.mark.anyio
async def test_play_query_auto_plays_unique_exact_match_from_bounded_top_results() -> None:
    spotify = FakeSpotify(
        [
            {
                "tracks": {
                    "total": 20,
                    "items": [
                        {
                            "id": "exact",
                            "uri": "spotify:track:exact",
                            "name": "Road Song",
                            "artists": [{"name": "Driver"}],
                        }
                    ],
                }
            },
            ACTIVE_DEVICES,
            None,
        ]
    )

    result = await PlaybackService(spotify).play(query="Road Song", item_type="track")

    assert result.status == "accepted"
    assert result.resolved_entity is not None
    assert result.resolved_entity.uri == "spotify:track:exact"
    assert spotify.calls[0][2]["limit"] == 10
    assert spotify.calls[-1][0:2] == ("PUT", "/me/player/play")


@pytest.mark.anyio
async def test_play_query_accepts_exact_track_and_artist_phrase() -> None:
    spotify = FakeSpotify(
        [
            {
                "tracks": {
                    "total": 25,
                    "items": [
                        {
                            "id": "peace-piece",
                            "uri": "spotify:track:peace-piece",
                            "name": "Peace Piece",
                            "artists": [{"name": "Bill Evans"}],
                        }
                    ],
                }
            },
            ACTIVE_DEVICES,
            None,
        ]
    )

    result = await PlaybackService(spotify).play(
        query="Peace Piece by Bill Evans", item_type="track"
    )

    assert result.status == "accepted"
    assert result.resolved_entity is not None
    assert result.resolved_entity.uri == "spotify:track:peace-piece"


@pytest.mark.anyio
async def test_play_query_returns_no_match_without_write() -> None:
    spotify = FakeSpotify([{"albums": {"total": 0, "items": []}}])

    result = await PlaybackService(spotify).play(query="Missing Album", item_type="album")

    assert result.status == "no_match"
    assert result.query == "Missing Album"
    assert result.candidates == []
    assert spotify.calls == [
        (
            "GET",
            "/search",
            {
                "q": "Missing Album",
                "type": "album",
                "limit": 10,
                "offset": 0,
                "market": "from_token",
            },
            None,
        )
    ]


@pytest.mark.anyio
async def test_play_query_rejects_mixed_exact_and_search_inputs_without_read_or_write() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match="query cannot be combined"):
        await PlaybackService(spotify).play(
            query="Road Song", item_type="track", uri="spotify:track:exact"
        )

    assert spotify.calls == []


@pytest.mark.anyio
async def test_play_and_observe_verifies_exact_track_without_retrying_write() -> None:
    spotify = FakeSpotify(
        [
            ACTIVE_DEVICES,
            None,
            {
                "is_playing": True,
                "device": ACTIVE_DEVICES["devices"][0],
                "item": {
                    "type": "track",
                    "id": "track-1",
                    "uri": "spotify:track:track-1",
                    "name": "Exact Track",
                },
            },
        ]
    )

    result = await PlaybackService(spotify).play_and_observe(
        uri="spotify:track:track-1", device_id="device-1"
    )

    assert result.status == "verified"
    assert result.requested_uri == "spotify:track:track-1"
    assert result.device_id == "device-1"
    assert result.observed.item is not None
    assert result.observed.item.uri == "spotify:track:track-1"
    assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/play")) == 1


@pytest.mark.anyio
async def test_play_and_observe_reports_unverified_mismatch_without_retrying_write() -> None:
    mismatched_observation = {
        "is_playing": True,
        "device": ACTIVE_DEVICES["devices"][0],
        "item": {
            "type": "track",
            "id": "different",
            "uri": "spotify:track:different",
            "name": "Different Track",
        },
    }
    spotify = FakeSpotify(
        [
            ACTIVE_DEVICES,
            None,
            mismatched_observation,
            mismatched_observation,
            mismatched_observation,
        ]
    )

    result = await PlaybackService(spotify).play_and_observe(
        uri="spotify:track:track-1", device_id="device-1"
    )

    assert result.status == "unverified"
    assert result.observed.item is not None
    assert result.observed.item.uri == "spotify:track:different"
    assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/play")) == 1


@pytest.mark.anyio
async def test_play_and_observe_verifies_context_uri_for_album() -> None:
    spotify = FakeSpotify(
        [
            ACTIVE_DEVICES,
            None,
            {
                "is_playing": True,
                "device": ACTIVE_DEVICES["devices"][0],
                "context": {"type": "album", "uri": "spotify:album:album-1"},
                "item": {
                    "type": "track",
                    "id": "album-track",
                    "uri": "spotify:track:album-track",
                    "name": "Album Track",
                },
            },
        ]
    )

    result = await PlaybackService(spotify).play_and_observe(
        uri="spotify:album:album-1", device_id="device-1"
    )

    assert result.status == "verified"
    assert result.observed.context_uri == "spotify:album:album-1"


@pytest.mark.anyio
async def test_play_and_observe_rechecks_stale_playlist_state_without_retrying_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr("spotify_mcp.application.playback.anyio.sleep", no_wait)
    spotify = FakeSpotify(
        [
            ACTIVE_DEVICES,
            None,
            {
                "is_playing": True,
                "device": ACTIVE_DEVICES["devices"][0],
                "context": {"type": "playlist", "uri": "spotify:playlist:previous"},
                "item": {"type": "track", "uri": "spotify:track:old", "name": "Old"},
            },
            {
                "is_playing": True,
                "device": ACTIVE_DEVICES["devices"][0],
                "context": {"type": "playlist", "uri": "spotify:playlist:hip"},
                "item": {"type": "track", "uri": "spotify:track:new", "name": "New"},
            },
        ]
    )

    result = await PlaybackService(spotify).play_and_observe(
        uri="spotify:playlist:hip", device_id="device-1"
    )

    assert result.status == "verified"
    assert result.observed.context_uri == "spotify:playlist:hip"
    assert [call[0:2] for call in spotify.calls].count(("GET", "/me/player")) == 2
    assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/play")) == 1


@pytest.mark.anyio
async def test_play_and_observe_requires_explicit_existing_device_before_write() -> None:
    service = PlaybackService(FakeSpotify([]))

    with pytest.raises(ValueError, match="device_id is required"):
        await service.play_and_observe(uri="spotify:track:track-1", device_id=None)

    spotify = FakeSpotify([ACTIVE_DEVICES])
    with pytest.raises(ValueError, match="Spotify device not found: missing"):
        await PlaybackService(spotify).play_and_observe(
            uri="spotify:track:track-1", device_id="missing"
        )

    assert spotify.calls == [("GET", "/me/player/devices", None, None)]


@pytest.mark.anyio
async def test_play_and_observe_rejects_restricted_device_before_write() -> None:
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "restricted",
                        "name": "TV",
                        "type": "TV",
                        "is_active": True,
                        "is_restricted": True,
                    }
                ]
            }
        ]
    )

    with pytest.raises(ValueError, match="cannot be controlled: TV"):
        await PlaybackService(spotify).play_and_observe(
            uri="spotify:track:track-1", device_id="restricted"
        )

    assert spotify.calls == [("GET", "/me/player/devices", None, None)]


@pytest.mark.anyio
async def test_play_and_observe_requires_playing_state_and_requested_device() -> None:
    for observed in (
        {
            "is_playing": False,
            "device": ACTIVE_DEVICES["devices"][0],
            "item": {
                "type": "track",
                "uri": "spotify:track:track-1",
                "name": "Exact Track",
            },
        },
        {
            "is_playing": True,
            "device": {**ACTIVE_DEVICES["devices"][0], "id": "other-device"},
            "item": {
                "type": "track",
                "uri": "spotify:track:track-1",
                "name": "Exact Track",
            },
        },
    ):
        spotify = FakeSpotify([ACTIVE_DEVICES, None, observed])
        result = await PlaybackService(spotify).play_and_observe(
            uri="spotify:track:track-1", device_id="device-1"
        )
        assert result.status == "unverified"
        assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/play")) == 1


@pytest.mark.anyio
async def test_play_and_observe_propagates_ambiguous_write_without_retry() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, AmbiguousWrite("verify remote state before retrying")])

    with pytest.raises(AmbiguousWrite, match="verify remote state"):
        await PlaybackService(spotify).play_and_observe(
            uri="spotify:track:track-1", device_id="device-1"
        )

    assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/play")) == 1


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
async def test_seek_shuffle_repeat_and_transfer_use_typed_request_shapes() -> None:
    spotify = FakeSpotify(
        [ACTIVE_DEVICES, None, ACTIVE_DEVICES, None, ACTIVE_DEVICES, None, ACTIVE_DEVICES, None]
    )
    service = PlaybackService(spotify)

    seek = await service.seek(12_500)
    shuffle = await service.set_shuffle(True)
    repeat = await service.set_repeat("context")
    transfer = await service.transfer_playback("device-1", play=True)

    assert seek.position_ms == 12_500
    assert shuffle.shuffle_state is True
    assert repeat.repeat_state == "context"
    assert transfer.play is True
    assert spotify.calls[1] == (
        "PUT",
        "/me/player/seek",
        {"position_ms": 12_500, "device_id": "device-1"},
        None,
    )
    assert spotify.calls[3] == (
        "PUT",
        "/me/player/shuffle",
        {"state": True, "device_id": "device-1"},
        None,
    )
    assert spotify.calls[5] == (
        "PUT",
        "/me/player/repeat",
        {"state": "context", "device_id": "device-1"},
        None,
    )
    assert spotify.calls[7] == (
        "PUT",
        "/me/player",
        None,
        {"device_ids": ["device-1"], "play": True},
    )


@pytest.mark.anyio
async def test_new_playback_controls_validate_before_write() -> None:
    spotify = FakeSpotify([])
    service = PlaybackService(spotify)

    with pytest.raises(ValueError, match="position_ms must be non-negative"):
        await service.seek(-1)
    with pytest.raises(ValueError, match="repeat_state"):
        await service.set_repeat("all")  # type: ignore[arg-type]

    assert spotify.calls == []


@pytest.mark.anyio
async def test_new_playback_control_propagates_ambiguous_write_without_retry() -> None:
    spotify = FakeSpotify([ACTIVE_DEVICES, AmbiguousWrite("verify remote state before retrying")])

    with pytest.raises(AmbiguousWrite, match="verify remote state"):
        await PlaybackService(spotify).seek(5_000)

    assert [call[0:2] for call in spotify.calls].count(("PUT", "/me/player/seek")) == 1


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
        "spotify_seek",
        "spotify_set_shuffle",
        "spotify_set_repeat",
        "spotify_transfer_playback",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert tools["spotify_now_playing"].annotations.read_only_hint is True
    assert tools["spotify_play"].annotations.read_only_hint is False
    assert tools["spotify_pause"].annotations.idempotent_hint is True
    assert tools["spotify_adjust_volume"].annotations.read_only_hint is False
    assert tools["spotify_adjust_volume"].annotations.idempotent_hint is False
    assert tools["spotify_seek"].annotations.idempotent_hint is True
    assert tools["spotify_set_shuffle"].annotations.idempotent_hint is True
    assert tools["spotify_set_repeat"].annotations.idempotent_hint is True
    assert tools["spotify_transfer_playback"].annotations.idempotent_hint is True
