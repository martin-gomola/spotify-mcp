"""Application composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server import MCPServer

from spotify_mcp.adapters.audio import ReccoBeatsAudioProvider, SpotifyAudioProvider
from spotify_mcp.adapters.persistence import SQLiteArtifactRepository
from spotify_mcp.adapters.spotify.client import SpotifyClient
from spotify_mcp.adapters.spotify.oauth import SpotifyOAuth
from spotify_mcp.application.audio import AudioAnalysisService
from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.config import SpotifyConfigError, load_settings
from spotify_mcp.domain.errors import AuthenticationRequired
from spotify_mcp.mcp_server.context import AppContext


class UnconfiguredSpotifyGateway:
    """Keep the MCP catalog available before local Spotify setup is complete."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        del method, path, params, json
        raise AuthenticationRequired(self.reason)


@asynccontextmanager
async def app_lifespan(_server: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
    """Create shared adapters once per MCP process and close them deterministically."""

    artifacts = SQLiteArtifactRepository()
    try:
        settings = load_settings()
    except SpotifyConfigError as exc:
        unconfigured_spotify = UnconfiguredSpotifyGateway(str(exc))
        yield AppContext(
            spotify=unconfigured_spotify,
            artifacts=artifacts,
            audio=AudioAnalysisService(
                SpotifyAudioProvider(unconfigured_spotify),
                ReccoBeatsAudioProvider(),
            ),
            configured=False,
            configuration_error=str(exc),
        )
        return

    timeout = httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        oauth = SpotifyOAuth(settings, http_client=http_client)
        spotify: SpotifyGateway = SpotifyClient(settings, oauth, http_client=http_client)
        yield AppContext(
            spotify=spotify,
            artifacts=artifacts,
            audio=AudioAnalysisService(
                SpotifyAudioProvider(spotify),
                ReccoBeatsAudioProvider(http_client),
            ),
        )
