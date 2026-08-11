"""Snapshot-safe execution of exact playlist permutations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol
from uuid import uuid4

from spotify_mcp.application.playlist_state import read_playlist_state
from spotify_mcp.application.ports import ArtifactRepository, SpotifyGateway
from spotify_mcp.domain.dj import stable_receipt_id
from spotify_mcp.domain.playlist_moves import plan_range_moves, simulate_range_moves

PlaylistMutationAction = Literal["apply", "restore"]
MutationStatus = Literal["dry-run", "unchanged", "accepted", "ambiguous", "stale", "partial"]


class ReceiptRepository(ArtifactRepository, Protocol):
    async def get_receipt(self, receipt_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Verified outcome of a playlist permutation attempt."""

    status: MutationStatus
    action: PlaylistMutationAction
    playlist_id: str
    expected_snapshot_id: str
    initial_snapshot_id: str
    final_snapshot_id: str | None
    completed_moves: int
    total_moves: int
    receipt_id: str | None
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def execute_playlist_permutation(
    spotify: SpotifyGateway,
    artifacts: ArtifactRepository,
    *,
    playlist_id: str,
    identity: Mapping[str, Any],
    original_order: tuple[str, ...],
    target_order: tuple[str, ...],
    expected_snapshot_id: str,
    action: PlaylistMutationAction,
    dry_run: bool,
) -> MutationResult:
    """Execute and verify an exact permutation, persisting progress before writes."""

    current = await read_playlist_state(spotify, playlist_id)
    destination = target_order if action == "apply" else original_order
    if current.snapshot_id != expected_snapshot_id:
        return _mutation_result(
            "stale",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            failure_reason="snapshot-mismatch",
        )
    if action == "apply" and current.order != original_order:
        return _mutation_result(
            "stale",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            failure_reason="source-order-mismatch",
        )
    if sorted(current.order) != sorted(destination):
        return _mutation_result(
            "stale",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            failure_reason="playlist-items-changed",
        )

    moves = plan_range_moves(current.order, destination)
    if not moves:
        return _mutation_result(
            "unchanged",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            final_snapshot_id=current.snapshot_id,
        )
    if dry_run:
        return _mutation_result(
            "dry-run",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            total_moves=len(moves),
            final_snapshot_id=current.snapshot_id,
        )

    attempt_nonce = str(uuid4())
    receipt_id = stable_receipt_id({**dict(identity), "attempt_nonce": attempt_nonce})
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "attempt_nonce": attempt_nonce,
        "playlist_id": playlist_id,
        "action": action,
        "status": "started",
        "expected_snapshot_id": expected_snapshot_id,
        "current_snapshot_id": current.snapshot_id,
        "original_order": list(original_order),
        "target_order": list(target_order),
        "moves": [move.model_dump() for move in moves],
        "completed_moves": 0,
        "warnings": [],
    }
    try:
        await artifacts.put_receipt(receipt_id, receipt)
    except Exception as error:  # a write without its recovery record is never attempted
        return _mutation_result(
            "ambiguous",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            total_moves=len(moves),
            warnings=(f"receipt persistence failed: {error}",),
            failure_reason="receipt-failure",
        )

    working = current.order
    snapshot_id = current.snapshot_id
    completed = 0
    warnings: list[str] = []
    for move in moves:
        expected_order = simulate_range_moves(working, (move,))
        request_failed: Exception | None = None
        try:
            await spotify.request(
                "PUT",
                f"playlists/{playlist_id}/items",
                json={
                    "range_start": move.range_start,
                    "insert_before": move.insert_before,
                    "range_length": move.range_length,
                    "snapshot_id": snapshot_id,
                },
            )
        except Exception as error:
            request_failed = error

        try:
            observed = await read_playlist_state(spotify, playlist_id)
        except Exception as error:
            warnings.append(f"fresh verification read failed: {error}")
            await _best_effort_receipt_update(
                artifacts,
                receipt_id,
                receipt,
                status="ambiguous",
                completed_moves=completed,
                snapshot_id=snapshot_id,
                warnings=warnings,
            )
            return _mutation_result(
                "ambiguous",
                action,
                playlist_id,
                expected_snapshot_id,
                current.snapshot_id,
                completed_moves=completed,
                total_moves=len(moves),
                receipt_id=receipt_id,
                warnings=tuple(warnings),
                failure_reason="verification-read-failure",
            )

        if observed.order != expected_order:
            status: MutationStatus = "ambiguous" if observed.order == working else "partial"
            failure = "ambiguous-write" if status == "ambiguous" else "divergent-order"
            if request_failed is not None:
                warnings.append(f"Spotify write raised {request_failed}")
            warnings.append("fresh playlist state did not prove the requested range move")
            await _best_effort_receipt_update(
                artifacts,
                receipt_id,
                receipt,
                status=status,
                completed_moves=completed,
                snapshot_id=observed.snapshot_id,
                warnings=warnings,
            )
            return _mutation_result(
                status,
                action,
                playlist_id,
                expected_snapshot_id,
                current.snapshot_id,
                final_snapshot_id=observed.snapshot_id,
                completed_moves=completed,
                total_moves=len(moves),
                receipt_id=receipt_id,
                warnings=tuple(warnings),
                failure_reason=failure,
            )

        if request_failed is not None:
            warnings.append("Spotify raised during a write that fresh state subsequently proved")
        working = observed.order
        snapshot_id = observed.snapshot_id
        completed += 1
        receipt_error = await _best_effort_receipt_update(
            artifacts,
            receipt_id,
            receipt,
            status="applying",
            completed_moves=completed,
            snapshot_id=snapshot_id,
            warnings=warnings,
        )
        if receipt_error is not None:
            warnings.append(receipt_error)
            return _mutation_result(
                "partial",
                action,
                playlist_id,
                expected_snapshot_id,
                current.snapshot_id,
                final_snapshot_id=snapshot_id,
                completed_moves=completed,
                total_moves=len(moves),
                receipt_id=receipt_id,
                warnings=tuple(warnings),
                failure_reason="receipt-update-failure",
            )

    try:
        final_state = await read_playlist_state(spotify, playlist_id)
    except Exception as error:
        warnings.append(f"final verification read failed: {error}")
        await _best_effort_receipt_update(
            artifacts,
            receipt_id,
            receipt,
            status="ambiguous",
            completed_moves=completed,
            snapshot_id=snapshot_id,
            warnings=warnings,
        )
        return _mutation_result(
            "ambiguous",
            action,
            playlist_id,
            expected_snapshot_id,
            current.snapshot_id,
            completed_moves=completed,
            total_moves=len(moves),
            receipt_id=receipt_id,
            warnings=tuple(warnings),
            failure_reason="final-verification-read-failure",
        )

    status = "accepted" if final_state.order == destination else "partial"
    failure_reason = None if status == "accepted" else "final-verification-mismatch"
    receipt_error = await _best_effort_receipt_update(
        artifacts,
        receipt_id,
        receipt,
        status=status,
        completed_moves=completed,
        snapshot_id=final_state.snapshot_id,
        warnings=warnings,
    )
    if receipt_error is not None:
        warnings.append(receipt_error)
        status = "partial"
        failure_reason = "receipt-update-failure"
    return _mutation_result(
        status,
        action,
        playlist_id,
        expected_snapshot_id,
        current.snapshot_id,
        final_snapshot_id=final_state.snapshot_id,
        completed_moves=completed,
        total_moves=len(moves),
        receipt_id=receipt_id,
        warnings=tuple(warnings),
        failure_reason=failure_reason,
    )


async def _update_receipt(
    artifacts: ArtifactRepository,
    receipt_id: str,
    receipt: dict[str, Any],
    *,
    status: str,
    completed_moves: int,
    snapshot_id: str,
    warnings: list[str],
) -> None:
    receipt.update(
        status=status,
        completed_moves=completed_moves,
        current_snapshot_id=snapshot_id,
        warnings=list(warnings),
    )
    await artifacts.put_receipt(receipt_id, receipt)


async def _best_effort_receipt_update(
    artifacts: ArtifactRepository,
    receipt_id: str,
    receipt: dict[str, Any],
    *,
    status: str,
    completed_moves: int,
    snapshot_id: str,
    warnings: list[str],
) -> str | None:
    try:
        await _update_receipt(
            artifacts,
            receipt_id,
            receipt,
            status=status,
            completed_moves=completed_moves,
            snapshot_id=snapshot_id,
            warnings=warnings,
        )
    except Exception as error:
        return f"receipt progress update failed: {error}"
    return None


def _mutation_result(
    status: MutationStatus,
    action: PlaylistMutationAction,
    playlist_id: str,
    expected_snapshot_id: str,
    initial_snapshot_id: str,
    *,
    final_snapshot_id: str | None = None,
    completed_moves: int = 0,
    total_moves: int = 0,
    receipt_id: str | None = None,
    warnings: tuple[str, ...] = (),
    failure_reason: str | None = None,
) -> MutationResult:
    return MutationResult(
        status=status,
        action=action,
        playlist_id=playlist_id,
        expected_snapshot_id=expected_snapshot_id,
        initial_snapshot_id=initial_snapshot_id,
        final_snapshot_id=final_snapshot_id,
        completed_moves=completed_moves,
        total_moves=total_moves,
        receipt_id=receipt_id,
        warnings=warnings,
        failure_reason=failure_reason,
    )
