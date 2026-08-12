from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.albums import (
    get_album_tracks,
    get_albums,
    get_saved_albums,
)
from spotify_mcp.domain.errors import SpotifyRequestError
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.albums import register


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


def album(album_id: str) -> dict[str, Any]:
    return {
        "id": album_id,
        "uri": f"spotify:album:{album_id}",
        "name": f"Album {album_id}",
        "artists": [{"name": "Artist"}],
        "release_date": "2026-08-11",
        "total_tracks": 10,
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
    }


@pytest.mark.anyio
async def test_albums_use_singular_endpoint_and_report_unknown_ids() -> None:
    spotify = FakeSpotify(
        [album("a"), SpotifyRequestError("not found", status_code=404), album("c")]
    )

    result = await get_albums(spotify, ["a", "missing", "spotify:album:c"])

    assert [item.id for item in result.albums] == ["a", "c"]
    assert result.albums[0].spotify_url == "https://open.spotify.com/album/a"
    assert result.missing_ids == ["missing"]
    assert [call[1] for call in spotify.calls] == ["/albums/a", "/albums/missing", "/albums/c"]
    assert all(call[2] is None for call in spotify.calls)


@pytest.mark.anyio
async def test_album_tracks_use_current_paginated_endpoint_and_tolerate_missing_fields() -> None:
    spotify = FakeSpotify(
        [
            {
                "total": 2,
                "items": [
                    {
                        "id": "track-1",
                        "name": "First",
                        "artists": [{"name": "Artist"}],
                        "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
                    },
                    None,
                ],
            }
        ]
    )

    result = await get_album_tracks(spotify, "spotify:album:a", limit=2, offset=5)

    assert result.album_id == "a"
    assert result.total == 2
    assert result.tracks[0].duration_ms is None
    assert result.tracks[0].spotify_url == "https://open.spotify.com/track/track-1"
    assert spotify.calls == [("GET", "/albums/a/tracks", {"limit": 2, "offset": 5}, None)]


@pytest.mark.anyio
async def test_saved_albums_preserve_added_timestamp_and_paging() -> None:
    spotify = FakeSpotify(
        [{"total": 11, "items": [{"added_at": "2026-01-01T00:00:00Z", "album": album("a")}]}]
    )

    result = await get_saved_albums(spotify, limit=1, offset=10)

    assert result.total == 11
    assert result.albums[0].added_at == "2026-01-01T00:00:00Z"
    assert result.albums[0].album.external_url == "https://open.spotify.com/album/a"
    assert spotify.calls == [("GET", "/me/albums", {"limit": 1, "offset": 10}, None)]


@pytest.mark.anyio
async def test_album_tools_are_structured_snake_case_and_accurately_annotated() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_albums",
        "spotify_album_tracks",
        "spotify_saved_albums",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert tools["spotify_albums"].annotations.read_only_hint is True
