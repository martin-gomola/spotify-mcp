from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.discovery import DiscoveryService
from spotify_mcp.domain.links import SpotifyEntityType, spotify_web_url
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
                            "album": {
                                "name": "Open Road",
                                "images": [{"url": "https://i.scdn.co/image/album-1"}],
                            },
                            "duration_ms": 245000,
                            "explicit": False,
                        }
                    ],
                }
            }
        ]
    )

    result = await DiscoveryService(spotify).search("road", "track", limit=10, offset=20)

    assert result.items[0].artists == ["Driver"]
    assert result.items[0].spotify_url == "https://open.spotify.com/track/track-1"
    assert result.items[0].image_url == "https://i.scdn.co/image/album-1"
    assert result.items[0].duration_ms == 245000
    assert result.items[0].explicit is False
    assert spotify.calls == [
        (
            "GET",
            "/search",
            {"q": "road", "type": "track", "limit": 10, "offset": 20, "market": "from_token"},
            None,
        )
    ]


@pytest.mark.parametrize(
    "entity_type",
    ["track", "album", "artist", "playlist", "episode", "show"],
)
def test_spotify_url_supports_public_entity_types(entity_type: SpotifyEntityType) -> None:
    assert spotify_web_url(entity_type, f"{entity_type}-1") == (
        f"https://open.spotify.com/{entity_type}/{entity_type}-1"
    )


def test_spotify_url_normalises_uris_and_rejects_invalid_ids() -> None:
    assert spotify_web_url("episode", "spotify:episode:episode-1") == (
        "https://open.spotify.com/episode/episode-1"
    )

    with pytest.raises(ValueError, match="does not match"):
        spotify_web_url("track", "spotify:album:album-1")
    with pytest.raises(ValueError, match="invalid"):
        spotify_web_url("show", "bad/id")
    with pytest.raises(ValueError, match="must not be empty"):
        spotify_web_url("artist", "  ")


@pytest.mark.anyio
async def test_search_links_podcast_entities_and_rejects_invalid_external_urls() -> None:
    spotify = FakeSpotify(
        [
            {
                "shows": {
                    "items": [
                        {
                            "id": "show-1",
                            "name": "Road Stories",
                            "external_urls": {"spotify": "https://example.test/not-spotify/show-1"},
                        }
                    ]
                }
            },
            {
                "episodes": {
                    "items": [
                        {
                            "id": "episode-1",
                            "uri": "spotify:episode:episode-1",
                            "name": "The Long Drive",
                            "external_urls": {
                                "spotify": "https://open.spotify.com/episode/episode-1"
                            },
                        }
                    ]
                }
            },
        ]
    )
    service = DiscoveryService(spotify)

    show = await service.search("road", "show")
    episode = await service.search("drive", "episode")

    assert show.items[0].spotify_url == "https://open.spotify.com/show/show-1"
    assert episode.items[0].spotify_url == "https://open.spotify.com/episode/episode-1"


@pytest.mark.anyio
async def test_search_preserves_collection_metadata_and_artwork() -> None:
    spotify = FakeSpotify(
        [
            {
                "playlists": {
                    "items": [
                        {
                            "id": "playlist-1",
                            "name": "Morning Run",
                            "owner": {"display_name": "Runner"},
                            "description": "Warm-up through cool-down",
                            "tracks": {"total": 23},
                            "images": [{"url": "https://mosaic.scdn.co/640/playlist-1"}],
                        }
                    ]
                }
            },
            {
                "albums": {
                    "items": [
                        {
                            "id": "album-1",
                            "name": "Morning Run Album",
                            "total_tracks": 12,
                            "release_date": "2026-08-12",
                            "images": [{"url": "https://i.scdn.co/image/album-1"}],
                        }
                    ]
                }
            },
        ]
    )

    result = await DiscoveryService(spotify).search("morning", "playlist")
    album_result = await DiscoveryService(spotify).search("morning", "album")

    assert result.items[0].owner == "Runner"
    assert result.items[0].description == "Warm-up through cool-down"
    assert result.items[0].item_count == 23
    assert result.items[0].image_url == "https://mosaic.scdn.co/640/playlist-1"
    assert album_result.items[0].item_count == 12
    assert album_result.items[0].release_date == "2026-08-12"
    assert album_result.items[0].image_url == "https://i.scdn.co/image/album-1"


@pytest.mark.anyio
async def test_top_entities_preserve_spotify_artwork() -> None:
    spotify = FakeSpotify(
        [
            {
                "items": [
                    {
                        "id": "track-1",
                        "name": "Track",
                        "album": {
                            "images": [{"url": "https://image-cdn-fa.spotifycdn.com/image/track-1"}]
                        },
                    }
                ]
            },
            {
                "items": [
                    {
                        "id": "artist-1",
                        "name": "Artist",
                        "images": [{"url": "https://mosaic.scdn.co/640/artist-1"}],
                    }
                ]
            },
        ]
    )
    service = DiscoveryService(spotify)

    tracks = await service.top_tracks()
    artists = await service.top_artists()

    assert tracks.tracks[0].image_url == ("https://image-cdn-fa.spotifycdn.com/image/track-1")
    assert artists.artists[0].image_url == "https://mosaic.scdn.co/640/artist-1"


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
