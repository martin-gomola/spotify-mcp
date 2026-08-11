---
name: setup-spotify-mcp
description: Connect, diagnose, or repair the local Spotify MCP server. Use when Spotify tools are not configured, authentication expired, the server cannot start, or the user asks to connect Spotify. Avoid for ordinary playlist or playback requests after the server is healthy.
---

# Set up Spotify MCP

Complete all reversible technical work yourself and ask only for the Spotify client ID or browser
approval that cannot be obtained locally.

1. Locate the checkout from `SPOTIFY_MCP_REPO`, defaulting to `~/dev/spotify-mcp`.
2. Ensure the ignored `.env` file contains `SPOTIFY_CLIENT_ID`; copy `.env.example` when needed.
3. If no client ID is configured, explain how to create a Spotify Web API app and register exactly
   `http://127.0.0.1:8888/callback`. Ask for the client ID only; PKCE needs no client secret.
4. Run `make auth`. Let the user approve the Spotify browser page.
5. Run `make doctor` and verify the MCP process can list its tools. Use `make run` for ordinary
   standalone startup; it authenticates automatically only when the saved grant is unavailable.
6. Report the concrete result. Never paste tokens, authorization codes, or credential-file content.

Spotify Development Mode requires the app owner to have Premium and currently limits allow-listed
users. Playback additionally needs Spotify open on an available device.
