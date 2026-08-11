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
    RepeatState,
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
            "Provide a Spotify URI, both item_type and item_id, or query with item_type. "
            "A query only starts playback when its top results contain exactly one exact name "
            "or exact name-and-artist match; otherwise it returns exact URI candidates "
            "without writing."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    async def spotify_play(
        ctx: Context[AppContext],
        query: str | None = None,
        uri: str | None = None,
        item_type: PlayableType | None = None,
        item_id: str | None = None,
        device_id: str | None = None,
        offset: Annotated[int | None, Field(ge=0)] = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).play(
            query=query,
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

    @server.tool(
        name="spotify_seek",
        title="Seek Spotify Playback",
        description="Seek to an exact millisecond position in the current Spotify item.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_seek(
        position_ms: Annotated[int, Field(ge=0)],
        ctx: Context[AppContext],
        device_id: str | None = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).seek(
            position_ms, device_id=device_id
        )

    @server.tool(
        name="spotify_set_shuffle",
        title="Set Spotify Shuffle",
        description="Enable or disable shuffle on a selected or active Spotify device.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_set_shuffle(
        state: bool,
        ctx: Context[AppContext],
        device_id: str | None = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).set_shuffle(
            state, device_id=device_id
        )

    @server.tool(
        name="spotify_set_repeat",
        title="Set Spotify Repeat",
        description="Set repeat to track, context, or off on a selected or active device.",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_set_repeat(
        repeat_state: RepeatState,
        ctx: Context[AppContext],
        device_id: str | None = None,
    ) -> PlaybackResult:
        return await PlaybackService(ctx.request_context.lifespan_context.spotify).set_repeat(
            repeat_state, device_id=device_id
        )

    @server.tool(
        name="spotify_transfer_playback",
        title="Transfer Spotify Playback",
        description=(
            "Transfer Spotify Connect to one explicit device, optionally starting playback."
        ),
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )
    async def spotify_transfer_playback(
        device_id: str,
        ctx: Context[AppContext],
        play: bool = False,
    ) -> PlaybackResult:
        return await PlaybackService(
            ctx.request_context.lifespan_context.spotify
        ).transfer_playback(device_id, play=play)
