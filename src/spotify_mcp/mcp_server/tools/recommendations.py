"""MCP registration for deterministic local taste recommendations."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.recommendations import TasteRecommendations, taste_recommendations
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    """Register the read-only local taste rediscovery tool."""

    @server.tool(
        name="spotify_taste_recommendations",
        title="Taste Rediscovery Recommendations",
        description=(
            "Build deterministic local rediscovery suggestions from top tracks, recent plays, "
            "and a stratified Liked Songs sample. This is local curation, not Spotify "
            "personalization."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_taste_recommendations(
        ctx: Context[AppContext],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> TasteRecommendations:
        return await taste_recommendations(
            ctx.request_context.lifespan_context.spotify, limit=limit
        )
