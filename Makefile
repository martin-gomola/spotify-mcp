.PHONY: run auth doctor sync format lint typecheck test release-check build check

run:
	@uv run spotify-mcp connect 1>&2
	@exec uv run spotify-mcp serve

auth:
	uv run spotify-mcp auth

doctor:
	uv run spotify-mcp doctor

sync:
	uv sync --all-groups

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest

release-check:
	uv run python scripts/check_release.py

build:
	uv build

check: lint typecheck test release-check build
