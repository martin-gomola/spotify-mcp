# Existing playlist route

- Use `spotify_search` with `item_type=playlist` when the exact playlist ID is unknown.
- Use `spotify_playlist` for metadata and `spotify_playlist_items` for contents. Follow pagination
  only as far as the request requires.
- Use `spotify_playlists` only when the user asks to browse their playlists.
- Use `spotify_render_results` once after the exact final playlist is resolved and verified.

For creation, curation, mutation, or DJ ordering, switch to `build-spotify-playlist` instead of
loading those tools here.
