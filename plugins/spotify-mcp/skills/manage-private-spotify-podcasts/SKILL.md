---
name: manage-private-spotify-podcasts
description: List and safely delete private episodes created through Save to Spotify. Use when the user wants to inspect, clean up, or remove an unwanted private Spotify episode. Avoid for unfollowing catalog podcasts, removing saved episodes, editing playlists, or deleting an entire show.
---

# Manage private Spotify podcasts

Use the external Save to Spotify CLI as the source of truth. This skill deletes individual private
episodes only; it does not delete shows or mutate Spotify MCP playlists.

## Preflight

1. Check whether `save-to-spotify` is available on `PATH`. If it is missing, stop and direct the
   user to run `make codex-install-bundle`, then start a new Codex task.
2. Run `save-to-spotify --json doctor`. If its separate authorization is missing, follow the
   external `$save-to-spotify` setup guidance before listing or deleting episodes.
3. Always use JSON mode. Never print, inspect, or transfer either tool's token.

## Resolve the exact episode

1. Run `save-to-spotify --json shows`, then list episodes in the relevant show with
   `save-to-spotify --json episodes --show-id <exact-show-uri>`.
2. Prefer an exact `spotify:episode:...` URI supplied by the user. If the user supplied a title,
   resolve it only from the private episode listings. Present title, exact episode URI, show, and
   processing status before deletion.
3. If zero episodes or multiple episodes match, do not guess. Ask the user to select one exact URI.
4. Never substitute a Spotify catalog episode, saved-library episode, or playlist item with a
   similar title.
5. Allow deletion in any observed processing state, including `PROCESSING`, `NOT_READY`, `READY`,
   or `FAILED`. Deletion does not require a readiness wait; surface the state so the user understands
   whether they are removing playable content or cleaning up a stuck upload.

## Delete safely

1. Treat episode deletion as irreversible. Unless the user's current message already names the
   exact URI and explicitly commands its deletion, prefer the client's structured-choice UI. Put
   the exact title, `spotify:episode:...` URI, show, and current status in the confirmation question,
   then offer exactly two choices:
   - **Delete episode - irreversible**: this selection is the explicit delete confirmation and is
     bound to the exact displayed URI.
   - **Cancel**: make no changes.
   Do not ask for another confirmation after the user selects the delete choice. If structured
   choices are unavailable, ask the user to reply with
   `delete <exact-episode-uri>` as the portable fallback.
2. Delete once with
   `save-to-spotify --json episodes delete <exact-episode-uri>`.
3. Success from the write must report `status: deleted` and the same exact episode ID. Preserve the
   original full URI in the user-facing result.
4. If the response is missing, times out, or is otherwise ambiguous, re-list the show's complete
   episode collection before considering any retry. Never repeat the delete blindly.
5. Verify completion by re-listing every episode in the exact show and confirming that the exact
   episode URI is absent. Do not claim deletion from the write response alone.

If the deleted episode had been placed in a playlist, report that playlist cleanup is separate and
requires its own exact-item read and approval. Do not mutate playlists as a side effect of deleting
the private episode.

Finish with the deleted episode title and exact URI, the verified absence result, and any separate
playlist cleanup that remains.
