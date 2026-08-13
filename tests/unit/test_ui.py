from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.server import MCPServer

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.ui import RESULTS_UI_URI, create_results_apps


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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ConcurrentContextSpotify:
    def __init__(self) -> None:
        self.started: set[str] = set()
        self.both_started = anyio.Event()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        assert method == "GET"
        assert params is None
        assert json is None
        self.started.add(path)
        if self.started == {"/me/player/devices", "/me/player"}:
            self.both_started.set()
        with anyio.fail_after(0.1):
            await self.both_started.wait()
        if path == "/me/player/devices":
            return ACTIVE_CONTEXT_DEVICES
        return {"is_playing": False}


ACTIVE_CONTEXT_DEVICES = {
    "devices": [
        {
            "id": "device-1",
            "name": "Desk",
            "type": "Computer",
            "is_active": True,
            "is_restricted": False,
        }
    ]
}


def server_with_spotify(spotify: SpotifyGateway) -> MCPServer[AppContext]:
    @asynccontextmanager
    async def lifespan(_server: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
        yield AppContext(spotify=spotify, artifacts=object(), audio=object())  # type: ignore[arg-type]

    return MCPServer("test", extensions=[create_results_apps()], lifespan=lifespan)


@pytest.mark.anyio
async def test_results_ui_is_optional_mcp_apps_resource_with_text_fallback() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        resources = {
            str(resource.uri): resource for resource in (await client.list_resources()).resources
        }

        tool = tools["spotify_render_results"]
        route_tool = tools["spotify_render_route_approval"]
        assert tool.meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["model"]},
        }
        assert route_tool.meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["model"]},
        }
        assert "prose-only" in (route_tool.description or "")
        assert tools["spotify_results_context"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_play"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_pause"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_context"].annotations.read_only_hint is True
        assert tools["spotify_results_play"].annotations.read_only_hint is False
        assert tools["spotify_results_pause"].annotations.idempotent_hint is True
        assert "exactly once" in (tool.description or "")
        assert tool.output_schema is not None
        assert resources[RESULTS_UI_URI].mime_type == "text/html;profile=mcp-app"
        assert resources[RESULTS_UI_URI].meta == {
            "ui": {
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [
                        "https://i.scdn.co",
                        "https://image-cdn-fa.spotifycdn.com",
                        "https://mosaic.scdn.co",
                    ],
                    "frameDomains": [],
                    "baseUriDomains": [],
                },
                "prefersBorder": True,
            }
        }

        rendered = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Road-trip picks",
                "items": [
                    {
                        "name": "Open Road",
                        "spotify_url": "https://open.spotify.com/track/track-1",
                        "image_url": "https://i.scdn.co/image/track-1",
                        "subtitle": "Driver - Long Way Home",
                        "kind": "track",
                        "artists": ["Driver"],
                        "album": "Long Way Home",
                        "duration_ms": 245000,
                        "explicit": False,
                    }
                ],
            },
        )
        route_approval = await client.call_tool(
            "spotify_render_route_approval",
            {
                "title": "Approve the Bratislava route",
                "summary": "2 pins, 1.2 km",
                "pins": [
                    {"order": 1, "name": "Michael's Gate", "kind": "chapter"},
                    {"order": 2, "name": "Turn left", "kind": "navigation"},
                ],
                "route_urls": ["https://maps.google.com/?q=route"],
            },
        )
        resource = await client.read_resource(RESULTS_UI_URI)

    assert rendered.is_error is False
    assert rendered.structured_content == {
        "title": "Road-trip picks",
        "items": [
            {
                "name": "Open Road",
                "spotify_url": "https://open.spotify.com/track/track-1",
                "image_url": "https://i.scdn.co/image/track-1",
                "subtitle": "Driver - Long Way Home",
                "kind": "track",
                "reason": None,
                "artists": ["Driver"],
                "album": "Long Way Home",
                "owner": None,
                "description": None,
                "duration_ms": 245000,
                "explicit": False,
                "item_count": None,
                "release_date": None,
            }
        ],
    }
    assert rendered.content
    assert route_approval.is_error is False
    assert route_approval.structured_content == {
        "view": "route_approval",
        "title": "Approve the Bratislava route",
        "summary": "2 pins, 1.2 km",
        "pins": [
            {
                "order": 1,
                "name": "Michael's Gate",
                "kind": "chapter",
                "note": None,
                "map_url": None,
            },
            {
                "order": 2,
                "name": "Turn left",
                "kind": "navigation",
                "note": None,
                "map_url": None,
            },
        ],
        "starting_point_url": None,
        "route_urls": ["https://maps.google.com/?q=route"],
    }
    assert "Road-trip picks" in rendered.content[0].text
    html = resource.contents[0].text
    assert html is not None
    assert "ui/notifications/tool-result" in html
    assert "textContent" in html
    assert "innerHTML" not in html
    assert "noopener noreferrer" in html
    assert "--radius-container:12px" in html
    assert "--radius-control:8px" in html
    assert ".play.is-pause" in html
    assert "Approve route" in html
    assert "Adjust pins" in html
    assert "ui/message" in html


@pytest.mark.anyio
async def test_route_approval_rejects_unsafe_map_urls() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        rendered = await client.call_tool(
            "spotify_render_route_approval",
            {
                "title": "Unsafe route",
                "summary": "One pin",
                "pins": [
                    {
                        "order": 1,
                        "name": "Bad pin",
                        "kind": "chapter",
                        "map_url": "https://user:secret@127.0.0.1/route",
                    }
                ],
            },
        )

    assert rendered.is_error is True


def test_results_ui_uses_even_pixel_spacing_and_radii() -> None:
    css = Path("ui/spotify-results/src/styles.css").read_text(encoding="utf-8")
    declarations = re.findall(
        r"(?:margin(?:-[a-z]+)?|padding(?:-[a-z]+)?|gap|border-radius)\s*:\s*([^;]+)",
        css,
    )
    pixel_values = [
        int(value)
        for declaration in declarations
        for value in re.findall(r"(?<![.\d])(\d+)px", declaration)
    ]

    assert pixel_values
    assert all(value % 2 == 0 for value in pixel_values)


@pytest.mark.anyio
async def test_results_ui_normalizes_raw_search_items() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        rendered = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Latest release",
                "items": [
                    {
                        "type": "track",
                        "name": "Everybody Scream",
                        "spotify_url": "https://open.spotify.com/track/track-1",
                        "artists": ["Florence + The Machine"],
                        "album": "Everybody Scream",
                    }
                ],
            },
        )

    assert rendered.is_error is False
    assert rendered.structured_content["items"] == [
        {
            "name": "Everybody Scream",
            "spotify_url": "https://open.spotify.com/track/track-1",
            "subtitle": "Florence + The Machine • Everybody Scream",
            "kind": "track",
            "reason": None,
            "image_url": None,
            "artists": ["Florence + The Machine"],
            "album": "Everybody Scream",
            "owner": None,
            "description": None,
            "duration_ms": None,
            "explicit": None,
            "item_count": None,
            "release_date": None,
        }
    ]


@pytest.mark.anyio
async def test_results_ui_rejects_non_spotify_links() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        result = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Unsafe",
                "items": [
                    {
                        "name": "Bad link",
                        "spotify_url": "https://example.com/not-spotify",
                        "kind": "track",
                    }
                ],
            },
        )

    assert result.is_error is True


@pytest.mark.anyio
async def test_results_ui_rejects_kind_and_url_mismatch() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        result = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Mismatched",
                "items": [
                    {
                        "name": "Wrong kind",
                        "spotify_url": "https://open.spotify.com/album/album-1",
                        "kind": "track",
                    }
                ],
            },
        )

    assert result.is_error is True


@pytest.mark.anyio
async def test_results_context_selects_active_device_and_returns_observed_state() -> None:
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "device-1",
                        "name": "Desk",
                        "type": "Computer",
                        "is_active": True,
                        "is_restricted": False,
                    },
                    {
                        "id": "restricted",
                        "name": "Restricted",
                        "type": "Speaker",
                        "is_active": False,
                        "is_restricted": True,
                    },
                ]
            },
            {
                "is_playing": True,
                "device": {
                    "id": "device-1",
                    "name": "Desk",
                    "type": "Computer",
                    "is_active": True,
                },
                "item": {
                    "type": "track",
                    "id": "track-1",
                    "uri": "spotify:track:track-1",
                    "name": "Track One",
                },
            },
        ]
    )

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool("spotify_results_context", {})

    assert result.is_error is False
    assert result.structured_content["selected_device_id"] == "device-1"
    assert result.structured_content["requires_device_selection"] is False
    assert result.structured_content["has_usable_devices"] is True
    assert result.structured_content["now_playing"]["item"]["uri"] == "spotify:track:track-1"


@pytest.mark.anyio
async def test_results_context_loads_independent_spotify_reads_concurrently() -> None:
    spotify = ConcurrentContextSpotify()

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool("spotify_results_context", {})

    assert result.is_error is False
    assert spotify.started == {"/me/player/devices", "/me/player"}


@pytest.mark.anyio
async def test_results_context_requires_choice_for_multiple_inactive_devices() -> None:
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "one",
                        "name": "One",
                        "type": "Computer",
                        "is_active": False,
                        "is_restricted": False,
                    },
                    {
                        "id": "two",
                        "name": "Two",
                        "type": "Speaker",
                        "is_active": False,
                        "is_restricted": False,
                    },
                ]
            },
            {"is_playing": False},
        ]
    )

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool("spotify_results_context", {})

    assert result.structured_content["selected_device_id"] is None
    assert result.structured_content["requires_device_selection"] is True


@pytest.mark.anyio
async def test_results_context_requires_choice_for_multiple_devices_even_when_one_is_active() -> (
    None
):
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "active",
                        "name": "Wrong active device",
                        "type": "Computer",
                        "is_active": True,
                        "is_restricted": False,
                    },
                    {
                        "id": "preferred",
                        "name": "Preferred speaker",
                        "type": "Speaker",
                        "is_active": False,
                        "is_restricted": False,
                    },
                ]
            },
            {"is_playing": True},
        ]
    )

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool("spotify_results_context", {})

    assert result.structured_content["selected_device_id"] is None
    assert result.structured_content["requires_device_selection"] is True


@pytest.mark.anyio
async def test_results_play_uses_canonical_url_and_returns_verified_observation() -> None:
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "device-1",
                        "name": "Desk",
                        "type": "Computer",
                        "is_active": True,
                        "is_restricted": False,
                    }
                ]
            },
            None,
            {
                "is_playing": True,
                "device": {
                    "id": "device-1",
                    "name": "Desk",
                    "type": "Computer",
                    "is_active": True,
                },
                "item": {
                    "type": "track",
                    "id": "track-1",
                    "uri": "spotify:track:track-1",
                    "name": "Track One",
                },
            },
        ]
    )

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool(
            "spotify_results_play",
            {
                "spotify_url": "https://open.spotify.com/track/track-1",
                "device_id": "device-1",
            },
        )

    assert result.is_error is False
    assert result.structured_content["status"] == "verified"
    assert result.structured_content["requested_uri"] == "spotify:track:track-1"
    assert spotify.calls[1] == (
        "PUT",
        "/me/player/play",
        {"device_id": "device-1"},
        {"uris": ["spotify:track:track-1"]},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "spotify_url",
    [
        "https://example.com/track/track-1",
        "https://open.spotify.com/episode/episode-1",
        "https://open.spotify.com/track/track-1?si=tracking",
    ],
)
async def test_results_play_rejects_unsupported_or_noncanonical_urls_before_gateway(
    spotify_url: str,
) -> None:
    spotify = FakeSpotify([])

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool(
            "spotify_results_play",
            {"spotify_url": spotify_url, "device_id": "device-1"},
        )

    assert result.is_error is True
    assert spotify.calls == []


@pytest.mark.anyio
async def test_results_pause_targets_the_selected_device() -> None:
    spotify = FakeSpotify(
        [
            {
                "devices": [
                    {
                        "id": "device-1",
                        "name": "Desk",
                        "type": "Computer",
                        "is_active": True,
                        "is_restricted": False,
                    }
                ]
            },
            None,
        ]
    )

    async with Client(server_with_spotify(spotify)) as client:
        result = await client.call_tool(
            "spotify_results_pause",
            {"device_id": "device-1"},
        )

    assert result.is_error is False
    assert result.structured_content["operation"] == "pause"
    assert spotify.calls[1] == (
        "PUT",
        "/me/player/pause",
        {"device_id": "device-1"},
        None,
    )
