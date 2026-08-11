from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.recommendations import taste_recommendations
from spotify_mcp.domain.errors import AuthenticationRequired, SpotifyRequestError
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.recommendations import register


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


def track(track_id: str, name: str | None = None) -> dict[str, Any]:
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name or f"Track {track_id}",
        "artists": [{"name": "Artist"}],
        "album": {"name": "Album"},
        "duration_ms": 123_000,
    }


def saved(track_id: str, position: int = 0) -> dict[str, Any]:
    return {
        "added_at": f"202{position}-01-01T00:00:00Z",
        "track": track(track_id),
    }


@pytest.mark.anyio
async def test_taste_recommendations_are_local_deterministic_and_exclude_recent() -> None:
    spotify = FakeSpotify(
        [
            {"items": [track("both"), track("top"), track("recent-top")]},
            {"items": [{"played_at": "2026-08-11T08:00:00Z", "track": track("recent-top")}]},
            {
                "total": 3,
                "items": [saved("liked"), saved("both", 1), saved("recent-top", 2)],
            },
            {"items": [saved("both", 1)]},
            {"items": [saved("recent-top", 2)]},
        ]
    )

    result = await taste_recommendations(spotify, limit=3)

    assert result.schema_version == 1
    assert result.strategy_version == "local-deterministic-v1"
    assert result.is_spotify_recommendation is False
    assert result.curation == "local-deterministic"
    assert [item.id for item in result.tracks] == ["both", "liked", "top"]
    assert result.tracks[0].source_signals == ["top_tracks", "liked_songs"]
    assert result.tracks[0].reasons == [
        "Appears in the medium-term top tracks signal.",
        "Selected from the stratified Liked Songs history sample.",
    ]
    assert result.tracks[0].spotify_url == "https://open.spotify.com/track/both"
    assert [coverage.signal for coverage in result.source_signal_coverage] == [
        "top_tracks",
        "recently_played",
        "liked_songs",
    ]
    assert all(coverage.available for coverage in result.source_signal_coverage)
    assert all(call[1] != "/recommendations" for call in spotify.calls)


@pytest.mark.anyio
async def test_taste_recommendations_reintroduce_recent_tracks_with_warning_when_needed() -> None:
    spotify = FakeSpotify(
        [
            {"items": [track("fresh"), track("recent-a"), track("recent-b")]},
            {
                "items": [
                    {"track": track("recent-a")},
                    {"track": track("recent-b")},
                ]
            },
            {"total": 3, "items": [saved("fresh"), saved("recent-a"), saved("recent-b")]},
            {"items": [saved("recent-a")]},
            {"items": [saved("recent-b")]},
        ]
    )

    result = await taste_recommendations(spotify, limit=3)

    assert [item.id for item in result.tracks] == ["fresh", "recent-a", "recent-b"]
    assert result.tracks[1].source_signals == [
        "top_tracks",
        "liked_songs",
        "recently_played",
    ]
    assert any("recently played" in warning for warning in result.warnings)


@pytest.mark.anyio
async def test_taste_recommendations_keep_partial_results_and_report_signal_failure() -> None:
    spotify = FakeSpotify(
        [
            SpotifyRequestError("top unavailable"),
            {"items": []},
            {"total": 2, "items": [saved("b"), saved("a")]},
            {"items": [saved("a")]},
        ]
    )

    result = await taste_recommendations(spotify, limit=2)

    assert [item.id for item in result.tracks] == ["b", "a"]
    assert result.source_signal_coverage[0].available is False
    assert result.source_signal_coverage[0].warning == "top_tracks unavailable: top unavailable"
    assert result.warnings == ["top_tracks unavailable: top unavailable"]


@pytest.mark.anyio
async def test_taste_recommendations_validate_limit_before_reading_spotify() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match="between 1 and 50"):
        await taste_recommendations(spotify, limit=0)

    assert spotify.calls == []


@pytest.mark.anyio
async def test_taste_recommendations_do_not_hide_missing_authentication() -> None:
    spotify = FakeSpotify([AuthenticationRequired("connect Spotify")])

    with pytest.raises(AuthenticationRequired, match="connect Spotify"):
        await taste_recommendations(spotify)


@pytest.mark.anyio
async def test_taste_recommendations_tool_is_typed_bounded_and_read_only() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {"spotify_taste_recommendations"}
    tool = tools["spotify_taste_recommendations"]
    assert tool.output_schema is not None
    assert tool.annotations and tool.annotations.read_only_hint is True
    assert tool.input_schema["properties"]["limit"]["minimum"] == 1
    assert tool.input_schema["properties"]["limit"]["maximum"] == 50
    assert "local" in tool.description.lower()
    assert "spotify-native" not in tool.description.lower()
