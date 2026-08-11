"""Repository-owned release contract checks with no runtime dependencies."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "spotify_mcp"
PLUGIN = ROOT / "plugins" / "spotify-mcp"

FORBIDDEN_ENDPOINTS = {
    "/recommendations": "Spotify recommendations are retired for new applications",
    "/playlists/{playlist_id}/tracks": "playlist item routes were renamed to /items",
}


def python_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def tool_names() -> set[str]:
    names: set[str] = set()
    for path in (SOURCE / "mcp_server" / "tools").glob("*.py"):
        for value in python_strings(path):
            if value.startswith("spotify_") and re.fullmatch(r"spotify_[a-z0-9_]+", value):
                names.add(value)
    names.add("spotify_status")
    return names


def check_endpoints(errors: list[str]) -> None:
    for path in SOURCE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(r'("PUT"|"DELETE")\s*,\s*"/me/albums"', source):
            errors.append(f"{path.relative_to(ROOT)}: saved-album writes must use /me/library")
        for value in python_strings(path):
            for endpoint, reason in FORBIDDEN_ENDPOINTS.items():
                if endpoint in value:
                    errors.append(f"{path.relative_to(ROOT)}: {reason}: {value!r}")
            if re.search(r"/playlists/[^\s]+/tracks", value):
                errors.append(
                    f"{path.relative_to(ROOT)}: playlist item routes must use /items: {value!r}"
                )


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}
    header = text.split("\n---\n", 1)[0][4:]
    result: dict[str, str] = {}
    for line in header.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def check_plugin(errors: list[str]) -> None:
    descriptor_path = PLUGIN / ".codex-plugin" / "plugin.json"
    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    for path in (descriptor_path, marketplace_path, PLUGIN / ".mcp.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")

    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if descriptor.get("name") != "spotify-mcp":
        errors.append("plugin descriptor name must be spotify-mcp")
    if descriptor.get("version") != "0.1.0":
        errors.append("plugin descriptor version must match the initial 0.1.0 release")

    published_tools = tool_names()
    for skill_dir in sorted((PLUGIN / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        metadata = frontmatter(skill_path)
        if metadata.get("name") != skill_dir.name:
            errors.append(f"{skill_path.relative_to(ROOT)}: frontmatter name must match folder")
        description = metadata.get("description", "")
        if not description or "Use" not in description:
            errors.append(f"{skill_path.relative_to(ROOT)}: description needs a use trigger")
        for fixture_name in ("triggers.yaml", "eval.yaml"):
            fixture = skill_dir / "tests" / fixture_name
            text = fixture.read_text(encoding="utf-8")
            if f"skill: {skill_dir.name}" not in text:
                errors.append(f"{fixture.relative_to(ROOT)}: skill name mismatch")
        text = skill_path.read_text(encoding="utf-8")
        referenced = set(re.findall(r"`(spotify_[a-z0-9_]+)`", text))
        unknown = sorted(referenced - published_tools)
        if unknown:
            errors.append(
                f"{skill_path.relative_to(ROOT)}: references unknown tools: {', '.join(unknown)}"
            )


def check_docs(errors: list[str]) -> None:
    markdown_paths = [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]
    markdown_paths.extend(PLUGIN.rglob("*.md"))
    for path in markdown_paths:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_target = target.split("#", 1)[0]
            if relative_target and not (path.parent / relative_target).resolve().exists():
                errors.append(f"{path.relative_to(ROOT)}: broken local link target: {target}")

    tool_catalog = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
    undocumented = sorted(name for name in tool_names() if f"`{name}`" not in tool_catalog)
    if undocumented:
        errors.append(f"docs/tools.md: undocumented tools: {', '.join(undocumented)}")


def check_local_startup(errors: list[str]) -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if "SPOTIFY_CLIENT_ID=" not in env_example:
        errors.append(".env.example: SPOTIFY_CLIENT_ID is required")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    if not re.search(
        r"^run:\n\t@uv run spotify-mcp connect 1>&2\n\t@exec uv run spotify-mcp serve$",
        makefile,
        re.M,
    ):
        errors.append("Makefile: run must connect when needed and then start stdio MCP")


def main() -> int:
    errors: list[str] = []
    check_endpoints(errors)
    check_plugin(errors)
    check_docs(errors)
    check_local_startup(errors)
    if errors:
        print("Release contract check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Release contracts OK: {len(tool_names())} tools, 3 skills, current endpoints")
    print("Known fallback: Spotify /audio-features is deprecated and may use ReccoBeats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
