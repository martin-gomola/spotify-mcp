"""DJ analysis, planning, and snapshot-safe playlist mutation use cases."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Literal, cast

from spotify_mcp.application.audio import AudioAnalysisGateway, project_dj_audio_features
from spotify_mcp.application.catalog import CatalogService
from spotify_mcp.application.discovery import DiscoveryService
from spotify_mcp.application.playlist_mutation import (
    MutationResult,
    ReceiptRepository,
    execute_playlist_permutation,
)
from spotify_mcp.application.playlist_state import (
    read_playlist_state,
    verify_playlist_snapshot,
)
from spotify_mcp.application.playlists import (
    add_playlist_items,
    create_playlist,
    get_playlist_items,
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
    DjCandidateResolution,
    DjFeatureEvidence,
    DjPlan,
    DjPlanStrategy,
    DjSkippedCandidate,
    DjTrack,
    DjTransition,
    EnergyCurve,
    MissingFeaturePolicy,
    PlannedTrack,
    camelot_code,
    normalize_tempo,
    occurrence_tokens,
    plan_dj_set,
    plan_transition_set,
    stable_receipt_id,
)
from spotify_mcp.domain.errors import SpotifyRequestError
from spotify_mcp.domain.links import spotify_id, spotify_uri

DjApplyOperation = Literal["reorder", "create"]
DjApplyStatus = Literal[
    "dry-run",
    "unchanged",
    "accepted",
    "verified",
    "already-applied",
    "ambiguous",
    "stale",
    "partial",
    "visibility-mismatch",
]

_SPOTIFY_TRACK_ID = re.compile(r"[A-Za-z0-9]{22}")


@dataclass(frozen=True, slots=True)
class DjApplyResult:
    """Common result envelope for reorder and new-playlist DJ plans."""

    operation: DjApplyOperation
    status: DjApplyStatus
    action: Literal["apply", "create"]
    plan_id: str
    playlist_id: str | None
    playlist_url: str | None = None
    expected_snapshot_id: str | None = None
    initial_snapshot_id: str | None = None
    final_snapshot_id: str | None = None
    completed_moves: int = 0
    total_moves: int = 0
    receipt_id: str | None = None
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None
    requested_public: bool | None = None
    observed_public: bool | None = None
    expected_order: tuple[str, ...] = ()
    observed_order: tuple[str, ...] = ()

    @classmethod
    def from_mutation(cls, plan_id: str, result: MutationResult) -> DjApplyResult:
        return cls(
            operation="reorder",
            status=result.status,
            action="apply",
            plan_id=plan_id,
            playlist_id=result.playlist_id,
            expected_snapshot_id=result.expected_snapshot_id,
            initial_snapshot_id=result.initial_snapshot_id,
            final_snapshot_id=result.final_snapshot_id,
            completed_moves=result.completed_moves,
            total_moves=result.total_moves,
            receipt_id=result.receipt_id,
            warnings=result.warnings,
            failure_reason=result.failure_reason,
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


async def analyze_dj_source(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    *,
    playlist_id: str | None = None,
    candidates: Sequence[str] = (),
    playlist_name: str = "AI Harmonized DJ Set",
    public: bool = False,
    audio: AudioAnalysisGateway | None = None,
    source: AudioLookupSource = AudioLookupSource.AUTO,
    overrides: Sequence[AudioOverride] = (),
    features: Sequence[Mapping[str, Any]] = (),
    missing_feature_policy: MissingFeaturePolicy | None = None,
) -> tuple[str, DjAnalysis]:
    """Analyze exactly one existing-playlist or candidate-list source."""

    has_playlist = bool(playlist_id and playlist_id.strip())
    has_candidates = bool(candidates)
    if has_playlist == has_candidates:
        raise ValueError("provide exactly one of playlist_id or candidates")
    if has_playlist:
        if missing_feature_policy == "skip":
            raise ValueError("missing_feature_policy='skip' is only valid for candidates")
        return await analyze_playlist(
            spotify,
            artifacts,
            playlist_id or "",
            audio=audio,
            source=source,
            overrides=overrides,
            features=features,
            missing_feature_policy=missing_feature_policy or "anchor",
        )
    return await analyze_candidates(
        spotify,
        artifacts,
        candidates,
        playlist_name=playlist_name,
        public=public,
        audio=audio,
        source=source,
        overrides=overrides,
        features=features,
    )


async def analyze_candidates(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    candidates: Sequence[str],
    *,
    playlist_name: str = "AI Harmonized DJ Set",
    public: bool = False,
    audio: AudioAnalysisGateway | None = None,
    source: AudioLookupSource = AudioLookupSource.AUTO,
    overrides: Sequence[AudioOverride] = (),
    features: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, DjAnalysis]:
    """Resolve candidate inputs, enrich exact tracks, and store complete positions only."""

    if not 2 <= len(candidates) <= 100:
        raise ValueError("candidates must contain between 2 and 100 items")
    if not playlist_name.strip():
        raise ValueError("playlist_name must not be empty")

    resolved: list[DjCandidateResolution] = []
    skipped: list[DjSkippedCandidate] = []
    catalog = CatalogService(spotify)
    discovery = DiscoveryService(spotify)
    for input_index, raw_candidate in enumerate(candidates):
        candidate = raw_candidate.strip()
        if not candidate:
            skipped.append(DjSkippedCandidate(input_index, raw_candidate, "empty-candidate"))
            continue
        try:
            exact_track_id = _candidate_track_id(candidate)
        except ValueError as error:
            skipped.append(
                DjSkippedCandidate(input_index, candidate, f"invalid-candidate: {error}")
            )
            continue
        try:
            resolution = await _resolve_candidate(
                catalog,
                discovery,
                candidate,
                input_index=input_index,
                exact_track_id=exact_track_id,
            )
        except SpotifyRequestError as error:
            if error.status_code != 404:
                raise
            resolution = None
        if resolution is None:
            skipped.append(DjSkippedCandidate(input_index, candidate, "no-track-result"))
            continue
        resolved.append(resolution)

    feature_by_id: dict[str, Mapping[str, Any]] = {}
    warnings: list[str] = []
    if audio is not None and resolved:
        track_ids = list(dict.fromkeys(item.track_id for item in resolved))
        report = await audio.lookup(track_ids, source=source, overrides=list(overrides))
        feature_by_id.update(
            (projection.track_id, projection.model_dump())
            for projection in project_dj_audio_features(report)
        )
        warnings.extend(report.warnings)
    _merge_explicit_features(feature_by_id, features)

    tokens = occurrence_tokens([item.uri for item in resolved])
    tracks: list[DjTrack] = []
    unresolved_tokens: list[str] = []
    tempo_count = 0
    key_count = 0
    energy_count = 0
    for resolution, token in zip(resolved, tokens, strict=True):
        feature = feature_by_id.get(resolution.track_id, {})
        bpm = _optional_float(feature.get("bpm", feature.get("tempo")))
        energy = _bounded_feature(feature.get("energy"))
        key = _optional_int(feature.get("key"))
        mode = _optional_int(feature.get("mode"))
        camelot = camelot_code(key, mode) if key is not None and mode is not None else None
        tempo_count += bpm is not None
        key_count += camelot is not None
        energy_count += energy is not None
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
            unresolved_tokens.append(token)
            skipped.append(
                DjSkippedCandidate(
                    resolution.input_index,
                    resolution.candidate,
                    "incomplete-audio-features",
                    track_id=resolution.track_id,
                    missing_fields=unresolved,
                )
            )
            continue
        evidence = _dj_feature_evidence(feature)
        sources = tuple(sorted({item.provider for item in evidence}))
        tracks.append(
            DjTrack(
                position_token=token,
                identity=resolution.uri,
                original_position=resolution.input_index,
                track_id=resolution.track_id,
                uri=resolution.uri,
                name=resolution.name,
                artists=resolution.artists,
                bpm=bpm,
                normalized_bpm=normalize_tempo(bpm or 0),
                energy=energy,
                camelot=camelot,
                provenance=evidence,
                sources=sources or ("unavailable",),
            )
        )

    if len(tracks) < 2:
        raise ValueError(
            "candidate DJ analysis requires at least two tracks with complete "
            "tempo, key, mode, and energy"
        )
    if skipped:
        warnings.append(f"{len(skipped)} candidate(s) were skipped; inspect skipped_candidates")
    analysis = DjAnalysis(
        playlist_id=None,
        playlist_name=playlist_name.strip(),
        snapshot_id=None,
        tracks=tuple(tracks),
        warnings=tuple(dict.fromkeys(warnings)),
        audio_source=source.value if audio is not None else "manual",
        missing_feature_policy="skip",
        coverage=DjAnalysisCoverage(
            track_count=len(resolved),
            tempo_count=tempo_count,
            key_count=key_count,
            energy_count=energy_count,
            complete_count=len(tracks),
            unresolved_position_tokens=tuple(unresolved_tokens),
        ),
        source_kind="candidates",
        requested_public=public,
        resolved_candidates=tuple(resolved),
        skipped_candidates=tuple(skipped),
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
    strategy: DjPlanStrategy = "auto",
) -> tuple[str, DjPlan]:
    """Create and persist a deterministic plan from an immutable analysis."""

    payload = await artifacts.get(analysis_id)
    analysis = _analysis_from_payload(payload)
    selected_strategy = (
        ("transition-cost" if analysis.source_kind == "candidates" else "energy-curve")
        if strategy == "auto"
        else strategy
    )
    plan = (
        plan_transition_set(analysis, analysis_id)
        if selected_strategy == "transition-cost"
        else plan_dj_set(
            analysis,
            analysis_id,
            energy_curve=energy_curve,
            artist_spacing=artist_spacing,
        )
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
) -> DjApplyResult:
    """Apply a stored target order, defaulting to a side-effect-free dry run."""

    plan = _plan_from_payload(await artifacts.get(plan_id))
    if plan.source_kind == "candidates":
        if expected_snapshot_id is not None:
            raise ValueError("expected_snapshot_id is only valid for playlist reorder plans")
        return await _apply_candidate_plan(
            spotify,
            artifacts,
            plan_id,
            plan,
            dry_run=dry_run,
        )
    if plan.playlist_id is None or plan.source_snapshot_id is None:
        raise ValueError("playlist DJ plan is missing playlist snapshot identity")
    expected = expected_snapshot_id or plan.source_snapshot_id
    mutation = await execute_playlist_permutation(
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
    return DjApplyResult.from_mutation(plan_id, mutation)


async def _apply_candidate_plan(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    plan_id: str,
    plan: DjPlan,
    *,
    dry_run: bool,
) -> DjApplyResult:
    token_to_uri = dict(
        zip(
            occurrence_tokens([item.uri for item in plan.resolved_candidates]),
            (item.uri for item in plan.resolved_candidates),
            strict=True,
        )
    )
    try:
        expected_order = tuple(token_to_uri[token] for token in plan.target_order)
    except KeyError as error:
        raise ValueError("candidate DJ plan target order has no exact URI mapping") from error
    if len(expected_order) < 2:
        raise ValueError("candidate DJ plan requires at least two exact track URIs")
    if dry_run:
        return DjApplyResult(
            operation="create",
            status="dry-run",
            action="create",
            plan_id=plan_id,
            playlist_id=None,
            requested_public=plan.requested_public,
            expected_order=expected_order,
        )

    receipt_id = stable_receipt_id({"action": "create", "plan_id": plan_id})
    started = {
        "schema_version": 2,
        "operation": "create",
        "status": "started",
        "action": "create",
        "plan_id": plan_id,
        "playlist_id": None,
        "playlist_url": None,
        "receipt_id": receipt_id,
        "requested_public": plan.requested_public,
        "observed_public": None,
        "expected_order": list(expected_order),
        "observed_order": [],
        "warnings": [],
        "failure_reason": None,
    }
    try:
        claimed, existing = await artifacts.claim_receipt(receipt_id, started)
    except Exception as error:
        return DjApplyResult(
            operation="create",
            status="ambiguous",
            action="create",
            plan_id=plan_id,
            playlist_id=None,
            receipt_id=receipt_id,
            warnings=(f"receipt persistence failed: {error}",),
            failure_reason="receipt-failure",
            requested_public=plan.requested_public,
            expected_order=expected_order,
        )
    if not claimed:
        return _candidate_result_from_receipt(existing, already_applied=True)

    try:
        created = await create_playlist(
            spotify,
            name=plan.playlist_name,
            description=_candidate_playlist_description(plan),
            public=plan.requested_public,
        )
    except Exception as error:
        return await _persist_candidate_result(
            artifacts,
            DjApplyResult(
                operation="create",
                status="ambiguous",
                action="create",
                plan_id=plan_id,
                playlist_id=None,
                receipt_id=receipt_id,
                warnings=(f"playlist creation failed: {error}",),
                failure_reason="playlist-creation-failure",
                requested_public=plan.requested_public,
                expected_order=expected_order,
            ),
        )
    if created.playlist_id is None:
        result = DjApplyResult(
            operation="create",
            status="ambiguous",
            action="create",
            plan_id=plan_id,
            playlist_id=None,
            receipt_id=receipt_id,
            warnings=((created.warning,) if created.warning else ()),
            failure_reason="playlist-creation-ambiguous",
            requested_public=plan.requested_public,
            expected_order=expected_order,
        )
        return await _persist_candidate_result(artifacts, result)

    if created.status != "verified" or created.observed_public is not plan.requested_public:
        status: DjApplyStatus = (
            "visibility-mismatch" if created.visibility_status == "mismatch" else "ambiguous"
        )
        result = DjApplyResult(
            operation="create",
            status=status,
            action="create",
            plan_id=plan_id,
            playlist_id=created.playlist_id,
            playlist_url=created.playlist_url,
            receipt_id=receipt_id,
            warnings=((created.warning,) if created.warning else ()),
            failure_reason="playlist-visibility-unverified",
            requested_public=plan.requested_public,
            observed_public=created.observed_public,
            expected_order=expected_order,
        )
        return await _persist_candidate_result(artifacts, result)

    try:
        add_result = await add_playlist_items(spotify, created.playlist_id, expected_order)
    except Exception as error:
        return await _persist_candidate_result(
            artifacts,
            DjApplyResult(
                operation="create",
                status="partial",
                action="create",
                plan_id=plan_id,
                playlist_id=created.playlist_id,
                playlist_url=created.playlist_url,
                receipt_id=receipt_id,
                warnings=(f"playlist item write failed: {error}",),
                failure_reason="playlist-item-write-failure",
                requested_public=plan.requested_public,
                observed_public=created.observed_public,
                expected_order=expected_order,
            ),
        )
    warnings = [] if add_result.status == "accepted" else ["playlist item write was ambiguous"]
    try:
        observed_order = await _read_all_playlist_uris(spotify, created.playlist_id)
    except Exception as error:
        warnings.append(f"fresh playlist verification failed: {error}")
        result = DjApplyResult(
            operation="create",
            status="ambiguous",
            action="create",
            plan_id=plan_id,
            playlist_id=created.playlist_id,
            playlist_url=created.playlist_url,
            receipt_id=receipt_id,
            warnings=tuple(warnings),
            failure_reason="verification-read-failure",
            requested_public=plan.requested_public,
            observed_public=created.observed_public,
            expected_order=expected_order,
        )
        return await _persist_candidate_result(artifacts, result)

    matched = observed_order == expected_order
    if not matched:
        warnings.append("fresh playlist contents did not match the planned exact URI order")
    result = DjApplyResult(
        operation="create",
        status="verified" if matched else "partial",
        action="create",
        plan_id=plan_id,
        playlist_id=created.playlist_id,
        playlist_url=created.playlist_url,
        final_snapshot_id=add_result.snapshot_id,
        receipt_id=receipt_id,
        warnings=tuple(warnings),
        failure_reason=None if matched else "playlist-order-mismatch",
        requested_public=plan.requested_public,
        observed_public=created.observed_public,
        expected_order=expected_order,
        observed_order=observed_order,
    )
    return await _persist_candidate_result(artifacts, result)


async def _read_all_playlist_uris(spotify: SpotifyGateway, playlist_id: str) -> tuple[str, ...]:
    uris: list[str] = []
    offset = 0
    while True:
        page = await get_playlist_items(spotify, playlist_id, limit=50, offset=offset)
        for item in page.items:
            if item.uri is None:
                raise ValueError(f"playlist position {item.position} has no URI")
            uris.append(item.uri)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return tuple(uris)


async def _persist_candidate_result(
    artifacts: ArtifactRepository, result: DjApplyResult
) -> DjApplyResult:
    if result.receipt_id is None:
        return result
    try:
        await artifacts.put_receipt(result.receipt_id, {"schema_version": 2, **asdict(result)})
    except Exception as error:
        return replace(
            result,
            warnings=(*result.warnings, f"receipt update failed: {error}"),
            failure_reason=result.failure_reason or "receipt-update-failure",
        )
    return result


def _candidate_result_from_receipt(
    payload: Mapping[str, Any], *, already_applied: bool
) -> DjApplyResult:
    raw_status = str(payload.get("status") or "ambiguous")
    status: DjApplyStatus
    if already_applied and raw_status == "verified":
        status = "already-applied"
    elif raw_status in {
        "dry-run",
        "verified",
        "ambiguous",
        "partial",
        "visibility-mismatch",
    }:
        status = cast(DjApplyStatus, raw_status)
    else:
        status = "ambiguous"
    warnings = list(_string_tuple(payload.get("warnings", []), "warnings"))
    if raw_status == "started":
        warnings.append("a candidate playlist creation attempt is already in progress")
    return DjApplyResult(
        operation="create",
        status=status,
        action="create",
        plan_id=_required_string(payload, "plan_id"),
        playlist_id=_optional_string(payload.get("playlist_id")),
        playlist_url=_optional_string(payload.get("playlist_url")),
        final_snapshot_id=_optional_string(payload.get("final_snapshot_id")),
        receipt_id=_optional_string(payload.get("receipt_id")),
        warnings=tuple(warnings),
        failure_reason=_optional_string(payload.get("failure_reason")),
        requested_public=(
            payload.get("requested_public")
            if isinstance(payload.get("requested_public"), bool)
            else None
        ),
        observed_public=(
            payload.get("observed_public")
            if isinstance(payload.get("observed_public"), bool)
            else None
        ),
        expected_order=_string_tuple(payload.get("expected_order", []), "expected_order"),
        observed_order=_string_tuple(payload.get("observed_order", []), "observed_order"),
    )


def _candidate_playlist_description(plan: DjPlan) -> str:
    if not plan.transitions:
        return "AI DJ set generated from exact Spotify recordings."
    first = plan.resolved_candidates[0] if plan.resolved_candidates else None
    prefix = f"AI DJ set with {len(plan.target_order)} tracks"
    return f"{prefix}; transition cost {plan.total_transition_cost:g}." + (
        f" Source: {first.name}." if first is not None else ""
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
    if source_receipt.get("operation") == "create":
        raise ValueError("candidate playlist creation receipts cannot be restored")
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
        playlist_id=_optional_string(payload.get("playlist_id")),
        playlist_name=_required_string(payload, "playlist_name"),
        snapshot_id=_optional_string(payload.get("snapshot_id")),
        tracks=tuple(
            _track_from_payload(_mapping(track, "analysis track")) for track in raw_tracks
        ),
        warnings=_string_tuple(payload.get("warnings", []), "warnings"),
        audio_source=str(payload.get("audio_source") or "manual"),
        missing_feature_policy=_missing_feature_policy(payload.get("missing_feature_policy")),
        coverage=_coverage_from_payload(payload.get("coverage")),
        source_kind="candidates" if payload.get("source_kind") == "candidates" else "playlist",
        requested_public=payload.get("requested_public") is True,
        resolved_candidates=_candidate_resolutions(payload.get("resolved_candidates", [])),
        skipped_candidates=_skipped_candidates(payload.get("skipped_candidates", [])),
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
        playlist_id=_optional_string(payload.get("playlist_id")),
        playlist_name=_required_string(payload, "playlist_name"),
        source_snapshot_id=_optional_string(payload.get("source_snapshot_id")),
        energy_curve=cast(EnergyCurve, curve),
        artist_spacing=int(payload.get("artist_spacing", 3)),
        original_order=_string_tuple(payload.get("original_order"), "original_order"),
        target_order=_string_tuple(payload.get("target_order"), "target_order"),
        ordered_tracks=tuple(
            PlannedTrack(
                position_token=_required_string(_mapping(item, "planned track"), "position_token"),
                original_position=int(_mapping(item, "planned track")["original_position"]),
                target_energy=_bounded_feature(
                    _mapping(item, "planned track").get("target_energy")
                ),
                uri=_optional_string(_mapping(item, "planned track").get("uri")),
                name=str(_mapping(item, "planned track").get("name") or "Unknown"),
                artists=_string_tuple(
                    _mapping(item, "planned track").get("artists", []), "artists"
                ),
                bpm=_optional_float(_mapping(item, "planned track").get("bpm")),
                energy=_bounded_feature(_mapping(item, "planned track").get("energy")),
                camelot=_optional_string(_mapping(item, "planned track").get("camelot")),
                sources=_string_tuple(
                    _mapping(item, "planned track").get("sources", []), "sources"
                ),
            )
            for item in raw_tracks
        ),
        warnings=_string_tuple(payload.get("warnings", []), "warnings"),
        source_kind="candidates" if payload.get("source_kind") == "candidates" else "playlist",
        requested_public=payload.get("requested_public") is True,
        strategy=(
            "transition-cost" if payload.get("strategy") == "transition-cost" else "energy-curve"
        ),
        transitions=_transitions(payload.get("transitions", [])),
        total_transition_cost=float(payload.get("total_transition_cost", 0)),
        resolved_candidates=_candidate_resolutions(payload.get("resolved_candidates", [])),
        skipped_candidates=_skipped_candidates(payload.get("skipped_candidates", [])),
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


async def _resolve_candidate(
    catalog: CatalogService,
    discovery: DiscoveryService,
    candidate: str,
    *,
    input_index: int,
    exact_track_id: str | None,
) -> DjCandidateResolution | None:
    if exact_track_id is not None:
        result = await catalog.get("track", exact_track_id)
        track = result.track
        if track is None:
            return None
        return DjCandidateResolution(
            input_index=input_index,
            candidate=candidate,
            track_id=track.id,
            uri=track.uri or spotify_uri("track", track.id),
            name=track.name,
            artists=tuple(track.artists),
        )

    results = await discovery.search(candidate, "track", limit=10)
    if not results.items:
        return None
    selected = results.items[0]
    return DjCandidateResolution(
        input_index=input_index,
        candidate=candidate,
        track_id=selected.id,
        uri=selected.uri or spotify_uri("track", selected.id),
        name=selected.name,
        artists=tuple(selected.artists),
    )


def _candidate_track_id(candidate: str) -> str | None:
    if candidate.startswith("spotify:") and not candidate.startswith("spotify:track:"):
        raise ValueError("Spotify candidate URI must identify a track")
    if candidate.startswith("spotify:track:") or _SPOTIFY_TRACK_ID.fullmatch(candidate):
        return spotify_id("track", candidate)
    return None


def _merge_explicit_features(
    feature_by_id: dict[str, Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
) -> None:
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


def _candidate_resolutions(value: object) -> tuple[DjCandidateResolution, ...]:
    return tuple(
        DjCandidateResolution(
            input_index=int(item["input_index"]),
            candidate=_required_string(item, "candidate"),
            track_id=_required_string(item, "track_id"),
            uri=_required_string(item, "uri"),
            name=_required_string(item, "name"),
            artists=_string_tuple(item.get("artists", []), "artists"),
        )
        for raw in _sequence(value, "resolved_candidates")
        for item in (_mapping(raw, "candidate resolution"),)
    )


def _skipped_candidates(value: object) -> tuple[DjSkippedCandidate, ...]:
    return tuple(
        DjSkippedCandidate(
            input_index=int(item["input_index"]),
            candidate=str(item.get("candidate") or ""),
            reason=_required_string(item, "reason"),
            track_id=_optional_string(item.get("track_id")),
            missing_fields=_string_tuple(item.get("missing_fields", []), "missing_fields"),
        )
        for raw in _sequence(value, "skipped_candidates")
        for item in (_mapping(raw, "skipped candidate"),)
    )


def _transitions(value: object) -> tuple[DjTransition, ...]:
    return tuple(
        DjTransition(
            from_position_token=_required_string(item, "from_position_token"),
            to_position_token=_required_string(item, "to_position_token"),
            bpm_delta=float(item["bpm_delta"]),
            energy_delta=float(item["energy_delta"]),
            key_penalty=float(item["key_penalty"]),
            cost=float(item["cost"]),
        )
        for raw in _sequence(value, "transitions")
        for item in (_mapping(raw, "DJ transition"),)
    )


def _missing_feature_policy(value: object) -> MissingFeaturePolicy:
    if value == "error":
        return "error"
    if value == "skip":
        return "skip"
    return "anchor"


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
