"""MCP registration for the compatibility BPM-sort workflow."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.bpm_sort import sort_playlist_by_bpm
from spotify_mcp.domain.audio import AudioLookupSource, AudioOverride
from spotify_mcp.domain.bpm_sort import BpmSortResult, PlaylistSortMode
from spotify_mcp.mcp_server.annotations import DESTRUCTIVE
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register the legacy-compatible sorter over the shared mutation executor."""

    @server.tool(
        name="spotify_playlist_sort_by_bpm",
        title="Sort Spotify Playlist by BPM",
        description=(
            "Preview or apply the compatibility BPM and energy ordering workflow. Dry-run is "
            "the default; applying uses snapshot checks, durable receipts, and fresh verification."
        ),
        annotations=DESTRUCTIVE,
        structured_output=True,
    )
    async def sort_by_bpm(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        mode: PlaylistSortMode = "tempoEnergy",
        dry_run: bool = True,
        allow_partial: bool = False,
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: Annotated[list[AudioOverride], Field(max_length=100)] | None = None,
    ) -> BpmSortResult:
        """Build an exact position-safe permutation and optionally apply it."""

        app = ctx.request_context.lifespan_context
        return await sort_playlist_by_bpm(
            app.spotify,
            app.artifacts,
            app.audio,
            playlist_id,
            mode=mode,
            dry_run=dry_run,
            allow_partial=allow_partial,
            source=source,
            overrides=overrides,
        )
