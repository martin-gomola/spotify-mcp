"""Spotify and ReccoBeats audio-analysis adapters."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx

from spotify_mcp.application.ports import SpotifyGateway
from spotify_mcp.domain.audio import (
    AudioFeature,
    AudioProvider,
    AudioProviderError,
    FeatureName,
    FeatureObservation,
    FeatureProvenance,
    TrackAudioAnalysis,
)
from spotify_mcp.domain.errors import SpotifyRequestError

_SPOTIFY_BATCH_SIZE = 100
_RECCOBEATS_BATCH_SIZE = 40
_RECCOBEATS_URL = "https://api.reccobeats.com/v1/audio-features"


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AudioProviderError(message)
    return value


def _number(value: object, field: FeatureName) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if field in {FeatureName.KEY, FeatureName.MODE} and float(value).is_integer():
        return int(value)
    return float(value)


def _feature(
    value: object,
    *,
    field: FeatureName,
    provider: AudioProvider,
    source_href: str | None,
    fetched_at: datetime,
) -> AudioFeature | None:
    number = _number(value, field)
    if number is None:
        return None
    return AudioFeature(
        selected=FeatureObservation(
            value=number,
            provenance=FeatureProvenance(
                provider=provider,
                fetched_at=fetched_at,
                source_href=source_href,
            ),
        )
    )


def _parse_track(
    raw: Mapping[str, Any],
    *,
    track_id: str,
    provider: AudioProvider,
    source_href: str | None,
) -> TrackAudioAnalysis:
    fetched_at = datetime.now(UTC)
    values: dict[str, AudioFeature | str | None] = {"track_id": track_id}
    for field in FeatureName:
        raw_value = raw.get(field.value)
        if field is FeatureName.KEY and raw_value == -1:
            raw_value = None
        values[field.value] = _feature(
            raw_value,
            field=field,
            provider=provider,
            source_href=source_href,
            fetched_at=fetched_at,
        )
    return TrackAudioAnalysis.model_validate(values)


def _ordered(track_ids: list[str], tracks: list[TrackAudioAnalysis]) -> list[TrackAudioAnalysis]:
    by_id = {track.track_id: track for track in tracks}
    return [by_id[track_id] for track_id in track_ids if track_id in by_id]


class SpotifyAudioProvider:
    """Read Spotify's exact-recording audio features through the authenticated gateway."""

    provider = AudioProvider.SPOTIFY

    def __init__(self, gateway: SpotifyGateway) -> None:
        self._gateway = gateway

    async def get_audio_features(self, track_ids: list[str]) -> list[TrackAudioAnalysis]:
        tracks: list[TrackAudioAnalysis] = []
        for start in range(0, len(track_ids), _SPOTIFY_BATCH_SIZE):
            batch = track_ids[start : start + _SPOTIFY_BATCH_SIZE]
            response = await self._gateway.request(
                "GET",
                "/audio-features",
                params={"ids": ",".join(batch)},
            )
            envelope = _mapping(response, "Spotify audio-features response is malformed")
            raw_features = envelope.get("audio_features")
            if not isinstance(raw_features, list):
                raise SpotifyRequestError("Spotify response has no audio_features array")
            for raw_value in raw_features:
                if raw_value is None:
                    continue
                raw = _mapping(raw_value, "Spotify audio-features item is malformed")
                track_id = raw.get("id")
                if not isinstance(track_id, str) or not track_id:
                    raise SpotifyRequestError("Spotify audio-features item has no track id")
                source_href = raw.get("track_href")
                tracks.append(
                    _parse_track(
                        raw,
                        track_id=track_id,
                        provider=self.provider,
                        source_href=source_href if isinstance(source_href, str) else None,
                    )
                )
        return _ordered(track_ids, tracks)


def _spotify_track_id(raw: Mapping[str, Any]) -> str | None:
    for key in ("href", "track_href"):
        href = raw.get(key)
        if not isinstance(href, str):
            continue
        match = re.search(r"(?:track/|track:)([^/?]+)", href)
        if match:
            return match.group(1)
    raw_id = raw.get("id")
    return raw_id if isinstance(raw_id, str) and raw_id else None


class ReccoBeatsAudioProvider:
    """Read public ReccoBeats analysis with bounded requests and no hidden provider chain."""

    provider = AudioProvider.RECCOBEATS

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @asynccontextmanager
    async def _http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            yield client

    async def get_audio_features(self, track_ids: list[str]) -> list[TrackAudioAnalysis]:
        tracks: list[TrackAudioAnalysis] = []
        async with self._http_client() as client:
            for start in range(0, len(track_ids), _RECCOBEATS_BATCH_SIZE):
                batch = track_ids[start : start + _RECCOBEATS_BATCH_SIZE]
                try:
                    response = await client.get(_RECCOBEATS_URL, params={"ids": ",".join(batch)})
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as error:
                    raise AudioProviderError(f"ReccoBeats request failed: {error}") from error
                envelope = _mapping(payload, "ReccoBeats response is malformed")
                raw_features = envelope.get("content")
                if not isinstance(raw_features, list):
                    raise AudioProviderError("ReccoBeats response has no content array")
                for raw_value in raw_features:
                    if raw_value is None:
                        continue
                    raw = _mapping(raw_value, "ReccoBeats audio-features item is malformed")
                    track_id = _spotify_track_id(raw)
                    if not track_id:
                        raise AudioProviderError(
                            "ReccoBeats audio-features item has no Spotify track id"
                        )
                    source_href = raw.get("href")
                    tracks.append(
                        _parse_track(
                            raw,
                            track_id=track_id,
                            provider=self.provider,
                            source_href=source_href if isinstance(source_href, str) else None,
                        )
                    )
        return _ordered(track_ids, tracks)
