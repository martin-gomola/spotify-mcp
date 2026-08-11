"""Deterministic local taste rediscovery over existing Spotify signals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.discovery import DiscoveryService, Track
from spotify_mcp.application.library import SavedTrack, sample_saved_tracks
from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.errors import SpotifyRequestError
from spotify_mcp.domain.links import spotify_web_url

SourceSignal = Literal["top_tracks", "recently_played", "liked_songs"]

_SIGNAL_ORDER: tuple[SourceSignal, ...] = (
    "top_tracks",
    "liked_songs",
    "recently_played",
)


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class SignalCoverage(Model):
    signal: SourceSignal
    available: bool
    track_count: int = Field(ge=0)
    warning: str | None = None


class RecommendedTrack(Model):
    id: str
    uri: str | None = None
    spotify_url: str
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    popularity: int | None = None
    source_signals: list[SourceSignal]
    reasons: list[str]


class TasteRecommendations(Model):
    schema_version: Literal[1] = 1
    strategy_version: Literal["local-deterministic-v1"] = "local-deterministic-v1"
    is_spotify_recommendation: Literal[False] = False
    curation: Literal["local-deterministic"] = "local-deterministic"
    requested_limit: int = Field(ge=1, le=50)
    returned_count: int = Field(ge=0, le=50)
    source_signal_coverage: list[SignalCoverage]
    warnings: list[str]
    tracks: list[RecommendedTrack]


class _Candidate:
    def __init__(self, track: Track | SavedTrack) -> None:
        self.track = track
        self.ranks: dict[SourceSignal, int] = {}

    def add_signal(self, signal: SourceSignal, rank: int) -> None:
        current = self.ranks.get(signal)
        if current is None or rank < current:
            self.ranks[signal] = rank

    @property
    def source_signals(self) -> list[SourceSignal]:
        return [signal for signal in _SIGNAL_ORDER if signal in self.ranks]

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        top_rank = self.ranks.get("top_tracks", 1_000_000)
        liked_rank = self.ranks.get("liked_songs", 1_000_000)
        candidate_signal_count = int("top_tracks" in self.ranks) + int("liked_songs" in self.ranks)
        return (
            -candidate_signal_count,
            min(top_rank, liked_rank),
            top_rank + liked_rank,
            self.track.id,
        )


async def taste_recommendations(
    spotify: SpotifyGateway, *, limit: int = 20
) -> TasteRecommendations:
    """Build a reproducible rediscovery list without Spotify's recommendation endpoint."""

    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    discovery = DiscoveryService(spotify)
    warnings: list[str] = []
    coverage: list[SignalCoverage] = []

    try:
        top_tracks = (await discovery.top_tracks(time_range="medium_term", limit=50)).tracks
        coverage.append(
            SignalCoverage(signal="top_tracks", available=True, track_count=len(top_tracks))
        )
    except SpotifyRequestError as error:
        top_tracks = []
        warning = f"top_tracks unavailable: {error}"
        warnings.append(warning)
        coverage.append(
            SignalCoverage(signal="top_tracks", available=False, track_count=0, warning=warning)
        )

    try:
        recent_tracks = (await discovery.recently_played(limit=50)).tracks
        coverage.append(
            SignalCoverage(signal="recently_played", available=True, track_count=len(recent_tracks))
        )
    except SpotifyRequestError as error:
        recent_tracks = []
        warning = f"recently_played unavailable: {error}"
        warnings.append(warning)
        coverage.append(
            SignalCoverage(
                signal="recently_played", available=False, track_count=0, warning=warning
            )
        )

    try:
        liked_sample = await sample_saved_tracks(spotify, sample_size=48)
        liked_tracks = liked_sample.tracks
        warnings.extend(liked_sample.warnings)
        coverage.append(
            SignalCoverage(signal="liked_songs", available=True, track_count=len(liked_tracks))
        )
    except SpotifyRequestError as error:
        liked_tracks = []
        warning = f"liked_songs unavailable: {error}"
        warnings.append(warning)
        coverage.append(
            SignalCoverage(signal="liked_songs", available=False, track_count=0, warning=warning)
        )

    candidates: dict[str, _Candidate] = {}
    for rank, top_track in enumerate(top_tracks):
        candidates.setdefault(top_track.id, _Candidate(top_track)).add_signal("top_tracks", rank)
    for rank, liked_track in enumerate(liked_tracks):
        candidates.setdefault(liked_track.id, _Candidate(liked_track)).add_signal(
            "liked_songs", rank
        )

    recent_ids = {recent_track.id for recent_track in recent_tracks}
    for rank, recent_track in enumerate(recent_tracks):
        candidate = candidates.get(recent_track.id)
        if candidate is not None:
            candidate.add_signal("recently_played", rank)

    ranked = sorted(candidates.values(), key=lambda candidate: candidate.sort_key)
    fresh = [candidate for candidate in ranked if candidate.track.id not in recent_ids]
    if len(fresh) >= limit:
        selected = fresh[:limit]
    else:
        recent = [candidate for candidate in ranked if candidate.track.id in recent_ids]
        selected = (fresh + recent)[:limit]
        if recent and len(selected) > len(fresh):
            warnings.append(
                "Not enough non-recent candidates were available; recently played tracks were "
                "included to satisfy the requested limit."
            )

    tracks = [_recommendation(candidate) for candidate in selected]
    return TasteRecommendations(
        requested_limit=limit,
        returned_count=len(tracks),
        source_signal_coverage=coverage,
        warnings=warnings,
        tracks=tracks,
    )


def _recommendation(candidate: _Candidate) -> RecommendedTrack:
    reasons: list[str] = []
    if "top_tracks" in candidate.ranks:
        reasons.append("Appears in the medium-term top tracks signal.")
    if "liked_songs" in candidate.ranks:
        reasons.append("Selected from the stratified Liked Songs history sample.")
    if "recently_played" in candidate.ranks:
        reasons.append("Recently played; included only because fresher candidates were limited.")

    track = candidate.track
    return RecommendedTrack(
        id=track.id,
        uri=track.uri,
        spotify_url=spotify_web_url("track", track.id),
        name=track.name,
        artists=track.artists,
        album=track.album,
        duration_ms=track.duration_ms,
        explicit=track.explicit,
        popularity=track.popularity,
        source_signals=candidate.source_signals,
        reasons=reasons,
    )
