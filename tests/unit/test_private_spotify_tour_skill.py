from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "spotify-mcp" / "skills" / "create-private-spotify-tour" / "SKILL.md"


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_tour_skill_composes_discovery_extraction_maps_and_production() -> None:
    text = _skill_text()

    discovery = text.index("invoke `find-tour`")
    extraction = text.index("invoke `tour-path-extractor`")
    approval = text.index("Present the route, chapter candidates")
    production = text.index("to `$create-private-spotify-podcast`")
    assert discovery < extraction < approval < production
    assert "specific tour URL, skip discovery" in text
    assert "existing Google Maps tools" in text
    assert "numbered route legs or a GPX/GeoJSON handoff" in text
    assert "silently dropping stops" in text


def test_tour_skill_keeps_route_content_and_production_boundaries() -> None:
    text = _skill_text()
    normalized = " ".join(text.split())

    assert "Never copy paid narration" in text
    assert "route structure, not narration to copy" in text
    assert "Tour-route approval does not replace" in normalized
    assert "exact `READY` gate" in text


def test_tour_skill_requires_interactive_route_approval_actions() -> None:
    text = _skill_text()

    assert "`spotify_render_route_approval`" in text
    assert '"Approve route"' in text
    assert '"Adjust pins"' in text
    assert "Do not leave the route-approval gate as a prose-only question" in text


def test_tour_skill_requires_map_metadata_and_final_audio_timestamps() -> None:
    text = _skill_text()

    assert "[City/Spot Name]: The 30-Minute Secret Walking Tour" in text
    assert "📍 Starting Point: [Google Maps Pin Link]" in text
    assert "⏱ Duration: [verified duration] | Distance: [verified distance]" in text
    assert "🗺 Interactive Route Map:" in text
    assert "Always duplicate the" in text and "chapter times in show notes" in text
    assert "final assembled audio" in text
    assert "do not claim a" in text and "30-minute tour" in text


def test_general_private_podcast_skill_stays_text_focused() -> None:
    general = (
        ROOT / "plugins" / "spotify-mcp" / "skills" / "create-private-spotify-podcast" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "documents, PDFs, notes, or transcripts" in general
    assert "find-tour" not in general
    assert "tour-path-extractor" not in general
