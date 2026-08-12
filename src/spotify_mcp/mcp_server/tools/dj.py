"""MCP v2 registration for DJ analysis, planning, apply, and restore tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.dj import (
    DjApplyResult as ApplicationDjApplyResult,
)
from spotify_mcp.application.dj import (
    analyze_dj_source,
    apply_plan,
    create_plan,
    restore_playlist,
)
from spotify_mcp.application.playlist_mutation import (
    MutationResult,
    MutationStatus,
    PlaylistMutationAction,
    ReceiptRepository,
)
from spotify_mcp.domain.audio import AudioLookupSource, AudioOverride
from spotify_mcp.domain.dj import DjPlanStrategy, EnergyCurve, MissingFeaturePolicy
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, WRITE
from spotify_mcp.mcp_server.context import AppContext

DjAudioSource = Literal["auto", "spotify", "reccobeats", "manual"]


class AudioFeatureInput(BaseModel):
    """Feature measurement for one exact Spotify recording."""

    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    bpm: float | None = Field(default=None, gt=0)
    energy: float | None = Field(default=None, ge=0, le=1)
    key: int | None = Field(default=None, ge=0, le=11)
    mode: int | None = Field(default=None, ge=0, le=1)


class DjAudioCoverageResult(BaseModel):
    """Audio-feature coverage for the analyzed playlist positions."""

    track_count: int = Field(ge=0)
    tempo_count: int = Field(ge=0)
    key_count: int = Field(ge=0)
    energy_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    unresolved_position_tokens: list[str]


class DjAudioResult(BaseModel):
    """Provider and coverage metadata for one DJ analysis."""

    requested_source: DjAudioSource
    missing_feature_policy: MissingFeaturePolicy
    provider_positions: dict[str, int]
    coverage: DjAudioCoverageResult


class DjResolvedCandidateResult(BaseModel):
    """A user input resolved to one exact Spotify recording."""

    input_index: int = Field(ge=0)
    candidate: str
    track_id: str
    uri: str
    name: str
    artists: list[str]


class DjSkippedCandidateResult(BaseModel):
    """A candidate excluded before transition planning."""

    input_index: int = Field(ge=0)
    candidate: str
    reason: str
    track_id: str | None
    missing_fields: list[str]


class DjPlannedTrackResult(BaseModel):
    position_token: str
    original_position: int = Field(ge=0)
    target_energy: float | None = Field(default=None, ge=0, le=1)
    uri: str | None
    name: str
    artists: list[str]
    bpm: float | None = Field(default=None, gt=0)
    normalized_bpm: float | None = Field(default=None, gt=0)
    energy: float | None = Field(default=None, ge=0, le=1)
    camelot: str | None
    sources: list[str]


class DjTransitionResult(BaseModel):
    from_position_token: str
    to_position_token: str
    bpm_delta: float = Field(ge=0)
    energy_delta: float = Field(ge=0, le=1)
    key_penalty: float = Field(ge=0)
    cost: float = Field(ge=0)
    from_normalized_bpm: float | None = Field(default=None, gt=0)
    to_normalized_bpm: float | None = Field(default=None, gt=0)


class DjAnalysisResult(BaseModel):
    """Stored playlist- or candidate-bound DJ analysis summary."""

    schema_version: Literal[2] = 2
    analysis_id: str
    source_kind: Literal["playlist", "candidates"]
    playlist_id: str | None
    playlist_name: str
    snapshot_id: str | None
    requested_public: bool
    positions: int = Field(ge=0)
    audio: DjAudioResult
    resolved_candidates: list[DjResolvedCandidateResult]
    skipped_candidates: list[DjSkippedCandidateResult]
    warnings: list[str]


class DjPlanResult(BaseModel):
    """Immutable deterministic DJ plan returned to MCP clients."""

    schema_version: Literal[2] = 2
    plan_id: str
    analysis_id: str
    source_kind: Literal["playlist", "candidates"]
    playlist_id: str | None
    source_snapshot_id: str | None
    requested_public: bool
    strategy: Literal["energy-curve", "transition-cost"]
    energy_curve: EnergyCurve
    original_order: list[str]
    target_order: list[str]
    ordered_tracks: list[DjPlannedTrackResult]
    transitions: list[DjTransitionResult]
    total_transition_cost: float = Field(ge=0)
    resolved_candidates: list[DjResolvedCandidateResult]
    skipped_candidates: list[DjSkippedCandidateResult]
    warnings: list[str]


class DjApplyResult(BaseModel):
    """Typed outcome for an existing reorder or candidate playlist creation."""

    schema_version: Literal[2] = 2
    operation: Literal["reorder", "create"]
    status: Literal[
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
    action: Literal["apply", "create"]
    plan_id: str
    playlist_id: str | None
    playlist_url: str | None
    expected_snapshot_id: str | None
    initial_snapshot_id: str | None
    final_snapshot_id: str | None
    completed_moves: int = Field(ge=0)
    total_moves: int = Field(ge=0)
    receipt_id: str | None
    warnings: list[str]
    failure_reason: str | None
    requested_public: bool | None
    observed_public: bool | None
    expected_order: list[str]
    observed_order: list[str]

    @classmethod
    def from_application(cls, result: ApplicationDjApplyResult) -> DjApplyResult:
        return cls(
            operation=result.operation,
            status=result.status,
            action=result.action,
            plan_id=result.plan_id,
            playlist_id=result.playlist_id,
            playlist_url=result.playlist_url,
            expected_snapshot_id=result.expected_snapshot_id,
            initial_snapshot_id=result.initial_snapshot_id,
            final_snapshot_id=result.final_snapshot_id,
            completed_moves=result.completed_moves,
            total_moves=result.total_moves,
            receipt_id=result.receipt_id,
            warnings=list(result.warnings),
            failure_reason=result.failure_reason,
            requested_public=result.requested_public,
            observed_public=result.observed_public,
            expected_order=list(result.expected_order),
            observed_order=list(result.observed_order),
        )


class DjMutationResult(BaseModel):
    """Typed outcome of applying or restoring a DJ playlist permutation."""

    schema_version: Literal[2] = 2
    operation: Literal["reorder"] = "reorder"
    status: MutationStatus
    action: PlaylistMutationAction
    playlist_id: str
    expected_snapshot_id: str
    initial_snapshot_id: str
    final_snapshot_id: str | None
    completed_moves: int = Field(ge=0)
    total_moves: int = Field(ge=0)
    receipt_id: str | None
    warnings: list[str]
    failure_reason: str | None

    @classmethod
    def from_mutation(cls, result: MutationResult) -> DjMutationResult:
        """Convert the internal immutable result without loosening failure fields."""

        return cls(
            status=result.status,
            action=result.action,
            playlist_id=result.playlist_id,
            expected_snapshot_id=result.expected_snapshot_id,
            initial_snapshot_id=result.initial_snapshot_id,
            final_snapshot_id=result.final_snapshot_id,
            completed_moves=result.completed_moves,
            total_moves=result.total_moves,
            receipt_id=result.receipt_id,
            warnings=list(result.warnings),
            failure_reason=result.failure_reason,
        )


def register(server: MCPServer[AppContext]) -> None:
    """Register DJ tools without binding concrete runtime dependencies."""

    @server.tool(
        name="spotify_dj_analyze",
        annotations=WRITE,
        structured_output=True,
    )
    async def analyze_dj_playlist(
        ctx: Context[AppContext, Any],
        playlist_id: Annotated[str | None, Field(min_length=1)] = None,
        candidates: Annotated[list[str] | None, Field(min_length=2, max_length=100)] = None,
        playlist_name: Annotated[str, Field(min_length=1, max_length=100)] = (
            "AI Harmonized DJ Set"
        ),
        public: bool = False,
        source: AudioLookupSource = AudioLookupSource.AUTO,
        missing_feature_policy: MissingFeaturePolicy | None = None,
        overrides: Annotated[list[AudioOverride], Field(max_length=100)] | None = None,
        features: list[AudioFeatureInput] | None = None,
    ) -> DjAnalysisResult:
        """Fetch current audio evidence and store a position-safe DJ analysis.

        Provide exactly one of ``playlist_id`` or ``candidates``. Playlist analysis
        defaults to anchoring missing-tempo positions. Candidate analysis resolves exact
        recordings, skips incomplete audio evidence, and stores no Spotify mutation.
        """

        app = ctx.request_context.lifespan_context
        analysis_id, analysis = await analyze_dj_source(
            app.spotify,
            app.artifacts,
            playlist_id=playlist_id,
            candidates=candidates or [],
            playlist_name=playlist_name,
            public=public,
            audio=app.audio,
            source=source,
            overrides=overrides or [],
            features=[feature.model_dump(exclude_none=True) for feature in features or []],
            missing_feature_policy=missing_feature_policy,
        )
        provider_positions: dict[str, int] = {}
        for track in analysis.tracks:
            for provider in track.sources:
                provider_positions[provider] = provider_positions.get(provider, 0) + 1
        return DjAnalysisResult(
            analysis_id=analysis_id,
            source_kind=analysis.source_kind,
            playlist_id=analysis.playlist_id,
            playlist_name=analysis.playlist_name,
            snapshot_id=analysis.snapshot_id,
            requested_public=analysis.requested_public,
            positions=len(analysis.tracks),
            audio=DjAudioResult(
                requested_source=cast(DjAudioSource, analysis.audio_source),
                missing_feature_policy=analysis.missing_feature_policy,
                provider_positions=provider_positions,
                coverage=DjAudioCoverageResult(
                    track_count=analysis.coverage.track_count,
                    tempo_count=analysis.coverage.tempo_count,
                    key_count=analysis.coverage.key_count,
                    energy_count=analysis.coverage.energy_count,
                    complete_count=analysis.coverage.complete_count,
                    unresolved_position_tokens=list(analysis.coverage.unresolved_position_tokens),
                ),
            ),
            resolved_candidates=[
                DjResolvedCandidateResult.model_validate(asdict(item))
                for item in analysis.resolved_candidates
            ],
            skipped_candidates=[
                DjSkippedCandidateResult.model_validate(asdict(item))
                for item in analysis.skipped_candidates
            ],
            warnings=list(analysis.warnings),
        )

    @server.tool(name="spotify_dj_plan", annotations=IDEMPOTENT_WRITE, structured_output=True)
    async def plan_dj_set_tool(
        analysis_id: str,
        ctx: Context[AppContext, Any],
        energy_curve: EnergyCurve = "warmup-build-peak-close",
        artist_spacing: Annotated[int, Field(ge=0, le=20)] = 3,
        strategy: DjPlanStrategy = "auto",
    ) -> DjPlanResult:
        """Create an immutable deterministic DJ order without changing Spotify."""

        app = ctx.request_context.lifespan_context
        plan_id, plan = await create_plan(
            app.artifacts,
            analysis_id,
            energy_curve=energy_curve,
            artist_spacing=artist_spacing,
            strategy=strategy,
        )
        return DjPlanResult(
            plan_id=plan_id,
            analysis_id=analysis_id,
            source_kind=plan.source_kind,
            playlist_id=plan.playlist_id,
            source_snapshot_id=plan.source_snapshot_id,
            requested_public=plan.requested_public,
            strategy=plan.strategy,
            energy_curve=plan.energy_curve,
            original_order=list(plan.original_order),
            target_order=list(plan.target_order),
            ordered_tracks=[
                DjPlannedTrackResult.model_validate(asdict(item)) for item in plan.ordered_tracks
            ],
            transitions=[
                DjTransitionResult.model_validate(asdict(item)) for item in plan.transitions
            ],
            total_transition_cost=plan.total_transition_cost,
            resolved_candidates=[
                DjResolvedCandidateResult.model_validate(asdict(item))
                for item in plan.resolved_candidates
            ],
            skipped_candidates=[
                DjSkippedCandidateResult.model_validate(asdict(item))
                for item in plan.skipped_candidates
            ],
            warnings=list(plan.warnings),
        )

    @server.tool(name="spotify_dj_apply", annotations=WRITE, structured_output=True)
    async def apply_dj_set_plan(
        plan_id: str,
        ctx: Context[AppContext, Any],
        expected_snapshot_id: str | None = None,
        dry_run: bool = True,
    ) -> DjApplyResult:
        """Preview or apply a plan with snapshot checks, receipts, and fresh verification."""

        app = ctx.request_context.lifespan_context
        result = await apply_plan(
            app.spotify,
            app.artifacts,
            plan_id,
            expected_snapshot_id=expected_snapshot_id,
            dry_run=dry_run,
        )
        return DjApplyResult.from_application(result)

    @server.tool(name="spotify_dj_restore", annotations=WRITE, structured_output=True)
    async def restore_dj_playlist(
        receipt_id: str,
        expected_snapshot_id: str,
        ctx: Context[AppContext, Any],
        dry_run: bool = True,
    ) -> DjMutationResult:
        """Preview or restore the exact pre-plan order recorded in a mutation receipt."""

        app = ctx.request_context.lifespan_context
        result = await restore_playlist(
            app.spotify,
            cast(ReceiptRepository, app.artifacts),
            receipt_id,
            expected_snapshot_id=expected_snapshot_id,
            dry_run=dry_run,
        )
        return DjMutationResult.from_mutation(result)
