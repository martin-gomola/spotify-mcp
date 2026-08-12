---
name: use-spotify
description: Use Spotify for exact catalog lookup, playback, library actions, podcasts, and simple playlist reads. Use when the user asks to find, inspect, play, pause, queue, save, remove, or show Spotify content. Avoid for playlist creation or DJ ordering; use build-spotify-playlist. Avoid for Liked Songs cleanup; use spotify-library-doctor. Avoid for setup failures; use setup-spotify-mcp.
---

# Use Spotify

Choose one route from the user's intent. Do not list or inventory the full Spotify MCP tool catalog.
Read only the matching route file, then call only the tools named there.

- Exact track, artist, releases, search, or library save/remove/check:
  [routes/catalog-library.md](routes/catalog-library.md)
- Current playback, devices, queue, or playback control:
  [routes/playback.md](routes/playback.md)
- Podcasts, shows, or episodes: [routes/podcasts.md](routes/podcasts.md)
- Existing playlist lookup or contents: [routes/playlists.md](routes/playlists.md)

If a request crosses routes, read only those routes. Preserve exact Spotify URIs, inspect uncertain
write results, and, when MCP Apps are supported, call `spotify_render_results` exactly once after
the final playable results are verified and before the textual completion response. Every rendered
item must include its concrete `kind`; use `kind: playlist` for playlist cards. A plain Markdown
link is not a substitute when the renderer is available. If rendering itself fails, report it and
fall back to canonical Spotify links without retrying the renderer.
