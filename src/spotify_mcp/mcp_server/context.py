"""Typed dependencies shared by MCP tools."""

from dataclasses import dataclass

from spotify_mcp.application.audio import AudioServiceGateway
from spotify_mcp.application.ports import ArtifactRepository, SpotifyGateway


@dataclass(slots=True)
class AppContext:
    spotify: SpotifyGateway
    artifacts: ArtifactRepository
    audio: AudioServiceGateway
    configured: bool = True
    configuration_error: str | None = None
