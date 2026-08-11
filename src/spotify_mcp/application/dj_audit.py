"""Complete, snapshot-consistent DJ playlist audit use case."""

from __future__ import annotations

from spotify_mcp.application.audio import AudioAnalysisGateway
from spotify_mcp.application.playlist_state import read_playlist_state, verify_playlist_snapshot
from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.audio import AudioLookupReport, AudioLookupSource, AudioOverride
from spotify_mcp.domain.dj_audit import DjPlaylistAuditReport, audit_playlist_data


async def audit_dj_playlist(
    spotify: SpotifyGateway,
    audio: AudioAnalysisGateway,
    playlist_id: str,
    *,
    source: AudioLookupSource = AudioLookupSource.AUTO,
    overrides: list[AudioOverride] | None = None,
) -> DjPlaylistAuditReport:
    """Read, enrich, and audit every playlist position without changing Spotify."""

    state = await read_playlist_state(spotify, playlist_id)
    track_ids = list(
        dict.fromkeys(
            position.track_id for position in state.positions if position.track_id is not None
        )
    )
    lookup = (
        await audio.lookup(track_ids, source, overrides)
        if track_ids
        else AudioLookupReport(
            requested_track_ids=[],
            tracks=[],
            missing_track_ids=[],
        )
    )
    await verify_playlist_snapshot(spotify, playlist_id, state.snapshot_id)
    return audit_playlist_data(state, lookup)
