# Spotify MCP for Codex

Use Spotify naturally from Codex: search and control playback, rediscover music across Liked Songs,
build verified playlists, audit saved recordings, and plan snapshot-safe DJ running orders.

The MCP server runs locally. Spotify OAuth tokens stay outside both the plugin and repository, and
PKCE does not require a client secret.

## Before enabling the plugin

1. Check out the repository at `~/dev/spotify-mcp`, or set `SPOTIFY_MCP_REPO` to its absolute path.
2. Copy `.env.example` to `.env` and set `SPOTIFY_CLIENT_ID`.
3. Create a Spotify Web API application with this exact redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Authenticate and verify access:

   ```bash
   make auth
   make doctor
   ```

For standalone use, `make run` performs first-time authentication when needed and then starts the
stdio server.

See the complete [setup guide](../../docs/setup.md) for Spotify Development Mode and troubleshooting.

## How the plugin starts the server

The plugin's [`.mcp.json`](.mcp.json) starts `uv run spotify-mcp serve` over stdio. It contains no
Spotify credentials. The repository path defaults to `~/dev/spotify-mcp` and can be overridden
before Codex starts:

```bash
export SPOTIFY_MCP_REPO=/absolute/path/to/spotify-mcp
```

## Example requests

- “Build a road-trip playlist from across my Liked Songs history.”
- “Audit my Liked Songs and show possible alternate recordings without changing anything.”
- “What is playing, and what is next in my queue?”
- “Plan a DJ running order that peaks late, but do not apply it.”
- “Audit this whole playlist, then preview a BPM and energy sort.”

The plugin includes dedicated skills for initial setup, playlist building, and Liked Songs audits.

## Safety boundaries

- Playlist and Liked Songs tools work with exact Spotify IDs or URIs.
- Ambiguous writes must be followed by a fresh read, never an automatic repeat.
- DJ apply and restore default to dry-run and use Spotify snapshot checks plus local receipts.
- Compatibility BPM sorting also defaults to dry-run and uses the same verified mutation engine.
- Liked Songs removal has no automatic undo.
- Playback needs an available Spotify Connect device.
- Spotify Development Mode currently requires the app owner to have Premium and supports up to five
  authenticated users.

See the [tool catalog](../../docs/tools.md) for exact capabilities and result states.
