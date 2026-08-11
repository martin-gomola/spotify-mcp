"""Spotify Authorization Code with PKCE and private local token persistence."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import webbrowser
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from spotify_mcp.config import SpotifySettings
from spotify_mcp.domain.errors import AuthenticationRequired, SpotifyRequestError

AUTHORIZE_PATH: Final = "/authorize"
TOKEN_PATH: Final = "/api/token"
REFRESH_MARGIN_SECONDS: Final = 300
DEFAULT_TOKEN_LIFETIME_SECONDS: Final = 3600

REQUIRED_SCOPES: tuple[str, ...] = (
    "user-read-private",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
    "user-library-modify",
    "user-read-recently-played",
    "user-read-playback-position",
    "user-top-read",
)


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Renewable Spotify credentials stored on the local machine."""

    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str | None = None
    token_type: str = "Bearer"

    def is_expiring(self, *, now: float, margin_seconds: int = REFRESH_MARGIN_SECONDS) -> bool:
        return self.expires_at <= now + margin_seconds


class TokenStore:
    """Atomic JSON token store with owner-only permissions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> TokenSet | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AuthenticationRequired(f"Could not read Spotify credentials: {exc}") from exc

        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise TypeError("token document is not an object")
            return TokenSet(
                access_token=_required_string(payload, "access_token"),
                refresh_token=_optional_string(payload, "refresh_token"),
                expires_at=float(payload["expires_at"]),
                scope=_optional_string(payload, "scope"),
                token_type=_optional_string(payload, "token_type") or "Bearer",
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationRequired(
                f"Spotify credentials at {self.path} are invalid; authenticate again."
            ) from exc

    def save(self, tokens: TokenSet) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _best_effort_chmod(self.path.parent, 0o700)
        serialized = json.dumps(asdict(tokens), indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                text=True,
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            _best_effort_chmod(self.path, 0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise AuthenticationRequired(f"Could not save Spotify credentials: {exc}") from exc

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise AuthenticationRequired(f"Could not clear Spotify credentials: {exc}") from exc


@dataclass(frozen=True, slots=True)
class PkceRequest:
    authorize_url: str
    state: str
    code_verifier: str


@dataclass(frozen=True, slots=True)
class AuthorizationCallback:
    code: str | None = None
    error: str | None = None
    state: str | None = None


def create_pkce_request(
    settings: SpotifySettings,
    *,
    scopes: Sequence[str] = REQUIRED_SCOPES,
) -> PkceRequest:
    """Create a state-bound Spotify authorization URL using S256 PKCE."""

    verifier = secrets.token_urlsafe(72)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": settings.client_id,
            "response_type": "code",
            "redirect_uri": settings.redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "show_dialog": "true",
        }
    )
    return PkceRequest(
        authorize_url=f"{settings.accounts_base_url}{AUTHORIZE_PATH}?{query}",
        state=state,
        code_verifier=verifier,
    )


def parse_authorization_callback(callback_url: str, *, expected_state: str) -> str:
    """Validate OAuth state and return the authorization code."""

    parsed = urlsplit(callback_url)
    query = parse_qs(parsed.query)
    state = _single_query_value(query, "state")
    if state != expected_state:
        raise AuthenticationRequired(
            "Spotify callback state did not match; start authorization again."
        )
    denial = _single_query_value(query, "error")
    if denial:
        raise AuthenticationRequired(f"Spotify authorization was denied: {denial}")
    code = _single_query_value(query, "code")
    if not code:
        raise AuthenticationRequired("Spotify callback did not include an authorization code.")
    return code


class SpotifyOAuth:
    """Owns PKCE exchange, token refresh, and loopback authorization."""

    def __init__(
        self,
        settings: SpotifySettings,
        *,
        token_store: TokenStore | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.token_store = token_store or TokenStore(settings.token_path)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=_timeout(settings))
        self._clock = clock
        self._refresh_lock = asyncio.Lock()

    async def ensure_access_token(self) -> str:
        """Return a usable token, coalescing concurrent refreshes."""

        tokens = self.token_store.load()
        if tokens is None:
            raise AuthenticationRequired("Spotify is not authenticated; run `spotify-mcp auth`.")
        _require_scopes(tokens)
        if not tokens.is_expiring(now=self._clock()):
            return tokens.access_token

        async with self._refresh_lock:
            current = self.token_store.load()
            if current is None:
                raise AuthenticationRequired(
                    "Spotify is not authenticated; run `spotify-mcp auth`."
                )
            _require_scopes(current)
            if not current.is_expiring(now=self._clock()):
                return current.access_token
            refreshed = await self.refresh(current)
            _require_scopes(refreshed)
            self.token_store.save(refreshed)
            return refreshed.access_token

    async def exchange_code(self, code: str, *, code_verifier: str) -> TokenSet:
        payload = await self._request_token(
            {
                "client_id": self.settings.client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        tokens = self._tokens_from_payload(payload)
        if tokens.scope is None:
            tokens = replace(tokens, scope=" ".join(REQUIRED_SCOPES))
        _require_scopes(tokens)
        self.token_store.save(tokens)
        return tokens

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise AuthenticationRequired("Spotify session cannot be refreshed; authenticate again.")
        payload = await self._request_token(
            {
                "client_id": self.settings.client_id,
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
            }
        )
        refreshed = self._tokens_from_payload(payload)
        if refreshed.refresh_token is None:
            refreshed = replace(refreshed, refresh_token=tokens.refresh_token)
        if refreshed.scope is None:
            refreshed = replace(refreshed, scope=tokens.scope)
        return refreshed

    async def authorize(
        self,
        *,
        open_browser: Callable[[str], Any] = webbrowser.open,
        callback_timeout_seconds: float = 180.0,
    ) -> TokenSet:
        """Run one local loopback PKCE flow and persist the resulting token."""

        request = create_pkce_request(self.settings)
        callback_task = asyncio.create_task(
            asyncio.to_thread(
                _wait_for_loopback_callback,
                self.settings.redirect_uri,
                callback_timeout_seconds,
            )
        )
        try:
            open_browser(request.authorize_url)
            callback_url = await callback_task
        except BaseException:
            callback_task.cancel()
            raise
        code = parse_authorization_callback(callback_url, expected_state=request.state)
        return await self.exchange_code(code, code_verifier=request.code_verifier)

    async def aclose(self) -> None:
        """Close the internally owned connection pool."""

        if self._owns_http_client:
            await self._http_client.aclose()

    async def _request_token(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http_client.post(
                f"{self.settings.accounts_base_url}{TOKEN_PATH}",
                data=form,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise SpotifyRequestError(f"Spotify token request failed: {exc}") from exc

        if response.is_error:
            error = _response_error(response)
            if response.status_code in {400, 401} and error.startswith("invalid_grant"):
                self.token_store.clear()
                raise AuthenticationRequired(
                    "Spotify rejected the saved grant; authenticate again."
                )
            raise SpotifyRequestError(
                f"Spotify token request failed ({response.status_code}): {error}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpotifyRequestError("Spotify token response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise SpotifyRequestError("Spotify token response was not a JSON object.")
        return payload

    def _tokens_from_payload(self, payload: dict[str, Any]) -> TokenSet:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SpotifyRequestError("Spotify token response omitted the access token.")
        expires_in = payload.get("expires_in", DEFAULT_TOKEN_LIFETIME_SECONDS)
        if not isinstance(expires_in, int | float) or expires_in <= 0:
            raise SpotifyRequestError("Spotify token response contained an invalid lifetime.")
        return TokenSet(
            access_token=access_token,
            refresh_token=_optional_string(payload, "refresh_token"),
            expires_at=self._clock() + float(expires_in),
            scope=_optional_string(payload, "scope"),
            token_type=_optional_string(payload, "token_type") or "Bearer",
        )


def _timeout(settings: SpotifySettings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )


def _require_scopes(tokens: TokenSet) -> None:
    granted = set(tokens.scope.split()) if tokens.scope else set()
    missing = sorted(set(REQUIRED_SCOPES) - granted)
    if missing:
        raise AuthenticationRequired(
            "Spotify authorization is missing required scopes: "
            f"{', '.join(missing)}. Run `spotify-mcp connect` to authorize again."
        )


def _wait_for_loopback_callback(redirect_uri: str, timeout_seconds: float) -> str:
    parsed = urlsplit(redirect_uri)
    callback_path = parsed.path or "/"
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested = urlsplit(self.path)
            if requested.path != callback_path:
                self.send_error(404)
                return
            result["url"] = f"{redirect_uri.split('?', maxsplit=1)[0]}?{requested.query}"
            body = b"Spotify authorization completed. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", parsed.port or 8888), CallbackHandler)
    server.timeout = timeout_seconds
    try:
        server.handle_request()
    finally:
        server.server_close()
    try:
        return result["url"]
    except KeyError as exc:
        raise AuthenticationRequired("Timed out waiting for Spotify authorization.") from exc


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} is not a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} is not a string")
    return value


def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300] or "no response body"
    if isinstance(payload, dict):
        error = payload.get("error")
        description = payload.get("error_description")
        if isinstance(error, str):
            return f"{error}: {description}" if isinstance(description, str) else error
    return response.text[:300] or "no response body"


def _best_effort_chmod(path: Path, mode: int) -> None:
    # Windows and some mounted filesystems do not provide POSIX mode bits.
    with suppress(OSError):
        path.chmod(mode)
