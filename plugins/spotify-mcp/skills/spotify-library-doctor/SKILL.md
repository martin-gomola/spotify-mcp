---
name: spotify-library-doctor
description: Audit and safely clean up Spotify Liked Songs. Use for duplicate or alternate recordings, live/remaster/edit cleanup, unavailable saves, library hygiene, or a read-only health report. Avoid for playlist cleanup; use build-spotify-playlist.
---

# Spotify library doctor

Audit first. A vague cleanup request authorizes a preview, not deletion.

1. Page through every saved track with `spotify_saved_tracks`, preserving position, saved date,
   duration, and exact URI. Restart once if the library changes during the scan.
2. Separate exact URI repeats, likely alternate recordings, clearly distinct versions, unavailable
   entries, and no-action observations. Absence from recent or top listening is not a removal reason.
3. Give candidates stable labels and show the proposed keep/remove pair, evidence, and uncertainty.
4. Apply only labels or exact URIs the user explicitly approved. Re-read candidate pages immediately
   before calling `spotify_library_remove` with full exact track URIs; abort if identity or ordering
   changed.
5. Re-scan after removal. Prove approved URIs are absent, keep URIs remain, and the count changed as
   expected. The server has no automatic undo for Liked Songs removal.
