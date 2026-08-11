"""Interfaces owned by application use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class SpotifyGateway(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any: ...


class ArtifactRepository(Protocol):
    async def put_immutable(self, kind: str, payload: Mapping[str, Any]) -> str: ...

    async def get(self, artifact_id: str) -> dict[str, Any]: ...

    async def put_receipt(self, receipt_id: str, payload: Mapping[str, Any]) -> None: ...
