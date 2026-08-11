"""MCP-independent async Spotify Web API transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final, Protocol

import httpx

from spotify_mcp.config import SpotifySettings
from spotify_mcp.domain.errors import (
    AmbiguousWrite,
    AuthenticationRequired,
    SpotifyRequestError,
)

TRANSIENT_GET_STATUSES: Final = frozenset({500, 502, 503, 504})
WRITE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BASE_BACKOFF_SECONDS: Final = 0.5


class AccessTokenProvider(Protocol):
    async def ensure_access_token(self) -> str: ...


class SpotifyClient:
    """Typed HTTP adapter implementing the application Spotify gateway."""

    def __init__(
        self,
        settings: SpotifySettings,
        oauth: AccessTokenProvider,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.oauth = oauth
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=_timeout(settings))

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        normalized_method = method.upper()
        url = f"{self.settings.api_base_url}/{path.lstrip('/')}"
        for attempt in range(1, self.settings.max_attempts + 1):
            access_token = await self.oauth.ensure_access_token()
            try:
                response = await self._send(
                    normalized_method,
                    url,
                    access_token=access_token,
                    params=params,
                    json_body=json,
                )
            except httpx.HTTPError as exc:
                if normalized_method in WRITE_METHODS:
                    raise AmbiguousWrite(
                        f"Spotify {normalized_method} did not return a response; "
                        "verify remote state."
                    ) from exc
                if attempt < self.settings.max_attempts:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue
                raise SpotifyRequestError(f"Spotify request failed: {exc}") from exc

            if response.is_success:
                return _read_success_body(response)

            if response.status_code == 401:
                raise AuthenticationRequired(
                    "Spotify rejected the access token; run `spotify-mcp auth` again."
                )

            retry_delay = _retry_delay(
                response,
                method=normalized_method,
                attempt=attempt,
                max_attempts=self.settings.max_attempts,
                max_retry_after_seconds=self.settings.max_retry_after_seconds,
            )
            if retry_delay is not None:
                await asyncio.sleep(retry_delay)
                continue

            if normalized_method in WRITE_METHODS and response.status_code >= 500:
                raise AmbiguousWrite(
                    f"Spotify {normalized_method} returned {response.status_code}; "
                    "verify remote state before retrying."
                )

            raise SpotifyRequestError(
                _request_error_message(normalized_method, path, response),
                status_code=response.status_code,
            )

        raise AssertionError("retry loop exhausted without returning or raising")

    async def aclose(self) -> None:
        """Close the internally owned connection pool, if any."""

        if self._owns_http_client:
            await self._http_client.aclose()

    async def _send(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        params: Mapping[str, Any] | None,
        json_body: Any,
    ) -> httpx.Response:
        return await self._http_client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )


def _timeout(settings: SpotifySettings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )


def _read_success_body(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise SpotifyRequestError(
            "Spotify returned invalid JSON for a successful request."
        ) from exc


def _retry_delay(
    response: httpx.Response,
    *,
    method: str,
    attempt: int,
    max_attempts: int,
    max_retry_after_seconds: float,
) -> float | None:
    if attempt >= max_attempts:
        return None
    if method == "GET" and response.status_code == 429:
        advised = _parse_retry_after(response.headers.get("Retry-After"))
        delay = advised if advised is not None else _backoff_seconds(attempt)
        return delay if delay <= max_retry_after_seconds else None
    if method == "GET" and response.status_code in TRANSIENT_GET_STATUSES:
        return _backoff_seconds(attempt)
    return None


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        now = datetime.now(retry_at.tzinfo)
        return max(0.0, (retry_at - now).total_seconds())


def _backoff_seconds(attempt: int) -> float:
    return BASE_BACKOFF_SECONDS * float(2 ** (attempt - 1))


def _request_error_message(method: str, path: str, response: httpx.Response) -> str:
    detail = _response_error(response)
    return f"Spotify API {method} {path.lstrip('/')} failed ({response.status_code}): {detail}"


def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300] or "no response body"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(error, str):
            description = payload.get("error_description")
            return f"{error}: {description}" if isinstance(description, str) else error
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return response.text[:300] or "no response body"
