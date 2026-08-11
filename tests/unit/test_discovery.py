from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.discovery import DiscoveryService
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.discovery import register


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
        return self.responses.pop(0)


@pytest.mark.anyio
async def test_search_uses_current_endpoint_and_caps_results() -> None:
    spotify = FakeSpotify(
        [
            {
                "tracks": {
                    "total": 1,
                    "items": [
                        {
                            "id": "track-1",
                            "uri": "spotify:track:track-1",
                            "name": "Road Song",
                            "artists": [{"name": "Driver"}],
                            "album": {"name": "Open Road"},
                        }
                    ],
                }
            }
        ]
    )

    result = await DiscoveryService(spotify).search("road", "track", limit=10, offset=20)

    assert result.items[0].artists == ["Driver"]
    assert result.items[0].duration_ms is None
    assert spotify.calls == [
        (
            "GET",
            "/search",
            {"q": "road", "type": "track", "limit": 10, "offset": 20, "market": "from_token"},
            None,
        )
    ]


@pytest.mark.anyio
async def test_search_rejects_more_than_ten_results() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match="between 1 and 10"):
        await DiscoveryService(spotify).search("road", "track", limit=11)

    assert spotify.calls == []


@pytest.mark.anyio
async def test_recent_and_top_tracks_tolerate_omitted_2026_fields() -> None:
    spotify = FakeSpotify(
        [
            {
                "items": [
                    {
                        "played_at": "2026-08-11T08:00:00Z",
                        "track": {"id": "one", "name": "One", "artists": []},
                    }
                ]
            },
            {"items": [{"id": "two", "name": "Two", "artists": [{"name": "A"}]}]},
        ]
    )
    service = DiscoveryService(spotify)

    recent = await service.recently_played(limit=5)
    top = await service.top_tracks(time_range="short_term", limit=7)

    assert recent.tracks[0].played_at == "2026-08-11T08:00:00Z"
    assert recent.tracks[0].album is None
    assert top.tracks[0].popularity is None
    assert spotify.calls[0][1:3] == ("/me/player/recently-played", {"limit": 5})
    assert spotify.calls[1][1:3] == (
        "/me/top/tracks",
        {"time_range": "short_term", "limit": 7},
    )


@pytest.mark.anyio
async def test_top_artists_preserves_unavailable_genres_and_popularity() -> None:
    spotify = FakeSpotify([{"items": [{"id": "artist-1", "name": "Minimal Artist"}]}])

    result = await DiscoveryService(spotify).top_artists()

    assert result.artists[0].genres is None
    assert result.artists[0].popularity is None


@pytest.mark.anyio
async def test_top_artists_preserves_an_explicit_empty_genre_list() -> None:
    spotify = FakeSpotify([{"items": [{"id": "artist-1", "name": "Minimal Artist", "genres": []}]}])

    result = await DiscoveryService(spotify).top_artists()

    assert result.artists[0].genres == []


@pytest.mark.anyio
async def test_discovery_tools_have_spotify_names_structured_outputs_and_read_annotations() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_search",
        "spotify_recently_played",
        "spotify_top_tracks",
        "spotify_top_artists",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    search_limit = tools["spotify_search"].input_schema["properties"]["limit"]
    assert search_limit["maximum"] == 10
