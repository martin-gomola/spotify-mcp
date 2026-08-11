"""Provider-neutral playlist position models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PlaylistItemType = Literal["track", "episode", "local", "unavailable", "unknown"]


@dataclass(frozen=True, slots=True)
class PlaylistPosition:
    """One observable playlist position, including items that cannot be reordered safely."""

    position_token: str
    identity: str
    original_position: int
    track_id: str | None = None
    uri: str | None = None
    name: str = "Unknown"
    artists: tuple[str, ...] = ()
    artist_ids: tuple[str, ...] = ()
    duration_ms: int | None = None
    item_type: PlaylistItemType = "unknown"
    fixed: bool = True
