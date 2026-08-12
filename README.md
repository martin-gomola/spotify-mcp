<div align="center">

# 🎵 Spotify for Codex

**Ask Codex to play music, find old favourites, build playlists, or plan a DJ set.**

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
[![MIT License](https://img.shields.io/badge/License-MIT-2F855A.svg)](LICENSE)
![Spotify MCP](https://img.shields.io/badge/Spotify-MCP-1DB954?logo=spotify&logoColor=white)

[Get started](#get-started) · [Codex plugin guide](plugins/spotify-mcp/README.md) ·
[See what you can ask](#what-can-i-ask) · [Setup guide](docs/setup.md)

</div>

> [!NOTE]
> This open-source project has no connection to Spotify AB. Use it in line with the
> [Spotify Developer Policy](https://developer.spotify.com/policy).

## ✨ Rich Spotify results, inside Codex

Verified tracks, albums, artists, and playlists can appear as compact cards inside Codex. Choose a
Spotify Connect device, start the exact result, or open its canonical Spotify page.

![Codex creating and verifying a Spotify playlist, then presenting it as a playable result card with device selection](docs/assets/codex-playlist-result-card.png)

<sub>A real Codex result: a 90-minute playlist created from Liked Songs, verified track by track,
and returned as a playable Spotify card.</sub>

## 💬 What can I ask?

Spotify MCP includes skills for playlist curation and Liked Songs cleanup. Copy a prompt below.
Codex reads the required pages, preserves exact recordings, and checks the result after each write.

**Audit your complete Liked Songs library**

```text
Audit all my Liked Songs for exact duplicates, alternate recordings, live versions, remasters,
and unavailable tracks. Show the exact keep/remove pairs and explain the evidence, but do not
remove anything.
```

**Rediscover music buried in years of listening history**

```text
Build me a three-hour road-trip playlist from across my full Liked Songs history. Keep the mix
varied across house, funk, indie, rock, and hip-hop, shape it into chapters, and verify the final
playlist track by track.
```

**Reshape an existing playlist without losing its character**

```text
Keep every track in my Road Trip playlist, add 25 songs that fit its existing taste, then order the
whole playlist into waves with intentional energy resets. Show me the proposed arc before changing
the playlist.
```

**Plan a DJ running order**

```text
Audit my House Party playlist for duplicates, missing tempo data, and awkward transitions. Plan a
DJ order that warms up, builds, peaks late, and closes with at least three tracks between the same
artist. Create a preview. Do not apply it yet.
```

You can also search music and podcasts, inspect your queue, control Spotify Connect devices, and
show verified results as playable cards inside Codex.

## ✨ What it can do

- 🎶 **Control playback:** resolve a precise track, album, artist, or playlist from a query, control
  seek, shuffle, repeat, volume, queue, and Spotify Connect devices.
- 🖼️ **Act on visual results:** present the final verified selection as compact, playable cards in
  Codex.
- 🎧 **Find music from your library:** search your full Liked Songs history, including tracks you
  saved years ago.
- 🩺 **Run Library Doctor:** audit exact duplicates, alternate recordings, live and remastered
  versions, unavailable saves, and cleanup candidates before removing anything.
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

### 🔑 2. Configure Spotify

Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), add
`http://127.0.0.1:8888/callback` as its Redirect URI, then put its Client ID in `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id
```

The [setup guide](docs/setup.md) covers the dashboard steps and Spotify Development Mode limits.

### 🔌 3. Install for Codex

```bash
make codex-install
```

Approve the Spotify page that opens, then start a new Codex task. Codex starts the local server when
you use it, so you can close the setup terminal. The [Codex plugin guide](plugins/spotify-mcp/README.md)
explains how the plugin starts the server, what it includes, and what to ask first.

![Spotify plugin page in Codex with example prompts and local MCP server](docs/assets/codex-plugin-page.png)

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
- 🧩 [Codex plugin guide](plugins/spotify-mcp/README.md)
- 🧰 [Available Spotify tools](docs/tools.md)
- 🧭 [Architecture and data flow](docs/architecture.md)
- 🧪 [Development and verification](docs/development.md)
- 🔒 [Security policy](SECURITY.md)

The source uses the [MIT License](LICENSE). Spotify AB owns the Spotify trademark and does not
sponsor or endorse this project.
