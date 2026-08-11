from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from spotify_mcp.adapters.spotify.oauth import (
    REQUIRED_SCOPES,
    TokenSet,
    TokenStore,
    spotify_app_fingerprint,
)
from spotify_mcp.cli import _connect, _doctor, _init, _validate_client_id, main
from spotify_mcp.config import SpotifyAppConfig, SpotifyConfigError, SpotifySettings
from spotify_mcp.domain.errors import AuthenticationRequired


class FakeOAuth:
    def __init__(self, *, authenticated: bool) -> None:
        self.authenticated = authenticated
        self.authorize_calls = 0
        self.closed = False

    async def ensure_access_token(self) -> str:
        if not self.authenticated:
            raise AuthenticationRequired("not connected")
        return "access"

    async def authorize(self) -> TokenSet:
        self.authorize_calls += 1
        return TokenSet("access", "refresh", 1_000.0, "scope-a scope-b")

    async def aclose(self) -> None:
        self.closed = True


class FakeSpotifyClient:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.requests: list[tuple[str, str]] = []
        self.closed = False

    async def request(self, method: str, path: str) -> dict[str, Any]:
        self.requests.append((method, path))
        return self.profile

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
@pytest.mark.parametrize("authenticated", [True, False])
async def test_connect_authenticates_only_when_needed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authenticated: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = SpotifySettings(client_id="client", token_path=tmp_path / "tokens.json")
    oauth = FakeOAuth(authenticated=authenticated)
    saved: list[Any] = []
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda: settings)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyOAuth", lambda _settings: oauth)
    monkeypatch.setattr("spotify_mcp.cli.save_app_config", lambda config: saved.append(config))

    assert await _connect() == 0

    assert oauth.closed is True
    assert oauth.authorize_calls == (0 if authenticated else 1)
    assert len(saved) == (0 if authenticated else 1)
    output = capsys.readouterr().out
    assert ("already_connected" in output) is authenticated
    assert ("connected" in output) is True


@pytest.mark.anyio
async def test_doctor_rejects_token_missing_current_required_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SpotifySettings(client_id="client", token_path=tmp_path / "tokens.json")
    old_scopes = " ".join(
        scope for scope in REQUIRED_SCOPES if scope != "user-read-playback-position"
    )
    TokenStore(settings.token_path).save(
        TokenSet(
            "access",
            "refresh",
            10_000.0,
            old_scopes,
            app_fingerprint=spotify_app_fingerprint(settings),
        )
    )
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda: settings)

    with pytest.raises(AuthenticationRequired, match="user-read-playback-position"):
        await _doctor()


@pytest.mark.anyio
@pytest.mark.parametrize("authenticated", [True, False])
async def test_init_saves_connects_verifies_and_reports_next_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authenticated: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client_id = "a" * 32
    settings = SpotifySettings(client_id=client_id, token_path=tmp_path / "tokens.json")
    oauth = FakeOAuth(authenticated=authenticated)
    client = FakeSpotifyClient(
        {"id": "spotify-user", "display_name": "Test User", "product": "premium"}
    )
    saved: list[Any] = []
    monkeypatch.setattr(
        "spotify_mcp.cli.load_app_config",
        lambda: SpotifyAppConfig(client_id),
    )
    monkeypatch.setattr(
        "spotify_mcp.cli.load_settings",
        lambda **kwargs: settings,
    )
    monkeypatch.setattr("spotify_mcp.cli.SpotifyOAuth", lambda _settings: oauth)
    monkeypatch.setattr(
        "spotify_mcp.cli.SpotifyClient",
        lambda _settings, _oauth: client,
    )
    monkeypatch.setattr(
        "spotify_mcp.cli.save_app_config",
        lambda config: saved.append(config) or tmp_path / "config.json",
    )

    assert await _init(client_id, None) == 0

    assert saved[0].client_id == client_id
    assert oauth.authorize_calls == (0 if authenticated else 1)
    assert oauth.closed is True
    assert client.closed is True
    assert client.requests == [("GET", "me")]
    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    expected_connection = "already_connected" if authenticated else "connected"
    assert f'"connection": "{expected_connection}"' in output
    assert '"user_id": "spotify-user"' in output
    assert '"next_steps"' in output


@pytest.mark.anyio
async def test_init_prompts_for_client_id_when_not_passed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client_id = "b" * 32
    settings = SpotifySettings(client_id=client_id, token_path=tmp_path / "tokens.json")
    oauth = FakeOAuth(authenticated=True)
    client = FakeSpotifyClient({"id": "spotify-user"})
    prompted: list[bool] = []
    monkeypatch.setattr(
        "spotify_mcp.cli.load_app_config",
        lambda: SpotifyAppConfig(client_id),
    )
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyOAuth", lambda _settings: oauth)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyClient", lambda _settings, _oauth: client)
    monkeypatch.setattr("spotify_mcp.cli.save_app_config", lambda config: tmp_path / "config.json")

    assert (
        await _init(
            None,
            None,
            prompt_client_id=lambda: prompted.append(True) or f"  {client_id}  ",
        )
        == 0
    )

    assert prompted == [True]


@pytest.mark.anyio
async def test_init_reauthorizes_when_saved_app_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client_id = "c" * 32
    settings = SpotifySettings(client_id=client_id, token_path=tmp_path / "tokens.json")
    oauth = FakeOAuth(authenticated=True)
    client = FakeSpotifyClient({"id": "spotify-user"})
    monkeypatch.setattr(
        "spotify_mcp.cli.load_app_config",
        lambda: SpotifyAppConfig("different-client-id"),
    )
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyOAuth", lambda _settings: oauth)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyClient", lambda _settings, _oauth: client)
    monkeypatch.setattr("spotify_mcp.cli.save_app_config", lambda config: tmp_path / "config.json")

    assert await _init(client_id, None) == 0

    assert oauth.authorize_calls == 1


@pytest.mark.anyio
async def test_init_preserves_saved_app_when_reauthorization_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client_id = "d" * 32
    settings = SpotifySettings(client_id=client_id, token_path=tmp_path / "tokens.json")
    saved: list[Any] = []

    class FailingOAuth(FakeOAuth):
        async def authorize(self) -> TokenSet:
            raise RuntimeError("authorization cancelled")

    oauth = FailingOAuth(authenticated=True)
    monkeypatch.setattr(
        "spotify_mcp.cli.load_app_config",
        lambda: SpotifyAppConfig("previous-client-id"),
    )
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("spotify_mcp.cli.SpotifyOAuth", lambda _settings: oauth)
    monkeypatch.setattr("spotify_mcp.cli.save_app_config", lambda config: saved.append(config))

    with pytest.raises(RuntimeError, match="authorization cancelled"):
        await _init(client_id, None)

    assert saved == []
    assert oauth.closed is True


@pytest.mark.parametrize(
    "client_id",
    ["", "short", "contains whitespace in it", "a" * 129, "abc!" * 8],
)
def test_init_client_id_validation_rejects_invalid_values(client_id: str) -> None:
    with pytest.raises(SpotifyConfigError, match="client ID"):
        _validate_client_id(client_id)


def test_init_noninteractive_mode_requires_explicit_client_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("spotify_mcp.cli.sys.stdin", io.StringIO())

    with pytest.raises(SystemExit) as exit_info:
        main(["init"])

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pass --client-id" in captured.err


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
