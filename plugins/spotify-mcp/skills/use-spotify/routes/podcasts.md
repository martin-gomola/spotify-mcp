# Podcast route

- Use `spotify_podcast_discover` when resolving a show or episode by name.
- Use `spotify_podcast_show`, `spotify_podcast_show_episodes`, or `spotify_podcast_episode` for exact
  metadata.
- Use `spotify_saved_shows` or `spotify_saved_episodes` only for library listing.
- Use the generic `spotify_library_contains`, `spotify_library_save`, and
  `spotify_library_remove` tools with exact show or episode URIs.
- Use `spotify_add_to_queue` for an episode or open its canonical Spotify link.

Do not claim direct episode playback: Spotify's documented play endpoint does not support it.
