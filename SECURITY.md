# Security

Report vulnerabilities privately through GitHub security advisories for this repository.

The default transport is local stdio. Spotify OAuth uses Authorization Code with PKCE and an
explicit `127.0.0.1` callback. Tokens are stored outside the checkout with owner-only permissions.
Never commit `.env` files, credentials, tokens, SQLite state, DJ artifacts, or captured Spotify API
responses containing personal library data.

Writes use bounded timeouts and are never retried after a response could have been applied. When
Spotify does not provide enough evidence, tools return an explicit ambiguous state and require a
fresh read before any further mutation.
