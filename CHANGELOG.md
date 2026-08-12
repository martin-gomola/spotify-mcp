# Changelog

## 0.4.0

- Added an optional `make codex-install-bundle` path and composition skill for private spoken-word
  episodes through Spotify's external Save to Spotify companion and local Kokoro speech.
- Added a 45-second generated-audio guard so short compatibility episodes do not stall in Spotify
  processing; short scripts return to approval instead of being padded with silence.
- Hardened private-podcast uploads with source-rights confirmation and clean single-stream MP3
  validation that keeps cover art and inherited metadata out of the audio container.
- Added a verified private-playlist visibility stop: public mismatches fall back to the private show
  without adding the episode, retrying privacy, or creating duplicate playlists.
- Added `manage-private-spotify-podcasts` for exact, confirmed, and readback-verified deletion of
  unwanted private Save to Spotify episodes without incidental playlist mutations.
- Made Spotify-side episode processing explicit before and after upload, with periodic status
  updates and truthful delayed-processing results instead of false plugin failures or early writes.
- Added one routed catalog tool for exact tracks, artists, and artist releases.
- Consolidated track and album library actions into exact URI-based tools that also support shows,
  episodes, and audiobooks.
- Added an intent router skill and shortened repeated server instructions to reduce unnecessary tool
  context; the public catalog now has 55 tools instead of 57.

## 0.3.0

- Added ambiguity-safe query playback plus seek, shuffle, repeat, and explicit Spotify Connect
  transfer controls.
- Made device fallback require an explicit choice when several inactive devices are available.
- Added guided `spotify-mcp init` onboarding with app-change reauthorization and live verification.
- Added richer inline Spotify result cards with artwork, playback controls, and responsive layouts.
- Rendered initial tool input after the MCP Apps handshake while preventing repeated result events
  and stale playback context from duplicating or flickering the inline results UI.
- Reduced inline-result latency with concurrent context reads and avoided false playback errors by
  polling fresh state briefly without repeating the Spotify write.
- Made newly created playlists public by default and clarified supported Spotify visibility values.
- Added multi-version GitHub CI, Dependabot coverage, and refreshed CI and UI test dependencies.

## 0.2.2

- Added Spotify-green plugin branding and local logo assets for a clearer Codex presence.
- Added a concise non-affiliation notice to the plugin onboarding page.
- Kept the Python PKCE setup as the only supported plugin path.

## 0.2.1

- Simplified the root README around a friendly Codex setup path with optional technical detail.
- Reduced the plugin suggestions to one general request and one Liked Songs rediscovery use case.
- Added typed DJ tool results so their public structured schemas describe the returned fields.

## 0.2.0

- Added canonical Spotify web links across music, library, playlist, playback, and podcast results.
- Added six podcast discovery and saved-library tools with episode queue and open-in-Spotify
  guidance.
- Added explicitly local deterministic taste rediscovery without Spotify's retired recommendations
  endpoint.
- Added an optional dependency-free MCP Apps result-card renderer while preserving structured and
  text fallbacks.
- Documented Spotify's official Save to Spotify CLI as a separate companion with isolated auth and
  token storage.

## 0.1.0

- Initial clean Python implementation using the official MCP SDK v2.
- Typed Spotify discovery, playback, library, playlist, audio, and DJ workflows.
- PKCE authentication, verified writes, deterministic Liked Songs sampling, and durable receipts.
- Relative volume adjustment, automatic DJ audio enrichment, full playlist DJ audits, and a
  snapshot-safe compatibility BPM sort.
