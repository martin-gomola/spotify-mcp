"""Liked Songs use cases independent of the MCP transport."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.errors import AmbiguousWrite, SpotifyRequestError
from spotify_mcp.domain.links import spotify_web_url

MAX_PAGE_SIZE = 50
MAX_LIBRARY_ITEMS_PER_WRITE = 40
MAX_SAMPLE_SIZE = 100
SAMPLE_SEGMENTS = 8


class Track(BaseModel):
    """Stable track fields returned to MCP clients."""

    id: str
    uri: str | None = None
    spotify_url: str | None = None
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    explicit: bool | None = None
    popularity: int | None = None


class SavedTrack(Track):
    """A track together with its position in Liked Songs."""

    added_at: str
    library_position: int = Field(ge=1)


class SavedTracksPage(BaseModel):
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    tracks: list[SavedTrack]
    warnings: list[str]


class SavedTracksSample(BaseModel):
    schema_version: Literal[1] = 1
    library_total: int = Field(ge=0)
    requested_sample_size: int = Field(ge=1)
    sampled_count: int = Field(ge=0)
    strategy: Literal["stratified-history-v1"] = "stratified-history-v1"
    sampled_offsets: list[int]
    tracks: list[SavedTrack]
    warnings: list[str]


class LibraryContainsResult(BaseModel):
    track_ids: list[str]
    saved: list[bool]


class LibraryMutationResult(BaseModel):
    operation: Literal["save", "remove"]
    track_ids: list[str]
    status: Literal["verified", "mismatch", "ambiguous"]
    observed_saved: list[bool] | None = None
    mismatches: list[str]
    warning: str | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _track(raw: Any) -> Track | None:
    data = _mapping(raw)
    track_id = data.get("id")
    name = data.get("name")
    if not isinstance(track_id, str) or not isinstance(name, str):
        return None

    artists = [
        artist["name"]
        for value in data.get("artists", [])
        if isinstance(value, Mapping) and isinstance((artist := value).get("name"), str)
    ]
    album_data = _mapping(data.get("album"))
    album = album_data.get("name")
    duration = data.get("duration_ms")
    explicit = data.get("explicit")
    popularity = data.get("popularity")
    uri = data.get("uri")
    external_urls = _mapping(data.get("external_urls"))
    return Track(
        id=track_id,
        uri=uri if isinstance(uri, str) else None,
        spotify_url=spotify_web_url(
            "track",
            track_id,
            external_url=external_urls.get("spotify")
            if isinstance(external_urls.get("spotify"), str)
            else None,
        ),
        name=name,
        artists=artists,
        album=album if isinstance(album, str) else None,
        duration_ms=duration if isinstance(duration, int) and duration >= 0 else 0,
        explicit=explicit if isinstance(explicit, bool) else None,
        popularity=popularity if isinstance(popularity, int) else None,
    )


def _saved_tracks(raw_items: Any, *, offset: int) -> tuple[list[SavedTrack], list[str]]:
    if not isinstance(raw_items, list):
        return [], []

    tracks: list[SavedTrack] = []
    warnings: list[str] = []
    for index, raw_entry in enumerate(raw_items):
        entry = _mapping(raw_entry)
        track = _track(entry.get("track") or entry.get("item"))
        position = offset + index + 1
        if track is None:
            warnings.append(f"Skipped unavailable item at Liked Songs position {position}")
            continue
        added_at = entry.get("added_at")
        tracks.append(
            SavedTrack(
                **track.model_dump(),
                added_at=added_at if isinstance(added_at, str) else "",
                library_position=position,
            )
        )
    return tracks, warnings


def _normalise_ids(track_ids: Iterable[str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in track_ids:
        candidate = value.strip()
        if candidate.startswith("spotify:track:"):
            candidate = candidate.removeprefix("spotify:track:")
        if candidate and candidate not in seen:
            ids.append(candidate)
            seen.add(candidate)
    return ids


def _track_uris(track_ids: Sequence[str]) -> str:
    return ",".join(f"spotify:track:{track_id}" for track_id in track_ids)


def stratified_sample_ranges(
    total: int, sample_size: int, max_segments: int = SAMPLE_SEGMENTS
) -> list[tuple[int, int]]:
    """Return deterministic page ranges spanning newest through oldest saves."""

    if total <= 0 or sample_size <= 0 or max_segments <= 0:
        return []
    target = min(total, sample_size)
    segment_count = min(max_segments, target)
    strata = [
        [index * total // segment_count, (index + 1) * total // segment_count, 1]
        for index in range(segment_count)
    ]
    remaining = target - segment_count
    while remaining:
        allocated = False
        for stratum in strata:
            if remaining == 0:
                break
            start, end, count = stratum
            if count >= end - start:
                continue
            stratum[2] += 1
            remaining -= 1
            allocated = True
        if not allocated:
            break

    ranges: list[tuple[int, int]] = []
    for index, (start, end, count) in enumerate(strata):
        if index == 0:
            offset = start
        elif index == len(strata) - 1:
            offset = end - count
        else:
            offset = start + (end - start - count) // 2
        ranges.append((offset, count))
    return ranges


async def get_saved_tracks(
    spotify: SpotifyGateway, *, limit: int = MAX_PAGE_SIZE, offset: int = 0
) -> SavedTracksPage:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    page = _mapping(
        await spotify.request("GET", "/me/tracks", params={"limit": limit, "offset": offset})
    )
    tracks, warnings = _saved_tracks(page.get("items"), offset=offset)
    total = page.get("total")
    return SavedTracksPage(
        total=total if isinstance(total, int) and total >= 0 else len(tracks),
        offset=offset,
        tracks=tracks,
        warnings=warnings,
    )


async def sample_saved_tracks(
    spotify: SpotifyGateway, *, sample_size: int = 48
) -> SavedTracksSample:
    if not 8 <= sample_size <= MAX_SAMPLE_SIZE:
        raise ValueError(f"sample_size must be between 8 and {MAX_SAMPLE_SIZE}")

    first_page = _mapping(
        await spotify.request("GET", "/me/tracks", params={"limit": MAX_PAGE_SIZE, "offset": 0})
    )
    first_items = first_page.get("items")
    fallback_total = len(first_items) if isinstance(first_items, list) else 0
    raw_total = first_page.get("total")
    library_total = raw_total if isinstance(raw_total, int) and raw_total >= 0 else fallback_total
    ranges = stratified_sample_ranges(library_total, sample_size)

    async def read_range(offset: int, limit: int) -> tuple[int, Any]:
        if offset == 0:
            return offset, first_items[:limit] if isinstance(first_items, list) else []
        page = _mapping(
            await spotify.request("GET", "/me/tracks", params={"limit": limit, "offset": offset})
        )
        return offset, page.get("items")

    pages = await asyncio.gather(*(read_range(offset, limit) for offset, limit in ranges))
    tracks: list[SavedTrack] = []
    warnings: list[str] = []
    for offset, items in pages:
        page_tracks, page_warnings = _saved_tracks(items, offset=offset)
        tracks.extend(page_tracks)
        warnings.extend(page_warnings)

    target = min(library_total, sample_size)
    if len(tracks) < target:
        warnings.append(f"Requested {target} available tracks but returned {len(tracks)}")
    return SavedTracksSample(
        library_total=library_total,
        requested_sample_size=sample_size,
        sampled_count=len(tracks),
        sampled_offsets=[offset for offset, _ in ranges],
        tracks=tracks,
        warnings=warnings,
    )


async def check_saved_tracks(
    spotify: SpotifyGateway, track_ids: Sequence[str]
) -> LibraryContainsResult:
    ids = _normalise_ids(track_ids)
    if not ids:
        raise ValueError("at least one track ID is required")
    if len(ids) > MAX_LIBRARY_ITEMS_PER_WRITE:
        raise ValueError(f"at most {MAX_LIBRARY_ITEMS_PER_WRITE} track IDs are allowed")
    response = await spotify.request(
        "GET", "/me/library/contains", params={"uris": _track_uris(ids)}
    )
    if (
        not isinstance(response, list)
        or len(response) != len(ids)
        or any(not isinstance(value, bool) for value in response)
    ):
        raise SpotifyRequestError("Spotify returned malformed library membership evidence")
    saved = list(response)
    return LibraryContainsResult(track_ids=ids, saved=saved)


async def _mutate_saved_tracks(
    spotify: SpotifyGateway, track_ids: Sequence[str], *, save: bool
) -> LibraryMutationResult:
    ids = _normalise_ids(track_ids)
    if not ids:
        raise ValueError("at least one track ID is required")
    if len(ids) > MAX_LIBRARY_ITEMS_PER_WRITE:
        raise ValueError(f"at most {MAX_LIBRARY_ITEMS_PER_WRITE} track IDs are allowed")
    try:
        await spotify.request(
            "PUT" if save else "DELETE",
            "/me/library",
            params={"uris": _track_uris(ids)},
        )
    except AmbiguousWrite as exc:
        return LibraryMutationResult(
            operation="save" if save else "remove",
            track_ids=ids,
            status="ambiguous",
            mismatches=[],
            warning=str(exc),
        )
    try:
        observed = await check_saved_tracks(spotify, ids)
    except Exception as exc:  # The write may already have succeeded; never invite a blind retry.
        return LibraryMutationResult(
            operation="save" if save else "remove",
            track_ids=ids,
            status="ambiguous",
            mismatches=[],
            warning=f"Spotify accepted the write, but verification failed: {exc}",
        )
    mismatches = [
        f"{track_id}: expected saved={save}, observed saved={actual}"
        for track_id, actual in zip(ids, observed.saved, strict=True)
        if actual is not save
    ]
    return LibraryMutationResult(
        operation="save" if save else "remove",
        track_ids=ids,
        status="mismatch" if mismatches else "verified",
        observed_saved=observed.saved,
        mismatches=mismatches,
    )


async def save_tracks(spotify: SpotifyGateway, track_ids: Sequence[str]) -> LibraryMutationResult:
    return await _mutate_saved_tracks(spotify, track_ids, save=True)


async def remove_saved_tracks(
    spotify: SpotifyGateway, track_ids: Sequence[str]
) -> LibraryMutationResult:
    return await _mutate_saved_tracks(spotify, track_ids, save=False)
