# Existing playlist route

- Use `spotify_search` with `item_type=playlist` when the exact playlist ID is unknown.
- Use `spotify_playlist` for metadata and `spotify_playlist_items` for contents. Follow pagination
  only as far as the request requires.
- Use `spotify_playlists` only when the user asks to browse their playlists.
- When MCP Apps are supported, call `spotify_render_results` exactly once after the exact final
  playlist is resolved and verified, before the textual completion response. Pass only the final
  entity with `kind: playlist`; use a canonical Spotify link only when cards are unavailable or the
  single render call fails.

For creation, curation, mutation, or DJ ordering, switch to `build-spotify-playlist` instead of
loading those tools here.
