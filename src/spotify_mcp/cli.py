"""Command-line entry points kept separate from MCP protocol stdout."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
from collections.abc import Sequence

import httpx

from spotify_mcp.adapters.spotify.client import SpotifyClient
from spotify_mcp.adapters.spotify.oauth import SpotifyOAuth, TokenStore
from spotify_mcp.config import (
    SpotifyAppConfig,
    SpotifyConfigError,
    load_settings,
    save_app_config,
)
from spotify_mcp.domain.errors import AuthenticationRequired, SpotifyMcpError


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


async def _connect() -> int:
    """Ensure local Spotify authentication exists, opening PKCE only when required."""

    settings = load_settings()
    oauth = SpotifyOAuth(settings)
    try:
        try:
            await oauth.ensure_access_token()
        except AuthenticationRequired:
            tokens = await oauth.authorize()
        else:
            print(json.dumps({"status": "already_connected"}, indent=2))
            return 0
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


async def _doctor() -> int:
    settings = load_settings()
    tokens = TokenStore(settings.token_path).load()
    if tokens is None:
        raise SpotifyConfigError("Spotify tokens are missing; run `spotify-mcp auth`.")
    oauth = SpotifyOAuth(settings)
    client = SpotifyClient(settings, oauth)
    try:
        profile = await client.request("GET", "me")
    finally:
        await client.aclose()
        await oauth.aclose()
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
        if args.command == "connect":
            raise SystemExit(asyncio.run(_connect()))
        if args.command == "doctor":
            raise SystemExit(asyncio.run(_doctor()))
    except (SpotifyConfigError, SpotifyMcpError, httpx.HTTPError) as error:
        print(f"spotify-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    raise AssertionError(f"unhandled command: {args.command}")
