# Spotify inline direct-play UI plan

Date: 2026-08-11
Mode: direct planning; no implementation in this pass

## Outcome

Replace the Spotify result card's external-link-first interaction with a verified inline playback
action. A user should be able to press **Play** on a track card, have the exact recording start on
the selected Spotify Connect device, and see the result confirmed inside the same Codex response.
The canonical **Open in Spotify** link remains available as a secondary action.

## Requirements summary

- Keep normal text/structured-data fallback for hosts without MCP Apps support.
- Preserve exact Spotify entity identity from the validated canonical URL; do not search again or
  substitute another recording.
- Make direct play available for Spotify tracks, albums, artists, and playlists. Episodes and shows
  remain link/queue flows because direct episode playback is explicitly rejected by the current
  playback service.
- Select the active Spotify device by default. If several devices exist and none is active, require
  an explicit device choice rather than silently using the first device.
- Never label a card **Playing** from the mutation response alone. Re-read now-playing state and
  require an exact item match.
- Never automatically repeat a playback write after an ambiguous, mismatched, or failed outcome.
- Keep the view self-contained: no runtime CDN, remote script, image, or font dependency.
- Make direct-play result lists the preferred presentation for play-oriented prompts so the model
  does not fall back to ordinary Markdown links when the MCP App is available.

## Current-state evidence

- The existing result view creates a canonical Spotify anchor and explicitly sets
  `target="_blank"`, so its only action is external navigation
  (`src/spotify_mcp/mcp_server/resources/spotify-results-v1.html:143-159`).
- The renderer is model-visible and read-only, and accepts canonical Spotify URLs only
  (`src/spotify_mcp/mcp_server/ui.py:19-50`, `src/spotify_mcp/mcp_server/ui.py:62-95`).
- `spotify_play` already supports exact track/album/artist/playlist URIs and optional device IDs,
  but returns an accepted playback result rather than observed proof
  (`src/spotify_mcp/mcp_server/tools/playback.py:60-84`).
- The playback service selects the active device, but falls back to the first available device when
  none is active (`src/spotify_mcp/application/playback.py:315-338`). That fallback is too surprising
  for a direct UI action when multiple devices are available.
- Direct episode playback is rejected and routed to queue/open behavior
  (`src/spotify_mcp/application/playback.py:340-360`).
- The current UI tests validate safe text rendering and external-link behavior, but do not exercise
  any interaction or playback state (`tests/unit/test_ui.py:10-89`).
- The server already composes the result UI as an MCP Apps extension
  (`src/spotify_mcp/mcp_server/server.py:43-54`).

## Product and interaction decisions

### Card hierarchy

Each playable card gets:

1. Track/entity name and existing metadata.
2. Primary **Play** button.
3. Secondary **Open in Spotify** link.
4. One compact status line reserved for progress, confirmation, or error feedback.

Episodes and shows do not display **Play**. They retain **Open episode/show** and may later gain an
explicit **Add to queue** action as a separate feature.

### Device behavior

- On view initialization, load the available devices and observed now-playing state.
- One active device: select it and show `Playing on <device>` in the header.
- No active device and one available device: select it and show `Play on <device>`.
- No active device and multiple available devices: show a compact labeled device selector and keep
  **Play** disabled until a device is chosen.
- No devices: disable **Play** and show `Open Spotify on a device to play here.`
- Keep device choice in view memory only; do not persist it globally.

### Playback state machine

`idle -> starting -> verified | unverified | error`

- **idle:** Play is enabled when a usable device is selected.
- **starting:** clicked button reads `Starting...`; all card playback actions are disabled to prevent
  overlapping writes; the external link remains available.
- **verified:** an observed now-playing read matches the exact requested type and ID. The card reads
  `Playing`, gets `aria-current="true"`, and the header names the observed device.
- **unverified:** Spotify accepted the request but the observed item did not match. Show
  `Playback requested, but Spotify did not confirm this track.` Do not retry the write.
- **error:** show a short actionable message such as `No Spotify device is available.` or
  `Spotify could not start playback.` Re-enable actions after the request settles.

If a different card was previously marked playing, clear that state only after the new request is
verified. This prevents optimistic UI from lying about playback.

### Accessibility and responsive behavior

- Use real `<button type="button">` elements for playback and anchors only for external navigation.
- Give each action an exact accessible name, for example `Play 900 Miles by Bakermat and Barbara
  Dane` and `Open 900 Miles in Spotify`.
- Put feedback in a polite `aria-live` region; errors use `role="alert"` only after a user action.
- Preserve visible keyboard focus, minimum 44px touch targets, logical tab order, and dark/light
  system colors.
- Keep the current single-column mobile collapse, but render the action group on one wrapping row so
  Play remains visually primary.
- Do not animate status changes beyond simple text/color changes; honor reduced-motion by default.

## Architecture decision

### Chosen approach: scoped app-only playback tools plus the standard MCP Apps bridge

Do not call the broad model-facing `spotify_play` tool directly from the embedded view. Add two
app-only tools bound to the results resource:

- `spotify_results_context` (read-only): returns devices, selected-device guidance, and observed
  now-playing state.
- `spotify_results_play` (write): accepts one validated canonical Spotify URL plus an explicit
  device ID, derives the exact Spotify URI server-side, performs one play write, then performs a
  bounded now-playing read and returns `verified`, `unverified`, or `error` with observed device/item.

This keeps the UI capability narrow, avoids arbitrary URI input, prevents model tool clutter, and
centralizes the observed-state contract on the server.

Use the official `@modelcontextprotocol/ext-apps` view API and `app.callServerTool()` rather than
maintaining a custom JSON-RPC bridge. Add it as a build-time UI dependency, bundle the view into one
HTML artifact, and keep the Python wheel/runtime free of JavaScript dependencies and remote assets.
This dependency addition is part of the plan and must be explicitly accepted with implementation.

### Alternatives considered

- **Keep Markdown/external links:** rejected because it cannot switch playback in place.
- **Call `spotify_play` directly from UI:** rejected because its accepted result is not observed
  proof, its input surface is broader than the card needs, and inactive-device fallback can target
  an unexpected device.
- **Hand-write the MCP Apps JSON-RPC bridge:** rejected because it saves a build-time dependency at
  the cost of duplicating protocol initialization, correlation, teardown, and compatibility logic.
- **Spotify Embed/player iframe:** rejected because it adds remote UI/runtime dependencies and does
  not reuse the authenticated Spotify Connect control path already present in the server.

## Implementation steps

### 1. Add a verified direct-play application use case

Files:

- `src/spotify_mcp/application/playback.py`
- `tests/unit/test_playback.py`

Add a typed outcome for `play_and_observe` that contains requested URI, observed item/device, and a
status of `verified` or `unverified`. Reuse the existing `play()` and `now_playing()` behavior, but
require an explicit device ID for this UI path and perform exactly one playback write. A delayed
read may be used only as a bounded observation; it must never trigger a second write.

Unit coverage:

- exact track match -> `verified`;
- accepted write plus different/empty observed item -> `unverified`;
- selected device missing -> error before write;
- episode/show URL -> rejected before write;
- ambiguous transport failure -> propagated without retry;
- exact request URI and device ID are preserved.

### 2. Register least-privilege app-only tools

Files:

- `src/spotify_mcp/mcp_server/ui.py`
- `src/spotify_mcp/mcp_server/server.py` only if composition changes are needed
- `tests/unit/test_ui.py`
- `tests/contract/test_mcp_server.py`

Extend `create_results_apps()` with app-only context and playback tools using
`visibility=("app",)`. Keep `spotify_render_results` model-only. Parse and validate canonical URLs
with the existing link/domain helpers and derive the entity ID/type on the server. Return compact,
typed structured content designed for the view.

Contract coverage:

- the renderer remains model-visible;
- the two control tools are app-only;
- annotations accurately distinguish read-only context from non-idempotent playback;
- non-canonical URLs, unsupported entity types, and missing device IDs are rejected;
- public/model tool inventory does not gain UI-only control tools.

### 3. Convert the result card into an interactive MCP App

Files:

- new source under `ui/spotify-results/` for HTML, styles, and TypeScript
- generated `src/spotify_mcp/mcp_server/resources/spotify-results-v1.html`
- new UI build configuration and lockfile entries
- `Makefile`
- `scripts/check_release.py`

Use `@modelcontextprotocol/ext-apps` to connect, consume the initial render result, call the two
app-only tools, and handle request results. Bundle to the existing single HTML resource so package
loading remains local and dependency-free at runtime. Preserve `textContent`-based rendering and
canonical URL validation; never inject model-provided HTML.

Add the device header/selector, Play/Open action group, state machine, accessible live feedback, and
global in-flight lock described above. Keep the external link secondary and open it through the MCP
Apps host link API where supported rather than relying on `target="_blank"`.

Make `make build` regenerate the resource deterministically and make `make release-check` fail when
the committed artifact is stale or contains remote runtime dependencies.

### 4. Route play-oriented result lists through the interactive renderer

Files:

- `src/spotify_mcp/mcp_server/instructions.md:11-15`
- `plugins/spotify-mcp/skills/build-spotify-playlist/SKILL.md:32-34`
- `docs/tools.md:157-165`
- `docs/architecture.md:20-23`

Change the guidance from optional generic presentation to a specific rule: after a final list of
playable entities is selected and verified, prefer `spotify_render_results` when the client exposes
it. Keep Markdown links as the fallback for clients without Apps. State explicitly that the
renderer may control playback but performs no discovery, ranking, or entity substitution.

Document that playback feedback is observed state, that episodes/shows are not directly playable,
and that the external link remains available.

### 5. Validate in both supported presentation paths

Automated checks:

```text
uv run pytest tests/unit/test_playback.py tests/unit/test_ui.py tests/contract/test_mcp_server.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run python scripts/check_release.py
uv build
```

Host-level smoke checks in Codex Desktop:

1. Request a top-track or recommendation list and confirm the inline card view appears instead of a
   Markdown-only list when Apps are supported.
2. With one active device, click a non-playing track and confirm no browser/window opens.
3. Confirm the exact clicked track starts on the named device and the card changes to **Playing**
   only after observed state matches.
4. Rapidly click two tracks and confirm only one write is in flight.
5. With multiple inactive devices, confirm playback stays disabled until a device is selected.
6. With no device, confirm the inline recovery message and secondary external link remain usable.
7. Trigger an accepted-but-unverified test response and confirm the UI reports uncertainty without
   retrying playback.
8. Use a host without Apps support and confirm structured text/canonical links still render.

## Acceptance criteria

- Clicking **Play** on a supported card starts the exact requested Spotify entity on the selected
  device without opening a browser or new Codex window.
- A card shows **Playing** only when a fresh now-playing read matches the exact requested type and ID.
- No interaction path automatically repeats a Spotify playback write.
- Multiple inactive devices require explicit selection; the UI never silently chooses the first.
- Episodes and shows never expose a direct-play control.
- The external Spotify link remains present and visually secondary.
- Keyboard-only users can select a device, start playback, reach the external link, and perceive
  pending/success/error feedback.
- The packaged view makes no runtime network request except tool calls mediated by the host and
  contains no remote script/style/font dependency.
- Model-visible tool inventory remains focused; UI-only tools carry app-only visibility metadata.
- All targeted automated checks and the eight Codex host smoke scenarios pass with fresh evidence.

## Risks and mitigations

- **Host support varies.** Keep structured text/Markdown fallback and test Codex Desktop separately
  from protocol-level tests.
- **Spotify propagation can lag.** Distinguish `unverified` from failure; allow a bounded read delay
  but never retry the write.
- **Playback may target the wrong device.** Require explicit device selection when no active device
  exists and multiple devices are available.
- **UI dependency/tooling could bloat the Python project.** Keep it build-time only, output one
  committed HTML artifact, pin versions, and add a stale-artifact release check.
- **App-only tools could leak into the model surface.** Assert visibility metadata and model-facing
  inventory in contract tests.
- **Generated HTML can weaken current injection defenses.** Preserve `textContent`, canonical URL
  validation, CSP restrictions, and tests prohibiting unsafe HTML insertion/remote dependencies.

## Definition of done

The work is complete only when direct play is implemented, the exact playback result is observed in
Spotify, external navigation is no longer the primary action, fallback rendering still works, all
automated checks pass, and the behavior is demonstrated inside Codex Desktop without opening a new
window.
