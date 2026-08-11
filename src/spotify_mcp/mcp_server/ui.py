"""Optional MCP Apps presentation for final, display-ready Spotify results."""

from __future__ import annotations

import asyncio
from importlib.resources import files
from typing import Literal, cast
from urllib.parse import urlsplit

from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spotify_mcp.application.playback import (
    Device,
    NowPlaying,
    ObservedPlaybackResult,
    PlaybackResult,
    PlaybackService,
)
from spotify_mcp.domain.links import SpotifyEntityType, spotify_uri, spotify_web_url
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, READ_ONLY, WRITE
from spotify_mcp.mcp_server.context import AppContext

RESULTS_UI_URI = "ui://spotify/results/v1.html"
_RESULTS_ASSET = "resources/spotify-results-v1.html"
_PLAYABLE_RESULT_TYPES = frozenset({"track", "album", "artist", "playlist"})


def _spotify_entity_from_url(value: str) -> tuple[SpotifyEntityType, str]:
    parsed = urlsplit(value)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "open.spotify.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 2
        or parts[0] not in {"track", "album", "artist", "playlist", "episode", "show"}
    ):
        raise ValueError("spotify_url must be a canonical open.spotify.com entity URL")
    entity_type = cast(SpotifyEntityType, parts[0])
    entity_id = parts[1]
    if spotify_web_url(entity_type, entity_id) != value:
        raise ValueError("spotify_url must be a canonical open.spotify.com entity URL")
    return entity_type, entity_id


class SpotifyResultCard(BaseModel):
    """One safe, display-ready Spotify result supplied by the model."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=200)
    spotify_url: str
    subtitle: str | None = Field(default=None, max_length=300)
    kind: Literal["track", "album", "artist", "playlist", "episode", "show"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("spotify_url")
    @classmethod
    def validate_spotify_url(cls, value: str) -> str:
        _spotify_entity_from_url(value)
        return value

    @model_validator(mode="after")
    def validate_kind_matches_url(self) -> SpotifyResultCard:
        entity_type, _ = _spotify_entity_from_url(self.spotify_url)
        if entity_type != self.kind:
            raise ValueError("kind must match the canonical Spotify URL entity type")
        return self


class SpotifyResultsView(BaseModel):
    """Structured content shared by the model and the optional UI."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=200)
    items: list[SpotifyResultCard] = Field(min_length=1, max_length=50)


class SpotifyResultsContext(BaseModel):
    """Device and playback state needed by the inline results view."""

    model_config = ConfigDict(frozen=True)

    devices: list[Device]
    selected_device_id: str | None
    requires_device_selection: bool
    has_usable_devices: bool
    now_playing: NowPlaying


def create_results_apps() -> Apps:
    """Build the optional result UI extension without changing data-tool behavior."""

    html = files("spotify_mcp.mcp_server").joinpath(_RESULTS_ASSET).read_text(encoding="utf-8")
    apps = Apps()
    apps.add_html_resource(
        RESULTS_UI_URI,
        html,
        name="spotify-results",
        title="Spotify results",
        description="Compact clickable Spotify result cards.",
        csp=ResourceCsp(
            connect_domains=[],
            resource_domains=[],
            frame_domains=[],
            base_uri_domains=[],
        ),
        prefers_border=True,
    )

    @apps.tool(
        resource_uri=RESULTS_UI_URI,
        visibility=("model",),
        name="spotify_render_results",
        title="Show Spotify results",
        description=(
            "Render a final, display-ready list of Spotify entities exactly once per response. "
            "Call data tools first, then pass only the final results the user should see; do not "
            "call this tool again in the same response."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def render_results(title: str, items: list[SpotifyResultCard]) -> SpotifyResultsView:
        return SpotifyResultsView(title=title, items=items)

    @apps.tool(
        resource_uri=RESULTS_UI_URI,
        visibility=("app",),
        name="spotify_results_context",
        title="Spotify results playback context",
        description="Return devices and observed playback state for the inline Spotify results UI.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def results_context(ctx: Context[AppContext]) -> SpotifyResultsContext:
        service = PlaybackService(ctx.request_context.lifespan_context.spotify)
        device_result, now_playing = await asyncio.gather(service.devices(), service.now_playing())
        devices = device_result.devices
        usable = [
            device for device in devices if device.id is not None and not device.is_restricted
        ]
        selected_device_id = usable[0].id if len(usable) == 1 else None
        return SpotifyResultsContext(
            devices=devices,
            selected_device_id=selected_device_id,
            requires_device_selection=len(usable) > 1,
            has_usable_devices=bool(usable),
            now_playing=now_playing,
        )

    @apps.tool(
        resource_uri=RESULTS_UI_URI,
        visibility=("app",),
        name="spotify_results_play",
        title="Play Spotify result",
        description=(
            "Play one exact result on one selected device and verify it with bounded fresh reads."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def results_play(
        ctx: Context[AppContext], spotify_url: str, device_id: str
    ) -> ObservedPlaybackResult:
        entity_type, entity_id = _spotify_entity_from_url(spotify_url)
        if entity_type not in _PLAYABLE_RESULT_TYPES:
            raise ValueError("direct play supports tracks, albums, artists, and playlists")
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).play_and_observe(
            uri=spotify_uri(entity_type, entity_id),
            device_id=device_id,
        )

    @apps.tool(
        resource_uri=RESULTS_UI_URI,
        visibility=("app",),
        name="spotify_results_pause",
        title="Pause Spotify result playback",
        description="Pause Spotify playback on the device selected by the inline results UI.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def results_pause(ctx: Context[AppContext], device_id: str) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).pause(
            device_id=device_id
        )

    return apps
