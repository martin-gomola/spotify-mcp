"""Spotify Web API and OAuth adapters."""

from .client import SpotifyClient
from .oauth import (
    REQUIRED_SCOPES,
    PkceRequest,
    SpotifyOAuth,
    TokenSet,
    TokenStore,
    create_pkce_request,
    parse_authorization_callback,
)

__all__ = [
    "REQUIRED_SCOPES",
    "PkceRequest",
    "SpotifyClient",
    "SpotifyOAuth",
    "TokenSet",
    "TokenStore",
    "create_pkce_request",
    "parse_authorization_callback",
]
