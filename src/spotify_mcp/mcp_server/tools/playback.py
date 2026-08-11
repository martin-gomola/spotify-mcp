"""MCP registration for Spotify Connect read and control tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.playback import (
    Devices,
    NowPlaying,
    PlayableType,
    PlaybackQueue,
    PlaybackResult,
    PlaybackService,
    QueueableType,
    VolumeAdjustmentResult,
)
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, READ_ONLY, WRITE
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register Spotify Connect tools on ``server``."""

    @server.tool(
        name="spotify_now_playing",
        title="Now Playing",
        description="Return the current Spotify playback item, state, device, and volume.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_now_playing(ctx: Context[AppContext]) -> NowPlaying:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).now_playing()

    @server.tool(
        name="spotify_devices",
        title="Spotify Devices",
        description="List available Spotify Connect devices and their current state.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_devices(ctx: Context[AppContext]) -> Devices:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).devices()

    @server.tool(
        name="spotify_queue",
        title="Spotify Queue",
        description="Return the current item and the next items in the Spotify playback queue.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_queue(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> PlaybackQueue:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).queue(
            limit=limit
        )

    @server.tool(
        name="spotify_play",
        title="Play on Spotify",
        description=(
            "Start a Spotify track, album, artist, or playlist on a selected or active device. "
            "Provide a Spotify URI or both item_type and item_id."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_play(
        ctx: Context[AppContext],
        uri: str | None = None,
        item_type: PlayableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
        offset: Annotated[int | None, Field(ge=0)] = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).play(
            uri=uri,
            item_type=item_type,
            item_id=item_id,
            device_id=device_id,
            offset=offset,
        )

    @server.tool(
        name="spotify_resume",
        title="Resume Spotify",
        description="Resume Spotify playback on a selected or active device.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_resume(
        ctx: Context[AppContext], device_id: str | None = None
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).resume(
            device_id=device_id
        )

    @server.tool(
        name="spotify_pause",
        title="Pause Spotify",
        description="Pause Spotify playback on a selected or active device.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_pause(
        ctx: Context[AppContext], device_id: str | None = None
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).pause(
            device_id=device_id
        )

    @server.tool(
        name="spotify_next",
        title="Next Spotify Item",
        description="Skip to the next item in the Spotify playback queue.",
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_next(
        ctx: Context[AppContext], device_id: str | None = None
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).next(
            device_id=device_id
        )

    @server.tool(
        name="spotify_previous",
        title="Previous Spotify Item",
        description="Skip to the previous item in Spotify playback.",
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_previous(
        ctx: Context[AppContext], device_id: str | None = None
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).previous(
            device_id=device_id
        )

    @server.tool(
        name="spotify_add_to_queue",
        title="Add to Spotify Queue",
        description=(
            "Add one track or podcast episode to the Spotify queue. Provide a Spotify URI "
            "or both item_type and item_id."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_add_to_queue(
        ctx: Context[AppContext],
        uri: str | None = None,
        item_type: QueueableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).add_to_queue(
            uri=uri,
            item_type=item_type,
            item_id=item_id,
            device_id=device_id,
        )

    @server.tool(
        name="spotify_set_volume",
        title="Set Spotify Volume",
        description="Set Spotify playback volume from 0 to 100 percent.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_set_volume(
        volume_percent: Annotated[int, Field(ge=0, le=100)],
        ctx: Context[AppContext],
        device_id: str | None = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).set_volume(
            volume_percent, device_id=device_id
        )

    @server.tool(
        name="spotify_adjust_volume",
        title="Adjust Spotify Volume",
        description=(
            "Increase or decrease Spotify playback volume relative to the selected device's "
            "current volume, clamped from 0 to 100 percent."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_adjust_volume(
        adjustment: Annotated[int, Field(ge=-100, le=100)],
        ctx: Context[AppContext],
        device_id: str | None = None,
    ) -> VolumeAdjustmentResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).adjust_volume(
            adjustment, device_id=device_id
        )
