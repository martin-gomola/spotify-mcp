from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "spotify-mcp" / "skills" / "manage-private-spotify-podcasts" / "SKILL.md"


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_management_skill_keeps_external_auth_and_tool_boundary() -> None:
    text = _skill_text()

    assert "make codex-install-bundle" in text
    assert "save-to-spotify --json doctor" in text
    assert "external `$save-to-spotify` setup guidance" in text
    assert "Never print, inspect, or transfer either tool's token" in text
    assert "does not delete shows or mutate Spotify MCP playlists" in text


def test_management_skill_resolves_only_exact_private_episode() -> None:
    text = _skill_text()

    assert "`save-to-spotify --json shows`" in text
    assert "`save-to-spotify --json episodes --show-id <exact-show-uri>`" in text
    assert "title, exact episode URI, show, and" in text
    assert "If zero episodes or multiple episodes match, do not guess" in text
    assert "Never substitute a Spotify catalog episode" in text


def test_management_skill_confirms_irreversible_delete() -> None:
    text = _skill_text()

    assert "Treat episode deletion as irreversible" in text
    assert "Ask for explicit confirmation" in text
    assert "names that exact URI" in text
    assert "explicitly commands its deletion" in text
    assert "`save-to-spotify --json episodes delete <exact-episode-uri>`" in text


def test_management_skill_can_delete_stuck_processing_episode() -> None:
    text = _skill_text()

    assert "including `PROCESSING`, `NOT_READY`, `READY`" in text
    assert "Deletion does not require a readiness wait" in text
    assert "cleaning up a stuck upload" in text


def test_management_skill_reads_after_ambiguous_delete_and_verifies_absence() -> None:
    text = _skill_text()

    assert "re-list the show's complete" in text
    assert "Never repeat the delete blindly" in text
    assert "confirming that the exact" in text and "episode URI is absent" in text
    assert "Do not claim deletion from the write response alone" in text


def test_management_skill_keeps_playlist_cleanup_separate() -> None:
    text = _skill_text()

    assert "playlist cleanup is separate" in text
    assert "Do not mutate playlists as a side effect" in text
    assert "any separate" in text and "playlist cleanup that remains" in text
