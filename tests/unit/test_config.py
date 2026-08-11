import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from spotify_mcp.cli import _parser
from spotify_mcp.config import (
    DEFAULT_REDIRECT_URI,
    SpotifyAppConfig,
    SpotifyConfigError,
    SpotifySettings,
    default_token_path,
    load_app_config,
    load_settings,
    save_app_config,
)


def test_settings_read_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "spotify-tokens.json"
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", " client ")
    monkeypatch.setenv("SPOTIFY_TOKEN_PATH", str(token_path))

    # The test intentionally exercises BaseSettings environment loading.
    settings = SpotifySettings()  # type: ignore[call-arg]

    assert settings.client_id == "client"
    assert settings.redirect_uri == DEFAULT_REDIRECT_URI
    assert settings.token_path == token_path


def test_load_settings_reads_client_id_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SPOTIFY_CLIENT_ID=dotenv-client\n", encoding="utf-8")

    settings = load_settings(app_config_path=tmp_path / "missing-config.json")

    assert settings.client_id == "dotenv-client"


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost:8888/callback",
        "https://127.0.0.1:8888/callback",
        "http://0.0.0.0:8888/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:8888/callback?token=bad",
    ],
)
def test_settings_reject_non_literal_or_unsafe_loopback_redirect(redirect_uri: str) -> None:
    with pytest.raises(ValidationError, match="redirect_uri"):
        SpotifySettings(client_id="client", redirect_uri=redirect_uri)


def test_default_token_path_uses_platform_config_directory() -> None:
    path = default_token_path()

    assert path.name == "tokens.json"
    assert "spotify-mcp" in path.parts


def test_saved_app_config_bootstraps_later_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    config_path = tmp_path / "config" / "config.json"

    saved_path = save_app_config(SpotifyAppConfig("saved-client"), config_path)
    settings = load_settings(
        app_config_path=config_path,
        token_path=tmp_path / "tokens.json",
        dotenv_path=None,
    )

    assert saved_path == config_path
    assert settings.client_id == "saved-client"
    assert load_app_config(config_path) == SpotifyAppConfig("saved-client")
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700


def test_environment_overrides_saved_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    save_app_config(
        SpotifyAppConfig("saved", "http://127.0.0.1:9999/callback"),
        config_path,
    )
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "environment")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:7777/callback")

    settings = load_settings(app_config_path=config_path)

    assert settings.client_id == "environment"
    assert settings.redirect_uri == "http://127.0.0.1:7777/callback"


def test_explicit_auth_values_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "environment")

    settings = load_settings(client_id="cli", redirect_uri="http://127.0.0.1:6666/callback")

    assert settings.client_id == "cli"
    assert settings.redirect_uri == "http://127.0.0.1:6666/callback"


def test_missing_or_invalid_saved_config_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    missing = tmp_path / "missing.json"
    with pytest.raises(SpotifyConfigError, match="client ID is missing"):
        load_settings(app_config_path=missing, dotenv_path=None)

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"redirect_uri": DEFAULT_REDIRECT_URI}), encoding="utf-8")
    with pytest.raises(SpotifyConfigError, match="is invalid"):
        load_settings(app_config_path=invalid)


def test_invalid_environment_redirect_has_actionable_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

    with pytest.raises(SpotifyConfigError, match="Spotify settings are invalid"):
        load_settings()


def test_auth_cli_does_not_override_environment_redirect_by_default() -> None:
    args = _parser().parse_args(["auth"])

    assert args.redirect_uri is None


def test_connect_cli_is_available_for_make_run() -> None:
    args = _parser().parse_args(["connect"])

    assert args.command == "connect"


def test_http_transport_rejects_non_loopback_binding() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["serve", "--transport", "streamable-http", "--host", "0.0.0.0"])
