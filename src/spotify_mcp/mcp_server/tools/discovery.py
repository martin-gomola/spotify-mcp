"""MCP registration for Spotify discovery tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.discovery import (
    DiscoveryService,
    RecentTracks,
    SearchResults,
    SearchType,
    TimeRange,
    TopArtists,
    TopTracks,
)
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register read-only discovery tools on ``server``."""

    @server.tool(
        name="spotify_search",
        title="Search Spotify",
        description=(
            "Search Spotify for tracks, albums, artists, playlists, podcast episodes, "
            "or shows. Returns at most 10 typed results per call."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_search(
        query: Annotated[str, Field(min_length=1)],
        item_type: SearchType,
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> SearchResults:
        return await DiscoveryService(ctx.request_context.lifespan_context.spotify).search(
            query, item_type, limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_recently_played",
        title="Recently Played",
        description="Return the current user's most recently played Spotify tracks.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_recently_played(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> RecentTracks:
        return await DiscoveryService(ctx.request_context.lifespan_context.spotify).recently_played(
            limit=limit
        )

    @server.tool(
        name="spotify_top_tracks",
        title="Top Tracks",
        description="Return the current user's most-played tracks for a Spotify time range.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_top_tracks(
        ctx: Context[AppContext],
        time_range: TimeRange = "medium_term",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> TopTracks:
        return await DiscoveryService(ctx.request_context.lifespan_context.spotify).top_tracks(
            time_range=time_range, limit=limit
        )

    @server.tool(
        name="spotify_top_artists",
        title="Top Artists",
        description="Return the current user's most-played artists for a Spotify time range.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_top_artists(
        ctx: Context[AppContext],
        time_range: TimeRange = "medium_term",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> TopArtists:
        return await DiscoveryService(ctx.request_context.lifespan_context.spotify).top_artists(
            time_range=time_range, limit=limit
        )
