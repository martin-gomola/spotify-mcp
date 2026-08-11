"""Optional MCP Apps presentation for final, display-ready Spotify results."""

from __future__ import annotations

from importlib.resources import files
from typing import Literal, cast
from urllib.parse import urlsplit

from mcp.server.apps import Apps
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, field_validator

from spotify_mcp.domain.links import SpotifyEntityType, spotify_web_url

RESULTS_UI_URI = "ui://spotify/results/v1.html"
_RESULTS_ASSET = "resources/spotify-results-v1.html"


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
        if spotify_web_url(entity_type, parts[1]) != value:
            raise ValueError("spotify_url must be a canonical open.spotify.com entity URL")
        return value


class SpotifyResultsView(BaseModel):
    """Structured content shared by the model and the optional UI."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=200)
    items: list[SpotifyResultCard] = Field(min_length=1, max_length=50)


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
        prefers_border=True,
    )

    @apps.tool(
        resource_uri=RESULTS_UI_URI,
        visibility=("model",),
        name="spotify_render_results",
        title="Show Spotify results",
        description=(
            "Render a final, display-ready list of Spotify entities. Call data tools first, "
            "then pass only the results the user should see."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        meta={"openai/outputTemplate": RESULTS_UI_URI},
        structured_output=True,
    )
    async def render_results(title: str, items: list[SpotifyResultCard]) -> SpotifyResultsView:
        return SpotifyResultsView(title=title, items=items)

    return apps
