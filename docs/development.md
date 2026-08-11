# Development

## Environment

The project supports Python 3.11 and newer, plus Node.js 22.12 or newer for the optional MCP App
bundle. Python and UI dependencies are reproducible through `uv.lock` and `package-lock.json`.

```bash
make sync
```

For ordinary local startup, run `uv run spotify-mcp init` once and then `make run`. The guided
setup saves the public app configuration outside the checkout and invokes the browser PKCE flow
only when a matching usable grant is absent. An ignored `.env` remains available for development
overrides.

Runtime dependencies are intentionally small: the official MCP Python SDK v2, HTTPX, Pydantic,
Pydantic Settings, and platformdirs. Development dependencies provide Ruff, strict mypy, pytest,
coverage, and MCP CLI helpers.

## Repository layout

```text
src/spotify_mcp/
  domain/          Pure models and deterministic algorithms
  application/     Use cases and gateway interfaces
  adapters/        Spotify HTTP, PKCE, audio providers, and SQLite
  mcp_server/      Thin MCP server assembly and typed tool registration
  bootstrap.py     Process-lifetime dependency composition
  cli.py           init, serve, auth, connect, and doctor commands
tests/unit/        Behavior and adapter tests
tests/contract/    Public MCP catalog and schema tests
scripts/           Repository-owned release contract checks
plugins/           Codex plugin manifest and workflow skills
ui/                TypeScript source and tests for the bundled MCP App
```

Keep domain and application modules independent of MCP decorators. Tool modules should translate a
typed MCP request into one application call and return structured output.

## Checks

Run the complete local verification suite:

```bash
make check
```

Equivalent commands:

```bash
uv run ruff format --check .
uv run ruff check .
npm run typecheck:ui
uv run mypy src
uv run pytest
npm run test:ui
uv run python scripts/check_release.py
npm run build:ui
uv build
```

The release contract check verifies the public tool count, plugin and skill metadata, retired
Spotify endpoints, and that the committed self-contained UI bundle is current.
The build command regenerates that bundle, then produces the source distribution and wheel in
`dist/`. GitHub Actions runs the same check on every pull request and `main` push across supported
Python versions.

Format and apply safe Ruff fixes with:

```bash
make format
```

Run a focused test module while developing:

```bash
uv run pytest tests/unit/test_playlists.py
```

Generate a terminal coverage report when changing behavior across layers:

```bash
uv run pytest --cov=spotify_mcp --cov-report=term-missing
```

## CLI smoke checks

These commands do not call Spotify:

```bash
uv run spotify-mcp --help
uv run spotify-mcp init --help
uv run spotify-mcp serve --help
uv run spotify-mcp auth --help
```

`doctor` does call Spotify and requires saved authentication:

```bash
uv run spotify-mcp doctor
```

## Tool contract

Every public tool must have:

- a stable `spotify_` name;
- typed input constraints;
- a structured output schema;
- accurate read-only, idempotent, and destructive annotations;
- no request-scoped dependency exposed in its input schema.

When adding or changing a tool, update [the tool catalog](tools.md), add application-level behavior
tests, and add an MCP contract test when its public schema changes.

## Spotify adapter rules

- Use current Spotify Web API endpoints and preserve exact IDs and URIs.
- Retry bounded safe reads only. Do not automatically retry writes, including rate-limited writes,
  because a repeated mutation can target stale user intent or duplicate an ambiguous result.
- Re-read observable state after library and metadata writes.
- Preserve Spotify playlist snapshot IDs and return an explicit ambiguity state when Spotify does
  not provide enough evidence.
- Keep OAuth token values, authorization codes, personal library responses, and local SQLite state
  out of tests, fixtures, and commits.

## Local state

PKCE configuration and tokens use `platformdirs.user_config_path("spotify-mcp")`. DJ analysis,
plans, and mutation receipts use `platformdirs.user_data_path("spotify-mcp")/state.sqlite3`.
Directories and files are created with owner-only permissions where the filesystem supports POSIX
modes.

Tests that exercise persistence should pass an explicit temporary path instead of reading or
modifying the developer's real local state.
