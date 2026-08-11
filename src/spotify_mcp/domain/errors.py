"""Domain failures that tools can report without leaking transport details."""


class SpotifyMcpError(Exception):
    """Base class for expected Spotify MCP failures."""


class AuthenticationRequired(SpotifyMcpError):
    """The local Spotify session is missing or must be renewed."""


class SpotifyRequestError(SpotifyMcpError):
    """Spotify rejected a request or returned an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AmbiguousWrite(SpotifyMcpError):
    """A write may have succeeded but Spotify did not prove the resulting state."""


class StalePlaylist(SpotifyMcpError):
    """A playlist changed after a plan was created."""
