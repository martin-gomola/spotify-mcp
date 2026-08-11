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

`bootstrap.py` is the composition root. One async HTTP client and the local repositories live for
the MCP server lifespan; tool modules never create hidden global clients.

## Safety invariants

- Stdio protocol output owns stdout; logs use stderr.
- Tokens and local state live outside the repository with owner-only permissions.
- Spotify writes are not retried after an ambiguous transport failure.
- Playlist item writes require Spotify snapshot evidence or return `ambiguous`.
- Destructive tools require exact Spotify URIs and advertise destructive MCP annotations.
- DJ application checks the live snapshot and observable order before the first write.
