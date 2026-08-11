"""MCP v2 registration for audio-analysis tools."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.domain.audio import (
    AudioAuditReport,
    AudioComparisonReport,
    AudioLookupReport,
    AudioLookupSource,
    AudioOverride,
)
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer) -> None:
    """Register audio tools without binding request-scoped dependencies globally."""

    @server.tool(
        name="spotify_audio_features",
        title="Get Spotify Track Audio Features",
        description=(
            "Get typed audio measurements for exact Spotify track IDs. Returns explicit missing "
            "tracks and fields, field-level provenance, retained conflicts, and user overrides. "
            "Auto mode falls back to ReccoBeats only when Spotify returns 403 or 404."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_track_audio_features(
        track_ids: Annotated[list[str], Field(min_length=1, max_length=100)],
        ctx: Context[AppContext],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: Annotated[list[AudioOverride], Field(max_length=100)] | None = None,
    ) -> AudioLookupReport:
        return await ctx.request_context.lifespan_context.audio.lookup(track_ids, source, overrides)

    @server.tool(
        name="spotify_audio_compare",
        title="Compare Spotify Track Analysis",
        description=(
            "Compare Spotify and ReccoBeats readings for exact track IDs. Provider failures, "
            "missing providers, missing fields, and material conflicts remain explicit."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def compare_track_analysis(
        track_ids: Annotated[list[str], Field(min_length=1, max_length=25)],
        ctx: Context[AppContext],
    ) -> AudioComparisonReport:
        return await ctx.request_context.lifespan_context.audio.compare(track_ids)

    @server.tool(
        name="spotify_audio_audit",
        title="Audit Spotify Audio Analysis",
        description=(
            "Audit audio-analysis coverage and conflicts for exact Spotify track IDs without "
            "changing Spotify or treating heuristic measurements as musical quality scores."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def audit_audio_analysis(
        track_ids: Annotated[list[str], Field(min_length=1, max_length=100)],
        ctx: Context[AppContext],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: Annotated[list[AudioOverride], Field(max_length=100)] | None = None,
    ) -> AudioAuditReport:
        return await ctx.request_context.lifespan_context.audio.audit(track_ids, source, overrides)
