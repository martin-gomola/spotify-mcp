.PHONY: setup run auth doctor codex-install codex-install-bundle codex-update codex-update-bundle save-to-spotify-install save-to-spotify-setup save-to-spotify-doctor sync format lint typecheck test release-check build check commit

CODEX ?= codex
CODEX_MARKETPLACE := spotify-mcp
CODEX_PLUGIN := spotify-mcp@spotify-mcp
SAVE_TO_SPOTIFY ?= save-to-spotify
SAVE_TO_SPOTIFY_VERSION ?= 0.2.0
SAVE_TO_SPOTIFY_INSTALLER ?= https://saveto.spotify.com/install.sh

# Connect only when needed, verify live Spotify access, and return to the shell.
setup:
	@uv run spotify-mcp connect
	@uv run spotify-mcp doctor

# Foreground stdio server for manual clients and development. Codex starts this itself.
run:
	@uv run spotify-mcp connect 1>&2
	@exec uv run spotify-mcp serve

auth:
	uv run spotify-mcp auth

doctor:
	uv run spotify-mcp doctor

# Install or refresh the public marketplace, then install the plugin when missing.
codex-install: setup
	@command -v $(CODEX) >/dev/null || { echo "Codex CLI is required: https://developers.openai.com/codex/cli" >&2; exit 1; }
	@if $(CODEX) plugin marketplace list --json | grep -Fq '"name": "$(CODEX_MARKETPLACE)"'; then \
		$(CODEX) plugin marketplace upgrade $(CODEX_MARKETPLACE); \
	else \
		$(CODEX) plugin marketplace add martin-gomola/spotify-mcp --ref main; \
	fi
	@if $(CODEX) plugin list --json | grep -Fq '"pluginId": "$(CODEX_PLUGIN)"'; then \
		echo "$(CODEX_PLUGIN) is already installed"; \
	else \
		$(CODEX) plugin add $(CODEX_PLUGIN); \
	fi
	@$(CODEX) plugin list --marketplace $(CODEX_MARKETPLACE)
	@echo "Spotify MCP is ready. Start a new Codex task to load the plugin."

codex-update: setup
	@$(CODEX) plugin marketplace upgrade $(CODEX_MARKETPLACE)
	@$(CODEX) plugin list --marketplace $(CODEX_MARKETPLACE)
	@echo "Start a new Codex task to load the updated plugin."

# Optional companion bundle for private spoken-word episodes. The official installer verifies the
# release checksum and owns the external skill; this repository does not copy its files or tokens.
save-to-spotify-install:
	@set -eu; \
	data_root="$${XDG_DATA_HOME:-$$HOME/.local/share}"; \
	sts_bin="$$(command -v $(SAVE_TO_SPOTIFY) 2>/dev/null || true)"; \
	if [ -z "$$sts_bin" ] && [ -x "$$HOME/.local/bin/save-to-spotify" ]; then sts_bin="$$HOME/.local/bin/save-to-spotify"; fi; \
	installed_version=""; \
	if [ -n "$$sts_bin" ]; then installed_version="$$("$$sts_bin" version 2>/dev/null | awk '{print $$2}')"; fi; \
	if [ "$$installed_version" = "$(SAVE_TO_SPOTIFY_VERSION)" ] && [ -f "$$data_root/save-to-spotify/skills/save-to-spotify/SKILL.md" ]; then \
		echo "Save to Spotify $(SAVE_TO_SPOTIFY_VERSION) and its skill are already installed."; \
	else \
		command -v curl >/dev/null || { echo "curl is required to install Save to Spotify" >&2; exit 1; }; \
		curl -fsSL "$(SAVE_TO_SPOTIFY_INSTALLER)" | bash -s -- --version "$(SAVE_TO_SPOTIFY_VERSION)"; \
	fi

save-to-spotify-doctor: save-to-spotify-install
	@set -eu; \
	sts_bin="$$(command -v $(SAVE_TO_SPOTIFY) 2>/dev/null || true)"; \
	if [ -z "$$sts_bin" ] && [ -x "$$HOME/.local/bin/save-to-spotify" ]; then sts_bin="$$HOME/.local/bin/save-to-spotify"; fi; \
	[ -n "$$sts_bin" ] || { echo "Save to Spotify was installed but is not on PATH" >&2; exit 1; }; \
	"$$sts_bin" --json doctor

save-to-spotify-setup: save-to-spotify-install
	@set -eu; \
	sts_bin="$$(command -v $(SAVE_TO_SPOTIFY) 2>/dev/null || true)"; \
	if [ -z "$$sts_bin" ] && [ -x "$$HOME/.local/bin/save-to-spotify" ]; then sts_bin="$$HOME/.local/bin/save-to-spotify"; fi; \
	[ -n "$$sts_bin" ] || { echo "Save to Spotify was installed but is not on PATH" >&2; exit 1; }; \
	"$$sts_bin" setup; \
	"$$sts_bin" --json doctor; \
	echo "No TTS API key is required. The podcast skill will offer the local Kokoro install on first use."

codex-install-bundle: codex-install save-to-spotify-setup
	@echo "Spotify MCP and Save to Spotify are ready. Start a new Codex task to load both skills."

codex-update-bundle: codex-update save-to-spotify-doctor
	@echo "Spotify MCP and Save to Spotify are up to date. Start a new Codex task."

sync:
	uv sync --all-groups
	npm ci

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .
	npm run typecheck:ui

typecheck:
	uv run mypy src

test:
	uv run pytest
	npm run test:ui

release-check:
	uv run python scripts/check_release.py

build:
	npm run build:ui
	uv build

check: lint typecheck test release-check build

commit:
	@read -r -p "Commit message: " msg && git commit -am "$$msg"
