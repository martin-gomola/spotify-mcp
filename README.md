<div align="center">

# Spotify for Codex

**Play music, rediscover old favourites, build playlists, and shape DJ sets—just by asking.**

[Get started](#get-started) · [See what you can ask](#what-can-i-ask) · [Setup guide](docs/setup.md)

</div>

> [!NOTE]
> This is an independent open-source project, not an official Spotify product. Use it in line with
> the [Spotify Developer Policy](https://developer.spotify.com/policy).

## What can I ask?

> Play something I’ll like.

> Build me a road-trip playlist that rediscovers music from across my Liked Songs history.

You can also search for music and podcasts, control playback, safely review your Liked Songs, or
turn an existing playlist into a DJ running order.

## Why it feels different

- **It knows your music:** explore your full Liked Songs history instead of only recent favourites.
- **It is careful with changes:** bundled workflows preserve exact Spotify identities, stop on
  uncertain outcomes, and start DJ reorders as previews with recovery receipts.
- **It goes beyond search:** shape playlists around a mood, activity, journey, or musical arc—and
  open results directly in Spotify.

## Get started

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and a Spotify Web API application. Spotify
uses your app’s Client ID; this project does not need its Client Secret.

### 1. Download the project

```bash
git clone https://github.com/martin-gomola/spotify-mcp.git
cd spotify-mcp
cp .env.example .env
```

### 2. Add your Spotify Client ID

Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), add
`http://127.0.0.1:8888/callback` as its Redirect URI, then put the Client ID in `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id
```

The [step-by-step setup guide](docs/setup.md) explains each dashboard step and Spotify Development
Mode restriction.

### 3. Connect Codex

```bash
make codex-install
```

Approve the Spotify page that opens, then start a new Codex task. Codex starts the local Spotify
server when needed; you do not leave another terminal running.

## Safety by default

- Spotify tokens stay outside the repository in a private local file.
- Audio and DJ fallback may send exact Spotify track IDs to ReccoBeats when Spotify’s own audio
  data is unavailable or incomplete.
- A write with an uncertain outcome is never repeated blindly.
- Low-level removal tools act immediately and have no automatic undo; the bundled library-audit
  workflow previews exact recording IDs before calling them.
- The bundled playlist workflow re-reads its intended result; low-level tools report the evidence
  Spotify returned rather than claiming more certainty.
- DJ apply and restore default to dry runs and verify the live playlist before changing it.

<details>
<summary><strong>Developing or connecting another MCP client?</strong></summary>

Complete authentication once:

```bash
make setup
```

Then configure your MCP client to launch `uv run spotify-mcp serve` with this repository as its
working directory. The exact configuration belongs to that client; this repository currently
provides guided installation only for Codex. For local development and verification, follow the
[development guide](docs/development.md).

</details>

## Learn more

- [Setup and troubleshooting](docs/setup.md)
- [Available Spotify tools](docs/tools.md)
- [Architecture and data flow](docs/architecture.md)
- [Development and verification](docs/development.md)
- [Security policy](SECURITY.md)

The source is available under the [MIT License](LICENSE). Spotify is a trademark of Spotify AB;
this project is independently developed and is not affiliated with, sponsored by, or endorsed by
Spotify AB.
