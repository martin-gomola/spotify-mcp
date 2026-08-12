"""MCP v2 registration for Liked Songs tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from spotify_mcp.application.library import (
    LibraryItemsContainsResult,
    LibraryItemsMutationResult,
    SavedTracksPage,
    SavedTracksSample,
    check_library_items,
    get_saved_tracks,
    mutate_library_items,
    sample_saved_tracks,
)
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, READ_ONLY
from spotify_mcp.mcp_server.context import AppContext

DESTRUCTIVE_IDEMPOTENT = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)


def register(server: MCPServer) -> None:
    """Register typed Liked Songs tools on ``server``."""

    @server.tool(
        name="spotify_saved_tracks",
        title="Get Spotify Liked Songs",
        description="Return one page of the current user's Spotify Liked Songs.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_saved_tracks(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> SavedTracksPage:
        return await get_saved_tracks(
            ctx.request_context.lifespan_context.spotify, limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_sample_liked_songs",
        title="Sample Spotify Liked Songs",
        description=(
            "Return a deterministic sample spanning the full history of Liked Songs. "
            "Use it for long-term taste and rediscovery instead of reading only the newest page."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_sample_saved_tracks(
        ctx: Context[AppContext],
        sample_size: Annotated[int, Field(ge=8, le=100)] = 48,
    ) -> SavedTracksSample:
        return await sample_saved_tracks(
            ctx.request_context.lifespan_context.spotify, sample_size=sample_size
        )

    @server.tool(
        name="spotify_library_contains",
        title="Check Spotify Library",
        description="Check up to 40 exact track, album, show, episode, or audiobook URIs.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_check_saved_tracks(
        uris: Annotated[list[str], Field(min_length=1, max_length=40)],
        ctx: Context[AppContext],
    ) -> LibraryItemsContainsResult:
        return await check_library_items(ctx.request_context.lifespan_context.spotify, uris)

    @server.tool(
        name="spotify_library_save",
        title="Save Spotify Library Items",
        description=(
            "Save up to 40 exact track, album, show, episode, or audiobook URIs and verify."
        ),
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_save_tracks(
        uris: Annotated[list[str], Field(min_length=1, max_length=40)],
        ctx: Context[AppContext],
    ) -> LibraryItemsMutationResult:
        return await mutate_library_items(
            ctx.request_context.lifespan_context.spotify, "save", uris
        )

    @server.tool(
        name="spotify_library_remove",
        title="Remove Spotify Library Items",
        description=(
            "Remove up to 40 exact track, album, show, episode, or audiobook URIs and verify."
        ),
        annotations=DESTRUCTIVE_IDEMPOTENT,
        structured_output=True,
    )
    async def spotify_remove_saved_tracks(
        uris: Annotated[list[str], Field(min_length=1, max_length=40)],
        ctx: Context[AppContext],
    ) -> LibraryItemsMutationResult:
        return await mutate_library_items(
            ctx.request_context.lifespan_context.spotify, "remove", uris
        )
