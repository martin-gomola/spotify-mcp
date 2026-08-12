from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from spotify_mcp.application.playlist_mutation import MutationResult
from spotify_mcp.mcp_server.tools.dj import DjMutationResult, register


@pytest.mark.anyio
async def test_dj_analyze_exposes_automatic_audio_enrichment_inputs() -> None:
    server = MCPServer("test")

    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}
    properties = tools["spotify_dj_analyze"].input_schema["properties"]
    assert properties["source"]["default"] == "auto"
    assert properties["missing_feature_policy"]["default"] is None
    policy_schema = properties["missing_feature_policy"]["anyOf"]
    assert set(policy_schema[0]["enum"]) == {"anchor", "error", "skip"}
    assert properties["playlist_name"]["default"] == "AI Harmonized DJ Set"
    assert properties["public"]["default"] is False
    assert properties["candidates"]["anyOf"][0]["maxItems"] == 100
    assert "overrides" in properties
    assert "features" in properties


@pytest.mark.anyio
async def test_dj_tools_expose_field_level_output_schemas() -> None:
    server = MCPServer("test")

    register(server)

    tools = {tool.name: tool for tool in await server.list_tools()}
    analyze_schema = tools["spotify_dj_analyze"].output_schema
    assert analyze_schema is not None
    assert set(analyze_schema["properties"]) == {
        "schema_version",
        "analysis_id",
        "source_kind",
        "playlist_id",
        "playlist_name",
        "snapshot_id",
        "requested_public",
        "positions",
        "audio",
        "resolved_candidates",
        "skipped_candidates",
        "warnings",
    }
    audio_schema = analyze_schema["$defs"]["DjAudioResult"]
    assert set(audio_schema["properties"]) == {
        "requested_source",
        "missing_feature_policy",
        "provider_positions",
        "coverage",
    }
    assert audio_schema["properties"]["requested_source"]["enum"] == [
        "auto",
        "spotify",
        "reccobeats",
        "manual",
    ]

    plan_schema = tools["spotify_dj_plan"].output_schema
    assert plan_schema is not None
    assert plan_schema["properties"]["energy_curve"]["enum"] == [
        "warmup-build-peak-close",
        "steady",
        "rising",
        "waves",
    ]
    assert plan_schema["properties"]["target_order"]["items"] == {"type": "string"}
    assert plan_schema["properties"]["strategy"]["enum"] == [
        "energy-curve",
        "transition-cost",
    ]
    assert tools["spotify_dj_plan"].input_schema["properties"]["strategy"]["default"] == "auto"
    planned_track_schema = plan_schema["$defs"]["DjPlannedTrackResult"]
    assert "normalized_bpm" in planned_track_schema["properties"]
    transition_schema = plan_schema["$defs"]["DjTransitionResult"]
    assert {
        "from_normalized_bpm",
        "to_normalized_bpm",
    } <= set(transition_schema["properties"])

    apply_schema = tools["spotify_dj_apply"].output_schema
    assert apply_schema is not None
    apply_properties = apply_schema["properties"]
    assert apply_properties["operation"]["enum"] == ["reorder", "create"]
    assert "verified" in apply_properties["status"]["enum"]
    assert "already-applied" in apply_properties["status"]["enum"]

    restore_schema = tools["spotify_dj_restore"].output_schema
    assert restore_schema is not None
    restore_properties = restore_schema["properties"]
    assert restore_properties["operation"]["const"] == "reorder"
    assert restore_properties["action"]["enum"] == ["apply", "restore"]


def test_dj_mutation_result_preserves_intentional_failure_fields() -> None:
    result = MutationResult(
        status="stale",
        action="apply",
        playlist_id="playlist-1",
        expected_snapshot_id="expected-snapshot",
        initial_snapshot_id="observed-snapshot",
        final_snapshot_id=None,
        completed_moves=0,
        total_moves=0,
        receipt_id=None,
        warnings=("playlist changed",),
        failure_reason="snapshot-mismatch",
    )

    typed = DjMutationResult.from_mutation(result)

    assert typed.status == "stale"
    assert typed.action == "apply"
    assert typed.failure_reason == "snapshot-mismatch"
    assert typed.warnings == ["playlist changed"]
    assert typed.model_dump()["schema_version"] == 2


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
