"""Pure planning and simulation for Spotify playlist range moves."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
from typing import Annotated, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ItemT = TypeVar("ItemT", bound=Hashable)


class PlaylistPositionIdentity(BaseModel):
    """An observable item identity plus its occurrence in playlist order."""

    model_config = ConfigDict(frozen=True)

    item_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    occurrence: int = Field(ge=0)


class RangeMove(BaseModel):
    """Spotify's move-one-contiguous-range operation."""

    model_config = ConfigDict(frozen=True)

    range_start: int = Field(ge=0)
    insert_before: int = Field(ge=0)
    range_length: int = Field(default=1, ge=1)


def playlist_position_identities(
    item_ids: Sequence[str],
) -> tuple[PlaylistPositionIdentity, ...]:
    """Disambiguate duplicate Spotify items without delimiter-based tokens."""
    occurrences: dict[str, int] = {}
    positioned: list[PlaylistPositionIdentity] = []
    for item_id in item_ids:
        if not item_id:
            raise ValueError("playlist item identities must not be empty")
        occurrence = occurrences.get(item_id, 0)
        positioned.append(PlaylistPositionIdentity(item_id=item_id, occurrence=occurrence))
        occurrences[item_id] = occurrence + 1
    return tuple(positioned)


def validate_permutation(current: Sequence[ItemT], target: Sequence[ItemT]) -> None:
    """Raise when target is not an exact multiset permutation of current."""
    if len(current) != len(target) or Counter(current) != Counter(target):
        raise ValueError("target must contain exactly the same item occurrences as current")


def plan_range_moves(
    current: Sequence[ItemT],
    target: Sequence[ItemT],
) -> tuple[RangeMove, ...]:
    """Create deterministic sequential moves that realize the target order.

    Duplicate values are assigned occurrence identities in their observable
    left-to-right order, so no delimiter or synthetic Spotify ID is required.
    """
    validate_permutation(current, target)
    working = list(_occurrence_keys(current))
    destination = list(_occurrence_keys(target))
    moves: list[RangeMove] = []

    for target_index, wanted in enumerate(destination):
        if working[target_index] == wanted:
            continue
        source_index = working.index(wanted, target_index + 1)
        range_length = 1
        while (
            source_index + range_length < len(working)
            and target_index + range_length < len(destination)
            and working[source_index + range_length] == destination[target_index + range_length]
        ):
            range_length += 1

        move = RangeMove(
            range_start=source_index,
            insert_before=target_index,
            range_length=range_length,
        )
        moves.append(move)
        working = list(simulate_range_moves(working, (move,)))

    if working != destination:
        raise RuntimeError("range-move planner did not reach the requested permutation")
    return tuple(moves)


def simulate_range_moves(
    items: Sequence[ItemT],
    moves: Sequence[RangeMove],
) -> tuple[ItemT, ...]:
    """Apply Spotify range-move semantics without mutating the input sequence."""
    result = list(items)
    for move in moves:
        item_count = len(result)
        range_end = move.range_start + move.range_length
        if range_end > item_count or move.insert_before > item_count:
            raise ValueError("range move falls outside the playlist")

        if move.range_start <= move.insert_before <= range_end:
            continue

        moved = result[move.range_start : range_end]
        del result[move.range_start : range_end]
        insertion_index = move.insert_before
        if move.insert_before > range_end:
            insertion_index -= move.range_length
        result[insertion_index:insertion_index] = moved
    return tuple(result)


def _occurrence_keys(items: Sequence[ItemT]) -> tuple[tuple[ItemT, int], ...]:
    occurrences: dict[ItemT, int] = {}
    result: list[tuple[ItemT, int]] = []
    for item in items:
        occurrence = occurrences.get(item, 0)
        result.append((item, occurrence))
        occurrences[item] = occurrence + 1
    return tuple(result)
