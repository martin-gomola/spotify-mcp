from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from uuid import UUID

import pytest

from spotify_mcp.application.dj import analyze_playlist, apply_plan, restore_playlist
from spotify_mcp.application.playlist_mutation import execute_playlist_permutation
from spotify_mcp.application.playlist_state import read_playlist_state
from spotify_mcp.domain.audio import (
    AudioFeature,
    AudioLookupReport,
    AudioLookupSource,
    AudioProvider,
    FeatureObservation,
    FeatureProvenance,
    TrackAudioAnalysis,
)
from spotify_mcp.domain.dj import (
    DjAnalysis,
    DjTrack,
    camelot_code,
    normalize_tempo,
    occurrence_tokens,
    plan_dj_set,
)
from spotify_mcp.domain.playlist_moves import plan_range_moves, simulate_range_moves


class MemoryArtifacts:
    def __init__(self) -> None:
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, dict[str, Any]] = {}

    async def put_immutable(self, kind: str, payload: Mapping[str, Any]) -> str:
        artifact_id = f"{kind}-1"
        self.artifacts[artifact_id] = dict(payload)
        return artifact_id

    async def get(self, artifact_id: str) -> dict[str, Any]:
        return self.artifacts[artifact_id]

    async def put_receipt(self, receipt_id: str, payload: Mapping[str, Any]) -> None:
        self.receipts[receipt_id] = dict(payload)

    async def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self.receipts[receipt_id]


class PlaylistGateway:
    def __init__(
        self, order: list[str], *, snapshot: str = "s1", apply_writes: bool = True
    ) -> None:
        self.order = order
        self.snapshot = snapshot
        self.apply_writes = apply_writes
        self.put_count = 0

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and path == "playlists/playlist-1":
            return {"name": "Set", "snapshot_id": self.snapshot}
        if method == "GET" and path == "playlists/playlist-1/items":
            offset = int((params or {}).get("offset", 0))
            items = [
                {
                    "item": {
                        "id": identity,
                        "uri": f"spotify:track:{identity}",
                        "name": identity.upper(),
                        "artists": [{"id": f"artist-{identity}", "name": identity}],
                    }
                }
                for identity in self.order
            ]
            return {"items": items[offset : offset + 50], "total": len(items)}
        if method == "PUT" and path == "playlists/playlist-1/items":
            self.put_count += 1
            assert isinstance(json, dict)
            if self.apply_writes:
                start = int(json["range_start"])
                length = int(json["range_length"])
                insert_before = int(json["insert_before"])
                moved = self.order[start : start + length]
                del self.order[start : start + length]
                insert_at = insert_before - length if insert_before > start else insert_before
                self.order[insert_at:insert_at] = moved
                self.snapshot = f"s{self.put_count + 1}"
            return {"snapshot_id": self.snapshot}
        raise AssertionError(f"unexpected request: {method} {path}")


class VerificationFailureGateway(PlaylistGateway):
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and self.put_count:
            raise RuntimeError("network unavailable")
        return await super().request(method, path, params=params, json=json)


class SnapshotDriftGateway(PlaylistGateway):
    def __init__(self, order: list[str]) -> None:
        super().__init__(order)
        self.metadata_reads = 0

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and path == "playlists/playlist-1":
            self.metadata_reads += 1
            snapshot = "s1" if self.metadata_reads == 1 else "s2"
            return {"name": "Set", "snapshot_id": snapshot}
        return await super().request(method, path, params=params, json=json)


class ReceiptUpdateFailureArtifacts(MemoryArtifacts):
    def __init__(self) -> None:
        super().__init__()
        self.receipt_writes = 0

    async def put_receipt(self, receipt_id: str, payload: Mapping[str, Any]) -> None:
        self.receipt_writes += 1
        if self.receipt_writes > 1:
            raise OSError("disk full")
        await super().put_receipt(receipt_id, payload)


class AudioGateway:
    def __init__(self) -> None:
        self.track_ids: list[str] = []
        self.source = AudioLookupSource.AUTO

    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[Any] | None = None,
    ) -> AudioLookupReport:
        self.track_ids = track_ids
        self.source = source
        return AudioLookupReport(
            requested_track_ids=track_ids,
            tracks=[
                TrackAudioAnalysis(
                    track_id=track_id,
                    tempo=audio_feature(120),
                    energy=audio_feature(0.6),
                    key=audio_feature(0),
                    mode=audio_feature(1),
                )
                for track_id in track_ids
            ],
            missing_track_ids=[],
            warnings=["fallback provider used"],
        )


class SnapshotChangingAudioGateway(AudioGateway):
    def __init__(self, spotify: PlaylistGateway) -> None:
        super().__init__()
        self.spotify = spotify

    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[Any] | None = None,
    ) -> AudioLookupReport:
        report = await super().lookup(track_ids, source=source, overrides=overrides)
        self.spotify.snapshot = "s2"
        return report


class IncompleteAudioGateway(AudioGateway):
    async def lookup(
        self,
        track_ids: list[str],
        source: AudioLookupSource = AudioLookupSource.AUTO,
        overrides: list[Any] | None = None,
    ) -> AudioLookupReport:
        return AudioLookupReport(
            requested_track_ids=track_ids,
            tracks=[TrackAudioAnalysis(track_id=track_id) for track_id in track_ids],
            missing_track_ids=[],
        )


def audio_feature(value: float | int) -> AudioFeature:
    return AudioFeature(
        selected=FeatureObservation(
            value=value,
            provenance=FeatureProvenance(provider=AudioProvider.RECCOBEATS),
        )
    )


def track(
    identity: str,
    position: int,
    *,
    energy: float,
    bpm: float,
    camelot: str,
    artist: str,
) -> DjTrack:
    return DjTrack(
        position_token=f"spotify:track:{identity}#0",
        identity=f"spotify:track:{identity}",
        original_position=position,
        track_id=identity,
        name=identity,
        artist_ids=(artist,),
        bpm=bpm,
        normalized_bpm=normalize_tempo(bpm),
        energy=energy,
        camelot=camelot,
    )


def stored_plan() -> dict[str, Any]:
    analysis = DjAnalysis(
        playlist_id="playlist-1",
        playlist_name="Set",
        snapshot_id="s1",
        tracks=(
            track("a", 0, energy=0.9, bpm=128, camelot="8B", artist="same"),
            track("b", 1, energy=0.2, bpm=126, camelot="9B", artist="other"),
        ),
    )
    plan = plan_dj_set(analysis, "analysis-1")
    assert plan.target_order == ("spotify:track:b#0", "spotify:track:a#0")
    return {"artifact_kind": "plan", **asdict(plan)}


def test_camelot_and_tempo_normalization() -> None:
    assert camelot_code(0, 1) == "8B"
    assert camelot_code(8, 0) == "1A"
    assert normalize_tempo(64) == 128
    assert normalize_tempo(174) == 87


def test_occurrence_tokens_keep_duplicate_positions_distinct() -> None:
    assert occurrence_tokens(("same", "other", "same")) == (
        "same#0",
        "other#0",
        "same#1",
    )


def test_planner_is_deterministic_and_preserves_every_position() -> None:
    analysis = DjAnalysis(
        playlist_id="p",
        playlist_name="Set",
        snapshot_id="snapshot",
        tracks=(
            track("one", 0, energy=0.15, bpm=64, camelot="8B", artist="artist-a"),
            track("two", 1, energy=0.9, bpm=128, camelot="9B", artist="artist-a"),
            track("three", 2, energy=0.55, bpm=130, camelot="10B", artist="artist-b"),
        ),
    )
    first = plan_dj_set(analysis, "dja_1", artist_spacing=2)
    second = plan_dj_set(analysis, "dja_1", artist_spacing=2)
    assert first == second
    assert sorted(first.target_order) == sorted(first.original_order)
    assert first.target_order[0] == "spotify:track:one#0"
    assert first.target_order[1] == "spotify:track:three#0"


def test_range_moves_reach_the_exact_target() -> None:
    current = ("a", "b", "c", "d")
    target = ("c", "d", "a", "b")
    moves = plan_range_moves(current, target)
    assert simulate_range_moves(current, moves) == target


@pytest.mark.anyio
async def test_playlist_state_reader_paginates_and_disambiguates_duplicates() -> None:
    identities = [f"track-{index}" for index in range(50)] + ["track-0"]
    state = await read_playlist_state(PlaylistGateway(identities), "playlist-1")

    assert state.playlist_id == "playlist-1"
    assert state.name == "Set"
    assert state.snapshot_id == "s1"
    assert len(state.positions) == 51
    assert state.positions[0].position_token == "spotify:track:track-0#0"
    assert state.positions[-1].position_token == "spotify:track:track-0#1"
    assert state.positions[0].item_type == "track"
    assert state.positions[0].fixed is False
    assert state.order == tuple(position.position_token for position in state.positions)


@pytest.mark.anyio
async def test_playlist_state_reader_rejects_snapshot_drift() -> None:
    with pytest.raises(ValueError, match="playlist changed while its items were being read"):
        await read_playlist_state(SnapshotDriftGateway(["a", "b"]), "playlist-1")


@pytest.mark.anyio
async def test_shared_permutation_executor_preserves_dry_run_contract() -> None:
    artifacts = MemoryArtifacts()
    spotify = PlaylistGateway(["a", "b"])

    result = await execute_playlist_permutation(
        spotify,
        artifacts,
        playlist_id="playlist-1",
        identity={"action": "apply", "plan_id": "plan-1"},
        original_order=("spotify:track:a#0", "spotify:track:b#0"),
        target_order=("spotify:track:b#0", "spotify:track:a#0"),
        expected_snapshot_id="s1",
        action="apply",
        dry_run=True,
    )

    assert result.status == "dry-run"
    assert result.total_moves == 1
    assert result.final_snapshot_id == "s1"
    assert spotify.put_count == 0


@pytest.mark.anyio
async def test_dj_analysis_enriches_audio_and_merges_explicit_features_last() -> None:
    artifacts = MemoryArtifacts()
    spotify = PlaylistGateway(["a", "b"])
    audio = AudioGateway()

    _, analysis = await analyze_playlist(
        spotify,
        artifacts,
        "playlist-1",
        audio=audio,
        source=AudioLookupSource.RECCOBEATS,
        features=[{"track_id": "a", "bpm": 130}],
    )

    assert audio.track_ids == ["a", "b"]
    assert audio.source is AudioLookupSource.RECCOBEATS
    assert analysis.tracks[0].bpm == 130
    assert analysis.tracks[0].energy == 0.6
    assert analysis.tracks[0].camelot == "8B"
    assert analysis.tracks[1].bpm == 120
    assert analysis.warnings == ("fallback provider used",)


@pytest.mark.anyio
async def test_dj_analysis_persists_field_evidence_coverage_and_legacy_override() -> None:
    artifacts = MemoryArtifacts()

    analysis_id, analysis = await analyze_playlist(
        PlaylistGateway(["a"]),
        artifacts,
        "playlist-1",
        audio=AudioGateway(),
        source=AudioLookupSource.RECCOBEATS,
        features=[{"track_id": "a", "bpm": 130}],
    )

    track = analysis.tracks[0]
    assert track.sources == ("override", "reccobeats")
    assert {item.field: item.provider for item in track.provenance} == {
        "tempo": "override",
        "energy": "reccobeats",
        "key": "reccobeats",
        "mode": "reccobeats",
    }
    assert track.unresolved_fields == ()
    assert analysis.audio_source == "reccobeats"
    assert analysis.coverage.complete_count == 1
    assert analysis.coverage.unresolved_position_tokens == ()
    stored_track = artifacts.artifacts[analysis_id]["tracks"][0]
    assert stored_track["provenance"][0]["fetched_at"]


@pytest.mark.anyio
async def test_dj_analysis_error_policy_rejects_before_artifact_creation() -> None:
    artifacts = MemoryArtifacts()

    with pytest.raises(ValueError, match="DJ analysis is incomplete for 1 position"):
        await analyze_playlist(
            PlaylistGateway(["a"]),
            artifacts,
            "playlist-1",
            audio=IncompleteAudioGateway(),
            missing_feature_policy="error",
        )

    assert artifacts.artifacts == {}


@pytest.mark.anyio
async def test_dj_anchor_records_unresolved_fields_and_fixes_missing_tempo() -> None:
    artifacts = MemoryArtifacts()

    _, analysis = await analyze_playlist(
        PlaylistGateway(["a"]),
        artifacts,
        "playlist-1",
        audio=IncompleteAudioGateway(),
    )

    assert analysis.tracks[0].fixed is True
    assert analysis.tracks[0].unresolved_fields == ("tempo", "key_or_mode", "energy")
    assert analysis.coverage.unresolved_position_tokens == ("spotify:track:a#0",)


@pytest.mark.anyio
async def test_dj_analysis_rejects_snapshot_change_during_audio_lookup() -> None:
    artifacts = MemoryArtifacts()
    spotify = PlaylistGateway(["a"])

    with pytest.raises(ValueError, match="playlist changed after its stable state was read"):
        await analyze_playlist(
            spotify,
            artifacts,
            "playlist-1",
            audio=SnapshotChangingAudioGateway(spotify),
        )

    assert artifacts.artifacts == {}


@pytest.mark.anyio
async def test_apply_is_dry_run_by_default_and_then_freshly_verified() -> None:
    artifacts = MemoryArtifacts()
    artifacts.artifacts["plan-1"] = stored_plan()
    spotify = PlaylistGateway(["a", "b"])

    preview = await apply_plan(spotify, artifacts, "plan-1")
    assert preview.status == "dry-run"
    assert spotify.put_count == 0

    applied = await apply_plan(spotify, artifacts, "plan-1", dry_run=False)
    assert applied.status == "accepted"
    assert applied.receipt_id in artifacts.receipts
    assert spotify.order == ["b", "a"]

    restored = await restore_playlist(
        spotify,
        artifacts,
        applied.receipt_id or "",
        expected_snapshot_id=applied.final_snapshot_id or "",
        dry_run=False,
    )
    assert restored.status == "accepted"
    assert spotify.order == ["a", "b"]


@pytest.mark.anyio
async def test_identical_mutation_attempts_receive_distinct_receipts() -> None:
    artifacts = MemoryArtifacts()
    results = []

    for _ in range(2):
        results.append(
            await execute_playlist_permutation(
                PlaylistGateway(["a", "b"]),
                artifacts,
                playlist_id="playlist-1",
                identity={"action": "apply", "plan_id": "plan-1"},
                original_order=("spotify:track:a#0", "spotify:track:b#0"),
                target_order=("spotify:track:b#0", "spotify:track:a#0"),
                expected_snapshot_id="s1",
                action="apply",
                dry_run=False,
            )
        )

    receipt_ids = [result.receipt_id for result in results]
    assert all(result.status == "accepted" for result in results)
    assert receipt_ids[0] != receipt_ids[1]
    assert len(artifacts.receipts) == 2
    nonces = [artifacts.receipts[receipt_id or ""]["attempt_nonce"] for receipt_id in receipt_ids]
    assert nonces[0] != nonces[1]
    assert all(str(UUID(nonce)) == nonce for nonce in nonces)


@pytest.mark.anyio
async def test_apply_reports_stale_without_writing() -> None:
    artifacts = MemoryArtifacts()
    artifacts.artifacts["plan-1"] = stored_plan()
    spotify = PlaylistGateway(["a", "b"], snapshot="someone-edited")
    result = await apply_plan(spotify, artifacts, "plan-1", dry_run=False)
    assert result.status == "stale"
    assert result.failure_reason == "snapshot-mismatch"
    assert spotify.put_count == 0


@pytest.mark.anyio
async def test_apply_never_retries_an_unproved_write() -> None:
    artifacts = MemoryArtifacts()
    artifacts.artifacts["plan-1"] = stored_plan()
    spotify = PlaylistGateway(["a", "b"], apply_writes=False)
    result = await apply_plan(spotify, artifacts, "plan-1", dry_run=False)
    assert result.status == "ambiguous"
    assert result.failure_reason == "ambiguous-write"
    assert spotify.put_count == 1


@pytest.mark.anyio
async def test_failed_post_write_read_is_ambiguous_without_retry() -> None:
    artifacts = MemoryArtifacts()
    artifacts.artifacts["plan-1"] = stored_plan()
    spotify = VerificationFailureGateway(["a", "b"])
    result = await apply_plan(spotify, artifacts, "plan-1", dry_run=False)
    assert result.status == "ambiguous"
    assert result.failure_reason == "verification-read-failure"
    assert spotify.put_count == 1


@pytest.mark.anyio
async def test_receipt_progress_failure_stops_further_mutation() -> None:
    artifacts = ReceiptUpdateFailureArtifacts()
    artifacts.artifacts["plan-1"] = stored_plan()
    spotify = PlaylistGateway(["a", "b"])
    result = await apply_plan(spotify, artifacts, "plan-1", dry_run=False)
    assert result.status == "partial"
    assert result.failure_reason == "receipt-update-failure"
    assert spotify.put_count == 1


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
