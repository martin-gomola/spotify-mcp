"""Deterministic read plans for sampling a Spotify library across its history."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

SPOTIFY_PAGE_LIMIT = 50


class SampleRange(BaseModel):
    """One bounded, offset-based read from the Liked Songs collection."""

    model_config = ConfigDict(frozen=True)

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=SPOTIFY_PAGE_LIMIT)

    @property
    def end(self) -> int:
        """Return the exclusive end offset."""
        return self.offset + self.limit


def liked_song_sample_ranges(
    total: int,
    sample_size: int,
    *,
    preferred_segments: int = 8,
) -> tuple[SampleRange, ...]:
    """Plan deterministic, non-overlapping reads across the full library timeline.

    When at least two tracks are requested from a larger library, the first and
    last saved tracks are always represented. Every read respects Spotify's
    maximum page size.
    """
    _require_non_negative_integer("total", total)
    _require_non_negative_integer("sample_size", sample_size)
    if (
        isinstance(preferred_segments, bool)
        or not isinstance(preferred_segments, int)
        or preferred_segments <= 0
    ):
        raise ValueError("preferred_segments must be a positive integer")

    requested = min(total, sample_size)
    if requested == 0:
        return ()
    if requested == total:
        return tuple(
            SampleRange(offset=offset, limit=min(SPOTIFY_PAGE_LIMIT, total - offset))
            for offset in range(0, total, SPOTIFY_PAGE_LIMIT)
        )
    if requested == 1:
        return (SampleRange(offset=0, limit=1),)

    minimum_segments = (requested + SPOTIFY_PAGE_LIMIT - 1) // SPOTIFY_PAGE_LIMIT
    segment_count = min(requested, max(2, preferred_segments, minimum_segments))
    lengths = _balanced_parts(requested, segment_count)
    gaps = _balanced_parts(total - requested, segment_count - 1)

    ranges: list[SampleRange] = []
    offset = 0
    for index, length in enumerate(lengths):
        ranges.append(SampleRange(offset=offset, limit=length))
        if index < len(gaps):
            offset += length + gaps[index]

    return tuple(ranges)


def sample_offsets(
    total: int,
    sample_size: int,
    *,
    preferred_segments: int = 8,
) -> tuple[int, ...]:
    """Return the starting offsets for a Liked Songs sample plan."""
    return tuple(
        item.offset
        for item in liked_song_sample_ranges(
            total,
            sample_size,
            preferred_segments=preferred_segments,
        )
    )


def _balanced_parts(total: int, part_count: int) -> tuple[int, ...]:
    quotient, remainder = divmod(total, part_count)
    return tuple(quotient + (index < remainder) for index in range(part_count))


def _require_non_negative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
