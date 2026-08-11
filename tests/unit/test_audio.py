from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.adapters.audio import ReccoBeatsAudioProvider, SpotifyAudioProvider
from spotify_mcp.application.audio import AudioAnalysisService, project_dj_audio_features
from spotify_mcp.domain.audio import (
    AudioFeature,
    AudioLookupSource,
    AudioOverride,
    AudioProvider,
    FeatureName,
    FeatureObservation,
    FeatureProvenance,
    TrackAudioAnalysis,
    audio_values_conflict,
)
from spotify_mcp.domain.errors import SpotifyRequestError
from spotify_mcp.mcp_server.tools.audio import register


def observation(value: float, provider: AudioProvider) -> FeatureObservation:
    return FeatureObservation(
        value=value,
        provenance=FeatureProvenance(provider=provider),
    )


def analysis(
    track_id: str,
    provider: AudioProvider,
    *,
    tempo: float | None = None,
    energy: float | None = None,
) -> TrackAudioAnalysis:
    return TrackAudioAnalysis(
        track_id=track_id,
        tempo=AudioFeature(selected=observation(tempo, provider)) if tempo else None,
        energy=AudioFeature(selected=observation(energy, provider)) if energy else None,
    )


class StubProvider:
    def __init__(
        self,
        provider: AudioProvider,
        tracks: list[TrackAudioAnalysis] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.provider = provider
        self.tracks = tracks or []
        self.error = error
        self.calls: list[list[str]] = []

    async def get_audio_features(self, track_ids: list[str]) -> list[TrackAudioAnalysis]:
        self.calls.append(track_ids)
        if self.error:
            raise self.error
        return self.tracks


class StubSpotifyGateway:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        self.calls.append((method, path, params))
        return self.response


def test_tempo_conflict_allows_half_and_double_time() -> None:
    assert not audio_values_conflict(FeatureName.TEMPO, 70, 140)
    assert audio_values_conflict(FeatureName.TEMPO, 70, 128)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [403, 404])
async def test_auto_uses_reccobeats_only_for_spotify_403_or_404(status_code: int) -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        error=SpotifyRequestError("unavailable", status_code=status_code),
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        [analysis("track-1", AudioProvider.RECCOBEATS, tempo=123)],
    )

    result = await AudioAnalysisService(spotify, recco).lookup(["track-1"])

    assert result.tracks[0].tempo.selected.value == 123
    assert result.tracks[0].tempo.selected.provenance.provider is AudioProvider.RECCOBEATS
    assert result.missing_track_ids == []
    assert recco.calls == [["track-1"]]
    assert str(status_code) in result.warnings[0]


@pytest.mark.anyio
async def test_auto_does_not_fallback_for_other_spotify_failures() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        error=SpotifyRequestError("rate limited", status_code=429),
    )
    recco = StubProvider(AudioProvider.RECCOBEATS)

    with pytest.raises(SpotifyRequestError, match="rate limited"):
        await AudioAnalysisService(spotify, recco).lookup(["track-1"])

    assert recco.calls == []


@pytest.mark.anyio
async def test_auto_backfills_missing_spotify_fields_without_replacing_spotify_values() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120)],
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        [analysis("track-1", AudioProvider.RECCOBEATS, tempo=121, energy=0.8)],
    )

    result = await AudioAnalysisService(spotify, recco).lookup(["track-1"])

    assert result.tracks[0].tempo.selected.value == 120
    assert result.tracks[0].tempo.selected.provenance.provider is AudioProvider.SPOTIFY
    assert result.tracks[0].energy.selected.value == 0.8
    assert result.tracks[0].energy.selected.provenance.provider is AudioProvider.RECCOBEATS
    assert FeatureName.ENERGY not in result.tracks[0].missing_fields
    assert recco.calls == [["track-1"]]
    assert "backfilled" in result.warnings[0]


@pytest.mark.anyio
async def test_auto_backfills_tracks_missing_from_spotify_response() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120, energy=0.5)],
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        [analysis("track-2", AudioProvider.RECCOBEATS, tempo=126, energy=0.8)],
    )

    result = await AudioAnalysisService(spotify, recco).lookup(["track-1", "track-2"])

    assert [track.track_id for track in result.tracks] == ["track-1", "track-2"]
    assert result.missing_track_ids == []
    assert recco.calls == [["track-1", "track-2"]]


@pytest.mark.anyio
async def test_auto_keeps_partial_spotify_result_when_backfill_provider_fails() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120)],
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        error=RuntimeError("provider offline"),
    )

    result = await AudioAnalysisService(spotify, recco).lookup(["track-1", "track-2"])

    assert [track.track_id for track in result.tracks] == ["track-1"]
    assert result.missing_track_ids == ["track-2"]
    assert "provider offline" in result.warnings[0]


@pytest.mark.anyio
async def test_explicit_spotify_source_does_not_call_backfill_provider() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120)],
    )
    recco = StubProvider(AudioProvider.RECCOBEATS)

    result = await AudioAnalysisService(spotify, recco).lookup(
        ["track-1"],
        AudioLookupSource.SPOTIFY,
    )

    assert result.tracks[0].energy is None
    assert recco.calls == []


@pytest.mark.anyio
async def test_dj_projection_preserves_selected_field_provenance() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120)],
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        [analysis("track-1", AudioProvider.RECCOBEATS, tempo=121, energy=0.8)],
    )
    lookup = await AudioAnalysisService(spotify, recco).lookup(["track-1"])

    projected = project_dj_audio_features(lookup)

    assert projected[0].bpm == 120
    assert projected[0].energy == 0.8
    assert projected[0].provenance[FeatureName.TEMPO].provider is AudioProvider.SPOTIFY
    assert projected[0].provenance[FeatureName.ENERGY].provider is AudioProvider.RECCOBEATS


@pytest.mark.anyio
async def test_override_preserves_original_observation_and_provenance() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("track-1", AudioProvider.SPOTIFY, tempo=120)],
    )
    service = AudioAnalysisService(spotify, StubProvider(AudioProvider.RECCOBEATS))

    result = await service.lookup(
        ["track-1"],
        overrides=[AudioOverride(track_id="track-1", tempo=128)],
    )

    tempo = result.tracks[0].tempo
    assert tempo.selected.value == 128
    assert tempo.selected.provenance.provider is AudioProvider.OVERRIDE
    assert tempo.overridden.value == 120
    assert tempo.conflicts[0].alternative.value == 120


@pytest.mark.anyio
async def test_compare_reports_conflicts_and_missing_providers_explicitly() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("one", AudioProvider.SPOTIFY, tempo=120, energy=0.8)],
    )
    recco = StubProvider(
        AudioProvider.RECCOBEATS,
        [analysis("one", AudioProvider.RECCOBEATS, tempo=128, energy=0.82)],
    )

    report = await AudioAnalysisService(spotify, recco).compare(["one", "two"])

    assert report.tracks[0].conflicts[0].field is FeatureName.TEMPO
    assert report.tracks[1].missing_providers == [
        AudioProvider.SPOTIFY,
        AudioProvider.RECCOBEATS,
    ]
    assert report.tracks[1].missing_fields == list(FeatureName)


@pytest.mark.anyio
async def test_audit_reports_field_coverage_and_missing_data() -> None:
    spotify = StubProvider(
        AudioProvider.SPOTIFY,
        [analysis("one", AudioProvider.SPOTIFY, tempo=120, energy=0.8)],
    )
    service = AudioAnalysisService(spotify, StubProvider(AudioProvider.RECCOBEATS))

    report = await service.audit(["one", "two"])

    assert report.coverage[FeatureName.TEMPO] == 1
    assert report.coverage[FeatureName.ENERGY] == 1
    assert report.missing_track_ids == ["two"]
    assert report.missing_fields_by_track["two"] == list(FeatureName)


@pytest.mark.anyio
async def test_spotify_adapter_parses_nullable_fields_and_requested_order() -> None:
    gateway = StubSpotifyGateway(
        {
            "audio_features": [
                {"id": "two", "tempo": 125.0, "key": -1, "mode": 1, "energy": None},
                {"id": "one", "tempo": 100.0, "energy": 0.5, "track_href": "spotify-url"},
            ]
        }
    )

    tracks = await SpotifyAudioProvider(gateway).get_audio_features(["one", "two"])

    assert [track.track_id for track in tracks] == ["one", "two"]
    assert tracks[0].tempo.selected.provenance.source_href == "spotify-url"
    assert tracks[1].key is None
    assert tracks[1].mode.selected.value == 1
    assert isinstance(tracks[1].mode.selected.value, int)
    assert tracks[1].energy is None
    assert gateway.calls == [("GET", "/audio-features", {"ids": "one,two"})]


@pytest.mark.anyio
async def test_reccobeats_adapter_extracts_spotify_id_and_uses_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ids"] == "track-1"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "href": "https://open.spotify.com/track/track-1",
                        "tempo": 111.5,
                        "energy": 0.61,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await ReccoBeatsAudioProvider(client).get_audio_features(["track-1"])

    assert tracks[0].track_id == "track-1"
    assert tracks[0].tempo.selected.value == 111.5


@pytest.mark.anyio
async def test_audio_tools_register_with_mcp_v2_server() -> None:
    server = MCPServer("test")

    register(server)

    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {
        "spotify_audio_features",
        "spotify_audio_compare",
        "spotify_audio_audit",
    }
