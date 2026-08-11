"""MCP v2 registration for playlist tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from spotify_mcp.application.playlists import (
    PlaylistCreateResult,
    PlaylistDetails,
    PlaylistItemsPage,
    PlaylistSnapshotResult,
    PlaylistsPage,
    PlaylistUnfollowResult,
    PlaylistUpdateResult,
    add_playlist_items,
    create_playlist,
    get_playlist,
    get_playlist_items,
    list_playlists,
    remove_playlist_items,
    reorder_playlist_items,
    unfollow_playlist,
    update_playlist,
)
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, READ_ONLY, WRITE
from spotify_mcp.mcp_server.context import AppContext

DESTRUCTIVE_IDEMPOTENT = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)


def register(server: MCPServer) -> None:
    """Register typed playlist tools on ``server``."""

    @server.tool(
        name="spotify_playlists",
        title="Get Spotify Playlists",
        description="Return one page of the current user's Spotify playlists.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_playlists(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> PlaylistsPage:
        return await list_playlists(
            ctx.request_context.lifespan_context.spotify, limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_playlist",
        title="Get Spotify Playlist",
        description="Return metadata for an exact Spotify playlist ID.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_playlist(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
    ) -> PlaylistDetails:
        return await get_playlist(ctx.request_context.lifespan_context.spotify, playlist_id)

    @server.tool(
        name="spotify_playlist_items",
        title="Get Spotify Playlist Items",
        description=(
            "Return one page of tracks and podcast episodes from an exact playlist ID using "
            "Spotify's current playlist-items endpoint."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_get_playlist_items(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> PlaylistItemsPage:
        return await get_playlist_items(
            ctx.request_context.lifespan_context.spotify,
            playlist_id,
            limit=limit,
            offset=offset,
        )

    @server.tool(
        name="spotify_playlist_create",
        title="Create Spotify Playlist",
        description=(
            "Create a Spotify playlist, then re-read its visibility once. A failed or mismatched "
            "verification is returned explicitly and is never retried blindly."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_create_playlist(
        name: Annotated[str, Field(min_length=1, max_length=100)],
        ctx: Context[AppContext],
        description: Annotated[str, Field(max_length=300)] = "",
        public: bool = False,
    ) -> PlaylistCreateResult:
        return await create_playlist(
            ctx.request_context.lifespan_context.spotify,
            name=name,
            description=description,
            public=public,
        )

    @server.tool(
        name="spotify_playlist_update",
        title="Update Spotify Playlist",
        description=(
            "Update metadata for an exact playlist ID and re-read each requested field once for "
            "verification."
        ),
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_update_playlist(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        description: Annotated[str | None, Field(max_length=300)] = None,
        public: bool | None = None,
        collaborative: bool | None = None,
    ) -> PlaylistUpdateResult:
        return await update_playlist(
            ctx.request_context.lifespan_context.spotify,
            playlist_id,
            name=name,
            description=description,
            public=public,
            collaborative=collaborative,
        )

    @server.tool(
        name="spotify_playlist_add",
        title="Add Spotify Playlist Items",
        description=(
            "Add exact Spotify track IDs or track/episode URIs. A returned snapshot proves "
            "acceptance; a missing snapshot is reported as ambiguous and must not be retried "
            "blindly."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_add_playlist_items(
        playlist_id: Annotated[str, Field(min_length=1)],
        item_ids_or_uris: Annotated[list[str], Field(min_length=1, max_length=100)],
        ctx: Context[AppContext],
        position: Annotated[int | None, Field(ge=0)] = None,
    ) -> PlaylistSnapshotResult:
        return await add_playlist_items(
            ctx.request_context.lifespan_context.spotify,
            playlist_id,
            item_ids_or_uris,
            position=position,
        )

    @server.tool(
        name="spotify_playlist_remove",
        title="Remove Spotify Playlist Items",
        description=(
            "Remove exact Spotify track IDs or track/episode URIs. Pass snapshot_id to target an "
            "exact playlist version. A missing returned snapshot is explicitly ambiguous."
        ),
        annotations=DESTRUCTIVE_IDEMPOTENT,
        structured_output=True,
    )
    async def spotify_remove_playlist_items(
        playlist_id: Annotated[str, Field(min_length=1)],
        item_ids_or_uris: Annotated[list[str], Field(min_length=1, max_length=100)],
        ctx: Context[AppContext],
        snapshot_id: str | None = None,
    ) -> PlaylistSnapshotResult:
        return await remove_playlist_items(
            ctx.request_context.lifespan_context.spotify,
            playlist_id,
            item_ids_or_uris,
            snapshot_id=snapshot_id,
        )

    @server.tool(
        name="spotify_playlist_reorder",
        title="Reorder Spotify Playlist Items",
        description=(
            "Move a consecutive range within an exact playlist ID using the current items "
            "endpoint. A missing returned snapshot is explicitly ambiguous."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_reorder_playlist_items(
        playlist_id: Annotated[str, Field(min_length=1)],
        range_start: Annotated[int, Field(ge=0)],
        insert_before: Annotated[int, Field(ge=0)],
        ctx: Context[AppContext],
        range_length: Annotated[int, Field(ge=1)] = 1,
        snapshot_id: str | None = None,
    ) -> PlaylistSnapshotResult:
        return await reorder_playlist_items(
            ctx.request_context.lifespan_context.spotify,
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
            range_length=range_length,
            snapshot_id=snapshot_id,
        )

    @server.tool(
        name="spotify_playlist_unfollow",
        title="Unfollow Spotify Playlist",
        description=(
            "Remove an exact playlist ID from the current user's library and verify that it is "
            "no longer saved. Spotify does not expose permanent playlist deletion."
        ),
        annotations=DESTRUCTIVE_IDEMPOTENT,
        structured_output=True,
    )
    async def spotify_unfollow_playlist(
        playlist_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
    ) -> PlaylistUnfollowResult:
        return await unfollow_playlist(ctx.request_context.lifespan_context.spotify, playlist_id)
