import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _dry_run(target: str) -> str:
    completed = subprocess.run(
        ["make", "--dry-run", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def test_basic_codex_install_does_not_install_save_to_spotify() -> None:
    output = _dry_run("codex-install")

    assert "save-to-spotify setup" not in output
    assert "saveto.spotify.com/install.sh" not in output


def test_bundle_install_adds_pinned_companion_setup_and_doctor() -> None:
    output = _dry_run("codex-install-bundle")

    assert "SAVE_TO_SPOTIFY_VERSION" not in output
    assert "https://saveto.spotify.com/install.sh" in output
    assert '--version "0.2.0"' in output
    assert '"$sts_bin" setup' in output
    assert '"$sts_bin" --json doctor' in output
    assert "local Kokoro install on first use" in output


def test_bundle_update_keeps_basic_update_and_checks_companion() -> None:
    output = _dry_run("codex-update-bundle")

    assert "plugin marketplace upgrade" in output
    assert "https://saveto.spotify.com/install.sh" in output
    assert '"$sts_bin" --json doctor' in output
