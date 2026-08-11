"""Deterministic compatibility ordering for the legacy BPM-sort workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.domain.audio import AudioLookupSource

PlaylistSortMode = Literal["tempoEnergy", "dj", "ascending", "descending"]
BpmSortStatus = Literal[
    "blocked",
    "dry-run",
    "unchanged",
    "accepted",
    "ambiguous",
    "stale",
    "partial",
]


@dataclass(frozen=True, slots=True)
class SortablePlaylistPosition:
    """One playlist position enriched with the fields needed for ordering."""

    position_token: str
    original_position: int
    track_id: str | None
    name: str
    tempo: float | None
    energy: float | None
    fixed: bool = False


class BpmSortPosition(BaseModel):
    """One position in the proposed playlist order."""

    model_config = ConfigDict(frozen=True)

    position_token: str
    track_id: str | None
    name: str
    original_position: int = Field(ge=0)
    target_position: int = Field(ge=0)
    tempo: float | None = Field(default=None, gt=0)
    normalized_tempo: float | None = Field(default=None, gt=0)
    energy: float | None = Field(default=None, ge=0, le=1)
    fixed: bool


class BpmSortResult(BaseModel):
    """Typed preview or verified mutation outcome for one compatibility sort."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    status: BpmSortStatus
    playlist_id: str
    playlist_name: str
    mode: PlaylistSortMode
    source: AudioLookupSource
    allow_partial: bool
    source_snapshot_id: str
    original_order: tuple[str, ...]
    target_order: tuple[str, ...]
    ordered_positions: tuple[BpmSortPosition, ...]
    missing_track_ids: tuple[str, ...] = ()
    fixed_positions: int = Field(default=0, ge=0)
    expected_snapshot_id: str
    initial_snapshot_id: str
    final_snapshot_id: str | None = None
    completed_moves: int = Field(default=0, ge=0)
    total_moves: int = Field(default=0, ge=0)
    receipt_id: str | None = None
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None


def normalize_dj_tempo(tempo: float) -> float:
    """Normalize a tempo into the legacy inclusive 90-180 BPM mixing range."""

    if tempo <= 0:
        raise ValueError("tempo must be positive")
    normalized = float(tempo)
    while normalized < 90:
        normalized *= 2
    while normalized > 180:
        normalized /= 2
    return normalized


def build_stable_target(
    positions: tuple[SortablePlaylistPosition, ...],
    mode: PlaylistSortMode,
) -> tuple[SortablePlaylistPosition, ...]:
    """Sort movable positions while retaining fixed items at absolute positions."""

    sortable = [position for position in positions if not position.fixed and position.tempo]
    sorted_positions = _sort_known_positions(sortable, mode)
    replacements = iter(sorted_positions)
    return tuple(
        position if position.fixed or position.tempo is None else next(replacements)
        for position in positions
    )


def _sort_known_positions(
    positions: list[SortablePlaylistPosition],
    mode: PlaylistSortMode,
) -> list[SortablePlaylistPosition]:
    if mode == "ascending":
        return sorted(positions, key=lambda position: position.tempo or 0)
    if mode == "descending":
        return sorted(positions, key=lambda position: -(position.tempo or 0))

    by_tempo = sorted(positions, key=lambda position: normalize_dj_tempo(position.tempo or 0))
    result: list[SortablePlaylistPosition] = []
    start = 0
    while start < len(by_tempo):
        first_tempo = normalize_dj_tempo(by_tempo[start].tempo or 0)
        end = start + 1
        while (
            end < len(by_tempo) and normalize_dj_tempo(by_tempo[end].tempo or 0) - first_tempo <= 3
        ):
            end += 1
        result.extend(
            sorted(
                by_tempo[start:end],
                key=lambda position: (
                    position.energy or 0,
                    normalize_dj_tempo(position.tempo or 0),
                ),
            )
        )
        start = end
    return result
