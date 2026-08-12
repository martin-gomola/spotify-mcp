from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.playlists import (
    add_playlist_items,
    create_playlist,
    get_playlist,
    get_playlist_items,
    list_playlists,
    remove_playlist_items,
    reorder_playlist_items,
    unfollow_playlist,
    update_playlist,
)
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.playlists import register


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


def playlist_metadata(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": "p1",
        "name": "Road Trip",
        "description": "Open road",
        "owner": {"id": "me", "display_name": "Me"},
        "items": {"total": 26},
        "public": False,
        "collaborative": False,
        "snapshot_id": "snapshot-1",
        "images": [{"url": "https://mosaic.scdn.co/640/playlist-cover"}],
        "external_urls": {"spotify": "https://open.spotify.com/playlist/p1"},
    }
    value.update(overrides)
    return value


@pytest.mark.anyio
async def test_playlist_reads_use_current_item_counts_and_items_endpoint() -> None:
    spotify = FakeSpotify(
        [
            {
                "total": 1,
                "items": [
                    {
                        "id": "p1",
                        "name": "Road Trip",
                        "items": {"total": 26},
                        "public": False,
                        "images": [{"url": "https://i.scdn.co/image/playlist-cover"}],
                        "external_urls": {"spotify": "https://open.spotify.com/playlist/p1"},
                    }
                ],
            },
            playlist_metadata(),
            {
                "total": 2,
                "items": [
                    {
                        "item": {
                            "type": "track",
                            "id": "t1",
                            "name": "Track",
                            "artists": [{"name": "Artist"}],
                            "duration_ms": 100,
                            "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
                        }
                    },
                    {"item": None},
                ],
            },
        ]
    )

    playlists = await list_playlists(spotify)
    details = await get_playlist(spotify, "spotify:playlist:p1")
    items = await get_playlist_items(spotify, "p1")

    assert playlists.playlists[0].item_count == 26
    assert playlists.playlists[0].spotify_url == "https://open.spotify.com/playlist/p1"
    assert playlists.playlists[0].image_url == "https://i.scdn.co/image/playlist-cover"
    assert details.item_count == 26
    assert details.spotify_url == "https://open.spotify.com/playlist/p1"
    assert details.image_url == "https://mosaic.scdn.co/640/playlist-cover"
    assert items.items[0].spotify_url == "https://open.spotify.com/track/t1"
    assert items.items[1].type == "unknown"
    assert spotify.calls[-1] == (
        "GET",
        "/playlists/p1/items",
        {"limit": 50, "offset": 0, "additional_types": "track,episode"},
        None,
    )


@pytest.mark.anyio
async def test_create_reports_visibility_mismatch_without_second_write() -> None:
    spotify = FakeSpotify(
        [
            {"id": "p1", "external_urls": {"spotify": "https://example.test/p1"}},
            playlist_metadata(public=True),
        ]
    )

    result = await create_playlist(spotify, name="Road Trip", public=False)

    assert result.status == "mismatch"
    assert result.visibility_status == "mismatch"
    assert result.spotify_url == "https://open.spotify.com/playlist/p1"
    assert result.image_url == "https://mosaic.scdn.co/640/playlist-cover"
    assert result.observed_public is True
    assert [call[0] for call in spotify.calls] == ["POST", "GET"]


@pytest.mark.anyio
async def test_update_verifies_each_requested_field_once() -> None:
    spotify = FakeSpotify([None, playlist_metadata(name="Old", public=False)])

    result = await update_playlist(spotify, "p1", name="New", public=False)

    assert result.status == "mismatch"
    assert result.spotify_url == "https://open.spotify.com/playlist/p1"
    assert result.mismatches == ["name: requested 'New', observed 'Old'"]
    assert [call[0] for call in spotify.calls] == ["PUT", "GET"]


@pytest.mark.anyio
async def test_update_reports_failed_verification_as_ambiguous() -> None:
    spotify = FakeSpotify([None, RuntimeError("read unavailable")])

    result = await update_playlist(spotify, "p1", public=False)

    assert result.status == "ambiguous"
    assert (
        result.warning == "Spotify accepted the update, but verification failed: read unavailable"
    )
    assert len(spotify.calls) == 2


@pytest.mark.anyio
async def test_playlist_writes_return_typed_ambiguity_on_transport_failure() -> None:
    from spotify_mcp.domain.errors import AmbiguousWrite

    create = await create_playlist(
        FakeSpotify([AmbiguousWrite("create outcome unknown")]), name="Road Trip"
    )
    update = await update_playlist(
        FakeSpotify([AmbiguousWrite("update outcome unknown")]), "p1", public=False
    )
    add = await add_playlist_items(
        FakeSpotify([AmbiguousWrite("add outcome unknown")]), "p1", ["t1"]
    )
    unfollow = await unfollow_playlist(
        FakeSpotify([AmbiguousWrite("unfollow outcome unknown")]), "p1"
    )

    assert create.visibility_status == "unknown"
    assert create.status == "ambiguous"
    assert create.playlist_id is None
    assert update.status == "ambiguous"
    assert add.status == "ambiguous"
    assert unfollow.status == "ambiguous"


@pytest.mark.anyio
async def test_create_reports_success_without_identifier_as_ambiguous() -> None:
    result = await create_playlist(FakeSpotify([{}]), name="Road Trip")

    assert result.status == "ambiguous"
    assert result.playlist_id is None
    assert result.warning and "without a playlist ID" in result.warning


@pytest.mark.anyio
async def test_unfollow_rejects_missing_membership_evidence() -> None:
    spotify = FakeSpotify([None, []])

    result = await unfollow_playlist(spotify, "p1")

    assert result.status == "ambiguous"
    assert result.warning and "malformed playlist membership evidence" in result.warning


@pytest.mark.anyio
async def test_add_returns_accepted_snapshot_and_preserves_episode_uri() -> None:
    spotify = FakeSpotify([{"snapshot_id": "snap-2"}])

    result = await add_playlist_items(spotify, "p1", ["t1", "spotify:episode:e1"], position=3)

    assert result.status == "accepted"
    assert result.snapshot_id == "snap-2"
    assert result.spotify_url == "https://open.spotify.com/playlist/p1"
    assert spotify.calls[0] == (
        "POST",
        "/playlists/p1/items",
        None,
        {"uris": ["spotify:track:t1", "spotify:episode:e1"], "position": 3},
    )


@pytest.mark.anyio
async def test_remove_and_reorder_report_missing_snapshots_as_ambiguous() -> None:
    spotify = FakeSpotify([{}, None])

    removed = await remove_playlist_items(spotify, "p1", ["t1"], snapshot_id="before")
    reordered = await reorder_playlist_items(
        spotify,
        "p1",
        range_start=0,
        insert_before=4,
        range_length=2,
        snapshot_id="before",
    )

    assert removed.status == "ambiguous"
    assert reordered.status == "ambiguous"
    assert [call[1] for call in spotify.calls] == [
        "/playlists/p1/items",
        "/playlists/p1/items",
    ]
    assert len(spotify.calls) == 2


@pytest.mark.anyio
async def test_unfollow_uses_shared_library_endpoint_and_verifies() -> None:
    spotify = FakeSpotify([None, [False]])

    result = await unfollow_playlist(spotify, "p1")

    assert result.status == "verified"
    assert spotify.calls == [
        ("DELETE", "/me/library", {"uris": "spotify:playlist:p1"}, None),
        ("GET", "/me/library/contains", {"uris": "spotify:playlist:p1"}, None),
    ]


@pytest.mark.anyio
async def test_playlist_tools_are_typed_and_accurately_annotated() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_playlists",
        "spotify_playlist",
        "spotify_playlist_items",
        "spotify_playlist_create",
        "spotify_playlist_update",
        "spotify_playlist_add",
        "spotify_playlist_remove",
        "spotify_playlist_reorder",
        "spotify_playlist_unfollow",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert tools["spotify_playlist"].annotations.read_only_hint is True
    assert tools["spotify_playlist_create"].annotations.idempotent_hint is False
    remove_annotations = tools["spotify_playlist_remove"].annotations
    assert remove_annotations.destructive_hint is True
    assert remove_annotations.idempotent_hint is True
