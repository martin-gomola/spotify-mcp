from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer

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


def server_with_spotify(spotify: FakeSpotify) -> MCPServer[AppContext]:
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
        assert tool.meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["model"]},
        }
        assert tools["spotify_results_context"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_play"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_context"].annotations.read_only_hint is True
        assert tools["spotify_results_play"].annotations.read_only_hint is False
        assert tool.output_schema is not None
        assert resources[RESULTS_UI_URI].mime_type == "text/html;profile=mcp-app"
        assert resources[RESULTS_UI_URI].meta == {
            "ui": {
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
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
                        "subtitle": "Driver - Long Way Home",
                        "kind": "track",
                    }
                ],
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
                "subtitle": "Driver - Long Way Home",
                "kind": "track",
                "reason": None,
            }
        ],
    }
    assert rendered.content
    assert "Road-trip picks" in rendered.content[0].text
    html = resource.contents[0].text
    assert html is not None
    assert "ui/notifications/tool-result" in html
    assert "textContent" in html
    assert "innerHTML" not in html
    assert "noopener noreferrer" in html


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
