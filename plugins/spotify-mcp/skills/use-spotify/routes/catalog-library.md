# Catalog and library route

- Use `spotify_search` to resolve a name when no exact ID or URI is known.
- Use `spotify_catalog` after resolution:
  - `route=track` for one exact track.
  - `route=artist` for one exact artist.
  - `route=artist_albums` for the artist's paginated albums and singles. Follow `total` and `offset`
    only as far as the request needs. For latest/newest requests, read every page, normalize and
    compare `release_date`, and inspect same-date variants before selecting; Spotify does not
    guarantee that the first page is newest-first.
- Use `spotify_albums` for one or more exact album details and `spotify_album_tracks` for an album's
  track list.
- Use `spotify_saved_tracks`, `spotify_saved_albums`, or `spotify_sample_liked_songs` only when the
  user asks about their library or taste history.
- Use `spotify_library_contains`, `spotify_library_save`, or `spotify_library_remove` with full,
  exact Spotify URIs. Supported library types are track, album, show, episode, and audiobook.

Do not use Spotify's retired recommendations, batch track/artist, related-artist, or artist-top-track
endpoints. Artist save/remove is not exposed because Spotify's current reference is inconsistent.
After library writes, accept only the returned verified state; stop on mismatch or ambiguity.
