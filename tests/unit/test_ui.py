from __future__ import annotations

import pytest
from mcp import Client
from mcp.server import MCPServer

from spotify_mcp.mcp_server.ui import RESULTS_UI_URI, create_results_apps


@pytest.mark.anyio
async def test_results_ui_is_optional_mcp_apps_resource_with_text_fallback() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        resources = {
            str(resource.uri): resource for resource in (await client.list_resources()).resources
        }

        tool = tools["spotify_render_results"]
        assert tool.meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["model"]},
            "openai/outputTemplate": RESULTS_UI_URI,
        }
        assert tool.output_schema is not None
        assert resources[RESULTS_UI_URI].mime_type == "text/html;profile=mcp-app"
        assert resources[RESULTS_UI_URI].meta == {"ui": {"prefersBorder": True}}

        rendered = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Road-trip picks",
                "items": [
                    {
                        "name": "Open Road",
                        "spotify_url": "https://open.spotify.com/track/track-1",
                        "subtitle": "Driver - Long Way Home",
                        "kind": "track",
                    }
                ],
            },
        )
        resource = await client.read_resource(RESULTS_UI_URI)

    assert rendered.is_error is False
    assert rendered.structured_content == {
        "title": "Road-trip picks",
        "items": [
            {
                "name": "Open Road",
                "spotify_url": "https://open.spotify.com/track/track-1",
                "subtitle": "Driver - Long Way Home",
                "kind": "track",
                "reason": None,
            }
        ],
    }
    assert rendered.content
    assert "Road-trip picks" in rendered.content[0].text
    html = resource.contents[0].text
    assert html is not None
    assert "ui/notifications/tool-result" in html
    assert "textContent" in html
    assert "innerHTML" not in html
    assert "noopener noreferrer" in html


@pytest.mark.anyio
async def test_results_ui_rejects_non_spotify_links() -> None:
    apps = create_results_apps()
    server: MCPServer[None] = MCPServer("test", extensions=[apps])

    async with Client(server) as client:
        result = await client.call_tool(
            "spotify_render_results",
            {
                "title": "Unsafe",
                "items": [
                    {
                        "name": "Bad link",
                        "spotify_url": "https://example.com/not-spotify",
                        "kind": "track",
                    }
                ],
            },
        )

    assert result.is_error is True
