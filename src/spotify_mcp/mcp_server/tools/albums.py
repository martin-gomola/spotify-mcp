"""MCP v2 registration for Spotify album tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.albums import (
    AlbumsResult,
    AlbumTracksPage,
    SavedAlbumsPage,
    get_album_tracks,
    get_albums,
    get_saved_albums,
)
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer) -> None:
    """Register typed album catalog and library tools on ``server``."""

    @server.tool(
        name="spotify_albums",
        title="Get Spotify Albums",
        description=(
            "Return typed details for exact Spotify album IDs. Albums are fetched through "
            "the supported singular endpoint; unknown IDs are reported separately."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_albums(
        album_ids: Annotated[list[str], Field(min_length=1, max_length=20)],
        ctx: Context[AppContext],
    ) -> AlbumsResult:
        return await get_albums(ctx.request_context.lifespan_context.spotify, album_ids)

    @server.tool(
        name="spotify_album_tracks",
        title="Get Spotify Album Tracks",
        description="Return one paginated page of tracks from an exact Spotify album ID.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_album_tracks(
        album_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> AlbumTracksPage:
        return await get_album_tracks(
            ctx.request_context.lifespan_context.spotify,
            album_id,
            limit=limit,
            offset=offset,
        )

    @server.tool(
        name="spotify_saved_albums",
        title="Get Saved Spotify Albums",
        description="Return one page of albums saved in the current user's Spotify library.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_saved_albums(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> SavedAlbumsPage:
        return await get_saved_albums(
            ctx.request_context.lifespan_context.spotify, limit=limit, offset=offset
        )
