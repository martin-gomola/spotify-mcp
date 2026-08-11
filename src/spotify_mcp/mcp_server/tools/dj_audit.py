"""MCP v2 registration for the full read-only DJ playlist audit."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.dj_audit import audit_dj_playlist
from spotify_mcp.domain.audio import AudioLookupSource, AudioOverride
from spotify_mcp.domain.dj_audit import DjPlaylistAuditReport
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register the playlist-wide audit without binding runtime dependencies globally."""

    @server.tool(
        name="spotify_dj_audit",
        title="Audit Spotify DJ Playlist",
        description=(
            "Audit every position in a Spotify playlist for audio-feature coverage, exact and "
            "likely duplicate recordings, tempo ambiguity, provider conflicts, and heuristic "
            "opening, peak, and reset candidates without changing Spotify."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def audit_playlist_tool(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext, Any],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[AudioOverride] | None = None,
    ) -> DjPlaylistAuditReport:
        app = ctx.request_context.lifespan_context
        return await audit_dj_playlist(
            app.spotify,
            app.audio,
            playlist_id,
            source=source,
            overrides=overrides,
        )
