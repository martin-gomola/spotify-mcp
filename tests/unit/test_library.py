from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.library import (
    check_saved_tracks,
    get_saved_tracks,
    remove_saved_tracks,
    sample_saved_tracks,
    save_tracks,
    stratified_sample_ranges,
)
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools.library import register


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


def saved_item(track_id: str, added_at: str = "2026-01-01T00:00:00Z") -> dict[str, Any]:
    return {
        "added_at": added_at,
        "track": {
            "id": track_id,
            "uri": f"spotify:track:{track_id}",
            "name": f"Track {track_id}",
            "artists": [{"name": "Artist"}],
            "album": {"name": "Album"},
            "duration_ms": 123_000,
        },
    }


@pytest.mark.anyio
async def test_saved_tracks_page_uses_paging_and_keeps_library_positions() -> None:
    spotify = FakeSpotify([{"total": 80, "items": [saved_item("a"), {"track": None}]}])

    result = await get_saved_tracks(spotify, limit=2, offset=50)

    assert result.total == 80
    assert result.tracks[0].library_position == 51
    assert result.warnings == ["Skipped unavailable item at Liked Songs position 52"]
    assert spotify.calls == [("GET", "/me/tracks", {"limit": 2, "offset": 50}, None)]


def test_stratified_ranges_are_deterministic_and_span_history() -> None:
    ranges = stratified_sample_ranges(1_000, 48)

    assert ranges == [
        (0, 6),
        (184, 6),
        (309, 6),
        (434, 6),
        (559, 6),
        (684, 6),
        (809, 6),
        (994, 6),
    ]


@pytest.mark.anyio
async def test_sample_saved_tracks_reuses_first_page_and_preserves_offsets() -> None:
    spotify = FakeSpotify(
        [
            {"total": 16, "items": [saved_item(str(index)) for index in range(16)]},
            *[
                {"items": [saved_item(str(offset)), saved_item(str(offset + 1))]}
                for offset in (2, 4, 6, 8, 10, 12, 14)
            ],
        ]
    )

    result = await sample_saved_tracks(spotify, sample_size=16)

    assert result.sampled_count == 16
    assert result.sampled_offsets == [0, 2, 4, 6, 8, 10, 12, 14]
    assert len(spotify.calls) == 8
    assert spotify.calls[0][2] == {"limit": 50, "offset": 0}


@pytest.mark.anyio
async def test_contains_uses_current_library_endpoint_and_exact_uris() -> None:
    spotify = FakeSpotify([[True, False]])

    result = await check_saved_tracks(spotify, ["a", "spotify:track:b"])

    assert result.saved == [True, False]
    assert spotify.calls == [
        (
            "GET",
            "/me/library/contains",
            {"uris": "spotify:track:a,spotify:track:b"},
            None,
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("response", [None, [], [False], [False, None]])
async def test_contains_rejects_incomplete_or_malformed_evidence(response: Any) -> None:
    spotify = FakeSpotify([response])

    with pytest.raises(Exception, match="malformed library membership evidence"):
        await check_saved_tracks(spotify, ["a", "b"])


@pytest.mark.anyio
async def test_library_writes_verify_once_without_retrying() -> None:
    spotify = FakeSpotify([None, [True, False], None, [False, True]])

    saved = await save_tracks(spotify, ["a", "b"])
    removed = await remove_saved_tracks(spotify, ["a", "b"])

    assert saved.status == "mismatch"
    assert saved.mismatches == ["b: expected saved=True, observed saved=False"]
    assert removed.status == "mismatch"
    assert removed.mismatches == ["b: expected saved=False, observed saved=True"]
    assert [call[0] for call in spotify.calls] == ["PUT", "GET", "DELETE", "GET"]


@pytest.mark.anyio
async def test_library_write_reports_failed_verification_as_ambiguous() -> None:
    spotify = FakeSpotify([None, RuntimeError("read unavailable")])

    result = await save_tracks(spotify, ["a"])

    assert result.status == "ambiguous"
    assert result.warning == "Spotify accepted the write, but verification failed: read unavailable"
    assert len(spotify.calls) == 2


@pytest.mark.anyio
async def test_library_write_reports_ambiguous_transport_without_verification() -> None:
    from spotify_mcp.domain.errors import AmbiguousWrite

    spotify = FakeSpotify([AmbiguousWrite("write outcome unknown")])

    result = await remove_saved_tracks(spotify, ["a"])

    assert result.status == "ambiguous"
    assert result.warning == "write outcome unknown"
    assert len(spotify.calls) == 1


@pytest.mark.anyio
async def test_library_tools_are_typed_and_accurately_annotated() -> None:
    server: MCPServer[AppContext] = MCPServer("test")
    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "spotify_saved_tracks",
        "spotify_sample_liked_songs",
        "spotify_library_contains",
        "spotify_library_save",
        "spotify_library_remove",
    }
    assert all(tool.output_schema is not None for tool in tools.values())
    assert tools["spotify_saved_tracks"].annotations.read_only_hint is True
    remove_annotations = tools["spotify_library_remove"].annotations
    assert remove_annotations.destructive_hint is True
    assert remove_annotations.idempotent_hint is True
