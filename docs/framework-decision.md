# Why the official MCP SDK

The initial release uses `mcp==2.0.0` and its high-level `MCPServer`.

The separate FastMCP framework has useful dependency injection, middleware, proxy, and hosted-auth
features, but its stable 3.x release targets MCP SDK 1.x. Its MCP-v2-compatible 4.x release is still
pre-release as of August 2026. This local stdio server needs only typed tools, structured output,
lifespan context, annotations, and in-memory tests, all supplied by the official stable SDK.

Spotify PKCE authenticates this application to Spotify; it is unrelated to MCP HTTP authorization.
Keeping domain and application modules independent of MCP decorators makes a future framework
change inexpensive if a concrete need appears.
