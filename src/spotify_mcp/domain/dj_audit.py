"""Deterministic, read-only rules for auditing complete DJ playlists."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.domain.audio import (
    AudioLookupReport,
    FeatureConflict,
    FeatureName,
    TrackAudioAnalysis,
    feature_for,
)


class PlaylistPositionLike(Protocol):
    """Playlist-position fields consumed by the pure audit rules."""

    @property
    def original_position(self) -> int: ...

    @property
    def track_id(self) -> str | None: ...

    @property
    def name(self) -> str: ...

    @property
    def artists(self) -> tuple[str, ...]: ...

    @property
    def duration_ms(self) -> int | None: ...


class PlaylistStateLike(Protocol):
    """Stable playlist state consumed by the pure audit rules."""

    @property
    def playlist_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def snapshot_id(self) -> str: ...

    @property
    def positions(self) -> Sequence[PlaylistPositionLike]: ...


class PlaylistAuditSummary(BaseModel):
    """Identity of the exact playlist snapshot that was audited."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    snapshot_id: str
    total_items: int = Field(ge=0)


class ExactDuplicateGroup(BaseModel):
    """Repeated positions containing the same exact Spotify recording."""

    model_config = ConfigDict(frozen=True)

    track_id: str
    positions: list[int]


class LikelyDuplicateRecording(BaseModel):
    """Two different IDs that probably represent alternate copies of one recording."""

    model_config = ConfigDict(frozen=True)

    left_position: int
    right_position: int
    left_track_id: str
    right_track_id: str
    reason: str


class PositionFeatureCoverage(BaseModel):
    """Audio-field coverage for one exact playlist position."""

    model_config = ConfigDict(frozen=True)

    position: int
    track_id: str | None
    covered_fields: list[FeatureName]
    missing_fields: list[FeatureName]


class TempoAmbiguity(BaseModel):
    """A displayed tempo outside the DJ audit's conventional 90-180 BPM band."""

    model_config = ConfigDict(frozen=True)

    position: int
    track_id: str
    displayed_bpm: float
    normalized_bpm: float


class PlaylistProviderConflict(BaseModel):
    """Provider disagreement associated with every occurrence of a recording."""

    model_config = ConfigDict(frozen=True)

    track_id: str
    positions: list[int]
    conflict: FeatureConflict


class ChapterSignal(BaseModel):
    """Heuristic chapter candidate that always requires listening confirmation."""

    model_config = ConfigDict(frozen=True)

    position: int
    track_id: str
    signal: Literal["opening", "peak", "reset"]
    reason: str


class DjPlaylistAuditReport(BaseModel):
    """Complete read-only audit of one stable playlist snapshot."""

    model_config = ConfigDict(frozen=True)

    playlist: PlaylistAuditSummary
    coverage: dict[FeatureName, int]
    position_coverage: list[PositionFeatureCoverage]
    exact_duplicates: list[ExactDuplicateGroup]
    likely_duplicate_recordings: list[LikelyDuplicateRecording]
    tempo_ambiguities: list[TempoAmbiguity]
    provider_conflicts: list[PlaylistProviderConflict]
    chapter_signals: list[ChapterSignal]
    missing_track_ids: list[str]
    warnings: list[str]
    recommendations: list[str]


def normalize_audit_tempo(bpm: float) -> float:
    """Normalize a half/double-time reading into the inclusive 90-180 BPM band."""

    if bpm <= 0:
        raise ValueError("bpm must be positive")
    normalized = float(bpm)
    while normalized < 90:
        normalized *= 2
    while normalized > 180:
        normalized /= 2
    return round(normalized, 3)


def audit_playlist_data(
    state: PlaylistStateLike,
    lookup: AudioLookupReport,
) -> DjPlaylistAuditReport:
    """Apply deterministic audit rules to snapshot-bound positions and audio evidence."""

    analyses = {track.track_id: track for track in lookup.tracks}
    positions_by_track_id: dict[str, list[int]] = defaultdict(list)
    for position in state.positions:
        if position.track_id:
            positions_by_track_id[position.track_id].append(position.original_position + 1)

    exact_duplicates = [
        ExactDuplicateGroup(track_id=track_id, positions=positions)
        for track_id, positions in positions_by_track_id.items()
        if len(positions) > 1
    ]
    likely_duplicates = _likely_duplicate_recordings(state.positions)
    position_coverage = _position_coverage(state.positions, analyses)
    coverage = {
        field: sum(field in item.covered_fields for item in position_coverage)
        for field in FeatureName
    }
    tempo_ambiguities: list[TempoAmbiguity] = []
    chapter_signals: list[ChapterSignal] = []
    for position in state.positions:
        if not position.track_id:
            continue
        analysis = analyses.get(position.track_id)
        if analysis is None:
            continue
        tempo = _value(analysis, FeatureName.TEMPO)
        if tempo is not None and (tempo < 90 or tempo > 180):
            tempo_ambiguities.append(
                TempoAmbiguity(
                    position=position.original_position + 1,
                    track_id=position.track_id,
                    displayed_bpm=tempo,
                    normalized_bpm=normalize_audit_tempo(tempo),
                )
            )
        chapter_signals.extend(
            _chapter_signals(position.original_position + 1, position.track_id, analysis)
        )

    missing_track_ids = list(
        dict.fromkeys(
            [*lookup.missing_track_ids]
            + [track_id for track_id in positions_by_track_id if track_id not in analyses]
        )
    )
    warnings = list(lookup.warnings)
    warnings.extend(
        f"Playlist position {position.original_position + 1} has no Spotify track ID and "
        "could not be enriched."
        for position in state.positions
        if position.track_id is None
    )
    provider_conflicts = _provider_conflicts(analyses, positions_by_track_id)
    recommendations = _recommendations(
        has_duplicates=bool(exact_duplicates or likely_duplicates),
        has_conflicts=bool(provider_conflicts),
        has_missing=bool(missing_track_ids),
        has_signals=bool(chapter_signals),
    )
    return DjPlaylistAuditReport(
        playlist=PlaylistAuditSummary(
            id=state.playlist_id,
            name=state.name,
            snapshot_id=state.snapshot_id,
            total_items=len(state.positions),
        ),
        coverage=coverage,
        position_coverage=position_coverage,
        exact_duplicates=exact_duplicates,
        likely_duplicate_recordings=likely_duplicates,
        tempo_ambiguities=tempo_ambiguities,
        provider_conflicts=provider_conflicts,
        chapter_signals=chapter_signals,
        missing_track_ids=missing_track_ids,
        warnings=list(dict.fromkeys(warnings)),
        recommendations=recommendations,
    )


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()


def _recording_signature(position: PlaylistPositionLike) -> tuple[str, tuple[str, ...]]:
    return (
        _normalized_text(position.name),
        tuple(sorted(_normalized_text(artist) for artist in position.artists)),
    )


def _likely_duplicate_recordings(
    positions: Sequence[PlaylistPositionLike],
) -> list[LikelyDuplicateRecording]:
    candidates = [position for position in positions if position.track_id]
    likely: list[LikelyDuplicateRecording] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            if left.track_id == right.track_id:
                continue
            if _recording_signature(left) != _recording_signature(right):
                continue
            if left.duration_ms is None or right.duration_ms is None:
                continue
            if abs(left.duration_ms - right.duration_ms) > 2_500:
                continue
            left_track_id = left.track_id
            right_track_id = right.track_id
            if left_track_id is None or right_track_id is None:
                continue
            likely.append(
                LikelyDuplicateRecording(
                    left_position=left.original_position + 1,
                    right_position=right.original_position + 1,
                    left_track_id=left_track_id,
                    right_track_id=right_track_id,
                    reason=(
                        "Same normalized artist/title and duration within 2500 ms; "
                        "review versions before removal"
                    ),
                )
            )
    return likely


def _position_coverage(
    positions: Sequence[PlaylistPositionLike],
    analyses: dict[str, TrackAudioAnalysis],
) -> list[PositionFeatureCoverage]:
    result: list[PositionFeatureCoverage] = []
    for position in positions:
        analysis = analyses.get(position.track_id) if position.track_id else None
        covered = [field for field in FeatureName if analysis and feature_for(analysis, field)]
        result.append(
            PositionFeatureCoverage(
                position=position.original_position + 1,
                track_id=position.track_id,
                covered_fields=covered,
                missing_fields=[field for field in FeatureName if field not in covered],
            )
        )
    return result


def _provider_conflicts(
    analyses: dict[str, TrackAudioAnalysis],
    positions_by_track_id: dict[str, list[int]],
) -> list[PlaylistProviderConflict]:
    result: list[PlaylistProviderConflict] = []
    for track_id, analysis in analyses.items():
        for field in FeatureName:
            audio_feature = feature_for(analysis, field)
            if audio_feature is None:
                continue
            result.extend(
                PlaylistProviderConflict(
                    track_id=track_id,
                    positions=positions_by_track_id.get(track_id, []),
                    conflict=conflict,
                )
                for conflict in audio_feature.conflicts
            )
    return result


def _value(track: TrackAudioAnalysis, field: FeatureName) -> float | None:
    audio_feature = feature_for(track, field)
    return float(audio_feature.selected.value) if audio_feature else None


def _chapter_signals(
    position: int,
    track_id: str,
    analysis: TrackAudioAnalysis,
) -> list[ChapterSignal]:
    energy = _value(analysis, FeatureName.ENERGY)
    danceability = _value(analysis, FeatureName.DANCEABILITY)
    valence = _value(analysis, FeatureName.VALENCE)
    signals: list[ChapterSignal] = []
    opening_danceability = danceability if danceability is not None else 0.5
    peak_danceability = danceability if danceability is not None else 0.65
    if energy is not None and energy <= 0.45 and opening_danceability >= 0.45:
        signals.append(
            ChapterSignal(
                position=position,
                track_id=track_id,
                signal="opening",
                reason="Lower energy with usable danceability",
            )
        )
    if energy is not None and energy >= 0.72 and peak_danceability >= 0.65:
        signals.append(
            ChapterSignal(
                position=position,
                track_id=track_id,
                signal="peak",
                reason="High energy and danceability",
            )
        )
    if (energy is not None and energy <= 0.38) or (valence is not None and valence <= 0.28):
        signals.append(
            ChapterSignal(
                position=position,
                track_id=track_id,
                signal="reset",
                reason="Low energy or low valence can create an intentional contrast",
            )
        )
    return signals


def _recommendations(
    *,
    has_duplicates: bool,
    has_conflicts: bool,
    has_missing: bool,
    has_signals: bool,
) -> list[str]:
    recommendations: list[str] = []
    if has_duplicates:
        recommendations.append("Review duplicate recordings before planning the final order.")
    if has_conflicts:
        recommendations.append(
            "Resolve material provider conflicts with exact-recording evidence or manual overrides."
        )
    if has_missing:
        recommendations.append(
            "Anchor tracks with missing tempo or provide exact-recording feature overrides."
        )
    if has_signals:
        recommendations.append(
            "Use chapter signals as candidates, then confirm musical intent by listening; "
            "they are not quality rankings."
        )
    return recommendations
