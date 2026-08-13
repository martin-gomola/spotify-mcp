from pathlib import Path
from typing import NoReturn

import pytest
from mcp import Client
from mcp.types import Tool, ToolAnnotations

from spotify_mcp.config import SpotifyConfigError, SpotifySettings
from spotify_mcp.mcp_server.server import create_server
from spotify_mcp.mcp_server.ui import RESULTS_UI_URI

PUBLIC_TOOLS = {
    "spotify_add_to_queue",
    "spotify_adjust_volume",
    "spotify_album_tracks",
    "spotify_albums",
    "spotify_audio_audit",
    "spotify_audio_compare",
    "spotify_audio_features",
    "spotify_catalog",
    "spotify_devices",
    "spotify_dj_analyze",
    "spotify_dj_audit",
    "spotify_dj_apply",
    "spotify_dj_plan",
    "spotify_dj_restore",
    "spotify_library_contains",
    "spotify_library_remove",
    "spotify_library_save",
    "spotify_next",
    "spotify_now_playing",
    "spotify_pause",
    "spotify_play",
    "spotify_podcast_discover",
    "spotify_podcast_episode",
    "spotify_podcast_show",
    "spotify_podcast_show_episodes",
    "spotify_playlist",
    "spotify_playlist_add",
    "spotify_playlist_create",
    "spotify_playlist_items",
    "spotify_playlist_remove",
    "spotify_playlist_reorder",
    "spotify_playlist_sort_by_bpm",
    "spotify_playlist_unfollow",
    "spotify_playlist_update",
    "spotify_playlists",
    "spotify_previous",
    "spotify_queue",
    "spotify_render_results",
    "spotify_render_route_approval",
    "spotify_recently_played",
    "spotify_taste_recommendations",
    "spotify_resume",
    "spotify_sample_liked_songs",
    "spotify_saved_albums",
    "spotify_saved_episodes",
    "spotify_saved_shows",
    "spotify_saved_tracks",
    "spotify_search",
    "spotify_set_volume",
    "spotify_seek",
    "spotify_set_shuffle",
    "spotify_set_repeat",
    "spotify_status",
    "spotify_top_artists",
    "spotify_top_tracks",
    "spotify_transfer_playback",
}

APP_ONLY_TOOLS = {
    "spotify_results_context",
    "spotify_results_pause",
    "spotify_results_play",
}


def _unconfigured() -> NoReturn:
    raise SpotifyConfigError("test has no local Spotify configuration")


def _annotations(tool: Tool) -> ToolAnnotations:
    assert tool.annotations is not None
    return tool.annotations


@pytest.mark.anyio
async def test_public_mcp_v2_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the published catalog through the official in-memory MCP client."""
    monkeypatch.setattr(
        "spotify_mcp.bootstrap.load_settings",
        _unconfigured,
    )

    async with Client(create_server()) as client:
        assert client.server_info is not None
        assert client.server_info.name == "spotify-mcp"
        assert client.instructions

        listing = await client.list_tools()
        tools = {tool.name: tool for tool in listing.tools}
        resources = {
            str(resource.uri): resource for resource in (await client.list_resources()).resources
        }

        assert set(tools) == PUBLIC_TOOLS | APP_ONLY_TOOLS
        model_visible_tools = {
            name
            for name, tool in tools.items()
            if (tool.meta or {}).get("ui", {}).get("visibility") != ["app"]
        }
        assert model_visible_tools == PUBLIC_TOOLS
        assert resources[RESULTS_UI_URI].mime_type == "text/html;profile=mcp-app"
        for tool in tools.values():
            assert tool.output_schema is not None, tool.name
            assert tool.output_schema.get("type") == "object", tool.name

            input_properties = tool.input_schema.get("properties", {})
            required_inputs = tool.input_schema.get("required", [])
            assert "ctx" not in input_properties, tool.name
            assert "context" not in input_properties, tool.name
            assert "ctx" not in required_inputs, tool.name
            assert "context" not in required_inputs, tool.name

        status_annotations = _annotations(tools["spotify_status"])
        assert status_annotations.read_only_hint is True
        assert status_annotations.destructive_hint is False
        assert status_annotations.idempotent_hint is True
        assert status_annotations.open_world_hint is True

        create_annotations = _annotations(tools["spotify_playlist_create"])
        assert create_annotations.read_only_hint is False
        assert create_annotations.destructive_hint is False
        assert create_annotations.idempotent_hint is False

        remove_annotations = _annotations(tools["spotify_playlist_remove"])
        assert remove_annotations.read_only_hint is False
        assert remove_annotations.destructive_hint is True
        assert remove_annotations.idempotent_hint is True

        analyze_annotations = _annotations(tools["spotify_dj_analyze"])
        assert analyze_annotations.read_only_hint is False
        assert analyze_annotations.destructive_hint is False
        assert analyze_annotations.idempotent_hint is False

        adjust_annotations = _annotations(tools["spotify_adjust_volume"])
        assert adjust_annotations.read_only_hint is False
        assert adjust_annotations.destructive_hint is False
        assert adjust_annotations.idempotent_hint is False

        for name in (
            "spotify_seek",
            "spotify_set_shuffle",
            "spotify_set_repeat",
            "spotify_transfer_playback",
        ):
            annotations = _annotations(tools[name])
            assert annotations.read_only_hint is False
            assert annotations.destructive_hint is False
            assert annotations.idempotent_hint is True

        audit_annotations = _annotations(tools["spotify_dj_audit"])
        assert audit_annotations.read_only_hint is True
        assert audit_annotations.destructive_hint is False
        assert audit_annotations.idempotent_hint is True

        sort_annotations = _annotations(tools["spotify_playlist_sort_by_bpm"])
        assert sort_annotations.read_only_hint is False
        assert sort_annotations.destructive_hint is True
        assert sort_annotations.idempotent_hint is False

        render_annotations = _annotations(tools["spotify_render_results"])
        assert render_annotations.read_only_hint is True
        assert tools["spotify_render_results"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["model"]},
        }
        assert tools["spotify_results_context"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        assert tools["spotify_results_play"].meta == {
            "ui": {"resourceUri": RESULTS_UI_URI, "visibility": ["app"]}
        }
        context_annotations = _annotations(tools["spotify_results_context"])
        assert context_annotations.read_only_hint is True
        assert context_annotations.idempotent_hint is True
        play_annotations = _annotations(tools["spotify_results_play"])
        assert play_annotations.read_only_hint is False
        assert play_annotations.destructive_hint is False
        assert play_annotations.idempotent_hint is False

        status = await client.call_tool("spotify_status", {})

    assert status.is_error is False
    assert status.structured_content == {
        "configured": False,
        "authenticated": False,
        "configuration_error": "test has no local Spotify configuration",
        "user_id": None,
        "display_name": None,
        "product": None,
    }


@pytest.mark.anyio
async def test_status_distinguishes_configured_from_authenticated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SpotifySettings(client_id="client", token_path=tmp_path / "missing-tokens.json")
    monkeypatch.setattr("spotify_mcp.bootstrap.load_settings", lambda: settings)

    async with Client(create_server()) as client:
        status = await client.call_tool("spotify_status", {})

    assert status.is_error is False
    assert status.structured_content == {
        "configured": True,
        "authenticated": False,
        "configuration_error": None,
        "user_id": None,
        "display_name": None,
        "product": None,
    }
