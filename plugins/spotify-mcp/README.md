# MCP tools for Spotify in Codex

Use Spotify from Codex: search music and podcasts, control playback, rediscover music
across Liked Songs, build verified playlists, and plan snapshot-safe DJ running orders. Results
include canonical Spotify links and can appear as compact cards inside Codex.

![Codex creating and verifying a Spotify playlist, then presenting it as a playable result card with device selection](../../docs/assets/codex-playlist-result-card.png)

The MCP server runs locally. Spotify OAuth tokens stay outside both the plugin and repository, and
PKCE does not require a client secret.

This is an independent open-source project and is not affiliated with or endorsed by Spotify AB.
Spotify is a trademark of Spotify AB.

## Before enabling the plugin

1. Check out the repository at `~/dev/spotify-mcp`, or set `SPOTIFY_MCP_REPO` to its absolute path.
2. Create a Spotify Web API application with this exact redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

3. Create the local environment file and add the Client ID from your Spotify application:

   ```bash
   cp .env.example .env
   ```

   ```dotenv
   SPOTIFY_CLIENT_ID=your_client_id
   ```

4. Connect Spotify, verify the account, and install or refresh the plugin:

   ```bash
   make codex-install
   ```

The install command opens Spotify authorization when needed, verifies access, and installs or
refreshes the plugin.
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

## Try a bundled workflow

Ask in plain language. Codex selects the matching skill and tools.

### Spotify Library Doctor

```text
Audit all my Liked Songs for exact duplicates, alternate recordings, live versions, remasters,
and unavailable tracks. Show the exact keep/remove pairs and explain the evidence, but do not
remove anything.
```

Library Doctor scans each page of your library. It separates alternate recordings from distinct
versions and waits for your approval before removing an exact recording.

### Taste-aware playlist builder

```text
Build me a three-hour road-trip playlist from across my full Liked Songs history. Keep the mix
varied, shape it into chapters with intentional energy resets, and verify the final playlist track
by track.
```

The playlist skill can preserve existing tracks while it adds music. It can also propose a new
order and wait for your approval before writing it to Spotify.

### Snapshot-safe DJ planner

```text
Audit my House Party playlist for duplicates, missing tempo data, and awkward transitions. Plan a
DJ order that warms up, builds, peaks late, and closes with at least three tracks between
the same artist. Create a preview. Do not apply it yet.
```

The DJ workflow checks tempo and energy coverage, previews the exact new order, and refuses to
change a playlist that has become stale. If you apply the plan, it keeps a receipt for restoration.

You can also ask “What is playing, and what is next in my queue?” or “Find podcasts about design
and show the best episodes as clickable cards.” A setup skill handles authentication and local
server problems.

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
