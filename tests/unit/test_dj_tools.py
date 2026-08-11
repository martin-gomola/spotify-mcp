from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.mcp_server.tools.dj import register


@pytest.mark.anyio
async def test_dj_analyze_exposes_automatic_audio_enrichment_inputs() -> None:
    server = MCPServer("test")

    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}
    properties = tools["spotify_dj_analyze"].input_schema["properties"]
    assert properties["source"]["default"] == "auto"
    assert properties["missing_feature_policy"]["default"] == "anchor"
    assert set(properties["missing_feature_policy"]["enum"]) == {"anchor", "error"}
    assert "overrides" in properties
    assert "features" in properties


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
