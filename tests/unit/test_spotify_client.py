import asyncio
from pathlib import Path

import httpx
import pytest

from spotify_mcp.adapters.spotify.client import SpotifyClient
from spotify_mcp.config import SpotifySettings
from spotify_mcp.domain.errors import (
    AmbiguousWrite,
    AuthenticationRequired,
    SpotifyRequestError,
)


class StubOAuth:
    async def ensure_access_token(self) -> str:
        return "access"


def _settings(tmp_path: Path, *, max_attempts: int = 4) -> SpotifySettings:
    return SpotifySettings(
        client_id="client",
        token_path=tmp_path / "tokens.json",
        max_attempts=max_attempts,
    )


def _run_request(
    tmp_path: Path,
    handler: httpx.MockTransport,
    *,
    method: str = "GET",
    path: str = "me",
    params: dict[str, object] | None = None,
    json: object = None,
    max_attempts: int = 4,
) -> object:
    async def scenario() -> object:
        async with httpx.AsyncClient(transport=handler) as http_client:
            client = SpotifyClient(
                _settings(tmp_path, max_attempts=max_attempts),
                StubOAuth(),
                http_client=http_client,
            )
            return await client.request(method, path, params=params, json=json)

    return asyncio.run(scenario())


def test_request_sends_bearer_query_and_json(tmp_path: Path) -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(201, json={"id": "playlist"})

    result = _run_request(
        tmp_path,
        httpx.MockTransport(handler),
        method="POST",
        path="/me/playlists",
        params={"market": "SK"},
        json={"name": "Road trip"},
    )

    assert result == {"id": "playlist"}
    assert captured is not None
    assert captured.url.path == "/v1/me/playlists"
    assert captured.url.params["market"] == "SK"
    assert captured.headers["Authorization"] == "Bearer access"
    assert captured.read() == b'{"name":"Road trip"}'


def test_empty_success_returns_none(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    assert _run_request(tmp_path, transport, method="PUT", path="me/player/pause") is None


def test_rate_limit_honors_zero_retry_after_then_succeeds(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    assert _run_request(tmp_path, httpx.MockTransport(handler)) == {"ok": True}
    assert calls == 3


def test_rate_limited_write_is_not_retried(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")

    with pytest.raises(SpotifyRequestError, match=r"failed \(429\)"):
        _run_request(
            tmp_path,
            httpx.MockTransport(handler),
            method="PUT",
            path="me/player/play",
            json={"uris": ["spotify:track:1"]},
        )
    assert calls == 1


def test_transient_get_is_retried_but_write_is_not(tmp_path: Path) -> None:
    get_calls = 0

    def get_handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        get_calls += 1
        return (
            httpx.Response(503, text="unavailable")
            if get_calls == 1
            else httpx.Response(200, json={"ok": True})
        )

    assert _run_request(tmp_path, httpx.MockTransport(get_handler)) == {"ok": True}
    assert get_calls == 2

    write_calls = 0

    def write_handler(request: httpx.Request) -> httpx.Response:
        nonlocal write_calls
        write_calls += 1
        return httpx.Response(503, text="ambiguous upstream result")

    with pytest.raises(AmbiguousWrite, match="verify remote state"):
        _run_request(
            tmp_path,
            httpx.MockTransport(write_handler),
            method="POST",
            path="playlists/p1/items",
            json={"uris": ["spotify:track:1"]},
        )
    assert write_calls == 1


def test_network_failure_on_write_is_ambiguous_and_not_retried(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(AmbiguousWrite, match="verify remote state"):
        _run_request(
            tmp_path,
            httpx.MockTransport(handler),
            method="DELETE",
            path="playlists/p1/items",
        )
    assert calls == 1


def test_rejected_token_and_response_errors_are_typed(tmp_path: Path) -> None:
    with pytest.raises(AuthenticationRequired):
        _run_request(
            tmp_path,
            httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad"})),
        )

    with pytest.raises(SpotifyRequestError, match="Insufficient scope") as caught:
        _run_request(
            tmp_path,
            httpx.MockTransport(
                lambda request: httpx.Response(
                    403,
                    json={"error": {"status": 403, "message": "Insufficient scope"}},
                )
            ),
        )
    assert caught.value.status_code == 403


def test_success_with_invalid_json_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SpotifyRequestError, match="invalid JSON"):
        _run_request(
            tmp_path,
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text="not-json",
                    headers={"Content-Type": "application/json"},
                )
            ),
        )
