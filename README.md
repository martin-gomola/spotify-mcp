# Spotify MCP

A local-first Spotify MCP server written in Python. It gives MCP clients typed tools for music
discovery, Spotify Connect playback, Liked Songs, playlists, audio analysis, and snapshot-safe DJ
planning.

The server uses the official MCP Python SDK v2 and Spotify Authorization Code with PKCE. Spotify
tokens stay outside the repository, so the server never needs a client secret.

## What it does

- Searches tracks, albums, artists, playlists, shows, and podcast episodes.
- Reads recent listening, top tracks and artists, playback state, devices, and queue.
- Samples the full history of Liked Songs instead of considering only the newest page.
- Creates and edits playlists with exact Spotify IDs or URIs and explicit mutation states.
- Compares Spotify and ReccoBeats audio measurements while retaining provenance and conflicts.
- Creates deterministic DJ plans, checks Spotify snapshots before mutation, and records restore
  receipts locally.

## Quick start

Requirements:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- A Spotify Web API application and its client ID

```bash
git clone https://github.com/martin-gomola/spotify-mcp.git
cd spotify-mcp
cp .env.example .env
# Edit .env and set SPOTIFY_CLIENT_ID, then:
make run
```

Register `http://127.0.0.1:8888/callback` as the Spotify application's redirect URI. Use the
literal IP address, not `localhost`. See [Setup](docs/setup.md) for the complete Spotify and Codex
configuration. On the first `make run`, Spotify MCP opens the browser authorization flow; later
runs reuse the private saved token and start the stdio server directly.

The bundled Codex plugin starts the server directly through
[`plugins/spotify-mcp/.mcp.json`](plugins/spotify-mcp/.mcp.json). It expects the checkout at
`~/dev/spotify-mcp` unless `SPOTIFY_MCP_REPO` points somewhere else; run `make auth` once before
enabling it.

Install the public Git-backed marketplace and plugin with:

```bash
codex plugin marketplace add martin-gomola/spotify-mcp --ref main
codex plugin add spotify-mcp@spotify-mcp
```

Codex can then refresh the marketplace from `main` with
`codex plugin marketplace upgrade spotify-mcp`.

## Safety model

- OAuth tokens and local DJ state use OS-appropriate private data directories, not the checkout.
- The Spotify HTTP adapter retries safe reads, but never blindly retries a write whose outcome is
  uncertain.
- Library and playlist mutations return verification or ambiguity states instead of hiding a
  mismatch.
- DJ apply and restore default to `dry_run=true`, require snapshot evidence, and record mutation
  receipts.
- Liked Songs removal and playlist removal/unfollow operations are marked destructive in MCP tool
  metadata.

Playback commands still depend on Spotify Connect and an available device. Spotify's Development
Mode restrictions also apply; see [Setup](docs/setup.md#spotify-development-mode).

## Documentation

- [Setup and authentication](docs/setup.md)
- [Tool catalog](docs/tools.md)
- [Architecture](docs/architecture.md)
- [Framework decision](docs/framework-decision.md)
- [Development](docs/development.md)
- [Security policy](SECURITY.md)

## Development

```bash
make check
```

This runs Ruff formatting and lint checks, strict mypy, the test suite, repository-owned release
contract checks, and a source/wheel build. See [Development](docs/development.md) for targeted
commands and repository boundaries.

## License

[MIT](LICENSE)
