"""Canonical links for public Spotify entities."""

from __future__ import annotations

import re
from typing import Literal, cast

SpotifyEntityType = Literal["track", "album", "artist", "playlist", "episode", "show"]

_ENTITY_TYPES = frozenset({"track", "album", "artist", "playlist", "episode", "show"})
_SPOTIFY_ID = re.compile(r"[A-Za-z0-9_-]+")


def _entity_type(value: str) -> SpotifyEntityType:
    if value not in _ENTITY_TYPES:
        raise ValueError(f"unsupported Spotify entity type: {value}")
    return cast(SpotifyEntityType, value)


def spotify_id(entity_type: SpotifyEntityType, value: str) -> str:
    """Return an entity ID from either a bare ID or a matching Spotify URI."""

    expected_type = _entity_type(entity_type)
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{expected_type} ID must not be empty")
    if candidate.startswith("spotify:"):
        parts = candidate.split(":")
        if len(parts) != 3 or parts[0] != "spotify":
            raise ValueError("invalid Spotify URI")
        if parts[1] != expected_type:
            raise ValueError(
                f"Spotify URI type {parts[1]!r} does not match expected {expected_type!r}"
            )
        candidate = parts[2]
    if _SPOTIFY_ID.fullmatch(candidate) is None:
        raise ValueError(f"invalid Spotify {expected_type} ID: {candidate!r}")
    return candidate


def spotify_uri(entity_type: SpotifyEntityType, value: str) -> str:
    """Return a normalized Spotify URI for a bare ID or matching URI."""

    return f"spotify:{entity_type}:{spotify_id(entity_type, value)}"


def spotify_web_url(
    entity_type: SpotifyEntityType,
    value: str,
    *,
    external_url: str | None = None,
) -> str:
    """Return the validated API URL or a canonical open.spotify.com fallback."""

    entity_id = spotify_id(entity_type, value)
    canonical = f"https://open.spotify.com/{entity_type}/{entity_id}"
    return external_url if external_url == canonical else canonical


def spotify_url(
    entity_type: SpotifyEntityType,
    value: str,
    *,
    external_url: str | None = None,
) -> str:
    """Backward-compatible alias for :func:`spotify_web_url`."""

    return spotify_web_url(entity_type, value, external_url=external_url)


def spotify_url_from_uri(uri: str, *, external_url: str | None = None) -> str:
    """Return a canonical URL from a supported Spotify URI."""

    parts = uri.strip().split(":")
    if len(parts) != 3 or parts[0] != "spotify":
        raise ValueError("invalid Spotify URI")
    entity_type = _entity_type(parts[1])
    return spotify_web_url(entity_type, uri, external_url=external_url)
