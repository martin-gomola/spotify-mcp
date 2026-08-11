"""Command-line entry points kept separate from MCP protocol stdout."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from spotify_mcp.adapters.spotify.client import SpotifyClient
from spotify_mcp.adapters.spotify.oauth import SpotifyOAuth, TokenSet, TokenStore
from spotify_mcp.config import (
    SpotifyAppConfig,
    SpotifyConfigError,
    SpotifySettings,
    load_app_config,
    load_settings,
    save_app_config,
)
from spotify_mcp.domain.errors import AuthenticationRequired, SpotifyMcpError

_CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9]{16,128}\Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spotify-mcp")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="Run the MCP server")
    serve.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    serve.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    auth = subcommands.add_parser("auth", help="Connect a Spotify account with PKCE")
    auth.add_argument("--client-id")
    auth.add_argument("--redirect-uri")

    init = subcommands.add_parser(
        "init",
        help="Save app configuration, connect with PKCE, and verify Spotify access",
    )
    init.add_argument("--client-id")
    init.add_argument("--redirect-uri")

    subcommands.add_parser(
        "connect",
        help="Reuse saved Spotify authentication or open PKCE setup when needed",
    )
    subcommands.add_parser("doctor", help="Verify local configuration and Spotify access")
    return parser


def _loopback_host(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("host must be a literal loopback IP address") from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("host must be a loopback IP address")
    return value


def _validate_client_id(value: str) -> str:
    """Normalize a Spotify client ID while rejecting obvious copy/paste mistakes."""

    client_id = value.strip()
    if not _CLIENT_ID_PATTERN.fullmatch(client_id):
        raise SpotifyConfigError(
            "Spotify client ID looks invalid; expected 16 to 128 letters or numbers."
        )
    return client_id


def _prompt_client_id() -> str:
    if not sys.stdin.isatty():
        raise SpotifyConfigError(
            "Spotify client ID is required in non-interactive mode; pass --client-id."
        )
    print("Spotify Client ID: ", end="", file=sys.stderr, flush=True)
    value = sys.stdin.readline()
    if not value:
        raise SpotifyConfigError("Spotify client ID input was cancelled.")
    return value


async def _ensure_connection(settings: SpotifySettings) -> tuple[str, TokenSet | None]:
    oauth = SpotifyOAuth(settings)
    try:
        try:
            await oauth.ensure_access_token()
        except AuthenticationRequired:
            return "connected", await oauth.authorize()
        return "already_connected", None
    finally:
        await oauth.aclose()


async def _replace_connection(settings: SpotifySettings) -> TokenSet:
    """Authorize a grant that is known to match newly saved app configuration."""

    oauth = SpotifyOAuth(settings)
    try:
        return await oauth.authorize()
    finally:
        await oauth.aclose()


async def _verify_profile(settings: SpotifySettings) -> dict[str, Any]:
    oauth = SpotifyOAuth(settings)
    client = SpotifyClient(settings, oauth)
    try:
        profile = await client.request("GET", "me")
    finally:
        await client.aclose()
        await oauth.aclose()
    return profile if isinstance(profile, dict) else {}


async def _authenticate(client_id: str | None, redirect_uri: str | None) -> int:
    settings = load_settings(client_id=client_id, redirect_uri=redirect_uri)
    oauth = SpotifyOAuth(settings)
    try:
        tokens = await oauth.authorize()
    finally:
        await oauth.aclose()
    save_app_config(SpotifyAppConfig(settings.client_id, settings.redirect_uri))
    print(
        json.dumps(
            {
                "status": "connected",
                "scopes": tokens.scope.split() if tokens.scope else [],
                "token_path": str(settings.token_path),
            },
            indent=2,
        )
    )
    return 0


async def _init(
    client_id: str | None,
    redirect_uri: str | None,
    *,
    prompt_client_id: Callable[[], str] = _prompt_client_id,
) -> int:
    """Run guided first-time configuration, authentication, and verification."""

    resolved_client_id = _validate_client_id(
        client_id if client_id is not None else prompt_client_id()
    )
    try:
        previous_config = load_app_config()
    except SpotifyConfigError:
        previous_config = None
    settings = load_settings(client_id=resolved_client_id, redirect_uri=redirect_uri)
    requested_config = SpotifyAppConfig(settings.client_id, settings.redirect_uri)
    app_changed = previous_config != requested_config
    if app_changed:
        await _replace_connection(settings)
        connection = "connected"
    else:
        connection, _tokens = await _ensure_connection(settings)
    config_path = save_app_config(requested_config)
    profile = await _verify_profile(settings)
    print(
        json.dumps(
            {
                "status": "ready",
                "connection": connection,
                "config_path": str(config_path),
                "token_path": str(settings.token_path),
                "user_id": profile.get("id"),
                "display_name": profile.get("display_name"),
                "product": profile.get("product"),
                "next_steps": [
                    "Run `make codex-install` to install or refresh the Codex plugin.",
                    "Start a new Codex task so it loads the Spotify MCP server.",
                ],
            },
            indent=2,
        )
    )
    return 0


async def _connect() -> int:
    """Ensure local Spotify authentication exists, opening PKCE only when required."""

    settings = load_settings()
    connection, tokens = await _ensure_connection(settings)
    if connection == "already_connected":
        print(json.dumps({"status": connection}, indent=2))
        return 0

    save_app_config(SpotifyAppConfig(settings.client_id, settings.redirect_uri))
    assert tokens is not None
    print(
        json.dumps(
            {
                "status": "connected",
                "scopes": tokens.scope.split() if tokens.scope else [],
                "token_path": str(settings.token_path),
            },
            indent=2,
        )
    )
    return 0


async def _doctor() -> int:
    settings = load_settings()
    tokens = TokenStore(settings.token_path).load()
    if tokens is None:
        raise SpotifyConfigError("Spotify tokens are missing; run `spotify-mcp auth`.")
    profile = await _verify_profile(settings)
    print(
        json.dumps(
            {
                "status": "ready",
                "user_id": profile.get("id") if isinstance(profile, dict) else None,
                "display_name": profile.get("display_name") if isinstance(profile, dict) else None,
                "product": profile.get("product") if isinstance(profile, dict) else None,
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            from spotify_mcp.mcp_server.server import server

            options = {}
            if args.transport == "streamable-http":
                options = {"host": args.host, "port": args.port}
            server.run(transport=args.transport, **options)
            return
        if args.command == "auth":
            raise SystemExit(asyncio.run(_authenticate(args.client_id, args.redirect_uri)))
        if args.command == "init":
            raise SystemExit(asyncio.run(_init(args.client_id, args.redirect_uri)))
        if args.command == "connect":
            raise SystemExit(asyncio.run(_connect()))
        if args.command == "doctor":
            raise SystemExit(asyncio.run(_doctor()))
    except (SpotifyConfigError, SpotifyMcpError, httpx.HTTPError) as error:
        print(f"spotify-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    raise AssertionError(f"unhandled command: {args.command}")
