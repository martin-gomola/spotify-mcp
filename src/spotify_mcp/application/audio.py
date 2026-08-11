"""Audio-analysis use cases and conservative provider policy."""

from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.domain.audio import (
    AudioAuditReport,
    AudioComparisonReport,
    AudioLookupReport,
    AudioLookupSource,
    AudioOverride,
    AudioProvider,
    AudioProviderError,
    AuditedConflict,
    FeatureName,
    FeatureProvenance,
    TrackAudioAnalysis,
    TrackProviderComparison,
    apply_override,
    compare_track_analyses,
    feature_for,
    merge_track_analyses,
)
from spotify_mcp.domain.errors import SpotifyRequestError


class AudioFeatureProvider(Protocol):
    """Port implemented by an external audio-analysis provider."""

    provider: AudioProvider

    async def get_audio_features(self, track_ids: list[str]) -> list[TrackAudioAnalysis]: ...


class AudioAnalysisGateway(Protocol):
    """Application port for consumers that need provider-neutral audio measurements."""

    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> AudioLookupReport: ...


class AudioServiceGateway(AudioAnalysisGateway, Protocol):
    """Full audio service surface used by the MCP audio tool group."""

    async def compare(self, track_ids: list[str]) -> AudioComparisonReport: ...

    async def audit(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> AudioAuditReport: ...


class DjAudioFeatureProjection(BaseModel):
    """DJ-ready values plus the evidence selected for every populated field."""

    model_config = ConfigDict(frozen=True)

    track_id: str
    bpm: float | None = None
    energy: float | None = None
    key: int | None = None
    mode: int | None = None
    provenance: dict[FeatureName, FeatureProvenance] = Field(default_factory=dict)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _ordered(track_ids: list[str], tracks: list[TrackAudioAnalysis]) -> list[TrackAudioAnalysis]:
    by_id = {track.track_id: track for track in tracks}
    return [by_id[track_id] for track_id in track_ids if track_id in by_id]


def project_dj_audio_features(
    report: AudioLookupReport,
) -> list[DjAudioFeatureProjection]:
    """Project provider-neutral analysis into the fields consumed by DJ planning."""
    projections: list[DjAudioFeatureProjection] = []
    for track in report.tracks:
        selected = {
            field: feature.selected
            for field in (FeatureName.TEMPO, FeatureName.ENERGY, FeatureName.KEY, FeatureName.MODE)
            if (feature := feature_for(track, field)) is not None
        }
        projections.append(
            DjAudioFeatureProjection(
                track_id=track.track_id,
                bpm=(
                    float(selected[FeatureName.TEMPO].value)
                    if FeatureName.TEMPO in selected
                    else None
                ),
                energy=(
                    float(selected[FeatureName.ENERGY].value)
                    if FeatureName.ENERGY in selected
                    else None
                ),
                key=(int(selected[FeatureName.KEY].value) if FeatureName.KEY in selected else None),
                mode=(
                    int(selected[FeatureName.MODE].value) if FeatureName.MODE in selected else None
                ),
                provenance={
                    field: observation.provenance for field, observation in selected.items()
                },
            )
        )
    return projections


class AudioAnalysisService:
    """Coordinates provider reads without hiding data quality or provider failures."""

    def __init__(
        self,
        spotify: AudioFeatureProvider,
        reccobeats: AudioFeatureProvider,
    ) -> None:
        self._spotify = spotify
        self._reccobeats = reccobeats

    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> AudioLookupReport:
        """Read exact recordings, falling back only on Spotify 403 or 404."""
        requested = _unique(track_ids)
        warnings: list[str] = []
        spotify_succeeded = False
        if source is AudioLookupSource.RECCOBEATS:
            tracks = await self._reccobeats.get_audio_features(requested)
        else:
            try:
                tracks = await self._spotify.get_audio_features(requested)
                spotify_succeeded = True
            except SpotifyRequestError as error:
                if source is not AudioLookupSource.AUTO or error.status_code not in {403, 404}:
                    raise
                try:
                    tracks = await self._reccobeats.get_audio_features(requested)
                except Exception as fallback_error:
                    raise AudioProviderError(
                        "Spotify audio features were unavailable "
                        f"({error.status_code}) and ReccoBeats fallback failed: {fallback_error}"
                    ) from fallback_error
                warnings.append(
                    "Spotify audio features were unavailable "
                    f"({error.status_code}); ReccoBeats fallback was used."
                )

            if source is AudioLookupSource.AUTO and spotify_succeeded:
                tracks, backfill_warnings = await self._backfill_incomplete(requested, tracks)
                warnings.extend(backfill_warnings)

        by_id = {track.track_id: track for track in tracks}
        for override in overrides or []:
            if override.track_id not in requested:
                continue
            current = by_id.get(override.track_id) or TrackAudioAnalysis(track_id=override.track_id)
            by_id[override.track_id] = apply_override(current, override)
        ordered = _ordered(requested, list(by_id.values()))
        return AudioLookupReport(
            requested_track_ids=requested,
            tracks=ordered,
            missing_track_ids=[track_id for track_id in requested if track_id not in by_id],
            warnings=warnings,
        )

    async def _backfill_incomplete(
        self,
        requested: list[str],
        primary_tracks: list[TrackAudioAnalysis],
    ) -> tuple[list[TrackAudioAnalysis], list[str]]:
        primary_by_id = {track.track_id: track for track in primary_tracks}
        incomplete_ids = [
            track_id
            for track_id in requested
            if track_id not in primary_by_id or primary_by_id[track_id].missing_fields
        ]
        if not incomplete_ids:
            return primary_tracks, []

        try:
            fallback_tracks = await self._reccobeats.get_audio_features(incomplete_ids)
        except Exception as error:
            return primary_tracks, [f"ReccoBeats audio backfill failed: {error}"]

        fallback_by_id = {track.track_id: track for track in fallback_tracks}
        merged: list[TrackAudioAnalysis] = []
        backfilled_fields = 0
        backfilled_tracks = 0
        for track_id in requested:
            primary = primary_by_id.get(track_id)
            fallback = fallback_by_id.get(track_id)
            if primary is None:
                if fallback is not None:
                    merged.append(fallback)
                    backfilled_tracks += 1
                continue
            if fallback is None:
                merged.append(primary)
                continue
            combined = merge_track_analyses(primary, fallback)
            backfilled_fields += len(primary.missing_fields) - len(combined.missing_fields)
            merged.append(combined)

        warnings: list[str] = []
        if backfilled_tracks or backfilled_fields:
            warnings.append(
                "ReccoBeats backfilled "
                f"{backfilled_tracks} missing track(s) and {backfilled_fields} missing field(s)."
            )
        return merged, warnings

    async def compare(self, track_ids: list[str]) -> AudioComparisonReport:
        """Read both providers explicitly and retain independent failure evidence."""
        requested = _unique(track_ids)
        providers = [self._spotify, self._reccobeats]
        settled = await asyncio.gather(
            *(provider.get_audio_features(requested) for provider in providers),
            return_exceptions=True,
        )
        by_provider: dict[AudioProvider, dict[str, TrackAudioAnalysis]] = {}
        warnings: list[str] = []
        for provider, result in zip(providers, settled, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                warnings.append(f"{provider.provider.value} comparison failed: {result}")
                by_provider[provider.provider] = {}
                continue
            by_provider[provider.provider] = {track.track_id: track for track in result}

        comparisons: list[TrackProviderComparison] = []
        requested_providers = [AudioProvider.SPOTIFY, AudioProvider.RECCOBEATS]
        for track_id in requested:
            analyses = [
                by_provider[provider][track_id]
                for provider in requested_providers
                if track_id in by_provider[provider]
            ]
            conflicts = (
                compare_track_analyses(analyses[0], analyses[1]) if len(analyses) == 2 else []
            )
            comparisons.append(
                TrackProviderComparison(
                    track_id=track_id,
                    analyses=analyses,
                    conflicts=conflicts,
                    missing_providers=[
                        provider
                        for provider in requested_providers
                        if track_id not in by_provider[provider]
                    ],
                    missing_fields=[
                        field
                        for field in FeatureName
                        if not any(feature_for(track, field) for track in analyses)
                    ],
                )
            )
        return AudioComparisonReport(
            requested_track_ids=requested,
            requested_providers=requested_providers,
            tracks=comparisons,
            warnings=warnings,
        )

    async def audit(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> AudioAuditReport:
        """Summarize coverage, absence, and conflicts without scoring musical quality."""
        lookup = await self.lookup(track_ids, source, overrides)
        by_id = {track.track_id: track for track in lookup.tracks}
        conflicts: list[AuditedConflict] = []
        for track in lookup.tracks:
            for field in FeatureName:
                feature = feature_for(track, field)
                if feature:
                    conflicts.extend(
                        AuditedConflict(track_id=track.track_id, conflict=conflict)
                        for conflict in feature.conflicts
                    )
        return AudioAuditReport(
            requested_track_ids=lookup.requested_track_ids,
            coverage={
                field: sum(feature_for(track, field) is not None for track in lookup.tracks)
                for field in FeatureName
            },
            missing_track_ids=lookup.missing_track_ids,
            missing_fields_by_track={
                track_id: (
                    by_id[track_id].missing_fields if track_id in by_id else list(FeatureName)
                )
                for track_id in lookup.requested_track_ids
            },
            conflicts=conflicts,
            warnings=lookup.warnings,
        )
