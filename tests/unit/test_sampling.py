from itertools import pairwise

import pytest

from spotify_mcp.domain.sampling import SampleRange, liked_song_sample_ranges, sample_offsets


def test_empty_library_or_zero_sample_needs_no_reads() -> None:
    assert liked_song_sample_ranges(0, 48) == ()
    assert liked_song_sample_ranges(500, 0) == ()


def test_small_library_is_covered_once_in_spotify_sized_pages() -> None:
    ranges = liked_song_sample_ranges(103, 200)

    assert ranges == (
        SampleRange(offset=0, limit=50),
        SampleRange(offset=50, limit=50),
        SampleRange(offset=100, limit=3),
    )


def test_sample_is_deterministic_non_overlapping_and_spans_history() -> None:
    first = liked_song_sample_ranges(1_000, 48)
    second = liked_song_sample_ranges(1_000, 48)

    assert first == second
    assert first[0].offset == 0
    assert first[-1].end == 1_000
    assert sum(item.limit for item in first) == 48
    assert all(item.limit <= 50 for item in first)
    assert all(left.end <= right.offset for left, right in pairwise(first))


def test_large_sample_adds_enough_ranges_to_respect_page_limit() -> None:
    ranges = liked_song_sample_ranges(5_000, 501, preferred_segments=2)

    assert len(ranges) == 11
    assert sum(item.limit for item in ranges) == 501
    assert max(item.limit for item in ranges) <= 50
    assert ranges[-1].end == 5_000


def test_single_item_sample_has_a_documented_first_item_fallback() -> None:
    assert liked_song_sample_ranges(100, 1) == (SampleRange(offset=0, limit=1),)
    assert sample_offsets(100, 1) == (0,)


@pytest.mark.parametrize(
    ("total", "sample_size"),
    [(-1, 1), (1, -1), (True, 1), (1, False)],
)
def test_invalid_counts_are_rejected(total: int, sample_size: int) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        liked_song_sample_ranges(total, sample_size)
