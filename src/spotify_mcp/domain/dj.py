"""Deterministic DJ-set planning primitives.

The planner deliberately models playlist *positions*, not only Spotify track IDs.
That distinction keeps repeated recordings stable and makes every generated order
an exact permutation of the source playlist.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import sin, tau
from statistics import median
from typing import Any, Literal

EnergyCurve = Literal["warmup-build-peak-close", "steady", "rising", "waves"]
MissingFeaturePolicy = Literal["anchor", "error", "skip"]
DjSourceKind = Literal["playlist", "candidates"]
DjPlanStrategy = Literal["auto", "energy-curve", "transition-cost"]

_CAMELOT_MAJOR = ("8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B")
_CAMELOT_MINOR = ("5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A")


@dataclass(frozen=True, slots=True)
class DjFeatureEvidence:
    """Serializable field-level evidence retained in a DJ analysis artifact."""

    field: str
    provider: str
    fetched_at: str
    source_href: str | None = None
    confidence: float | None = None
    confidence_basis: str = "unknown"


@dataclass(frozen=True, slots=True)
class DjAnalysisCoverage:
    """Coverage counts and unresolved positions for one immutable analysis."""

    track_count: int = 0
    tempo_count: int = 0
    key_count: int = 0
    energy_count: int = 0
    complete_count: int = 0
    unresolved_position_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DjTrack:
    """One observable playlist position and its available audio features."""

    position_token: str
    identity: str
    original_position: int
    track_id: str | None = None
    uri: str | None = None
    name: str = "Unknown"
    artists: tuple[str, ...] = ()
    artist_ids: tuple[str, ...] = ()
    duration_ms: int | None = None
    item_type: str = "track"
    fixed: bool = False
    bpm: float | None = None
    normalized_bpm: float | None = None
    energy: float | None = None
    camelot: str | None = None
    provenance: tuple[DjFeatureEvidence, ...] = ()
    sources: tuple[str, ...] = ()
    unresolved_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DjCandidateResolution:
    """One user candidate resolved to an exact Spotify recording."""

    input_index: int
    candidate: str
    track_id: str
    uri: str
    name: str
    artists: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DjSkippedCandidate:
    """A candidate excluded before planning with explicit evidence."""

    input_index: int
    candidate: str
    reason: str
    track_id: str | None = None
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DjAnalysis:
    """Playlist- or candidate-bound analysis suitable for immutable storage."""

    playlist_id: str | None
    playlist_name: str
    snapshot_id: str | None
    tracks: tuple[DjTrack, ...]
    warnings: tuple[str, ...] = ()
    audio_source: str = "manual"
    missing_feature_policy: MissingFeaturePolicy = "anchor"
    coverage: DjAnalysisCoverage = field(default_factory=DjAnalysisCoverage)
    source_kind: DjSourceKind = "playlist"
    requested_public: bool = False
    resolved_candidates: tuple[DjCandidateResolution, ...] = ()
    skipped_candidates: tuple[DjSkippedCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedTrack:
    """A selected position plus the target curve value used to select it."""

    position_token: str
    original_position: int
    target_energy: float | None
    uri: str | None = None
    name: str = "Unknown"
    artists: tuple[str, ...] = ()
    bpm: float | None = None
    normalized_bpm: float | None = None
    energy: float | None = None
    camelot: str | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DjTransition:
    """Exact transition evidence for two adjacent planned positions."""

    from_position_token: str
    to_position_token: str
    bpm_delta: float
    energy_delta: float
    key_penalty: float
    cost: float
    from_normalized_bpm: float | None = None
    to_normalized_bpm: float | None = None


@dataclass(frozen=True, slots=True)
class DjPlan:
    """A deterministic target permutation tied to an analysis artifact."""

    analysis_id: str
    playlist_id: str | None
    playlist_name: str
    source_snapshot_id: str | None
    energy_curve: EnergyCurve
    artist_spacing: int
    original_order: tuple[str, ...]
    target_order: tuple[str, ...]
    ordered_tracks: tuple[PlannedTrack, ...]
    warnings: tuple[str, ...] = ()
    source_kind: DjSourceKind = "playlist"
    requested_public: bool = False
    strategy: Literal["energy-curve", "transition-cost"] = "energy-curve"
    transitions: tuple[DjTransition, ...] = ()
    total_transition_cost: float = 0.0
    resolved_candidates: tuple[DjCandidateResolution, ...] = ()
    skipped_candidates: tuple[DjSkippedCandidate, ...] = ()


def stable_receipt_id(identity: Mapping[str, Any]) -> str:
    """Derive a stable local receipt ID from mutation identity fields."""

    canonical = json.dumps(
        dict(identity), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return f"djr_{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


def camelot_code(pitch_class: int, mode: int) -> str:
    """Convert Spotify pitch class and mode into canonical Camelot notation."""

    if not 0 <= pitch_class <= 11:
        raise ValueError("pitch_class must be between 0 and 11")
    if mode not in (0, 1):
        raise ValueError("mode must be 0 (minor) or 1 (major)")
    return (_CAMELOT_MAJOR if mode == 1 else _CAMELOT_MINOR)[pitch_class]


def normalize_tempo(bpm: float) -> float:
    """Normalize half/double-time readings into the inclusive 80-160 BPM band."""

    if bpm <= 0:
        raise ValueError("bpm must be positive")
    normalized = float(bpm)
    while normalized < 80:
        normalized *= 2
    while normalized > 160:
        normalized /= 2
    return normalized


def occurrence_tokens(identities: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Assign deterministic tokens that keep duplicate playlist positions distinct."""

    counts: dict[str, int] = {}
    tokens: list[str] = []
    for identity in identities:
        occurrence = counts.get(identity, 0)
        counts[identity] = occurrence + 1
        tokens.append(f"{identity}#{occurrence}")
    return tuple(tokens)


def energy_targets(
    curve: EnergyCurve, count: int, energies: tuple[float, ...] = ()
) -> tuple[float, ...]:
    """Return a reproducible target energy for every set position."""

    if count < 0:
        raise ValueError("count must not be negative")
    if count == 0:
        return ()
    steady = median(energies) if energies else 0.55
    targets: list[float] = []
    for index in range(count):
        position = index / max(count - 1, 1)
        if curve == "steady":
            value = steady
        elif curve == "rising":
            value = 0.25 + 0.65 * position
        elif curve == "waves":
            value = 0.55 + 0.25 * sin(tau * 2 * position - tau / 4)
        elif position <= 0.75:
            value = 0.25 + 0.7 * (position / 0.75)
        else:
            value = 0.95 - 0.4 * ((position - 0.75) / 0.25)
        targets.append(round(min(1.0, max(0.0, value)), 4))
    return tuple(targets)


def plan_dj_set(
    analysis: DjAnalysis,
    analysis_id: str,
    *,
    energy_curve: EnergyCurve = "warmup-build-peak-close",
    artist_spacing: int = 3,
) -> DjPlan:
    """Build a deterministic order balancing energy, tempo, key, and artist spacing."""

    if artist_spacing < 0:
        raise ValueError("artist_spacing must not be negative")
    tokens = tuple(track.position_token for track in analysis.tracks)
    if len(set(tokens)) != len(tokens):
        raise ValueError("analysis contains duplicate position tokens")
    known_energies = tuple(track.energy for track in analysis.tracks if track.energy is not None)
    targets = energy_targets(energy_curve, len(analysis.tracks), known_energies)
    remaining = list(analysis.tracks)
    ordered: list[DjTrack] = []
    planned: list[PlannedTrack] = []

    for target in targets:
        previous = ordered[-1] if ordered else None
        recent = ordered[-artist_spacing:] if artist_spacing else []
        selected = min(
            remaining,
            key=lambda candidate: _candidate_score(candidate, previous, recent, target),
        )
        remaining.remove(selected)
        ordered.append(selected)
        planned.append(
            PlannedTrack(
                position_token=selected.position_token,
                original_position=selected.original_position,
                target_energy=target,
                uri=selected.uri,
                name=selected.name,
                artists=selected.artists,
                bpm=selected.bpm,
                normalized_bpm=selected.normalized_bpm,
                energy=selected.energy,
                camelot=selected.camelot,
                sources=selected.sources,
            )
        )

    warnings = list(analysis.warnings)
    missing = sum(
        track.energy is None or track.normalized_bpm is None or track.camelot is None
        for track in analysis.tracks
    )
    if missing:
        warnings.append(f"{missing} position(s) have incomplete audio features")
    return DjPlan(
        analysis_id=analysis_id,
        playlist_id=analysis.playlist_id,
        playlist_name=analysis.playlist_name,
        source_snapshot_id=analysis.snapshot_id,
        energy_curve=energy_curve,
        artist_spacing=artist_spacing,
        original_order=tokens,
        target_order=tuple(track.position_token for track in ordered),
        ordered_tracks=tuple(planned),
        warnings=tuple(dict.fromkeys(warnings)),
        source_kind=analysis.source_kind,
        requested_public=analysis.requested_public,
        strategy="energy-curve",
        resolved_candidates=analysis.resolved_candidates,
        skipped_candidates=analysis.skipped_candidates,
    )


def transition_key_penalty(previous: str, candidate: str) -> float:
    """Return the specification's Camelot compatibility penalty."""

    previous_number, previous_mode = _parse_camelot(previous)
    candidate_number, candidate_mode = _parse_camelot(candidate)
    distance = abs(previous_number - candidate_number)
    circle_distance = min(distance, 12 - distance)
    if previous == candidate:
        return 0.0
    if previous_mode == candidate_mode and circle_distance == 1:
        return 2.0
    if previous_number == candidate_number and previous_mode != candidate_mode:
        return 3.0
    return 10.0 + circle_distance * 2.0


def transition_cost(previous: DjTrack, candidate: DjTrack) -> DjTransition:
    """Calculate the exact BPM, Camelot, and energy transition cost."""

    if previous.bpm is None or previous.energy is None or previous.camelot is None:
        raise ValueError("previous track has incomplete transition features")
    if candidate.bpm is None or candidate.energy is None or candidate.camelot is None:
        raise ValueError("candidate track has incomplete transition features")
    previous_tempo = _transition_tempo(previous)
    candidate_tempo = _transition_tempo(candidate)
    bpm_delta = abs(previous_tempo - candidate_tempo)
    energy_delta = abs(previous.energy - candidate.energy)
    key_penalty = transition_key_penalty(previous.camelot, candidate.camelot)
    cost = _transition_cost_value(previous, candidate)
    return DjTransition(
        from_position_token=previous.position_token,
        to_position_token=candidate.position_token,
        bpm_delta=round(bpm_delta, 6),
        energy_delta=round(energy_delta, 6),
        key_penalty=key_penalty,
        cost=round(cost, 6),
        from_normalized_bpm=previous_tempo,
        to_normalized_bpm=candidate_tempo,
    )


def plan_transition_set(analysis: DjAnalysis, analysis_id: str) -> DjPlan:
    """Build the specification's deterministic nearest-neighbor DJ sequence."""

    if len(analysis.tracks) < 2:
        raise ValueError("transition-cost planning requires at least two tracks")
    if any(
        track.bpm is None or track.energy is None or track.camelot is None
        for track in analysis.tracks
    ):
        raise ValueError("transition-cost planning requires complete tempo, key, and energy")
    tokens = tuple(track.position_token for track in analysis.tracks)
    if len(set(tokens)) != len(tokens):
        raise ValueError("analysis contains duplicate position tokens")

    remaining = list(analysis.tracks)
    current = min(
        remaining,
        key=lambda track: (
            _transition_tempo(track),
            float(track.energy or 0),
            track.original_position,
            track.position_token,
        ),
    )
    remaining.remove(current)
    ordered = [current]
    transitions: list[DjTransition] = []
    while remaining:
        scored = [
            (
                _transition_cost_value(current, candidate),
                transition_cost(current, candidate),
                candidate,
            )
            for candidate in remaining
        ]
        _, selected_transition, selected = min(
            scored,
            key=lambda item: (
                item[0],
                item[2].original_position,
                item[2].position_token,
            ),
        )
        transitions.append(selected_transition)
        ordered.append(selected)
        remaining.remove(selected)
        current = selected

    return DjPlan(
        analysis_id=analysis_id,
        playlist_id=analysis.playlist_id,
        playlist_name=analysis.playlist_name,
        source_snapshot_id=analysis.snapshot_id,
        energy_curve="steady",
        artist_spacing=0,
        original_order=tokens,
        target_order=tuple(track.position_token for track in ordered),
        ordered_tracks=tuple(
            PlannedTrack(
                position_token=track.position_token,
                original_position=track.original_position,
                target_energy=None,
                uri=track.uri,
                name=track.name,
                artists=track.artists,
                bpm=track.bpm,
                normalized_bpm=_transition_tempo(track),
                energy=track.energy,
                camelot=track.camelot,
                sources=track.sources,
            )
            for track in ordered
        ),
        warnings=analysis.warnings,
        source_kind=analysis.source_kind,
        requested_public=analysis.requested_public,
        strategy="transition-cost",
        transitions=tuple(transitions),
        total_transition_cost=round(sum(item.cost for item in transitions), 6),
        resolved_candidates=analysis.resolved_candidates,
        skipped_candidates=analysis.skipped_candidates,
    )


def _parse_camelot(value: str) -> tuple[int, str]:
    if len(value) not in {2, 3} or value[-1] not in {"A", "B"}:
        raise ValueError(f"invalid Camelot code: {value!r}")
    try:
        number = int(value[:-1])
    except ValueError as error:
        raise ValueError(f"invalid Camelot code: {value!r}") from error
    if not 1 <= number <= 12:
        raise ValueError(f"invalid Camelot code: {value!r}")
    return number, value[-1]


def _transition_cost_value(previous: DjTrack, candidate: DjTrack) -> float:
    if previous.bpm is None or previous.energy is None or previous.camelot is None:
        raise ValueError("previous track has incomplete transition features")
    if candidate.bpm is None or candidate.energy is None or candidate.camelot is None:
        raise ValueError("candidate track has incomplete transition features")
    return (
        abs(_transition_tempo(previous) - _transition_tempo(candidate)) * 1.5
        + transition_key_penalty(previous.camelot, candidate.camelot)
        + abs(previous.energy - candidate.energy) * 5.0
    )


def _transition_tempo(track: DjTrack) -> float:
    if track.bpm is None:
        raise ValueError("track has no tempo")
    return normalize_tempo(track.bpm)


def _candidate_score(
    candidate: DjTrack,
    previous: DjTrack | None,
    recent: list[DjTrack],
    target_energy: float,
) -> tuple[float, int, str]:
    energy = candidate.energy if candidate.energy is not None else 0.5
    score = abs(energy - target_energy) * 5
    if previous is not None:
        if previous.normalized_bpm is not None and candidate.normalized_bpm is not None:
            score += abs(previous.normalized_bpm - candidate.normalized_bpm) / 20
        score += _harmonic_penalty(previous.camelot, candidate.camelot)
    artists = set(candidate.artist_ids or candidate.artists)
    for distance, recent_track in enumerate(reversed(recent), start=1):
        if artists.intersection(recent_track.artist_ids or recent_track.artists):
            score += 8 / distance
    return (round(score, 8), candidate.original_position, candidate.position_token)


def _harmonic_penalty(previous: str | None, candidate: str | None) -> float:
    if previous is None or candidate is None:
        return 0.5
    if previous == candidate:
        return 0.0
    previous_number, previous_mode = int(previous[:-1]), previous[-1]
    candidate_number, candidate_mode = int(candidate[:-1]), candidate[-1]
    if previous_number == candidate_number:
        return 0.2
    circle_distance = abs(previous_number - candidate_number)
    if previous_mode == candidate_mode and circle_distance in (1, 11):
        return 0.1
    return 1.0
