from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.dj_audit import audit_dj_playlist
from spotify_mcp.application.playlist_state import PlaylistPosition, PlaylistState
from spotify_mcp.domain.audio import (
    AudioFeature,
    AudioLookupReport,
    AudioLookupSource,
    AudioOverride,
    AudioProvider,
    FeatureConflict,
    FeatureName,
    FeatureObservation,
    FeatureProvenance,
    TrackAudioAnalysis,
)
from spotify_mcp.domain.dj_audit import audit_playlist_data, normalize_audit_tempo
from spotify_mcp.mcp_server.tools.dj_audit import register


def observation(value: float, provider: AudioProvider) -> FeatureObservation:
    return FeatureObservation(
        value=value,
        provenance=FeatureProvenance(provider=provider),
    )


def feature(
    value: float,
    *,
    provider: AudioProvider = AudioProvider.SPOTIFY,
    conflict: float | None = None,
) -> AudioFeature:
    selected = observation(value, provider)
    conflicts = (
        [
            FeatureConflict(
                field=FeatureName.ENERGY,
                selected=selected,
                alternative=observation(conflict, AudioProvider.RECCOBEATS),
            )
        ]
        if conflict is not None
        else []
    )
    return AudioFeature(selected=selected, conflicts=conflicts)


def position(
    track_id: str | None,
    index: int,
    *,
    name: str = "Track",
    artists: tuple[str, ...] = ("Artist",),
    duration_ms: int | None = 180_000,
) -> PlaylistPosition:
    identity = f"spotify:track:{track_id}" if track_id else f"unavailable:{index}"
    return PlaylistPosition(
        position_token=f"{identity}#0",
        identity=identity,
        original_position=index,
        track_id=track_id,
        uri=identity if track_id else None,
        name=name,
        artists=artists,
        artist_ids=(),
        duration_ms=duration_ms,
        item_type="track" if track_id else "unavailable",
        fixed=track_id is None,
    )


def audio(
    track_id: str,
    *,
    tempo: float | None = None,
    energy: float | None = None,
    danceability: float | None = None,
    valence: float | None = None,
    conflict: float | None = None,
) -> TrackAudioAnalysis:
    return TrackAudioAnalysis(
        track_id=track_id,
        tempo=feature(tempo) if tempo is not None else None,
        energy=feature(energy, conflict=conflict) if energy is not None else None,
        danceability=feature(danceability) if danceability is not None else None,
        valence=feature(valence) if valence is not None else None,
    )


def test_playlist_audit_reports_duplicates_coverage_conflicts_and_chapter_signals() -> None:
    state = PlaylistState(
        playlist_id="playlist-1",
        name="Set",
        snapshot_id="snapshot-1",
        positions=(
            position("duplicate", 0, name="Same"),
            position("duplicate", 1, name="Same"),
            position(
                "variant-a",
                2,
                name="Café Mix",
                artists=("Beta", "Alpha"),
                duration_ms=200_000,
            ),
            position(
                "variant-b",
                3,
                name="Cafe Mix",
                artists=("alpha", "Béta"),
                duration_ms=202_500,
            ),
            position("peak", 4, name="Peak"),
            position("missing", 5, name="Missing"),
            position(None, 6),
        ),
    )
    lookup = AudioLookupReport(
        requested_track_ids=["duplicate", "variant-a", "variant-b", "peak", "missing"],
        tracks=[
            audio("duplicate", tempo=120, energy=0.4, danceability=0.5, conflict=0.8),
            audio("variant-a", tempo=128, energy=0.3, danceability=0.5, valence=0.5),
            audio("variant-b", tempo=128, energy=0.6, danceability=0.6),
            audio("peak", tempo=200, energy=0.8, danceability=0.8),
        ],
        missing_track_ids=["missing"],
        warnings=["provider fallback used"],
    )

    report = audit_playlist_data(state, lookup)

    assert report.playlist.total_items == 7
    assert report.exact_duplicates[0].track_id == "duplicate"
    assert report.exact_duplicates[0].positions == [1, 2]
    assert len(report.likely_duplicate_recordings) == 1
    assert report.likely_duplicate_recordings[0].left_position == 3
    assert report.likely_duplicate_recordings[0].right_position == 4
    assert report.coverage[FeatureName.TEMPO] == 5  # duplicate positions count separately
    assert report.position_coverage[5].track_id == "missing"
    assert report.position_coverage[5].missing_fields == list(FeatureName)
    assert report.position_coverage[6].track_id is None
    assert report.tempo_ambiguities[0].position == 5
    assert report.tempo_ambiguities[0].normalized_bpm == 100
    assert report.provider_conflicts[0].positions == [1, 2]
    assert {signal.signal for signal in report.chapter_signals} == {
        "opening",
        "peak",
        "reset",
    }
    assert report.missing_track_ids == ["missing"]
    assert "provider fallback used" in report.warnings
    assert any("position 7" in warning for warning in report.warnings)
    assert len(report.recommendations) == 4


def test_likely_recording_requires_compatible_duration() -> None:
    state = PlaylistState(
        playlist_id="playlist-1",
        name="Set",
        snapshot_id="snapshot-1",
        positions=(
            position("a", 0, name="Version", duration_ms=180_000),
            position("b", 1, name="Version", duration_ms=182_501),
        ),
    )
    report = audit_playlist_data(
        state,
        AudioLookupReport(
            requested_track_ids=["a", "b"],
            tracks=[],
            missing_track_ids=["a", "b"],
        ),
    )

    assert report.likely_duplicate_recordings == []


def test_zero_danceability_does_not_use_default_signal_thresholds() -> None:
    state = PlaylistState(
        playlist_id="playlist-1",
        name="Set",
        snapshot_id="snapshot-1",
        positions=(position("low", 0), position("high", 1)),
    )
    report = audit_playlist_data(
        state,
        AudioLookupReport(
            requested_track_ids=["low", "high"],
            tracks=[
                audio("low", energy=0.4, danceability=0),
                audio("high", energy=0.8, danceability=0),
            ],
            missing_track_ids=[],
        ),
    )

    assert report.chapter_signals == []


@pytest.mark.parametrize(
    ("tempo", "normalized"),
    [(45, 90), (64, 128), (90, 90), (180, 180), (200, 100), (360, 180)],
)
def test_audit_tempo_normalizes_to_90_180(tempo: float, normalized: float) -> None:
    assert normalize_audit_tempo(tempo) == normalized


class StubSpotify:
    def __init__(self) -> None:
        self.metadata_reads = 0

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and path == "playlists/playlist-1":
            self.metadata_reads += 1
            return {"name": "Set", "snapshot_id": "snapshot-1"}
        if method == "GET" and path == "playlists/playlist-1/items":
            return {
                "items": [
                    {
                        "item": {
                            "id": "track-1",
                            "uri": "spotify:track:track-1",
                            "type": "track",
                            "name": "Track",
                            "duration_ms": 180_000,
                            "artists": [{"id": "artist-1", "name": "Artist"}],
                        }
                    }
                ],
                "total": 1,
            }
        raise AssertionError(f"unexpected request: {method} {path}")


class StubAudio:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], AudioLookupSource, list[AudioOverride] | None]] = []

    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> AudioLookupReport:
        self.calls.append((track_ids, source, overrides))
        return AudioLookupReport(
            requested_track_ids=track_ids,
            tracks=[audio("track-1", tempo=120, energy=0.7)],
            missing_track_ids=[],
        )


@pytest.mark.anyio
async def test_application_reads_playlist_enriches_unique_ids_and_rechecks_snapshot() -> None:
    spotify = StubSpotify()
    audio_gateway = StubAudio()
    override = AudioOverride(track_id="track-1", tempo=122)

    report = await audit_dj_playlist(
        spotify,
        audio_gateway,
        "playlist-1",
        source=AudioLookupSource.RECCOBEATS,
        overrides=[override],
    )

    assert report.playlist.snapshot_id == "snapshot-1"
    assert audio_gateway.calls == [(["track-1"], AudioLookupSource.RECCOBEATS, [override])]
    assert spotify.metadata_reads == 3


@pytest.mark.anyio
async def test_dj_audit_tool_registers_as_read_only() -> None:
    server = MCPServer("test")

    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}
    tool = tools["spotify_dj_audit"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
