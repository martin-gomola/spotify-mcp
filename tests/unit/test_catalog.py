from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.catalog import CatalogService
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.catalog import register


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
async def test_catalog_routes_exact_track_and_artist_reads() -> None:
    spotify = FakeSpotify(
        [
            {
                "id": "track-1",
                "name": "Track",
                "uri": "spotify:track:track-1",
                "artists": [{"name": "Artist"}],
                "album": {
                    "name": "Album",
                    "images": [{"url": "https://i.scdn.co/image/album"}],
                },
            },
            {
                "id": "artist-1",
                "name": "Artist",
                "uri": "spotify:artist:artist-1",
                "images": [{"url": "https://i.scdn.co/image/artist"}],
            },
        ]
    )
    service = CatalogService(spotify)

    track = await service.get("track", "spotify:track:track-1")
    artist = await service.get("artist", "spotify:artist:artist-1")

    assert track.track and track.track.spotify_url == "https://open.spotify.com/track/track-1"
    assert track.track.artists == ["Artist"]
    assert artist.artist and artist.artist.image_url == "https://i.scdn.co/image/artist"
    assert spotify.calls == [
        ("GET", "/tracks/track-1", {"market": "from_token"}, None),
        ("GET", "/artists/artist-1", None, None),
    ]


@pytest.mark.anyio
async def test_catalog_routes_artist_albums_with_current_limits() -> None:
    spotify = FakeSpotify(
        [
            {
                "total": 1,
                "items": [
                    {
                        "id": "album-1",
                        "name": "Album",
                        "uri": "spotify:album:album-1",
                        "artists": [{"name": "Artist"}],
                        "album_type": "album",
                        "release_date": "2026-08-12",
                        "total_tracks": 11,
                        "images": [{"url": "https://i.scdn.co/image/album"}],
                    }
                ],
            }
        ]
    )

    result = await CatalogService(spotify).get(
        "artist_albums",
        "artist-1",
        include_groups=["album", "single"],
        limit=10,
        offset=20,
    )

    assert result.albums and result.albums.total == 1
    assert result.albums.items[0].spotify_url == "https://open.spotify.com/album/album-1"
    assert spotify.calls == [
        (
            "GET",
            "/artists/artist-1/albums",
            {
                "include_groups": "album,single",
                "market": "from_token",
                "limit": 10,
                "offset": 20,
            },
            None,
        )
    ]


@pytest.mark.anyio
async def test_catalog_is_one_read_only_routed_tool() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {"spotify_catalog"}
    tool = tools["spotify_catalog"]
    assert tool.annotations and tool.annotations.read_only_hint is True
    assert tool.input_schema["properties"]["route"]["enum"] == [
        "track",
        "artist",
        "artist_albums",
    ]
    assert tool.input_schema["properties"]["limit"]["maximum"] == 10
