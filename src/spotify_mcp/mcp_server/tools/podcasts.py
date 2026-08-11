"""MCP registration for read-only Spotify podcast tools."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.podcasts import (
    PodcastDiscoveryResult,
    PodcastEpisode,
    PodcastEpisodesPage,
    PodcastService,
    PodcastShow,
    SavedEpisodesPage,
    SavedShowsPage,
)
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register typed podcast discovery, catalog, and library tools."""

    @server.tool(
        name="spotify_podcast_discover",
        title="Discover Spotify Podcasts",
        description=(
            "Search Spotify shows and podcast episodes together, returning at most 10 "
            "typed results of each kind with canonical Spotify links."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_podcast_discover(
        query: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> PodcastDiscoveryResult:
        return await PodcastService(ctx.request_context.lifespan_context.spotify).discover(
            query, limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_podcast_show",
        title="Get Spotify Podcast Show",
        description="Return typed details and a canonical Spotify link for one exact show ID.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_podcast_show(
        show_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
    ) -> PodcastShow:
        return await PodcastService(ctx.request_context.lifespan_context.spotify).get_show(show_id)

    @server.tool(
        name="spotify_podcast_show_episodes",
        title="Get Spotify Podcast Show Episodes",
        description="Return one bounded page of episodes for an exact Spotify show ID.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_podcast_show_episodes(
        show_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> PodcastEpisodesPage:
        return await PodcastService(ctx.request_context.lifespan_context.spotify).get_show_episodes(
            show_id, limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_podcast_episode",
        title="Get Spotify Podcast Episode",
        description=(
            "Return typed metadata for one exact Spotify episode ID. Preview URL evidence "
            "may be absent and no full audio is returned."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_podcast_episode(
        episode_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
    ) -> PodcastEpisode:
        return await PodcastService(ctx.request_context.lifespan_context.spotify).get_episode(
            episode_id
        )

    @server.tool(
        name="spotify_saved_shows",
        title="Get Saved Spotify Shows",
        description="Return one bounded page of shows saved in the current user's library.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_saved_shows(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> SavedShowsPage:
        return await PodcastService(ctx.request_context.lifespan_context.spotify).get_saved_shows(
            limit=limit, offset=offset
        )

    @server.tool(
        name="spotify_saved_episodes",
        title="Get Saved Spotify Episodes",
        description="Return one bounded page of episodes saved in the current user's library.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_saved_episodes(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> SavedEpisodesPage:
        return await PodcastService(
            ctx.request_context.lifespan_context.spotify
        ).get_saved_episodes(limit=limit, offset=offset)
