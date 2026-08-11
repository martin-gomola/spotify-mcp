# Changelog

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
