# MCP tools for Spotify in Codex

Use Spotify naturally from Codex: search music and podcasts, control playback, rediscover music
across Liked Songs, build verified playlists, and plan snapshot-safe DJ running orders. Results
include canonical Spotify links and can appear as compact cards in clients with MCP Apps support.

The MCP server runs locally. Spotify OAuth tokens stay outside both the plugin and repository, and
PKCE does not require a client secret.

This is an independent open-source project and is not affiliated with or endorsed by Spotify AB.
Spotify is a trademark of Spotify AB.

## Before enabling the plugin

1. Check out the repository at `~/dev/spotify-mcp`, or set `SPOTIFY_MCP_REPO` to its absolute path.
2. Copy `.env.example` to `.env` and set `SPOTIFY_CLIENT_ID`.
3. Create a Spotify Web API application with this exact redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Complete the one-time setup and install the plugin:

   ```bash
   make codex-install
   ```

The command connects Spotify when needed, verifies access, and installs or refreshes the plugin.
Start a new Codex task afterward. Codex starts and stops the stdio server itself, so no terminal
needs to remain open. For standalone development only, `make run` starts a foreground server that
stays attached to its terminal until `Ctrl-C`.

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
- “Find podcasts about design and show the best episodes as clickable cards.”
- “Rediscover music from my taste without calling it a Spotify recommendation.”
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

For personal text or audio uploads, use Spotify's official
[Save to Spotify](https://github.com/spotify/save-to-spotify) CLI as a separately installed
companion. It has its own authorization grant and token store; this plugin does not bundle it or
share credentials with it.
