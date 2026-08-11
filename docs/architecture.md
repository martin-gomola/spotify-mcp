# Architecture

Spotify MCP is a local stdio application with four deliberate module layers.

```text
MCP tools -> application use cases -> domain models and algorithms
                         |
                         +-> Spotify, provider, and persistence adapters
```

- `domain` contains pure models and deterministic algorithms. It does not know about MCP, HTTP,
  files, environment variables, or clocks.
- `application` owns use cases such as library sampling, write verification, provider resolution,
  and DJ mutation coordination. Its interfaces are the primary test surface.
- `adapters` implement Spotify Web API, PKCE credentials, analysis providers, and local durable
  state.
- `mcp_server` is a thin typed transport. MCP SDK v2 derives input and output schemas from Python
  annotations and Pydantic models.

The optional MCP Apps extension is deliberately separate from data acquisition. Normal tools
return typed data and canonical Spotify URLs first; `spotify_render_results` presents a final
selection from that data. The view can call two resource-bound, app-visible controls to load usable
devices and play one exact card with bounded observed-state reads. The independent device and
now-playing reads load concurrently. These controls are hidden from the model by discovery
metadata, not an authorization boundary. Its packaged HTML is self-contained and declares an empty
remote-resource CSP; clients without Apps support keep structured JSON, text, and canonical-link
fallbacks.

`bootstrap.py` is the composition root. One async HTTP client and the local repositories live for
the MCP server lifespan; tool modules never create hidden global clients.

## Safety invariants

- Stdio protocol output owns stdout; logs use stderr.
- Tokens and local state live outside the repository with owner-only permissions.
- Renewable tokens are bound to the Client ID and redirect URI that issued them; legacy or
  mismatched grants require fresh authorization before use.
- Spotify writes are not retried after an ambiguous transport failure.
- Playlist item writes require Spotify snapshot evidence or return `ambiguous`.
- Destructive tools require exact Spotify URIs and advertise destructive MCP annotations.
- DJ application checks the live snapshot and observable order before the first write.
- Presentation accepts only canonical `https://open.spotify.com/{type}/{id}` entity URLs.
- Inline playback requires an explicit usable device and performs one write followed by bounded
  fresh reads; only exact observed item/context and device matches are reported as verified.
- Inline playback never trusts an active-device flag when several controllable devices exist; the
  user must choose the target for that result view.
