from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.bpm_sort import sort_playlist_by_bpm
from spotify_mcp.domain.audio import (
    AudioFeature,
    AudioLookupReport,
    AudioOverride,
    AudioProvider,
    FeatureObservation,
    FeatureProvenance,
    TrackAudioAnalysis,
)
from spotify_mcp.domain.bpm_sort import (
    SortablePlaylistPosition,
    build_stable_target,
    normalize_dj_tempo,
)
from spotify_mcp.mcp_server.tools.bpm_sort import register


def _feature(value: float) -> AudioFeature:
    return AudioFeature(
        selected=FeatureObservation(
            value=value,
            provenance=FeatureProvenance(provider=AudioProvider.SPOTIFY),
        )
    )


def _analysis(
    track_id: str,
    tempo: float,
    energy: float | None = None,
) -> TrackAudioAnalysis:
    return TrackAudioAnalysis(
        track_id=track_id,
        tempo=_feature(tempo),
        energy=_feature(energy) if energy is not None else None,
    )


class StubAudio:
    def __init__(self, tracks: list[TrackAudioAnalysis]) -> None:
        self.tracks = tracks
        self.calls: list[list[str]] = []

    async def lookup(self, track_ids: list[str], source: Any, overrides: Any) -> AudioLookupReport:
        self.calls.append(track_ids)
        returned = [track for track in self.tracks if track.track_id in track_ids]
        returned_ids = {track.track_id for track in returned}
        return AudioLookupReport(
            requested_track_ids=track_ids,
            tracks=returned,
            missing_track_ids=[track_id for track_id in track_ids if track_id not in returned_ids],
            warnings=[],
        )


class UnavailableAudio:
    def __init__(self) -> None:
        self.calls = 0

    async def lookup(self, track_ids: list[str], source: Any, overrides: Any) -> AudioLookupReport:
        self.calls += 1
        raise RuntimeError("audio provider unavailable")


class MemoryArtifacts:
    def __init__(self) -> None:
        self.receipts: dict[str, dict[str, Any]] = {}

    async def put_immutable(self, kind: str, payload: Mapping[str, Any]) -> str:
        del payload
        return f"{kind}-1"

    async def get(self, artifact_id: str) -> dict[str, Any]:
        raise KeyError(artifact_id)

    async def put_receipt(self, receipt_id: str, payload: Mapping[str, Any]) -> None:
        self.receipts[receipt_id] = dict(payload)


class PlaylistGateway:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.snapshot = "s1"
        self.put_count = 0

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and path == "playlists/playlist-1":
            return {"name": "Roadtrip", "snapshot_id": self.snapshot}
        if method == "GET" and path == "playlists/playlist-1/items":
            offset = int((params or {}).get("offset", 0))
            return {"items": self.items[offset : offset + 50], "total": len(self.items)}
        if method == "PUT" and path == "playlists/playlist-1/items":
            self.put_count += 1
            assert isinstance(json, dict)
            start = int(json["range_start"])
            length = int(json["range_length"])
            insert_before = int(json["insert_before"])
            moved = self.items[start : start + length]
            del self.items[start : start + length]
            insert_at = insert_before - length if insert_before > start else insert_before
            self.items[insert_at:insert_at] = moved
            self.snapshot = f"s{self.put_count + 1}"
            return {"snapshot_id": self.snapshot}
        raise AssertionError(f"unexpected request: {method} {path}")


def _track(track_id: str, *, uri: str | None = None) -> dict[str, Any]:
    return {
        "item": {
            "type": "track",
            "id": track_id,
            "uri": uri or f"spotify:track:{track_id}",
            "name": track_id,
            "artists": [{"id": f"artist-{track_id}", "name": track_id}],
        }
    }


def _episode(episode_id: str) -> dict[str, Any]:
    return {
        "item": {
            "type": "episode",
            "id": episode_id,
            "uri": f"spotify:episode:{episode_id}",
            "name": episode_id,
        }
    }


def test_normalize_dj_tempo_matches_legacy_90_to_180_range() -> None:
    assert normalize_dj_tempo(42) == 168
    assert normalize_dj_tempo(70) == 140
    assert normalize_dj_tempo(190) == 95
    assert normalize_dj_tempo(360) == 180
    assert normalize_dj_tempo(128) == 128


def test_build_target_keeps_duplicate_positions_distinct_and_stable() -> None:
    positions = (
        SortablePlaylistPosition("duplicate#0", 0, "same", "Same", 128, None),
        SortablePlaylistPosition("slow", 1, "slow", "Slow", 110, None),
        SortablePlaylistPosition("duplicate#1", 2, "same", "Same", 128, None),
    )

    assert tuple(item.position_token for item in build_stable_target(positions, "ascending")) == (
        "slow",
        "duplicate#0",
        "duplicate#1",
    )


def test_ascending_and_descending_use_raw_tempo_for_legacy_compatibility() -> None:
    positions = (
        SortablePlaylistPosition("half-time", 0, "half", "Half", 70, None),
        SortablePlaylistPosition("regular", 1, "regular", "Regular", 100, None),
    )

    assert tuple(item.position_token for item in build_stable_target(positions, "ascending")) == (
        "half-time",
        "regular",
    )
    assert tuple(item.position_token for item in build_stable_target(positions, "descending")) == (
        "regular",
        "half-time",
    )


def test_build_target_keeps_fixed_slots_and_uses_three_bpm_energy_band() -> None:
    positions = (
        SortablePlaylistPosition("high", 0, "high", "High", 128, 0.9),
        SortablePlaylistPosition("episode", 1, None, "Episode", None, None, fixed=True),
        SortablePlaylistPosition("low", 2, "low", "Low", 130.9, 0.2),
        SortablePlaylistPosition("outside", 3, "outside", "Outside", 131.1, 0.1),
    )

    target = build_stable_target(positions, "tempoEnergy")

    assert tuple(item.position_token for item in target) == (
        "low",
        "episode",
        "high",
        "outside",
    )
    assert build_stable_target(positions, "dj") == target


@pytest.mark.anyio
async def test_missing_tempo_blocks_without_partial_permission() -> None:
    spotify = PlaylistGateway([_track("fast"), _track("missing"), _track("slow")])
    audio = StubAudio([_analysis("fast", 130), _analysis("slow", 100)])

    result = await sort_playlist_by_bpm(
        spotify,
        MemoryArtifacts(),
        audio,
        "playlist-1",
        mode="ascending",
        dry_run=False,
    )

    assert result.status == "blocked"
    assert result.failure_reason == "missing-audio-features"
    assert result.missing_track_ids == ("missing",)
    assert result.original_order == result.target_order
    assert spotify.put_count == 0


@pytest.mark.anyio
async def test_partial_dry_run_keeps_missing_non_track_and_duplicates_position_safe() -> None:
    spotify = PlaylistGateway(
        [
            _track("same"),
            _episode("show"),
            _track("missing"),
            _track("slow"),
            _track("same"),
        ]
    )
    audio = StubAudio([_analysis("same", 128), _analysis("slow", 100)])

    result = await sort_playlist_by_bpm(
        spotify,
        MemoryArtifacts(),
        audio,
        "playlist-1",
        mode="ascending",
        allow_partial=True,
    )

    assert result.status == "dry-run"
    assert result.original_order == (
        "spotify:track:same#0",
        "spotify:episode:show#0",
        "spotify:track:missing#0",
        "spotify:track:slow#0",
        "spotify:track:same#1",
    )
    assert result.target_order == (
        "spotify:track:slow#0",
        "spotify:episode:show#0",
        "spotify:track:missing#0",
        "spotify:track:same#0",
        "spotify:track:same#1",
    )
    assert result.fixed_positions == 2
    assert result.total_moves == 2
    assert result.receipt_id is None
    assert spotify.put_count == 0


@pytest.mark.anyio
async def test_apply_returns_verified_receipt() -> None:
    spotify = PlaylistGateway([_track("fast"), _track("slow")])
    artifacts = MemoryArtifacts()

    result = await sort_playlist_by_bpm(
        spotify,
        artifacts,
        StubAudio([_analysis("fast", 130), _analysis("slow", 100)]),
        "playlist-1",
        mode="ascending",
        dry_run=False,
    )

    assert result.status == "accepted"
    assert result.receipt_id in artifacts.receipts
    assert result.completed_moves == result.total_moves == 1
    assert [item["item"]["id"] for item in spotify.items] == ["slow", "fast"]


@pytest.mark.anyio
async def test_complete_tempo_overrides_sort_without_provider_lookup() -> None:
    spotify = PlaylistGateway([_track("fast"), _track("slow")])
    audio = UnavailableAudio()

    result = await sort_playlist_by_bpm(
        spotify,
        MemoryArtifacts(),
        audio,
        "playlist-1",
        mode="ascending",
        overrides=[
            AudioOverride(track_id="fast", tempo=130, energy=0.8),
            AudioOverride(track_id="slow", tempo=100, energy=0.3),
        ],
    )

    assert result.status == "dry-run"
    assert result.target_order == (
        "spotify:track:slow#0",
        "spotify:track:fast#0",
    )
    assert result.missing_track_ids == ()
    assert audio.calls == 0


@pytest.mark.anyio
async def test_mixed_tempo_overrides_fetch_only_unresolved_tracks() -> None:
    spotify = PlaylistGateway([_track("override"), _track("provider")])
    audio = StubAudio([_analysis("provider", 100, 0.4)])

    result = await sort_playlist_by_bpm(
        spotify,
        MemoryArtifacts(),
        audio,
        "playlist-1",
        mode="ascending",
        overrides=[AudioOverride(track_id="override", tempo=130, energy=0.8)],
    )

    assert result.status == "dry-run"
    assert result.target_order == (
        "spotify:track:provider#0",
        "spotify:track:override#0",
    )
    assert audio.calls == [["provider"]]


@pytest.mark.anyio
async def test_bpm_sort_tool_registers_as_destructive() -> None:
    server = MCPServer("test")

    register(server)

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["spotify_playlist_sort_by_bpm"]
    assert tools[0].annotations is not None
    assert tools[0].annotations.read_only_hint is False
    assert tools[0].annotations.destructive_hint is True
    assert tools[0].annotations.idempotent_hint is False


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
