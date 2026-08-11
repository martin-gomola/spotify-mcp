---
name: build-spotify-playlist
description: Build, extend, curate, verify, or DJ-order Spotify playlists. Use for mood, activity, era, artist, Liked Songs, rediscovery, exact recording selection, playlist edits, BPM/key flow, or DJ running order. Avoid for simply finding, showing, or opening an existing playlist; call the playlist read tools directly. Avoid for removing items from Liked Songs; use spotify-library-doctor.
---

# Build a Spotify playlist

Use exact Spotify URIs and finish with an observed playlist, not an optimistic success message.

## Choose the source

- For general discovery, draft a varied candidate list and resolve each candidate with
  `spotify_search`. Reject mismatched artists, tribute recordings, karaoke, and unintended edits.
- For taste-based work, call `spotify_sample_liked_songs` so candidates span newest through oldest
  saves. Use `spotify_saved_tracks` only for exact nearby pages or a complete audit.
- For a deterministic rediscovery shortlist, call `spotify_taste_recommendations`. State that it
  is local curation from top, recent, and sampled liked-song signals, not Spotify personalization.
- For an existing playlist, resolve its exact ID and read every page with `spotify_playlist_items`.

## Build safely

1. Preserve recording URIs returned by Spotify. Matching title and artist do not make two versions
   interchangeable.
2. Shape an intentional arc for the activity; do not globally sort one scalar unless explicitly
   requested.
3. Create public by default, matching Spotify's default, unless the user requests private. Add at
   most 100 URIs per write.
4. Treat `ambiguous`, `mismatch`, `stale`, or `partial` as stop states. Re-read before deciding what
   happened and never repeat the write automatically.
5. Re-read the entire result and compare exact URIs and order. Return the playlist URL, track list,
   arc, skipped candidates, and verification state.

When the client supports MCP Apps, prefer `spotify_render_results` for the final verified playable
entities. Its cards can start the exact track, album, artist, or playlist on a selected device and
verify playback with bounded fresh reads; they never discover, rank, verify source data, or
substitute an entity. Episodes and shows remain link/queue flows. Return canonical Markdown links
when MCP Apps are unavailable.

For DJ flow, start with the read-only `spotify_dj_audit`, then run `spotify_dj_analyze` and
`spotify_dj_plan`. Analysis enriches recordings automatically and accepts exact overrides when
provider evidence is incomplete. Use `missing_feature_policy=error` when every position must have
complete planning evidence; otherwise keep `anchor` so missing-tempo positions cannot move.
Preview the plan; use `spotify_dj_apply` only when mutation is explicitly requested, retaining its
receipt for restore.

Use `spotify_playlist_sort_by_bpm` only when the user explicitly wants the compatibility BPM sort.
Keep its default dry run, inspect missing-feature and fixed-position warnings, and apply only after
the preview is acceptable.
