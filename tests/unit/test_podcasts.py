from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.podcasts import PodcastService
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.podcasts import register


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


def show(show_id: str = "show-1") -> dict[str, Any]:
    return {
        "id": show_id,
        "uri": f"spotify:show:{show_id}",
        "name": "Deep Signals",
        "description": "Long-form interviews",
        "publisher": "Signal House",
        "languages": ["en", "sk"],
        "explicit": False,
        "total_episodes": 42,
        "external_urls": {"spotify": "https://evil.invalid/not-canonical"},
    }


def episode(episode_id: str = "episode-1") -> dict[str, Any]:
    return {
        "id": episode_id,
        "uri": f"spotify:episode:{episode_id}",
        "name": "The First Signal",
        "description": "An episode",
        "release_date": "2026-08-11",
        "duration_ms": 123_000,
        "explicit": True,
        "languages": ["en"],
        "is_playable": False,
        "restrictions": {"reason": "market"},
        "audio_preview_url": None,
        "audio": "must-not-be-exposed",
        "external_urls": {"spotify": "https://evil.invalid/not-canonical"},
    }


@pytest.mark.anyio
async def test_discover_searches_shows_and_episodes_with_one_bounded_request() -> None:
    spotify = FakeSpotify(
        [
            {
                "shows": {"total": 12, "items": [show()]},
                "episodes": {"total": 8, "items": [episode()]},
            }
        ]
    )

    result = await PodcastService(spotify).discover("signals", limit=10, offset=20)

    assert result.show_total == 12
    assert result.episode_total == 8
    assert result.shows[0].spotify_url == "https://open.spotify.com/show/show-1"
    assert result.episodes[0].spotify_url == "https://open.spotify.com/episode/episode-1"
    assert result.episodes[0].is_playable is False
    assert result.episodes[0].restrictions.reason == "market"
    assert result.episodes[0].audio_preview_url is None
    assert "audio" not in result.episodes[0].model_dump()
    assert spotify.calls == [
        (
            "GET",
            "/search",
            {
                "q": "signals",
                "type": "show,episode",
                "limit": 10,
                "offset": 20,
                "market": "from_token",
            },
            None,
        )
    ]


@pytest.mark.anyio
async def test_discover_rejects_more_than_ten_results_per_type() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match="between 1 and 10"):
        await PodcastService(spotify).discover("signals", limit=11)

    assert spotify.calls == []


@pytest.mark.anyio
async def test_get_show_and_episode_use_singular_market_aware_endpoints() -> None:
    spotify = FakeSpotify([show(), episode()])
    service = PodcastService(spotify)

    found_show = await service.get_show("spotify:show:show-1")
    found_episode = await service.get_episode("spotify:episode:episode-1")

    assert found_show.id == "show-1"
    assert found_episode.id == "episode-1"
    assert spotify.calls == [
        ("GET", "/shows/show-1", {"market": "from_token"}, None),
        ("GET", "/episodes/episode-1", {"market": "from_token"}, None),
    ]


@pytest.mark.anyio
async def test_exact_reads_reject_a_mismatched_spotify_uri_before_transport() -> None:
    spotify = FakeSpotify([])

    with pytest.raises(ValueError, match="does not match expected 'show'"):
        await PodcastService(spotify).get_show("spotify:episode:episode-1")

    assert spotify.calls == []


@pytest.mark.anyio
async def test_show_episodes_are_bounded_and_preserve_paging_evidence() -> None:
    spotify = FakeSpotify(
        [{"total": 101, "limit": 2, "offset": 4, "next": "next", "items": [episode()]}]
    )

    result = await PodcastService(spotify).get_show_episodes(
        "spotify:show:show-1", limit=2, offset=4
    )

    assert result.show_id == "show-1"
    assert result.total == 101
    assert result.limit == 2
    assert result.offset == 4
    assert result.next_url == "next"
    assert spotify.calls == [
        (
            "GET",
            "/shows/show-1/episodes",
            {"limit": 2, "offset": 4, "market": "from_token"},
            None,
        )
    ]


@pytest.mark.anyio
async def test_saved_shows_and_episodes_use_current_library_endpoints() -> None:
    spotify = FakeSpotify(
        [
            {"total": 1, "items": [{"added_at": "2026-08-01T10:00:00Z", "show": show()}]},
            {
                "total": 1,
                "items": [{"added_at": "2026-08-02T10:00:00Z", "episode": episode()}],
            },
        ]
    )
    service = PodcastService(spotify)

    saved_shows = await service.get_saved_shows(limit=5, offset=10)
    saved_episodes = await service.get_saved_episodes(limit=6, offset=12)

    assert saved_shows.items[0].added_at == "2026-08-01T10:00:00Z"
    assert saved_shows.items[0].show.id == "show-1"
    assert saved_episodes.items[0].added_at == "2026-08-02T10:00:00Z"
    assert saved_episodes.items[0].episode.id == "episode-1"
    assert spotify.calls == [
        ("GET", "/me/shows", {"limit": 5, "offset": 10}, None),
        (
            "GET",
            "/me/episodes",
            {"limit": 6, "offset": 12, "market": "from_token"},
            None,
        ),
    ]


@pytest.mark.anyio
async def test_podcast_pages_reject_unbounded_or_negative_pagination() -> None:
    spotify = FakeSpotify([])
    service = PodcastService(spotify)

    with pytest.raises(ValueError, match="between 1 and 50"):
        await service.get_saved_shows(limit=51)
    with pytest.raises(ValueError, match="non-negative"):
        await service.get_saved_episodes(offset=-1)

    assert spotify.calls == []


@pytest.mark.anyio
async def test_podcast_tools_are_structured_and_read_only() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_podcast_discover",
        "spotify_podcast_show",
        "spotify_podcast_show_episodes",
        "spotify_podcast_episode",
        "spotify_saved_shows",
        "spotify_saved_episodes",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    discover_limit = tools["spotify_podcast_discover"].input_schema["properties"]["limit"]
    assert discover_limit["maximum"] == 10
    for name in (
        "spotify_podcast_show_episodes",
        "spotify_saved_shows",
        "spotify_saved_episodes",
    ):
        assert tools[name].input_schema["properties"]["limit"]["maximum"] == 50
