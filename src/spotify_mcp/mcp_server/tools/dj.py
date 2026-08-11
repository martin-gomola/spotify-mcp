"""MCP v2 registration for DJ analysis, planning, apply, and restore tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ConfigDict, Field

from spotify_mcp.application.dj import (
    analyze_playlist,
    apply_plan,
    create_plan,
    restore_playlist,
)
from spotify_mcp.application.playlist_mutation import ReceiptRepository
from spotify_mcp.domain.audio import AudioLookupSource, AudioOverride
from spotify_mcp.domain.dj import EnergyCurve, MissingFeaturePolicy
from spotify_mcp.mcp_server.annotations import IDEMPOTENT_WRITE, WRITE
from spotify_mcp.mcp_server.context import AppContext


class AudioFeatureInput(BaseModel):
    """Feature measurement for one exact Spotify recording."""

    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    bpm: float | None = Field(default=None, gt=0)
    energy: float | None = Field(default=None, ge=0, le=1)
    key: int | None = Field(default=None, ge=0, le=11)
    mode: int | None = Field(default=None, ge=0, le=1)


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
    ) -> dict[str, Any]:
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
        return {
            "schema_version": 1,
            "analysis_id": analysis_id,
            "playlist_id": analysis.playlist_id,
            "playlist_name": analysis.playlist_name,
            "snapshot_id": analysis.snapshot_id,
            "positions": len(analysis.tracks),
            "audio": {
                "requested_source": analysis.audio_source,
                "missing_feature_policy": analysis.missing_feature_policy,
                "provider_positions": provider_positions,
                "coverage": asdict(analysis.coverage),
            },
            "warnings": list(analysis.warnings),
        }

    @server.tool(name="spotify_dj_plan", annotations=IDEMPOTENT_WRITE, structured_output=True)
    async def plan_dj_set_tool(
        analysis_id: str,
        ctx: Context[AppContext, Any],
        energy_curve: EnergyCurve = "warmup-build-peak-close",
        artist_spacing: Annotated[int, Field(ge=0, le=20)] = 3,
    ) -> dict[str, Any]:
        """Create an immutable deterministic DJ order without changing Spotify."""

        app = ctx.request_context.lifespan_context
        plan_id, plan = await create_plan(
            app.artifacts,
            analysis_id,
            energy_curve=energy_curve,
            artist_spacing=artist_spacing,
        )
        return {
            "schema_version": 1,
            "plan_id": plan_id,
            "analysis_id": analysis_id,
            "playlist_id": plan.playlist_id,
            "source_snapshot_id": plan.source_snapshot_id,
            "energy_curve": plan.energy_curve,
            "original_order": list(plan.original_order),
            "target_order": list(plan.target_order),
            "warnings": list(plan.warnings),
        }

    @server.tool(name="spotify_dj_apply", annotations=WRITE, structured_output=True)
    async def apply_dj_set_plan(
        plan_id: str,
        ctx: Context[AppContext, Any],
        expected_snapshot_id: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Preview or apply a plan with snapshot checks, receipts, and fresh verification."""

        app = ctx.request_context.lifespan_context
        result = await apply_plan(
            app.spotify,
            app.artifacts,
            plan_id,
            expected_snapshot_id=expected_snapshot_id,
            dry_run=dry_run,
        )
        return {"schema_version": 1, **result.to_dict()}

    @server.tool(name="spotify_dj_restore", annotations=WRITE, structured_output=True)
    async def restore_dj_playlist(
        receipt_id: str,
        expected_snapshot_id: str,
        ctx: Context[AppContext, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Preview or restore the exact pre-plan order recorded in a mutation receipt."""

        app = ctx.request_context.lifespan_context
        result = await restore_playlist(
            app.spotify,
            cast(ReceiptRepository, app.artifacts),
            receipt_id,
            expected_snapshot_id=expected_snapshot_id,
            dry_run=dry_run,
        )
        return {"schema_version": 1, **result.to_dict()}
