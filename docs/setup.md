# Setup

Spotify MCP runs locally and uses Spotify Authorization Code with PKCE. You need a Spotify client
ID, but you do not need or provide a client secret.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- A Spotify account
- A Spotify Web API application owned by the account that will run the server

Spotify Connect playback tools also need Spotify open on an available device.

## Create the Spotify application

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an
   application.
2. Enable the Web API for the application.
3. Add this exact redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Save the application and copy its client ID.

Spotify requires an explicit loopback IP address for an HTTP callback; `localhost` is not allowed.
The redirect URI passed to Spotify MCP must match the registered value. See Spotify's
[redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).

Do not copy the client secret into this repository, an environment variable, or an MCP
configuration. PKCE does not use it.

### Spotify Development Mode

New Spotify applications start in Development Mode. Spotify currently requires the app owner to
have Premium, allows up to five authenticated users, and requires other users to be allow-listed.
See Spotify's [quota modes documentation](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
for the current restrictions.

## Guided setup

From the repository root, run:

```bash
uv run spotify-mcp init
```

The command prompts for the client ID, saves the public app configuration outside the repository,
opens Spotify's PKCE approval page only when the saved grant cannot be reused, and verifies the
connected account. A healthy result contains `"status": "ready"` plus concise plugin next steps.

For scripts or other non-interactive environments, pass the client ID explicitly:

```bash
uv run spotify-mcp init --client-id your_spotify_client_id
```

Interactive prompting is intentionally disabled when stdin is not a terminal, so unattended setup
fails clearly instead of hanging. You can alternatively create the ignored local `.env` file:

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

The file is ignored by Git. A Spotify client ID is a public application identifier, but keeping
machine-specific configuration in `.env` can be useful for development and avoids committing it by
accident. Never add a client secret or OAuth token to `.env`.

## Reconnect and verify

After guided setup, reconnect when necessary and verify live Spotify access without leaving a
server running:

```bash
make setup
```

When authentication is missing, Spotify MCP opens the Spotify approval page and listens temporarily
on `127.0.0.1:8888` for the callback. After approval it saves renewable tokens in an OS-appropriate
private configuration file. Later `init` or `make setup` calls reuse or refresh that grant, verify
the account, and return to the shell without opening the browser.

Use `make auth` when you explicitly want to replace or reconnect the saved grant. Use `make doctor`
for a standalone live-access check.

To use a different loopback port, register the same URI in Spotify first and change the value in
`.env`:

```bash
SPOTIFY_REDIRECT_URI=http://127.0.0.1:9876/callback
```

The implementation accepts only a literal `http://127.0.0.1:PORT/...` redirect with no credentials,
query, or fragment.

Verify the saved configuration and live Spotify access:

```bash
make doctor
```

A healthy result contains `"status": "ready"` and the connected Spotify profile. If the saved
grant expires or is revoked, run the `auth` command again.

## Run the MCP server

The default and recommended local transport is stdio. Use this command only for standalone clients
or manual development:

```bash
make run
```

The command intentionally stays in the foreground because that terminal owns the stdio connection.
Stop it with `Ctrl-C`. Do not run it separately for Codex—the plugin starts and stops its own server
process. Do not wrap it with anything that writes ordinary output to stdout; stdout carries the MCP
protocol and diagnostics belong on stderr.

The CLI also exposes a loopback Streamable HTTP transport for local development:

```bash
uv run spotify-mcp serve --transport streamable-http --host 127.0.0.1 --port 8765
```

This transport does not add MCP authentication. Keep it bound to a trusted loopback interface.

## Use the Codex plugin

The plugin manifest at `plugins/spotify-mcp/.codex-plugin/plugin.json` references
`plugins/spotify-mcp/.mcp.json`. Its MCP entry starts the stdio server with:

```bash
uv run spotify-mcp serve
```

The entry resolves the repository in this order:

1. `SPOTIFY_MCP_REPO`, when set.
2. `~/dev/spotify-mcp`.

If the checkout is elsewhere, set the absolute path before starting Codex:

```bash
export SPOTIFY_MCP_REPO=/absolute/path/to/spotify-mcp
```

From the configured checkout, one command completes Spotify setup, installs or refreshes the public
marketplace, and enables the plugin:

```bash
make codex-install
```

The target is safe to repeat: it reuses valid Spotify authentication, upgrades an existing
marketplace, and installs the plugin only when missing. Start a new Codex task afterward so Codex
loads the MCP server and bundled skills. No Spotify terminal needs to remain open.

The equivalent manual commands are:

```bash
codex plugin marketplace add martin-gomola/spotify-mcp --ref main
codex plugin add spotify-mcp@spotify-mcp
```

Refresh future releases, verify the loaded version, and then start a new Codex task:

```bash
make codex-update
```

The update command also runs the connection check. If a release needs a new Spotify permission,
it opens the PKCE authorization flow once so an older token cannot silently miss new tools.

Remove the plugin and its marketplace when no longer needed:

```bash
codex plugin remove spotify-mcp@spotify-mcp
codex plugin marketplace remove spotify-mcp
```

The plugin contributes the MCP server plus setup, playlist-building, and library-audit skills.

The bundled `.mcp.json` deliberately contains no Spotify credentials. It only locates the checkout
and starts the local process.

## Configuration precedence

Spotify MCP resolves application settings in this order:

1. Explicit CLI options for the current command.
2. Exported `SPOTIFY_CLIENT_ID` and `SPOTIFY_REDIRECT_URI` environment variables.
3. Values in the checkout's ignored `.env` file.
4. The non-secret configuration saved by `spotify-mcp auth`.

Advanced runtime settings also use the `SPOTIFY_` prefix, including `SPOTIFY_TOKEN_PATH`,
`SPOTIFY_API_BASE_URL`, and bounded timeout or retry settings. Most users should keep their
defaults.

## Troubleshooting

### Client ID is missing

Set `SPOTIFY_CLIENT_ID` in `.env`, then run `make setup` or `make auth`. A client secret is neither
required nor accepted.

### Spotify rejects the redirect URI

Confirm the dashboard and command both use the same literal `127.0.0.1` URI and port. Do not use
`localhost`.

### Authentication succeeds but API calls return 403

Check Spotify Development Mode ownership, Premium, and user allow-list restrictions. A user may be
able to approve the application but still receive 403 responses when not allowed to use it.

### Playback reports no device

Open Spotify on a phone, desktop, speaker, or other Spotify Connect device, then call
`spotify_devices` again. Some playback operations require Premium under Spotify's own API rules.

### A write is ambiguous

Do not repeat it automatically. Read the relevant library or playlist state first and decide from
the observed Spotify state. See [Tool safety and result states](tools.md#safety-and-result-states).
