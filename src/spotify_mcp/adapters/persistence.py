"""Private SQLite persistence for immutable artifacts and mutation receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

_SCHEMA_VERSION = 1
_KIND_PREFIXES = {"analysis": "dja", "plan": "djp"}
_FORBIDDEN_KEYS = {
    "accesstoken",
    "authorization",
    "clientsecret",
    "idtoken",
    "password",
    "refreshtoken",
    "token",
}


class ArtifactIntegrityError(ValueError):
    """Stored state no longer matches its recorded content digest."""


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically for hashing and byte-for-byte comparison."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def content_digest(value: object) -> str:
    """Return a SHA-256 digest of canonical JSON content."""

    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class SQLiteArtifactRepository:
    """Async facade over a small private SQLite database.

    Connections stay thread-local to each operation, so callers never block the
    event loop and no sqlite connection crosses a thread boundary.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        default_path = user_data_path("spotify-mcp", appauthor=False) / "state.sqlite3"
        self.path = Path(path or default_path).expanduser().resolve()
        self._initialize_lock = threading.Lock()
        self._initialized = False

    async def put_immutable(self, kind: str, payload: Mapping[str, Any]) -> str:
        return await asyncio.to_thread(self._put_immutable, kind, dict(payload))

    async def get(self, artifact_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get, artifact_id)

    async def put_receipt(self, receipt_id: str, payload: Mapping[str, Any]) -> None:
        await asyncio.to_thread(self._put_receipt, receipt_id, dict(payload))

    async def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_receipt, receipt_id)

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        digest TEXT NOT NULL,
                        schema_version INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS receipts (
                        receipt_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        digest TEXT NOT NULL,
                        schema_version INTEGER NOT NULL
                    );
                    """
                )
            os.chmod(self.path, 0o600)
            self._initialized = True

    def _put_immutable(self, kind: str, payload: dict[str, Any]) -> str:
        try:
            prefix = _KIND_PREFIXES[kind]
        except KeyError as error:
            raise ValueError(f"unsupported immutable artifact kind: {kind}") from error
        _assert_no_credentials(payload)
        digest_payload = {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            "payload": payload,
        }
        digest = content_digest(digest_payload)
        artifact_id = f"{prefix}_{digest[:24]}"
        payload_json = canonical_json(payload)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifacts
                    (artifact_id, kind, payload_json, digest, schema_version)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, kind, payload_json, digest, _SCHEMA_VERSION),
            )
            row = connection.execute(
                "SELECT kind, payload_json, digest, schema_version "
                "FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        stored_payload = self._verify_artifact_row(artifact_id, row)
        if stored_payload != payload:
            raise ArtifactIntegrityError(f"artifact ID collision detected: {artifact_id}")
        return artifact_id

    def _get(self, artifact_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT kind, payload_json, digest, schema_version "
                "FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._verify_artifact_row(artifact_id, row)

    def _verify_artifact_row(self, artifact_id: str, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise KeyError(f"artifact not found: {artifact_id}")
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as error:
            raise ArtifactIntegrityError(
                f"artifact payload is invalid JSON: {artifact_id}"
            ) from error
        if not isinstance(payload, dict):
            raise ArtifactIntegrityError(f"artifact payload is not an object: {artifact_id}")
        kind = str(row["kind"])
        schema_version = int(row["schema_version"])
        digest = content_digest(
            {"schema_version": schema_version, "kind": kind, "payload": payload}
        )
        prefix = _KIND_PREFIXES.get(kind)
        expected_id = f"{prefix}_{digest[:24]}" if prefix else ""
        if (
            schema_version != _SCHEMA_VERSION
            or digest != row["digest"]
            or artifact_id != expected_id
        ):
            raise ArtifactIntegrityError(f"artifact digest verification failed: {artifact_id}")
        _assert_no_credentials(payload)
        return payload

    def _put_receipt(self, receipt_id: str, payload: dict[str, Any]) -> None:
        if not receipt_id.startswith("djr_"):
            raise ValueError("receipt_id must start with djr_")
        _assert_no_credentials(payload)
        payload_json = canonical_json(payload)
        digest = content_digest(
            {"schema_version": _SCHEMA_VERSION, "receipt_id": receipt_id, "payload": payload}
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO receipts (receipt_id, payload_json, digest, schema_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(receipt_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    digest = excluded.digest,
                    schema_version = excluded.schema_version
                """,
                (receipt_id, payload_json, digest, _SCHEMA_VERSION),
            )
        self._get_receipt(receipt_id)

    def _get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload_json, digest, schema_version FROM receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"receipt not found: {receipt_id}")
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as error:
            raise ArtifactIntegrityError(
                f"receipt payload is invalid JSON: {receipt_id}"
            ) from error
        if not isinstance(payload, dict):
            raise ArtifactIntegrityError(f"receipt payload is not an object: {receipt_id}")
        schema_version = int(row["schema_version"])
        digest = content_digest(
            {"schema_version": schema_version, "receipt_id": receipt_id, "payload": payload}
        )
        if schema_version != _SCHEMA_VERSION or digest != row["digest"]:
            raise ArtifactIntegrityError(f"receipt digest verification failed: {receipt_id}")
        _assert_no_credentials(payload)
        return payload


def _assert_no_credentials(value: object, key: str | None = None) -> None:
    normalized_key = "".join(character for character in (key or "").lower() if character.isalnum())
    if normalized_key in _FORBIDDEN_KEYS:
        raise ValueError(f'artifacts must not contain credential field "{key}"')
    if isinstance(value, str) and value.lower().startswith("bearer "):
        raise ValueError("artifacts must not contain bearer credentials")
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            _assert_no_credentials(child_value, str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_no_credentials(child)
