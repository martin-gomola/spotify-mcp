"""MCP v2 registration for DJ analysis, planning, apply, and restore tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.dj import (
    analyze_playlist,
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
from spotify_mcp.domain.dj import EnergyCurve, MissingFeaturePolicy
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


class DjAnalysisResult(BaseModel):
    """Stored, snapshot-bound DJ analysis summary."""

    schema_version: Literal[1] = 1
    analysis_id: str
    playlist_id: str
    playlist_name: str
    snapshot_id: str
    positions: int = Field(ge=0)
    audio: DjAudioResult
    warnings: list[str]


class DjPlanResult(BaseModel):
    """Immutable deterministic DJ plan returned to MCP clients."""

    schema_version: Literal[1] = 1
    plan_id: str
    analysis_id: str
    playlist_id: str
    source_snapshot_id: str
    energy_curve: EnergyCurve
    original_order: list[str]
    target_order: list[str]
    warnings: list[str]


class DjMutationResult(BaseModel):
    """Typed outcome of applying or restoring a DJ playlist permutation."""

    schema_version: Literal[1] = 1
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
        playlist_id: str,
        ctx: Context[AppContext, Any],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        missing_feature_policy: MissingFeaturePolicy = "anchor",
        overrides: Annotated[list[AudioOverride], Field(max_length=100)] | None = None,
        features: list[AudioFeatureInput] | None = None,
    ) -> DjAnalysisResult:
        """Fetch current audio evidence and store a position-safe DJ analysis.

        Use ``anchor`` to retain incomplete tracks in place or ``error`` to reject
        incomplete analysis. Explicit legacy ``features`` override provider values.
        Audio is fetched for each call; this tool does not maintain a feature cache.
        """

        app = ctx.request_context.lifespan_context
        analysis_id, analysis = await analyze_playlist(
            app.spotify,
            app.artifacts,
            playlist_id,
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
            playlist_id=analysis.playlist_id,
            playlist_name=analysis.playlist_name,
            snapshot_id=analysis.snapshot_id,
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
            warnings=list(analysis.warnings),
        )

    @server.tool(name="spotify_dj_plan", annotations=IDEMPOTENT_WRITE, structured_output=True)
    async def plan_dj_set_tool(
        analysis_id: str,
        ctx: Context[AppContext, Any],
        energy_curve: EnergyCurve = "warmup-build-peak-close",
        artist_spacing: Annotated[int, Field(ge=0, le=20)] = 3,
    ) -> DjPlanResult:
        """Create an immutable deterministic DJ order without changing Spotify."""

        app = ctx.request_context.lifespan_context
        plan_id, plan = await create_plan(
            app.artifacts,
            analysis_id,
            energy_curve=energy_curve,
            artist_spacing=artist_spacing,
        )
        return DjPlanResult(
            plan_id=plan_id,
            analysis_id=analysis_id,
            playlist_id=plan.playlist_id,
            source_snapshot_id=plan.source_snapshot_id,
            energy_curve=plan.energy_curve,
            original_order=list(plan.original_order),
            target_order=list(plan.target_order),
            warnings=list(plan.warnings),
        )

    @server.tool(name="spotify_dj_apply", annotations=WRITE, structured_output=True)
    async def apply_dj_set_plan(
        plan_id: str,
        ctx: Context[AppContext, Any],
        expected_snapshot_id: str | None = None,
        dry_run: bool = True,
    ) -> DjMutationResult:
        """Preview or apply a plan with snapshot checks, receipts, and fresh verification."""

        app = ctx.request_context.lifespan_context
        result = await apply_plan(
            app.spotify,
            app.artifacts,
            plan_id,
            expected_snapshot_id=expected_snapshot_id,
            dry_run=dry_run,
        )
        return DjMutationResult.from_mutation(result)

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
