from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from uuid import UUID

import pytest

from spotify_mcp.application.dj import (
    analyze_candidates,
    analyze_dj_source,
    analyze_playlist,
    apply_plan,
    create_plan,
    restore_playlist,
)
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
    plan_transition_set,
    transition_cost,
    transition_key_penalty,
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

    async def claim_receipt(
        self, receipt_id: str, payload: Mapping[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        if receipt_id in self.receipts:
            return False, self.receipts[receipt_id]
        self.receipts[receipt_id] = dict(payload)
        return True, self.receipts[receipt_id]


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


class CandidateGateway:
    def __init__(
        self,
        *,
        observed_public: bool = False,
        apply_items: bool = True,
        ambiguous_add: bool = False,
        fail_add: bool = False,
        malformed_track: bool = False,
    ) -> None:
        self.observed_public = observed_public
        self.apply_items = apply_items
        self.ambiguous_add = ambiguous_add
        self.fail_add = fail_add
        self.malformed_track = malformed_track
        self.created = 0
        self.added = 0
        self.item_reads = 0
        self.order: list[str] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if method == "GET" and path.startswith("/tracks/"):
            track_id = path.rsplit("/", 1)[-1]
            if self.malformed_track:
                return {"id": track_id}
            return _candidate_payload(track_id, f"Exact {track_id[-2:]}")
        if method == "GET" and path == "/search":
            assert params and params["limit"] == 10
            return {
                "tracks": {
                    "total": 1,
                    "items": [_candidate_payload("q" * 22, "Ranked query result")],
                }
            }
        if method == "POST" and path == "/me/playlists":
            self.created += 1
            return {
                "id": "created-1",
                "external_urls": {"spotify": "https://open.spotify.com/playlist/created-1"},
            }
        if method == "GET" and path == "/playlists/created-1":
            return {
                "id": "created-1",
                "name": "Generated",
                "description": "",
                "owner": {"id": "me"},
                "public": self.observed_public,
            }
        if method == "POST" and path == "/playlists/created-1/items":
            self.added += 1
            if self.fail_add:
                raise RuntimeError("write rejected")
            assert isinstance(json, dict)
            if self.apply_items:
                self.order = list(json["uris"])
            return {} if self.ambiguous_add else {"snapshot_id": "generated-snapshot"}
        if method == "GET" and path == "/playlists/created-1/items":
            self.item_reads += 1
            offset = int((params or {}).get("offset", 0))
            items = [
                {"item": {"id": uri.rsplit(":", 1)[-1], "uri": uri, "type": "track", "name": uri}}
                for uri in self.order
            ]
            return {"items": items[offset : offset + 50], "total": len(items)}
        raise AssertionError(f"unexpected request: {method} {path}")


def _candidate_payload(track_id: str, name: str) -> dict[str, Any]:
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "type": "track",
        "artists": [{"id": "artist-1", "name": "Artist"}],
        "album": {"name": "Album"},
    }


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


@pytest.mark.parametrize(
    ("pitch", "mode", "expected"),
    [
        (0, 1, "8B"),
        (1, 1, "3B"),
        (2, 1, "10B"),
        (3, 1, "5B"),
        (4, 1, "12B"),
        (5, 1, "7B"),
        (6, 1, "2B"),
        (7, 1, "9B"),
        (8, 1, "4B"),
        (9, 1, "11B"),
        (10, 1, "6B"),
        (11, 1, "1B"),
        (0, 0, "5A"),
        (1, 0, "12A"),
        (2, 0, "7A"),
        (3, 0, "2A"),
        (4, 0, "9A"),
        (5, 0, "4A"),
        (6, 0, "11A"),
        (7, 0, "6A"),
        (8, 0, "1A"),
        (9, 0, "8A"),
        (10, 0, "3A"),
        (11, 0, "10A"),
    ],
)
def test_camelot_code_maps_all_pitch_mode_pairs(pitch: int, mode: int, expected: str) -> None:
    assert camelot_code(pitch, mode) == expected


def test_transition_cost_uses_exact_specification_components() -> None:
    first = track("a", 0, energy=0.4, bpm=120, camelot="8A", artist="one")
    second = track("b", 1, energy=0.7, bpm=124, camelot="9A", artist="two")

    result = transition_cost(first, second)

    assert transition_key_penalty("8A", "8A") == 0
    assert transition_key_penalty("12B", "1B") == 2
    assert transition_key_penalty("8A", "8B") == 3
    assert transition_key_penalty("8A", "10B") == 14
    assert result.bpm_delta == 4
    assert result.energy_delta == 0.3
    assert result.key_penalty == 2
    assert result.cost == 9.5


def test_transition_cost_uses_half_time_normalized_tempo() -> None:
    first = track("a", 0, energy=0.5, bpm=86, camelot="8A", artist="one")
    second = track("b", 1, energy=0.5, bpm=171, camelot="8A", artist="two")

    result = transition_cost(first, second)

    assert result.bpm_delta == 0.5
    assert result.cost == 0.75
    assert result.from_normalized_bpm == 86
    assert result.to_normalized_bpm == 85.5


def test_transition_cost_normalizes_the_small_set_half_time_track() -> None:
    first = track("feel", 0, energy=0.924, bpm=127.937, camelot="9B", artist="Calvin")
    second = track("lights", 1, energy=0.73, bpm=171.001, camelot="3B", artist="Weeknd")

    result = transition_cost(first, second)

    assert result.from_normalized_bpm == 127.937
    assert result.to_normalized_bpm == 85.5005
    assert result.bpm_delta == 42.4365
    assert result.cost == 86.62475


def test_transition_planner_starts_with_lowest_normalized_tempo() -> None:
    analysis = DjAnalysis(
        playlist_id=None,
        playlist_name="Generated",
        snapshot_id=None,
        source_kind="candidates",
        tracks=(
            track("slow", 0, energy=0.5, bpm=86, camelot="8A", artist="one"),
            track("double", 1, energy=0.5, bpm=171, camelot="8A", artist="two"),
            track("fast", 2, energy=0.5, bpm=120, camelot="8A", artist="three"),
        ),
    )

    plan = plan_transition_set(analysis, "analysis-1")

    assert plan.target_order[:2] == (
        "spotify:track:double#0",
        "spotify:track:slow#0",
    )
    assert plan.transitions[0].bpm_delta == 0.5


def test_transition_planner_is_deterministic_and_starts_at_lowest_tempo() -> None:
    analysis = DjAnalysis(
        playlist_id=None,
        playlist_name="Generated",
        snapshot_id=None,
        source_kind="candidates",
        tracks=(
            track("high", 0, energy=0.2, bpm=128, camelot="8B", artist="a"),
            track("intro", 1, energy=0.3, bpm=118, camelot="8B", artist="b"),
            track("neighbor", 2, energy=0.35, bpm=120, camelot="9B", artist="c"),
        ),
    )

    first = plan_transition_set(analysis, "analysis-1")
    second = plan_transition_set(analysis, "analysis-1")

    assert first == second
    assert first.target_order == (
        "spotify:track:intro#0",
        "spotify:track:neighbor#0",
        "spotify:track:high#0",
    )
    assert len(first.transitions) == 2
    assert first.total_transition_cost == sum(item.cost for item in first.transitions)


def test_transition_planner_selects_by_unrounded_cost_before_tie_breaking() -> None:
    analysis = DjAnalysis(
        playlist_id=None,
        playlist_name="Generated",
        snapshot_id=None,
        source_kind="candidates",
        tracks=(
            track("expensive", 0, energy=0.4, bpm=100.666666993, camelot="8A", artist="a"),
            track("cheaper", 1, energy=0.4, bpm=100.666666933, camelot="8A", artist="b"),
            track("intro", 2, energy=0.4, bpm=100, camelot="8A", artist="c"),
        ),
    )

    plan = plan_transition_set(analysis, "analysis-1")

    assert plan.target_order[:2] == (
        "spotify:track:intro#0",
        "spotify:track:cheaper#0",
    )
    assert plan.total_transition_cost == sum(item.cost for item in plan.transitions)


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
async def test_candidate_analysis_resolves_mixed_inputs_and_skips_incomplete_tracks() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway()
    first_id = "a" * 22
    second_id = "b" * 22
    missing_id = "c" * 22
    complete = [
        {"track_id": first_id, "bpm": 118, "energy": 0.3, "key": 0, "mode": 1},
        {"track_id": second_id, "bpm": 120, "energy": 0.4, "key": 7, "mode": 1},
    ]

    analysis_id, analysis = await analyze_candidates(
        spotify,
        artifacts,
        [f"spotify:track:{first_id}", second_id, missing_id, "Halo"],
        features=[
            *complete,
            {"track_id": "q" * 22, "bpm": 122, "energy": 0.5, "key": 2, "mode": 1},
        ],
    )

    assert analysis.source_kind == "candidates"
    assert analysis.playlist_id is None
    assert analysis.snapshot_id is None
    assert [track.track_id for track in analysis.tracks] == [first_id, second_id, "q" * 22]
    assert analysis.resolved_candidates[-1].name == "Ranked query result"
    assert analysis.skipped_candidates[0].track_id == missing_id
    assert analysis.skipped_candidates[0].missing_fields == (
        "tempo",
        "key_or_mode",
        "energy",
    )
    assert artifacts.artifacts[analysis_id]["source_kind"] == "candidates"


@pytest.mark.anyio
async def test_dj_source_requires_exactly_one_playlist_or_candidate_source() -> None:
    artifacts = MemoryArtifacts()

    with pytest.raises(ValueError, match="exactly one"):
        await analyze_dj_source(CandidateGateway(), artifacts)
    with pytest.raises(ValueError, match="exactly one"):
        await analyze_dj_source(
            CandidateGateway(), artifacts, playlist_id="playlist-1", candidates=["a", "b"]
        )


@pytest.mark.anyio
async def test_auto_strategy_retains_energy_curve_for_playlist_analysis() -> None:
    artifacts = MemoryArtifacts()
    analysis = DjAnalysis(
        playlist_id="playlist-1",
        playlist_name="Set",
        snapshot_id="s1",
        tracks=(
            track("a", 0, energy=0.7, bpm=124, camelot="8B", artist="one"),
            track("b", 1, energy=0.3, bpm=120, camelot="9B", artist="two"),
        ),
    )
    artifacts.artifacts["analysis-1"] = {"artifact_kind": "analysis", **asdict(analysis)}

    _, plan = await create_plan(artifacts, "analysis-1")

    assert plan.source_kind == "playlist"
    assert plan.strategy == "energy-curve"


@pytest.mark.anyio
async def test_candidate_analysis_rejects_fewer_than_two_complete_tracks_without_artifact() -> None:
    artifacts = MemoryArtifacts()
    first_id = "a" * 22
    second_id = "b" * 22

    with pytest.raises(ValueError, match="at least two tracks with complete"):
        await analyze_candidates(
            CandidateGateway(),
            artifacts,
            [first_id, second_id],
            features=[{"track_id": first_id, "bpm": 118, "energy": 0.3, "key": 0, "mode": 1}],
        )

    assert artifacts.artifacts == {}


@pytest.mark.anyio
async def test_candidate_analysis_propagates_malformed_provider_responses() -> None:
    artifacts = MemoryArtifacts()

    with pytest.raises(ValueError, match="malformed track metadata"):
        await analyze_candidates(
            CandidateGateway(malformed_track=True),
            artifacts,
            ["a" * 22, "b" * 22],
        )

    assert artifacts.artifacts == {}


@pytest.mark.anyio
async def test_candidate_auto_plan_and_apply_create_verified_private_playlist() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway()
    ids = ["a" * 22, "b" * 22, "c" * 22]
    features = [
        {"track_id": ids[0], "bpm": 124, "energy": 0.7, "key": 7, "mode": 1},
        {"track_id": ids[1], "bpm": 118, "energy": 0.3, "key": 0, "mode": 1},
        {"track_id": ids[2], "bpm": 120, "energy": 0.4, "key": 7, "mode": 1},
    ]
    analysis_id, _ = await analyze_candidates(
        spotify,
        artifacts,
        ids,
        playlist_name="Generated",
        features=features,
    )
    plan_id, plan = await create_plan(artifacts, analysis_id)

    preview = await apply_plan(spotify, artifacts, plan_id)
    applied = await apply_plan(spotify, artifacts, plan_id, dry_run=False)
    repeated = await apply_plan(spotify, artifacts, plan_id, dry_run=False)

    assert plan.strategy == "transition-cost"
    assert preview.status == "dry-run"
    assert spotify.created == 1
    assert spotify.added == 1
    assert applied.status == "verified"
    assert applied.expected_order == applied.observed_order
    assert repeated.status == "already-applied"
    assert repeated.playlist_id == "created-1"


@pytest.mark.anyio
async def test_candidate_apply_stops_before_items_when_visibility_mismatches() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway(observed_public=True)
    ids = ["a" * 22, "b" * 22]
    analysis_id, _ = await analyze_candidates(
        spotify,
        artifacts,
        ids,
        features=[
            {"track_id": ids[0], "bpm": 118, "energy": 0.3, "key": 0, "mode": 1},
            {"track_id": ids[1], "bpm": 120, "energy": 0.4, "key": 7, "mode": 1},
        ],
    )
    plan_id, _ = await create_plan(artifacts, analysis_id)

    result = await apply_plan(spotify, artifacts, plan_id, dry_run=False)

    assert result.status == "visibility-mismatch"
    assert result.failure_reason == "playlist-visibility-unverified"
    assert spotify.added == 0


@pytest.mark.anyio
async def test_candidate_apply_accepts_ambiguous_add_only_after_exact_readback() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway(ambiguous_add=True)
    ids = ["a" * 22, "b" * 22]
    analysis_id, _ = await analyze_candidates(
        spotify,
        artifacts,
        ids,
        features=[
            {"track_id": ids[0], "bpm": 118, "energy": 0.3, "key": 0, "mode": 1},
            {"track_id": ids[1], "bpm": 120, "energy": 0.4, "key": 7, "mode": 1},
        ],
    )
    plan_id, _ = await create_plan(artifacts, analysis_id)

    result = await apply_plan(spotify, artifacts, plan_id, dry_run=False)

    assert result.status == "verified"
    assert spotify.added == 1
    assert "playlist item write was ambiguous" in result.warnings


@pytest.mark.anyio
async def test_candidate_apply_records_created_playlist_when_item_write_fails() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway(fail_add=True)
    ids = ["a" * 22, "b" * 22]
    analysis_id, _ = await analyze_candidates(
        spotify,
        artifacts,
        ids,
        features=[
            {"track_id": ids[0], "bpm": 118, "energy": 0.3, "key": 0, "mode": 1},
            {"track_id": ids[1], "bpm": 120, "energy": 0.4, "key": 7, "mode": 1},
        ],
    )
    plan_id, _ = await create_plan(artifacts, analysis_id)

    result = await apply_plan(spotify, artifacts, plan_id, dry_run=False)
    repeated = await apply_plan(spotify, artifacts, plan_id, dry_run=False)

    assert result.status == "partial"
    assert result.playlist_id == "created-1"
    assert result.failure_reason == "playlist-item-write-failure"
    assert repeated.status == "partial"
    assert repeated.playlist_id == "created-1"
    assert spotify.created == 1


@pytest.mark.anyio
async def test_candidate_apply_pages_complete_verification_for_51_tracks() -> None:
    artifacts = MemoryArtifacts()
    spotify = CandidateGateway()
    ids = [f"{index:022d}" for index in range(51)]
    features = [
        {
            "track_id": track_id,
            "bpm": 118 + index / 10,
            "energy": 0.3 + index / 200,
            "key": index % 12,
            "mode": index % 2,
        }
        for index, track_id in enumerate(ids)
    ]
    analysis_id, _ = await analyze_candidates(spotify, artifacts, ids, features=features)
    plan_id, _ = await create_plan(artifacts, analysis_id)

    result = await apply_plan(spotify, artifacts, plan_id, dry_run=False)

    assert result.status == "verified"
    assert len(result.observed_order) == 51
    assert spotify.item_reads == 2


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
