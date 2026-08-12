---
name: create-private-spotify-podcast
description: Convert user-provided documents, PDFs, notes, or transcripts into polished private Spotify podcast episodes. Use when the user asks to turn written source material into private Spotify audio. This integration composes the external $save-to-spotify production skill with local Kokoro narration and optional placement in an owned private Spotify playlist.
---

# Create a private Spotify podcast

Use the official external `$save-to-spotify` skill for production. Do not reproduce, replace, or
weaken its interview, chapter approval, preview, upload, timeline, cover, or readiness workflow.

## Preflight

1. Check whether `save-to-spotify` is available on `PATH`. If it is missing, stop cleanly and tell
   the user to run `make codex-install-bundle`, then start a new Codex task. Do not install the
   companion directly from this skill.
2. Run `save-to-spotify --json doctor` before sourcing or scripting. If authentication is missing,
   follow `$save-to-spotify` setup guidance; its Spotify authorization is separate from Spotify MCP.
3. Version one supports only Kokoro. If doctor does not report Kokoro as available, explain that it
   is a free local download of approximately 340 MB, request confirmation, then run
   `save-to-spotify tts setup --engine kokoro`. Do not offer or require cloud TTS providers or API
   keys. Confirm Kokoro is available before scripting.
4. Inspect the proposed source before upload. Refuse content containing credentials, third-party
   personal data, or confidential business information. Ask the user for a redacted source instead;
   never copy sensitive values into scripts, logs, descriptions, timelines, or tool arguments.
5. Confirm that the user owns the source or has the right to reproduce it as spoken audio. Do not
   upload third-party text or audio merely because the user supplied a copy.

## Produce the episode

Invoke `$save-to-spotify` and follow its complete production pipeline. In particular, wait for the
user's plan approval and chapter approval, provide the required local preview before upload, keep
the episode private, set its timeline, and poll until the episode status is exactly `READY`.

Before asking for upload approval, explain that Spotify processes uploaded audio asynchronously.
The private show may display `PROCESSING` or `NOT_READY` for several minutes, occasionally longer;
that state means Spotify is still preparing the episode and does not mean the plugin failed.
Immediately after upload, report the exact episode URI and observed processing state. While polling,
give a short progress update when the state changes or about once per minute so the user is not left
guessing. Do not call processing a failure, re-upload, or attempt playlist placement unless Spotify
returns a terminal `FAILED` state; playlist placement still requires exact `READY`.

If the episode remains `PROCESSING` or `NOT_READY` beyond the initial wait, make one fresh status
read and report a delayed-but-valid upload with its exact URI, verified timeline state when
available, and the fact that Spotify processing is still pending. Continue bounded read-only status
checks when the task remains active. Never hide the pending state behind a generic success message.

Before offering the final preview, measure the assembled audio with `ffprobe`. Require at least 45
seconds of spoken episode audio because very short files can remain stuck in Spotify processing.
If it is shorter, extend the useful script and return through content approval before regenerating.
Do not satisfy this guard by padding the episode with silence, and never upload a sub-45-second
generated episode.

Use MP3 as the version-one output. Before preview and upload, inspect it with `ffprobe`: require one
audio stream, no attached-picture stream, and no unexpected format tags. If the assembled file has
embedded artwork or inherited metadata, re-encode it with FFmpeg using `-vn -map_metadata -1`; pass
the required cover separately through Save to Spotify's `--image` option. This follows Spotify's
guidance to keep embedded artwork, ID3v2 tags, and other MP3 metadata small while preserving the
companion CLI's stricter file contract.

Preserve the exact `spotify:episode:...` URI returned by Save to Spotify. Do not derive, normalize,
search for, or substitute another episode URI.

## Place it in a private playlist

Attempt playlist placement only after the episode is `READY`.

1. Read `spotify_status` for the authenticated user ID. If the user named a playlist, use it only
   after `spotify_playlist` confirms that its owner ID matches that user ID and it is private.
   Otherwise, find an owned private playlist named
   `Personal Podcasts`; create it with `spotify_playlist_create` and `public=false` when none exists.
   Never add the episode to a public, collaborative, followed, or ambiguously owned playlist.
   If creation or a metadata update re-reads as public, stop: do not retry visibility, create a
   duplicate playlist, or add the episode. Use the private-show fallback, report the exact empty
   playlist that was created, and ask before removing or unfollowing it.
2. Call `spotify_playlist_add` once with the exact episode URI.
3. Treat `ambiguous`, `mismatch`, `stale`, or `partial` as stop states. Read before deciding what
   happened and never retry the write blindly.
4. Read every `spotify_playlist_items` page, advancing by the returned page size until the reported
   total is exhausted. Success requires observing the exact episode URI in the complete playlist.
5. If Spotify rejects personal episodes in playlists, do not treat that as an episode-production
   failure and do not seek a write workaround. Report that the user's episode is ready in their
   private Save to Spotify show, and state plainly that playlist placement was unavailable.

Finish by reporting the private show result, the exact episode URI, readiness state, and either the
fully verified private playlist or the private-show fallback. Centre user-facing wording on what the
user created.
