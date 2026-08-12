# Installation layout

Spotify MCP keeps source, installed integrations, credentials, models, caches, and temporary media
in separate locations. Runtime state stays outside Git.

On macOS, the standard installation creates or uses these paths:

| Location | Owner and contents | Lifecycle |
| --- | --- | --- |
| Repository checkout, normally `~/dev/spotify-mcp/` | Source, installer, plugin manifest, integration skills, tests, version pin, documentation, and the non-secret `.env` Client ID. Development commands may generate ignored `.venv/`, `node_modules/`, and `dist/` directories. | Keep in Git; generated directories can be rebuilt. |
| `~/Library/Application Support/spotify-mcp/` | Spotify MCP `config.json`, private OAuth `tokens.json`, and `state.sqlite3` when DJ plans or mutation receipts exist. | Private runtime state; never commit. Removing it disconnects Spotify MCP and removes local receipts. |
| `~/.codex/plugins/cache/spotify-mcp/` | Codex's installed plugin snapshot. | Codex-managed and replaceable through install or update; do not edit it as source. |
| `~/.local/bin/save-to-spotify` | Tested official Save to Spotify CLI binary. | Installer-managed and replaceable. |
| `~/.local/share/save-to-spotify/skills/save-to-spotify/` | Official external Save to Spotify production skill and references. | Installer-managed; this repository does not copy or modify it. |
| `~/.agents/skills/save-to-spotify` and supported-client equivalents | Symlinks to the official external skill, created by its installer where applicable. | Installer-managed and replaceable. |
| `~/.config/save-to-spotify/` | Separate private OAuth and DPoP files, TTS configuration, Kokoro Python environment, the approximately 310 MB model, and approximately 27 MB voices file. | Private companion state; never commit. Kokoro can be downloaded again with `save-to-spotify tts setup --engine kokoro`. |
| `~/Library/Caches/save-to-spotify/` | Local voice previews and other disposable cache files. | Safe to remove when no preview is open. |
| macOS temporary directory | Per-request scripts, WAV/MP3 audio, cover art, timeline JSON, and browser-preview files before upload. | Local working artifacts; remove after the episode is verified or the workflow is abandoned. |

Linux and Windows use their normal platform-specific config, data, cache, and temporary directories.
Run `uv run spotify-mcp doctor` and `save-to-spotify --json doctor` to verify the active installation
instead of copying runtime directories between machines. Back up source documents separately; the
Kokoro model, generated environments, plugin cache, CLI, and external skill are reproducible.

Return to the [main README](../README.md) for installation and product examples.
