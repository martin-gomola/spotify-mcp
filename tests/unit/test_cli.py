from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spotify_mcp.adapters.spotify.oauth import REQUIRED_SCOPES, TokenSet, TokenStore
from spotify_mcp.cli import _connect, _doctor
from spotify_mcp.config import SpotifySettings
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
    TokenStore(settings.token_path).save(TokenSet("access", "refresh", 10_000.0, old_scopes))
    monkeypatch.setattr("spotify_mcp.cli.load_settings", lambda: settings)

    with pytest.raises(AuthenticationRequired, match="user-read-playback-position"):
        await _doctor()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
