.PHONY: setup run auth doctor codex-install codex-update sync format lint typecheck test release-check build check commit

CODEX ?= codex
CODEX_MARKETPLACE := spotify-mcp
CODEX_PLUGIN := spotify-mcp@spotify-mcp

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
