# Changelog

## Unreleased

- Added ambiguity-safe query playback plus seek, shuffle, repeat, and explicit Spotify Connect
  transfer controls.
- Made device fallback require an explicit choice when several inactive devices are available.
- Added guided `spotify-mcp init` onboarding with app-change reauthorization and live verification.
- Added multi-version GitHub CI and Dependabot coverage.

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
