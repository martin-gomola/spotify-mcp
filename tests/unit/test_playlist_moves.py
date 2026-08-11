import pytest

from spotify_mcp.domain.playlist_moves import (
    PlaylistPositionIdentity,
    RangeMove,
    plan_range_moves,
    playlist_position_identities,
    simulate_range_moves,
    validate_permutation,
)


def test_position_identities_disambiguate_duplicates_without_string_tokens() -> None:
    identities = playlist_position_identities(("track", "other", "track"))

    assert identities == (
        PlaylistPositionIdentity(item_id="track", occurrence=0),
        PlaylistPositionIdentity(item_id="other", occurrence=0),
        PlaylistPositionIdentity(item_id="track", occurrence=1),
    )


def test_plan_reaches_exact_duplicate_safe_permutation() -> None:
    current = ("a", "b", "a", "c", "d")
    target = ("a", "a", "d", "b", "c")

    moves = plan_range_moves(current, target)

    assert simulate_range_moves(current, moves) == target
    assert current == ("a", "b", "a", "c", "d")


def test_planner_combines_an_adjacent_target_run() -> None:
    moves = plan_range_moves(("a", "b", "c", "d"), ("c", "d", "a", "b"))

    assert moves == (RangeMove(range_start=2, insert_before=0, range_length=2),)


def test_simulator_supports_forward_and_backward_spotify_moves() -> None:
    assert simulate_range_moves(
        ("a", "b", "c", "d"),
        (RangeMove(range_start=0, insert_before=4, range_length=2),),
    ) == ("c", "d", "a", "b")
    assert simulate_range_moves(
        ("a", "b", "c", "d"),
        (RangeMove(range_start=2, insert_before=0),),
    ) == ("c", "a", "b", "d")


def test_simulator_rejects_out_of_bounds_moves() -> None:
    with pytest.raises(ValueError, match="outside"):
        simulate_range_moves(("a",), (RangeMove(range_start=1, insert_before=0),))
    with pytest.raises(ValueError, match="outside"):
        simulate_range_moves(("a",), (RangeMove(range_start=0, insert_before=2),))


def test_permutation_validation_counts_duplicate_occurrences() -> None:
    with pytest.raises(ValueError, match="same item occurrences"):
        validate_permutation(("a", "a", "b"), ("a", "b", "b"))
    with pytest.raises(ValueError, match="same item occurrences"):
        plan_range_moves(("a", "b"), ("a",))
