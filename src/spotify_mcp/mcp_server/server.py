"""Official MCP SDK v2 server assembly."""

from __future__ import annotations

from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ConfigDict

from spotify_mcp import __version__
from spotify_mcp.bootstrap import app_lifespan
from spotify_mcp.domain.errors import AuthenticationRequired
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext
from spotify_mcp.mcp_server.tools import (
    albums,
    audio,
    bpm_sort,
    discovery,
    dj,
    dj_audit,
    library,
    playback,
    playlists,
)


class SpotifyStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    authenticated: bool
    configuration_error: str | None = None
    user_id: str | None = None
    display_name: str | None = None
    product: str | None = None


def create_server() -> MCPServer[AppContext]:
    instructions = (Path(__file__).with_name("instructions.md")).read_text(encoding="utf-8")
    server = MCPServer[AppContext](
        name="spotify-mcp",
        title="Spotify MCP",
        description="Local-first Spotify playback, library, playlist, audio, and DJ tools.",
        instructions=instructions,
        version=__version__,
        lifespan=app_lifespan,
    )

    @server.tool(
        name="spotify_status",
        title="Spotify status",
        description="Check whether local Spotify configuration and authentication work.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_status(ctx: Context[AppContext]) -> SpotifyStatus:
        app = ctx.request_context.lifespan_context
        if not app.configured:
            return SpotifyStatus(
                configured=False,
                authenticated=False,
                configuration_error=app.configuration_error,
            )
        try:
            profile = await app.spotify.request("GET", "me")
        except AuthenticationRequired:
            return SpotifyStatus(configured=True, authenticated=False)
        return SpotifyStatus(
            configured=True,
            authenticated=True,
            user_id=profile.get("id") if isinstance(profile, dict) else None,
            display_name=profile.get("display_name") if isinstance(profile, dict) else None,
            product=profile.get("product") if isinstance(profile, dict) else None,
        )

    for module in (
        discovery,
        playback,
        library,
        albums,
        playlists,
        audio,
        dj,
        dj_audit,
        bpm_sort,
    ):
        module.register(server)
    return server


server = create_server()
