"""Read-only podcast discovery and library use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.links import spotify_id, spotify_web_url

MAX_DISCOVERY_RESULTS = 10
MAX_PAGE_SIZE = 50


class PodcastModel(BaseModel):
    """Typed, immutable output that tolerates additions to Spotify responses."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class PodcastRestrictions(PodcastModel):
    reason: str | None = None


class PodcastShow(PodcastModel):
    id: str
    name: str
    uri: str | None = None
    description: str | None = None
    publisher: str | None = None
    languages: list[str] = Field(default_factory=list)
    explicit: bool | None = None
    total_episodes: int | None = Field(default=None, ge=0)
    media_type: str | None = None
    is_externally_hosted: bool | None = None
    is_playable: bool | None = None
    restrictions: PodcastRestrictions | None = None
    spotify_url: str


class PodcastEpisode(PodcastModel):
    id: str
    name: str
    uri: str | None = None
    description: str | None = None
    release_date: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    explicit: bool | None = None
    languages: list[str] = Field(default_factory=list)
    is_externally_hosted: bool | None = None
    is_playable: bool | None = None
    restrictions: PodcastRestrictions | None = None
    audio_preview_url: str | None = Field(
        default=None,
        description="Deprecated Spotify preview evidence when the API still supplies it.",
    )
    spotify_url: str


class PodcastDiscoveryResult(PodcastModel):
    query: str
    offset: int = Field(ge=0)
    show_total: int = Field(ge=0)
    episode_total: int = Field(ge=0)
    shows: list[PodcastShow]
    episodes: list[PodcastEpisode]


class PodcastEpisodesPage(PodcastModel):
    show_id: str
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0)
    next_url: str | None = None
    previous_url: str | None = None
    episodes: list[PodcastEpisode]


class SavedPodcastShow(PodcastModel):
    added_at: str | None = None
    show: PodcastShow


class SavedShowsPage(PodcastModel):
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0)
    next_url: str | None = None
    previous_url: str | None = None
    items: list[SavedPodcastShow]


class SavedPodcastEpisode(PodcastModel):
    added_at: str | None = None
    episode: PodcastEpisode


class SavedEpisodesPage(PodcastModel):
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0)
    next_url: str | None = None
    previous_url: str | None = None
    items: list[SavedPodcastEpisode]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _restrictions(value: Any) -> PodcastRestrictions | None:
    data = _mapping(value)
    return PodcastRestrictions(reason=_string(data.get("reason"))) if data else None


def _show(value: Any) -> PodcastShow | None:
    data = _mapping(value)
    show_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if show_id is None or name is None:
        return None
    total_episodes = _integer(data.get("total_episodes"))
    return PodcastShow(
        id=show_id,
        name=name,
        uri=_string(data.get("uri")),
        description=_string(data.get("description")),
        publisher=_string(data.get("publisher")),
        languages=_string_list(data.get("languages")),
        explicit=_boolean(data.get("explicit")),
        total_episodes=(total_episodes if total_episodes is None or total_episodes >= 0 else None),
        media_type=_string(data.get("media_type")),
        is_externally_hosted=_boolean(data.get("is_externally_hosted")),
        is_playable=_boolean(data.get("is_playable")),
        restrictions=_restrictions(data.get("restrictions")),
        spotify_url=spotify_web_url("show", show_id),
    )


def _episode(value: Any) -> PodcastEpisode | None:
    data = _mapping(value)
    episode_id = _string(data.get("id"))
    name = _string(data.get("name"))
    if episode_id is None or name is None:
        return None
    duration_ms = _integer(data.get("duration_ms"))
    return PodcastEpisode(
        id=episode_id,
        name=name,
        uri=_string(data.get("uri")),
        description=_string(data.get("description")),
        release_date=_string(data.get("release_date")),
        duration_ms=duration_ms if duration_ms is None or duration_ms >= 0 else None,
        explicit=_boolean(data.get("explicit")),
        languages=_string_list(data.get("languages")),
        is_externally_hosted=_boolean(data.get("is_externally_hosted")),
        is_playable=_boolean(data.get("is_playable")),
        restrictions=_restrictions(data.get("restrictions")),
        audio_preview_url=_string(data.get("audio_preview_url")),
        spotify_url=spotify_web_url("episode", episode_id),
    )


def _items(value: Any) -> list[Any]:
    items = _mapping(value).get("items")
    return list(items) if isinstance(items, list) else []


def _total(page: Mapping[str, Any], item_count: int) -> int:
    total = _integer(page.get("total"))
    return total if total is not None and total >= 0 else item_count


def _exact_id(value: str, resource_type: Literal["show", "episode"]) -> str:
    return spotify_id(resource_type, value)


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be non-negative")


class PodcastService:
    """Transport-independent podcast reads over supported Spotify endpoints."""

    def __init__(self, spotify: SpotifyGateway) -> None:
        self._spotify = spotify

    async def discover(
        self, query: str, *, limit: int = MAX_DISCOVERY_RESULTS, offset: int = 0
    ) -> PodcastDiscoveryResult:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= MAX_DISCOVERY_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_DISCOVERY_RESULTS}")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        payload = _mapping(
            await self._spotify.request(
                "GET",
                "/search",
                params={
                    "q": query,
                    "type": "show,episode",
                    "limit": limit,
                    "offset": offset,
                    "market": "from_token",
                },
            )
        )
        show_page = _mapping(payload.get("shows"))
        episode_page = _mapping(payload.get("episodes"))
        shows = [show_item for raw in _items(show_page) if (show_item := _show(raw)) is not None]
        episodes = [
            episode_item
            for raw in _items(episode_page)
            if (episode_item := _episode(raw)) is not None
        ]
        return PodcastDiscoveryResult(
            query=query,
            offset=offset,
            show_total=_total(show_page, len(shows)),
            episode_total=_total(episode_page, len(episodes)),
            shows=shows,
            episodes=episodes,
        )

    async def get_show(self, show_id: str) -> PodcastShow:
        exact_id = _exact_id(show_id, "show")
        result = _show(
            await self._spotify.request(
                "GET", f"/shows/{exact_id}", params={"market": "from_token"}
            )
        )
        if result is None:
            raise ValueError("Spotify returned malformed show data")
        return result

    async def get_show_episodes(
        self, show_id: str, *, limit: int = 20, offset: int = 0
    ) -> PodcastEpisodesPage:
        _validate_page(limit, offset)
        exact_id = _exact_id(show_id, "show")
        page = _mapping(
            await self._spotify.request(
                "GET",
                f"/shows/{exact_id}/episodes",
                params={"limit": limit, "offset": offset, "market": "from_token"},
            )
        )
        episodes = [item for raw in _items(page) if (item := _episode(raw)) is not None]
        return PodcastEpisodesPage(
            show_id=exact_id,
            total=_total(page, len(episodes)),
            limit=limit,
            offset=offset,
            next_url=_string(page.get("next")),
            previous_url=_string(page.get("previous")),
            episodes=episodes,
        )

    async def get_episode(self, episode_id: str) -> PodcastEpisode:
        exact_id = _exact_id(episode_id, "episode")
        result = _episode(
            await self._spotify.request(
                "GET", f"/episodes/{exact_id}", params={"market": "from_token"}
            )
        )
        if result is None:
            raise ValueError("Spotify returned malformed episode data")
        return result

    async def get_saved_shows(self, *, limit: int = 20, offset: int = 0) -> SavedShowsPage:
        _validate_page(limit, offset)
        page = _mapping(
            await self._spotify.request(
                "GET", "/me/shows", params={"limit": limit, "offset": offset}
            )
        )
        saved: list[SavedPodcastShow] = []
        for raw in _items(page):
            entry = _mapping(raw)
            parsed = _show(entry.get("show"))
            if parsed is not None:
                saved.append(SavedPodcastShow(added_at=_string(entry.get("added_at")), show=parsed))
        return SavedShowsPage(
            total=_total(page, len(saved)),
            limit=limit,
            offset=offset,
            next_url=_string(page.get("next")),
            previous_url=_string(page.get("previous")),
            items=saved,
        )

    async def get_saved_episodes(self, *, limit: int = 20, offset: int = 0) -> SavedEpisodesPage:
        _validate_page(limit, offset)
        page = _mapping(
            await self._spotify.request(
                "GET",
                "/me/episodes",
                params={"limit": limit, "offset": offset, "market": "from_token"},
            )
        )
        saved: list[SavedPodcastEpisode] = []
        for raw in _items(page):
            entry = _mapping(raw)
            parsed = _episode(entry.get("episode"))
            if parsed is not None:
                saved.append(
                    SavedPodcastEpisode(added_at=_string(entry.get("added_at")), episode=parsed)
                )
        return SavedEpisodesPage(
            total=_total(page, len(saved)),
            limit=limit,
            offset=offset,
            next_url=_string(page.get("next")),
            previous_url=_string(page.get("previous")),
            items=saved,
        )
