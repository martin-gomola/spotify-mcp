import pytest
from pydantic import ValidationError

from spotify_mcp.domain.models import Artist, Page, Playlist, Track, WriteState, WriteStatus


def test_track_accepts_fields_spotify_may_omit() -> None:
    track = Track.model_validate(
        {
            "id": "track-1",
            "name": "Night Drive",
            "artists": [{"name": "Artist", "unknown_future_field": True}],
            "market_specific_field": "ignored",
        }
    )

    assert track.artists == (Artist(name="Artist"),)
    assert track.popularity is None
    assert track.uri is None


def test_models_reject_invalid_bounded_values_and_blank_names() -> None:
    with pytest.raises(ValidationError):
        Artist(name="   ")
    with pytest.raises(ValidationError):
        Track(name="Track", popularity=101)
    with pytest.raises(ValidationError):
        Playlist(id="playlist", name="Playlist", track_count=-1)


def test_page_supports_spotify_link_aliases_and_is_immutable() -> None:
    page = Page[Track].model_validate(
        {
            "items": [{"id": "one", "name": "One"}],
            "total": 2,
            "limit": 1,
            "offset": 0,
            "next": "https://api.spotify.test/next",
        }
    )

    assert page.next_url == "https://api.spotify.test/next"
    with pytest.raises(ValidationError):
        page.offset = 1


def test_page_rejects_more_items_than_its_limit() -> None:
    with pytest.raises(ValidationError, match="page limit"):
        Page[int](items=(1, 2), total=2, limit=1, offset=0)


def test_mismatch_status_requires_verification_evidence() -> None:
    with pytest.raises(ValidationError, match="at least one mismatch"):
        WriteStatus(operation="update playlist", state=WriteState.MISMATCH)

    result = WriteStatus(
        operation="update playlist",
        state=WriteState.MISMATCH,
        resource_id="playlist-1",
        changed=True,
        mismatches=("public remained true",),
    )

    assert result.state == "mismatch"
