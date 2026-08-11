"""DJ analysis, planning, and snapshot-safe playlist mutation use cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any, cast

from spotify_mcp.application.audio import AudioAnalysisGateway, project_dj_audio_features
from spotify_mcp.application.playlist_mutation import (
    MutationResult,
    ReceiptRepository,
    execute_playlist_permutation,
)
from spotify_mcp.application.playlist_state import (
    read_playlist_state,
    verify_playlist_snapshot,
)
from spotify_mcp.application.ports import ArtifactRepository, SpotifyGateway
from spotify_mcp.domain.audio import (
    AudioLookupSource,
    AudioOverride,
    AudioProvider,
    ConfidenceBasis,
    FeatureName,
    FeatureProvenance,
)
from spotify_mcp.domain.dj import (
    DjAnalysis,
    DjAnalysisCoverage,
    DjFeatureEvidence,
    DjPlan,
    DjTrack,
    EnergyCurve,
    MissingFeaturePolicy,
    PlannedTrack,
    camelot_code,
    normalize_tempo,
    plan_dj_set,
)


async def analyze_playlist(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    playlist_id: str,
    *,
    audio: AudioAnalysisGateway | None = None,
    source: AudioLookupSource = AudioLookupSource.AUTO,
    overrides: Sequence[AudioOverride] = (),
    features: Sequence[Mapping[str, Any]] = (),
    missing_feature_policy: MissingFeaturePolicy = "anchor",
) -> tuple[str, DjAnalysis]:
    """Capture a playlist snapshot and merge provider and explicit audio measurements."""

    state = await read_playlist_state(spotify, playlist_id)
    warnings: list[str] = []
    feature_by_id: dict[str, Mapping[str, Any]] = {}
    if audio is not None:
        track_ids = list(
            dict.fromkeys(
                position.track_id
                for position in state.positions
                if position.track_id is not None and not position.fixed
            )
        )
        report = await audio.lookup(track_ids, source=source, overrides=list(overrides))
        feature_by_id.update(
            (projection.track_id, projection.model_dump())
            for projection in project_dj_audio_features(report)
        )
        warnings.extend(report.warnings)
        await verify_playlist_snapshot(spotify, playlist_id, state.snapshot_id)
    for feature in features:
        if not feature.get("track_id"):
            continue
        track_id = str(feature["track_id"])
        merged = dict(feature_by_id.get(track_id, {}))
        merged.update(feature)
        provenance = dict(_mapping_or_empty(merged.get("provenance")))
        for input_name, evidence_name in (
            ("bpm", FeatureName.TEMPO),
            ("tempo", FeatureName.TEMPO),
            ("energy", FeatureName.ENERGY),
            ("key", FeatureName.KEY),
            ("mode", FeatureName.MODE),
        ):
            if feature.get(input_name) is not None:
                provenance[evidence_name] = FeatureProvenance(
                    provider=AudioProvider.OVERRIDE,
                    confidence=1,
                    confidence_basis=ConfidenceBasis.USER,
                ).model_dump()
        merged["provenance"] = provenance
        feature_by_id[track_id] = merged
    tracks: list[DjTrack] = []
    unresolved_tokens: list[str] = []
    for position in state.positions:
        feature = feature_by_id.get(position.track_id or "", {})
        bpm = _optional_float(feature.get("bpm", feature.get("tempo")))
        energy = _bounded_feature(feature.get("energy"))
        key = _optional_int(feature.get("key"))
        mode = _optional_int(feature.get("mode"))
        camelot = camelot_code(key, mode) if key is not None and mode is not None else None
        unresolved = tuple(
            field
            for field, missing in (
                ("tempo", bpm is None),
                ("key_or_mode", camelot is None),
                ("energy", energy is None),
            )
            if missing
        )
        if unresolved:
            unresolved_tokens.append(position.position_token)
        evidence = _dj_feature_evidence(feature)
        sources = tuple(sorted({item.provider for item in evidence}))
        tracks.append(
            DjTrack(
                position_token=position.position_token,
                identity=position.identity,
                original_position=position.original_position,
                track_id=position.track_id,
                uri=position.uri,
                name=position.name,
                artists=position.artists,
                artist_ids=position.artist_ids,
                duration_ms=position.duration_ms,
                item_type=position.item_type,
                fixed=position.fixed or (missing_feature_policy == "anchor" and bpm is None),
                bpm=bpm,
                normalized_bpm=normalize_tempo(bpm) if bpm is not None else None,
                energy=energy,
                camelot=camelot,
                provenance=evidence,
                sources=sources or ("unavailable",),
                unresolved_fields=unresolved,
            )
        )
    if missing_feature_policy == "error" and unresolved_tokens:
        raise ValueError(
            "DJ analysis is incomplete for "
            f"{len(unresolved_tokens)} position(s); use missing_feature_policy='anchor' "
            "or supply overrides"
        )
    if unresolved_tokens:
        warnings.append(
            f"{len(unresolved_tokens)} position(s) have unresolved audio fields; "
            "positions without tempo are anchored"
        )
    track_positions = [track for track in tracks if track.item_type == "track"]
    coverage = DjAnalysisCoverage(
        track_count=len(track_positions),
        tempo_count=sum(track.bpm is not None for track in track_positions),
        key_count=sum(track.camelot is not None for track in track_positions),
        energy_count=sum(track.energy is not None for track in track_positions),
        complete_count=sum(not track.unresolved_fields for track in track_positions),
        unresolved_position_tokens=tuple(unresolved_tokens),
    )
    analysis = DjAnalysis(
        playlist_id=state.playlist_id,
        playlist_name=state.name,
        snapshot_id=state.snapshot_id,
        tracks=tuple(tracks),
        warnings=tuple(dict.fromkeys(warnings)),
        audio_source=source.value if audio is not None else "manual",
        missing_feature_policy=missing_feature_policy,
        coverage=coverage,
    )
    payload = {"artifact_kind": "analysis", **asdict(analysis)}
    artifact_id = await artifacts.put_immutable("analysis", payload)
    return artifact_id, analysis


async def create_plan(
    artifacts: ArtifactRepository,
    analysis_id: str,
    *,
    energy_curve: EnergyCurve = "warmup-build-peak-close",
    artist_spacing: int = 3,
) -> tuple[str, DjPlan]:
    """Create and persist a deterministic plan from an immutable analysis."""

    payload = await artifacts.get(analysis_id)
    analysis = _analysis_from_payload(payload)
    plan = plan_dj_set(
        analysis,
        analysis_id,
        energy_curve=energy_curve,
        artist_spacing=artist_spacing,
    )
    plan_payload = {"artifact_kind": "plan", **asdict(plan)}
    plan_id = await artifacts.put_immutable("plan", plan_payload)
    return plan_id, plan


async def apply_plan(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    plan_id: str,
    *,
    expected_snapshot_id: str | None = None,
    dry_run: bool = True,
) -> MutationResult:
    """Apply a stored target order, defaulting to a side-effect-free dry run."""

    plan = _plan_from_payload(await artifacts.get(plan_id))
    expected = expected_snapshot_id or plan.source_snapshot_id
    return await execute_playlist_permutation(
        spotify,
        artifacts,
        playlist_id=plan.playlist_id,
        identity={
            "action": "apply",
            "plan_id": plan_id,
            "playlist_id": plan.playlist_id,
            "source_snapshot_id": expected,
        },
        original_order=plan.original_order,
        target_order=plan.target_order,
        expected_snapshot_id=expected,
        action="apply",
        dry_run=dry_run,
    )


async def restore_playlist(
    spotify: SpotifyGateway,
    artifacts: ReceiptRepository,
    receipt_id: str,
    *,
    expected_snapshot_id: str,
    dry_run: bool = True,
) -> MutationResult:
    """Restore the original permutation recorded before a DJ plan was applied."""

    source_receipt = await artifacts.get_receipt(receipt_id)
    playlist_id = _required_string(source_receipt, "playlist_id")
    original_order = _string_tuple(source_receipt.get("original_order"), "original_order")
    target_order = _string_tuple(source_receipt.get("target_order"), "target_order")
    return await execute_playlist_permutation(
        spotify,
        artifacts,
        playlist_id=playlist_id,
        identity={
            "action": "restore",
            "source_receipt_id": receipt_id,
            "playlist_id": playlist_id,
            "source_snapshot_id": expected_snapshot_id,
        },
        original_order=original_order,
        target_order=target_order,
        expected_snapshot_id=expected_snapshot_id,
        action="restore",
        dry_run=dry_run,
    )


def _analysis_from_payload(payload: Mapping[str, Any]) -> DjAnalysis:
    if payload.get("artifact_kind") != "analysis":
        raise ValueError("artifact is not a DJ analysis")
    raw_tracks = payload.get("tracks")
    if not isinstance(raw_tracks, (list, tuple)):
        raise ValueError("analysis tracks are invalid")
    return DjAnalysis(
        playlist_id=_required_string(payload, "playlist_id"),
        playlist_name=_required_string(payload, "playlist_name"),
        snapshot_id=_required_string(payload, "snapshot_id"),
        tracks=tuple(
            _track_from_payload(_mapping(track, "analysis track")) for track in raw_tracks
        ),
        warnings=_string_tuple(payload.get("warnings", []), "warnings"),
        audio_source=str(payload.get("audio_source") or "manual"),
        missing_feature_policy=_missing_feature_policy(payload.get("missing_feature_policy")),
        coverage=_coverage_from_payload(payload.get("coverage")),
    )


def _plan_from_payload(payload: Mapping[str, Any]) -> DjPlan:
    if payload.get("artifact_kind") != "plan":
        raise ValueError("artifact is not a DJ plan")
    curve = str(payload.get("energy_curve"))
    if curve not in {"warmup-build-peak-close", "steady", "rising", "waves"}:
        raise ValueError("plan has an invalid energy curve")
    raw_tracks = payload.get("ordered_tracks")
    if not isinstance(raw_tracks, (list, tuple)):
        raise ValueError("plan ordered_tracks are invalid")
    return DjPlan(
        analysis_id=_required_string(payload, "analysis_id"),
        playlist_id=_required_string(payload, "playlist_id"),
        playlist_name=_required_string(payload, "playlist_name"),
        source_snapshot_id=_required_string(payload, "source_snapshot_id"),
        energy_curve=cast(EnergyCurve, curve),
        artist_spacing=int(payload.get("artist_spacing", 3)),
        original_order=_string_tuple(payload.get("original_order"), "original_order"),
        target_order=_string_tuple(payload.get("target_order"), "target_order"),
        ordered_tracks=tuple(
            PlannedTrack(
                position_token=_required_string(_mapping(item, "planned track"), "position_token"),
                original_position=int(_mapping(item, "planned track")["original_position"]),
                target_energy=float(_mapping(item, "planned track")["target_energy"]),
            )
            for item in raw_tracks
        ),
        warnings=_string_tuple(payload.get("warnings", []), "warnings"),
    )


def _track_from_payload(payload: Mapping[str, Any]) -> DjTrack:
    return DjTrack(
        position_token=_required_string(payload, "position_token"),
        identity=_required_string(payload, "identity"),
        original_position=int(payload["original_position"]),
        track_id=_optional_string(payload.get("track_id")),
        uri=_optional_string(payload.get("uri")),
        name=str(payload.get("name") or "Unknown"),
        artists=_string_tuple(payload.get("artists", []), "artists"),
        artist_ids=_string_tuple(payload.get("artist_ids", []), "artist_ids"),
        duration_ms=_optional_non_negative_int(payload.get("duration_ms")),
        item_type=str(payload.get("item_type") or "track"),
        fixed=payload.get("fixed") is True,
        bpm=_optional_float(payload.get("bpm")),
        normalized_bpm=_optional_float(payload.get("normalized_bpm")),
        energy=_bounded_feature(payload.get("energy")),
        camelot=_optional_string(payload.get("camelot")),
        provenance=tuple(
            _evidence_from_payload(_mapping(item, "DJ feature evidence"))
            for item in _sequence(payload.get("provenance", ()), "provenance")
        ),
        sources=_string_tuple(payload.get("sources", []), "sources"),
        unresolved_fields=_string_tuple(payload.get("unresolved_fields", []), "unresolved_fields"),
    )


def _dj_feature_evidence(feature: Mapping[str, Any]) -> tuple[DjFeatureEvidence, ...]:
    provenance = _mapping_or_empty(feature.get("provenance"))
    evidence: list[DjFeatureEvidence] = []
    for field in (FeatureName.TEMPO, FeatureName.ENERGY, FeatureName.KEY, FeatureName.MODE):
        raw = provenance.get(field, provenance.get(field.value))
        if isinstance(raw, FeatureProvenance):
            raw = raw.model_dump()
        if not isinstance(raw, Mapping):
            continue
        provider = raw.get("provider")
        fetched_at = raw.get("fetched_at")
        confidence_basis = raw.get("confidence_basis", "unknown")
        evidence.append(
            DjFeatureEvidence(
                field=field.value,
                provider=provider.value if isinstance(provider, AudioProvider) else str(provider),
                fetched_at=(
                    fetched_at.isoformat() if isinstance(fetched_at, datetime) else str(fetched_at)
                ),
                source_href=_optional_string(raw.get("source_href")),
                confidence=_optional_unit_float(raw.get("confidence")),
                confidence_basis=(
                    confidence_basis.value
                    if isinstance(confidence_basis, ConfidenceBasis)
                    else str(confidence_basis)
                ),
            )
        )
    return tuple(evidence)


def _evidence_from_payload(payload: Mapping[str, Any]) -> DjFeatureEvidence:
    return DjFeatureEvidence(
        field=_required_string(payload, "field"),
        provider=_required_string(payload, "provider"),
        fetched_at=_required_string(payload, "fetched_at"),
        source_href=_optional_string(payload.get("source_href")),
        confidence=_optional_unit_float(payload.get("confidence")),
        confidence_basis=str(payload.get("confidence_basis") or "unknown"),
    )


def _coverage_from_payload(value: object) -> DjAnalysisCoverage:
    payload = _mapping_or_empty(value)
    return DjAnalysisCoverage(
        track_count=int(payload.get("track_count", 0)),
        tempo_count=int(payload.get("tempo_count", 0)),
        key_count=int(payload.get("key_count", 0)),
        energy_count=int(payload.get("energy_count", 0)),
        complete_count=int(payload.get("complete_count", 0)),
        unresolved_position_tokens=_string_tuple(
            payload.get("unresolved_position_tokens", []), "unresolved_position_tokens"
        ),
    )


def _missing_feature_policy(value: object) -> MissingFeaturePolicy:
    return "error" if value == "error" else "anchor"


def _mapping_or_empty(value: object) -> Mapping[Any, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Spotify {label} response is invalid")
    return value


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"missing required string: {key}")
    return result


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(value)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result > 0 else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _bounded_feature(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if 0 <= result <= 1 else None


def _optional_unit_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if 0 <= result <= 1 else None
