<div align="center">

# 🎵 Spotify for Codex

**Ask Codex to play music, find old favourites, build playlists, or plan a DJ set.**

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
[![MIT License](https://img.shields.io/badge/License-MIT-2F855A.svg)](LICENSE)
![Spotify MCP](https://img.shields.io/badge/Spotify-MCP-1DB954?logo=spotify&logoColor=white)

[Get started](#get-started) · [See what you can ask](#what-can-i-ask) · [Setup guide](docs/setup.md)

</div>

> [!NOTE]
> This open-source project has no connection to Spotify AB. Use it in line with the
> [Spotify Developer Policy](https://developer.spotify.com/policy).

## 💬 What can I ask?

> Play something I’ll like.

> Build me a road-trip playlist that rediscovers music from across my Liked Songs history.

You can also search for music and podcasts, control playback, review your Liked Songs, or turn a
playlist into a DJ running order.

## ✨ What it can do

- 🎧 **Find music from your library:** search your full Liked Songs history, including tracks you
  saved years ago.
- 🧩 **Build with safeguards:** bundled workflows preserve Spotify track identities. They stop
  after an uncertain write and preview DJ reorders before they change a playlist.

You can shape a playlist around a mood or journey, then open the result in Spotify.

## 🚀 Get started

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and a Spotify Web API app. The server uses
your app’s Client ID. It does not need the Client Secret.

### 📦 1. Download the project

```bash
git clone https://github.com/martin-gomola/spotify-mcp.git
cd spotify-mcp
cp .env.example .env
```

### 🔑 2. Add your Spotify Client ID

Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), add
`http://127.0.0.1:8888/callback` as its Redirect URI, then put the Client ID in `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id
```

The [setup guide](docs/setup.md) covers the dashboard steps and Spotify Development Mode limits.

### 🔌 3. Connect Codex

```bash
make codex-install
```

Approve the Spotify page that opens, then start a new Codex task. Codex starts the local server when
you use it, so you can close the setup terminal.

## 🛡️ Safety by default

- 🔐 Spotify tokens stay outside the repository in a private local file.
- 🎚️ Audio analysis and the DJ fallback may send exact Spotify track IDs to ReccoBeats when
  Spotify lacks the required audio data.
- ⛔ The server stops after a write with an uncertain outcome. It does not retry that write.
- 🗑️ Low-level removal tools apply changes at once and offer no undo. The library audit workflow
  shows exact recording IDs before removal.
- ✅ After a playlist write, the workflow fetches the playlist and compares the result. Low-level
  tools return Spotify’s response without treating an ambiguous result as success.
- 🧾 DJ apply and restore start with a dry run. Each command checks the live playlist before a
  write.

<details>
<summary><strong>🛠️ Developing or connecting another MCP client?</strong></summary>

Complete authentication once:

```bash
make setup
```

Configure your MCP client to launch `uv run spotify-mcp serve` with this repository as its working
directory. Each client uses its own configuration. This repository provides a guided installer for
Codex. For local development and verification, follow the
[development guide](docs/development.md).

</details>

## 📚 Learn more

- 🚀 [Setup and troubleshooting](docs/setup.md)
- 🧰 [Available Spotify tools](docs/tools.md)
- 🧭 [Architecture and data flow](docs/architecture.md)
- 🧪 [Development and verification](docs/development.md)
- 🔒 [Security policy](SECURITY.md)

The source uses the [MIT License](LICENSE). Spotify AB owns the Spotify trademark and does not
sponsor or endorse this project.
