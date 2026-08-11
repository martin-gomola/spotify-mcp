from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from spotify_mcp.adapters.persistence import (
    ArtifactIntegrityError,
    SQLiteArtifactRepository,
)
from spotify_mcp.domain.dj import stable_receipt_id


@pytest.mark.anyio
async def test_immutable_artifacts_are_content_addressed_and_verified(tmp_path: Path) -> None:
    repository = SQLiteArtifactRepository(tmp_path / "private" / "state.sqlite3")
    payload = {"artifact_kind": "analysis", "playlist_id": "playlist-1", "tracks": []}
    first = await repository.put_immutable("analysis", payload)
    second = await repository.put_immutable("analysis", payload)
    assert first == second
    assert first.startswith("dja_")
    assert await repository.get(first) == payload
    assert repository.path.stat().st_mode & 0o777 == 0o600
    assert repository.path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.anyio
async def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    repository = SQLiteArtifactRepository(tmp_path / "state.sqlite3")
    artifact_id = await repository.put_immutable("plan", {"artifact_kind": "plan"})
    with closing(sqlite3.connect(repository.path)) as connection, connection:
        connection.execute(
            "UPDATE artifacts SET payload_json = ? WHERE artifact_id = ?",
            ('{"artifact_kind":"plan","tampered":true}', artifact_id),
        )
    with pytest.raises(ArtifactIntegrityError, match="digest verification"):
        await repository.get(artifact_id)


@pytest.mark.anyio
async def test_receipts_have_stable_ids_and_verified_updates(tmp_path: Path) -> None:
    repository = SQLiteArtifactRepository(tmp_path / "state.sqlite3")
    identity = {"plan_id": "djp_123", "action": "apply", "source_snapshot_id": "s1"}
    receipt_id = stable_receipt_id(identity)
    assert receipt_id == stable_receipt_id(identity)
    await repository.put_receipt(receipt_id, {"status": "started", **identity})
    await repository.put_receipt(receipt_id, {"status": "accepted", **identity})
    assert await repository.get_receipt(receipt_id) == {"status": "accepted", **identity}


@pytest.mark.anyio
async def test_credentials_are_rejected_before_persistence(tmp_path: Path) -> None:
    repository = SQLiteArtifactRepository(tmp_path / "state.sqlite3")
    with pytest.raises(ValueError, match="credential field"):
        await repository.put_immutable("analysis", {"access_token": "secret"})
    assert not repository.path.exists()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
