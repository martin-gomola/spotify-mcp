"""MCP registration for compact routed Spotify catalog reads."""

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from spotify_mcp.application.catalog import AlbumGroup, CatalogResult, CatalogRoute, CatalogService
from spotify_mcp.mcp_server.annotations import READ_ONLY
from spotify_mcp.mcp_server.context import AppContext


def register(server: MCPServer[AppContext]) -> None:
    @server.tool(
        name="spotify_catalog",
        title="Read Spotify Catalog",
        description=(
            "Route one exact catalog read: track metadata, artist metadata, or an artist's "
            "paginated albums and singles."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def spotify_catalog(
        route: CatalogRoute,
        entity_id: Annotated[str, Field(min_length=1)],
        ctx: Context[AppContext],
        include_groups: Annotated[tuple[AlbumGroup, ...], Field(min_length=1, max_length=4)] = (
            "album",
            "single",
        ),
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> CatalogResult:
        return await CatalogService(ctx.request_context.lifespan_context.spotify).get(
            route,
            entity_id,
            include_groups=include_groups,
            limit=limit,
            offset=offset,
        )
