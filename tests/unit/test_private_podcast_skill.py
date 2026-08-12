from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "spotify-mcp" / "skills" / "create-private-spotify-podcast" / "SKILL.md"


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_private_podcast_skill_keeps_external_companion_and_kokoro_boundary() -> None:
    text = _skill_text()

    assert "$save-to-spotify" in text
    assert "make codex-install-bundle" in text
    assert "save-to-spotify --json doctor" in text
    assert "save-to-spotify tts setup --engine kokoro" in text
    assert "Do not offer or require cloud TTS providers or API" in text


def test_private_podcast_skill_requires_ready_before_playlist_write() -> None:
    text = _skill_text()

    ready_gate = text.index("Attempt playlist placement only after the episode is `READY`")
    playlist_write = text.index("Call `spotify_playlist_add` once")
    assert ready_gate < playlist_write


def test_private_podcast_skill_explains_spotify_processing() -> None:
    text = _skill_text()

    assert "Before asking for upload approval" in text
    assert "Spotify processes uploaded audio asynchronously" in text
    assert "`PROCESSING` or `NOT_READY` for several minutes" in text
    assert "does not mean the plugin failed" in text
    assert "about once per minute" in text
    assert "Do not call processing a failure, re-upload" in text
    assert "playlist placement still requires exact `READY`" in text


def test_private_podcast_skill_reports_delayed_processing_truthfully() -> None:
    text = _skill_text()

    assert "one fresh status" in text
    assert "delayed-but-valid upload" in text
    assert "verified timeline state when" in text
    assert "Continue bounded read-only status" in text
    assert "Never hide the pending state behind a generic success message" in text


def test_private_podcast_skill_rejects_too_short_generated_audio() -> None:
    text = _skill_text()

    assert "measure the assembled audio with `ffprobe`" in text
    assert "at least 45" in text
    assert "return through content approval" in text
    assert "Do not satisfy this guard by padding the episode with silence" in text
    assert "never upload a sub-45-second" in text


def test_private_podcast_skill_hardens_audio_container_and_rights() -> None:
    text = _skill_text()

    assert "owns the source or has the right to reproduce it" in text
    assert "Use MP3 as the version-one output" in text
    assert "require one" in text and "audio stream" in text
    assert "no attached-picture stream" in text
    assert "no unexpected format tags" in text
    assert "`-vn -map_metadata -1`" in text
    assert "cover separately" in text and "`--image`" in text


def test_private_podcast_skill_verifies_owner_privacy_and_every_page() -> None:
    text = _skill_text()

    assert "Read `spotify_status` for the authenticated user ID" in text
    assert "owner ID matches that user ID" in text
    assert "`public=false`" in text
    assert "Read every `spotify_playlist_items` page" in text
    assert "observing the exact episode URI" in text


def test_private_podcast_skill_stops_on_visibility_mismatch() -> None:
    text = _skill_text()
    normalized = " ".join(text.split())

    assert "creation or a metadata update re-reads as public" in text
    assert "do not retry visibility" in text
    assert "create a duplicate playlist" in normalized
    assert "ask before removing or unfollowing it" in text


def test_private_podcast_skill_has_read_first_fallback_without_reupload() -> None:
    text = _skill_text()
    normalized = " ".join(text.split())

    assert "never retry the write blindly" in text
    assert "do not treat that as an episode-production failure" in normalized
    assert "private Save to Spotify show" in text
    assert "do not seek a write workaround" in text


def test_private_podcast_skill_blocks_sensitive_uploads() -> None:
    text = _skill_text()

    assert "credentials, third-party" in text
    assert "confidential business information" in text
    assert "Ask the user for a redacted source" in text
