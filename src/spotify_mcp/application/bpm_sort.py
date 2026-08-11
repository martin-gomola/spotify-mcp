"""Compatibility BPM-sort orchestration over shared playlist safety services."""

from __future__ import annotations

from spotify_mcp.application.audio import AudioAnalysisGateway
from spotify_mcp.application.playlist_mutation import execute_playlist_permutation
from spotify_mcp.application.playlist_state import PlaylistState, read_playlist_state
from spotify_mcp.application.ports import ArtifactRepository, SpotifyGateway
from spotify_mcp.domain.audio import (
    AudioLookupReport,
    AudioLookupSource,
    AudioOverride,
    FeatureName,
    TrackAudioAnalysis,
    apply_override,
    feature_for,
)
from spotify_mcp.domain.bpm_sort import (
    BpmSortPosition,
    BpmSortResult,
    BpmSortStatus,
    PlaylistSortMode,
    SortablePlaylistPosition,
    build_stable_target,
    normalize_dj_tempo,
)


async def sort_playlist_by_bpm(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    audio: AudioAnalysisGateway,
    playlist_id: str,
    *,
    mode: PlaylistSortMode = "tempoEnergy",
    dry_run: bool = True,
    allow_partial: bool = False,
    source: AudioLookupSource = AudioLookupSource.AUTO,
    overrides: list[AudioOverride] | None = None,
) -> BpmSortResult:
    """Preview or safely apply the legacy tempo/energy ordering strategy."""

    state = await read_playlist_state(spotify, playlist_id)
    track_ids = list(
        dict.fromkeys(
            position.track_id
            for position in state.positions
            if position.track_id is not None and not position.fixed
        )
    )
    lookup = await _lookup_audio(audio, track_ids, source, overrides)
    analysis_by_id = {analysis.track_id: analysis for analysis in lookup.tracks}

    sortable: list[SortablePlaylistPosition] = []
    missing_track_ids: list[str] = []
    for position in state.positions:
        analysis = analysis_by_id.get(position.track_id or "")
        tempo_feature = feature_for(analysis, FeatureName.TEMPO) if analysis else None
        energy_feature = feature_for(analysis, FeatureName.ENERGY) if analysis else None
        tempo = float(tempo_feature.selected.value) if tempo_feature else None
        energy = float(energy_feature.selected.value) if energy_feature else None
        fixed = position.fixed or tempo is None
        if position.track_id is not None and not position.fixed and tempo is None:
            missing_track_ids.append(position.track_id)
        sortable.append(
            SortablePlaylistPosition(
                position_token=position.position_token,
                original_position=position.original_position,
                track_id=position.track_id,
                name=position.name,
                tempo=tempo,
                energy=energy,
                fixed=fixed,
            )
        )

    unique_missing = tuple(dict.fromkeys(missing_track_ids))
    warnings = list(lookup.warnings)
    if mode == "dj":
        warnings.append(
            'mode "dj" is a deprecated alias for tempoEnergy; use DJ planning for '
            "multi-objective set planning"
        )

    original = tuple(sortable)
    if unique_missing and not allow_partial:
        warnings.append(f"missing BPM for {len(unique_missing)} track(s); playlist was not changed")
        return _result(
            status="blocked",
            state=state,
            mode=mode,
            source=source,
            allow_partial=allow_partial,
            original=original,
            target=original,
            missing_track_ids=unique_missing,
            warnings=tuple(warnings),
            failure_reason="missing-audio-features",
        )

    target = build_stable_target(original, mode)
    mutation = await execute_playlist_permutation(
        spotify,
        artifacts,
        playlist_id=playlist_id,
        identity={
            "operation": "sortPlaylistByBpm",
            "playlist_id": playlist_id,
            "source_snapshot_id": state.snapshot_id,
            "mode": mode,
            "source": source.value,
            "allow_partial": allow_partial,
        },
        original_order=state.order,
        target_order=tuple(position.position_token for position in target),
        expected_snapshot_id=state.snapshot_id,
        action="apply",
        dry_run=dry_run,
    )
    return _result(
        status=mutation.status,
        state=state,
        mode=mode,
        source=source,
        allow_partial=allow_partial,
        original=original,
        target=target,
        missing_track_ids=unique_missing,
        warnings=tuple(dict.fromkeys([*warnings, *mutation.warnings])),
        expected_snapshot_id=mutation.expected_snapshot_id,
        initial_snapshot_id=mutation.initial_snapshot_id,
        final_snapshot_id=mutation.final_snapshot_id,
        completed_moves=mutation.completed_moves,
        total_moves=mutation.total_moves,
        receipt_id=mutation.receipt_id,
        failure_reason=mutation.failure_reason,
    )


async def _lookup_audio(
    audio: AudioAnalysisGateway,
    track_ids: list[str],
    source: AudioLookupSource,
    overrides: list[AudioOverride] | None,
) -> AudioLookupReport:
    """Fetch only recordings whose required tempo is not supplied explicitly."""

    supplied_overrides = {
        override.track_id: override for override in overrides or [] if override.tempo is not None
    }
    unresolved_ids = [track_id for track_id in track_ids if track_id not in supplied_overrides]
    unresolved_overrides = [
        override for override in overrides or [] if override.track_id in unresolved_ids
    ]
    provider_report = (
        await audio.lookup(unresolved_ids, source, unresolved_overrides)
        if unresolved_ids
        else AudioLookupReport(requested_track_ids=[], tracks=[], missing_track_ids=[], warnings=[])
    )
    analyses = {analysis.track_id: analysis for analysis in provider_report.tracks}
    for track_id, override in supplied_overrides.items():
        if track_id in track_ids:
            analyses[track_id] = apply_override(TrackAudioAnalysis(track_id=track_id), override)
    return AudioLookupReport(
        requested_track_ids=track_ids,
        tracks=[analyses[track_id] for track_id in track_ids if track_id in analyses],
        missing_track_ids=provider_report.missing_track_ids,
        warnings=provider_report.warnings,
    )


def _result(
    *,
    status: BpmSortStatus,
    state: PlaylistState,
    mode: PlaylistSortMode,
    source: AudioLookupSource,
    allow_partial: bool,
    original: tuple[SortablePlaylistPosition, ...],
    target: tuple[SortablePlaylistPosition, ...],
    missing_track_ids: tuple[str, ...],
    warnings: tuple[str, ...],
    expected_snapshot_id: str | None = None,
    initial_snapshot_id: str | None = None,
    final_snapshot_id: str | None = None,
    completed_moves: int = 0,
    total_moves: int = 0,
    receipt_id: str | None = None,
    failure_reason: str | None = None,
) -> BpmSortResult:
    playlist_id = state.playlist_id
    playlist_name = state.name
    snapshot_id = state.snapshot_id
    return BpmSortResult(
        status=status,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        mode=mode,
        source=source,
        allow_partial=allow_partial,
        source_snapshot_id=snapshot_id,
        original_order=tuple(position.position_token for position in original),
        target_order=tuple(position.position_token for position in target),
        ordered_positions=tuple(
            BpmSortPosition(
                position_token=position.position_token,
                track_id=position.track_id,
                name=position.name,
                original_position=position.original_position,
                target_position=target_position,
                tempo=position.tempo,
                normalized_tempo=(
                    normalize_dj_tempo(position.tempo) if position.tempo is not None else None
                ),
                energy=position.energy,
                fixed=position.fixed,
            )
            for target_position, position in enumerate(target)
        ),
        missing_track_ids=missing_track_ids,
        fixed_positions=sum(position.fixed for position in original),
        expected_snapshot_id=expected_snapshot_id or snapshot_id,
        initial_snapshot_id=initial_snapshot_id or snapshot_id,
        final_snapshot_id=final_snapshot_id,
        completed_moves=completed_moves,
        total_moves=total_moves,
        receipt_id=receipt_id,
        warnings=warnings,
        failure_reason=failure_reason,
    )
