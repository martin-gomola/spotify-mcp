import asyncio
import base64
import hashlib
import json
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from spotify_mcp.adapters.spotify.oauth import (
    REQUIRED_SCOPES,
    SpotifyOAuth,
    TokenSet,
    TokenStore,
    create_pkce_request,
    parse_authorization_callback,
    spotify_app_fingerprint,
)
from spotify_mcp.config import SpotifySettings
from spotify_mcp.domain.errors import AuthenticationRequired


def _settings(tmp_path: Path) -> SpotifySettings:
    return SpotifySettings(client_id="client", token_path=tmp_path / "tokens.json")


def test_pkce_authorization_url_has_s256_challenge_and_required_scopes(tmp_path: Path) -> None:
    request = create_pkce_request(_settings(tmp_path))
    parsed = urlsplit(request.authorize_url)
    query = parse_qs(parsed.query)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(request.code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    assert parsed.hostname == "accounts.spotify.com"
    assert query["client_id"] == ["client"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8888/callback"]
    assert query["state"] == [request.state]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [challenge]
    assert set(query["scope"][0].split()) == set(REQUIRED_SCOPES)
    assert "user-read-playback-position" in REQUIRED_SCOPES


def test_callback_requires_matching_state_and_code() -> None:
    assert (
        parse_authorization_callback(
            "http://127.0.0.1:8888/callback?code=abc&state=expected",
            expected_state="expected",
        )
        == "abc"
    )
    with pytest.raises(AuthenticationRequired, match="state did not match"):
        parse_authorization_callback(
            "http://127.0.0.1:8888/callback?code=abc&state=attacker",
            expected_state="expected",
        )
    with pytest.raises(AuthenticationRequired, match="denied"):
        parse_authorization_callback(
            "http://127.0.0.1:8888/callback?error=access_denied&state=expected",
            expected_state="expected",
        )


def test_token_store_is_atomic_and_owner_only(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "nested" / "tokens.json")
    tokens = TokenSet("access", "refresh", 1234.0, "scope")

    store.save(tokens)

    assert store.load() == tokens
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert not list(store.path.parent.glob(f".{store.path.name}.*"))


def test_invalid_token_document_requires_authentication(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"access_token": "only"}), encoding="utf-8")

    with pytest.raises(AuthenticationRequired, match="invalid"):
        TokenStore(path).load()


def test_exchange_uses_public_client_pkce_without_client_secret(tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(parse_qs(request.content.decode(), keep_blank_values=True))
        return httpx.Response(
            200,
            json={"access_token": "access", "refresh_token": "refresh", "expires_in": 60},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            oauth = SpotifyOAuth(_settings(tmp_path), http_client=client, clock=lambda: 100.0)
            tokens = await oauth.exchange_code("code", code_verifier="verifier")
            assert tokens.expires_at == 160.0
            assert set((tokens.scope or "").split()) == set(REQUIRED_SCOPES)
            assert tokens.app_fingerprint == spotify_app_fingerprint(_settings(tmp_path))

    asyncio.run(scenario())
    assert captured["client_id"] == ["client"]
    assert captured["code_verifier"] == ["verifier"]
    assert "client_secret" not in captured


def test_concurrent_expired_token_reads_share_one_refresh(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = TokenStore(settings.token_path)
    granted_scopes = " ".join(REQUIRED_SCOPES)
    fingerprint = spotify_app_fingerprint(settings)
    store.save(TokenSet("old", "refresh", 0.0, granted_scopes, app_fingerprint=fingerprint))
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            oauth = SpotifyOAuth(
                settings, token_store=store, http_client=client, clock=lambda: 100.0
            )
            refreshed = await asyncio.gather(
                oauth.ensure_access_token(),
                oauth.ensure_access_token(),
                oauth.ensure_access_token(),
            )
            assert list(refreshed) == ["new", "new", "new"]

    asyncio.run(scenario())
    assert calls == 1
    assert store.load() == TokenSet(
        "new", "refresh", 3700.0, granted_scopes, app_fingerprint=fingerprint
    )


def test_existing_token_missing_new_scope_requires_authorization_upgrade(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = TokenStore(settings.token_path)
    old_scopes = " ".join(
        scope for scope in REQUIRED_SCOPES if scope != "user-read-playback-position"
    )
    store.save(
        TokenSet(
            "access",
            "refresh",
            10_000.0,
            old_scopes,
            app_fingerprint=spotify_app_fingerprint(settings),
        )
    )

    async def scenario() -> None:
        oauth = SpotifyOAuth(settings, token_store=store, clock=lambda: 100.0)
        try:
            with pytest.raises(
                AuthenticationRequired,
                match=r"user-read-playback-position.*spotify-mcp connect",
            ):
                await oauth.ensure_access_token()
        finally:
            await oauth.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("fingerprint", [None, "different-app"])
def test_saved_token_must_match_current_app_before_use(
    tmp_path: Path, fingerprint: str | None
) -> None:
    settings = _settings(tmp_path)
    store = TokenStore(settings.token_path)
    store.save(
        TokenSet(
            "access",
            "refresh",
            10_000.0,
            " ".join(REQUIRED_SCOPES),
            app_fingerprint=fingerprint,
        )
    )

    async def scenario() -> None:
        oauth = SpotifyOAuth(settings, token_store=store, clock=lambda: 100.0)
        try:
            with pytest.raises(AuthenticationRequired, match=r"app.*spotify-mcp connect"):
                await oauth.ensure_access_token()
        finally:
            await oauth.aclose()

    asyncio.run(scenario())


def test_invalid_grant_clears_saved_token(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = TokenStore(settings.token_path)
    tokens = TokenSet(
        "old",
        "dead",
        0.0,
        app_fingerprint=spotify_app_fingerprint(settings),
    )
    store.save(tokens)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            oauth = SpotifyOAuth(settings, token_store=store, http_client=client)
            with pytest.raises(AuthenticationRequired, match="authenticate again"):
                await oauth.refresh(tokens)

    asyncio.run(scenario())
    assert store.load() is None
