"""Provider-neutral audio analysis models and comparison rules."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class AudioProvider(StrEnum):
    """Known origins for an audio measurement."""

    SPOTIFY = "spotify"
    RECCOBEATS = "reccobeats"
    OVERRIDE = "override"


class AudioLookupSource(StrEnum):
    """Provider selection policy exposed by the application."""

    AUTO = "auto"
    SPOTIFY = "spotify"
    RECCOBEATS = "reccobeats"


class ConfidenceBasis(StrEnum):
    """Who supplied confidence for a field observation."""

    PROVIDER = "provider"
    USER = "user"
    UNKNOWN = "unknown"


class FeatureName(StrEnum):
    """Audio fields supported consistently across provider adapters."""

    TEMPO = "tempo"
    KEY = "key"
    MODE = "mode"
    ENERGY = "energy"
    DANCEABILITY = "danceability"
    ACOUSTICNESS = "acousticness"
    INSTRUMENTALNESS = "instrumentalness"
    LIVENESS = "liveness"
    LOUDNESS = "loudness"
    SPEECHINESS = "speechiness"
    VALENCE = "valence"


UnitInterval = Annotated[float, Field(ge=0, le=1)]
MusicalKey = Annotated[int, Field(ge=0, le=11)]
MusicalMode = Annotated[int, Field(ge=0, le=1)]


class FeatureProvenance(BaseModel):
    """Evidence describing where one selected field value came from."""

    model_config = ConfigDict(frozen=True)

    provider: AudioProvider
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_href: str | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    confidence_basis: ConfidenceBasis = ConfidenceBasis.PROVIDER


class FeatureObservation(BaseModel):
    """One provider's observation for one audio field."""

    model_config = ConfigDict(frozen=True)

    value: float | int
    provenance: FeatureProvenance


class FeatureConflict(BaseModel):
    """A material disagreement retained alongside the selected observation."""

    model_config = ConfigDict(frozen=True)

    field: FeatureName
    selected: FeatureObservation
    alternative: FeatureObservation


class AudioFeature(BaseModel):
    """Selected value plus its complete field-level evidence."""

    model_config = ConfigDict(frozen=True)

    selected: FeatureObservation
    conflicts: list[FeatureConflict] = Field(default_factory=list)
    overridden: FeatureObservation | None = None


class TrackAudioAnalysis(BaseModel):
    """Typed analysis for one exact Spotify track recording."""

    model_config = ConfigDict(frozen=True)

    track_id: str = Field(min_length=1)
    tempo: AudioFeature | None = None
    key: AudioFeature | None = None
    mode: AudioFeature | None = None
    energy: AudioFeature | None = None
    danceability: AudioFeature | None = None
    acousticness: AudioFeature | None = None
    instrumentalness: AudioFeature | None = None
    liveness: AudioFeature | None = None
    loudness: AudioFeature | None = None
    speechiness: AudioFeature | None = None
    valence: AudioFeature | None = None

    @model_validator(mode="after")
    def validate_feature_ranges(self) -> TrackAudioAnalysis:
        """Reject provider payloads whose field values violate the shared contract."""
        unit_interval_fields = {
            FeatureName.ENERGY,
            FeatureName.DANCEABILITY,
            FeatureName.ACOUSTICNESS,
            FeatureName.INSTRUMENTALNESS,
            FeatureName.LIVENESS,
            FeatureName.SPEECHINESS,
            FeatureName.VALENCE,
        }
        for field in FeatureName:
            feature = feature_for(self, field)
            if not feature:
                continue
            value = feature.selected.value
            if field is FeatureName.TEMPO and value <= 0:
                raise ValueError("tempo must be positive")
            if field is FeatureName.KEY and (not float(value).is_integer() or not 0 <= value <= 11):
                raise ValueError("key must be an integer from 0 to 11")
            if field is FeatureName.MODE and value not in {0, 1}:
                raise ValueError("mode must be 0 or 1")
            if field in unit_interval_fields and not 0 <= value <= 1:
                raise ValueError(f"{field.value} must be from 0 to 1")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def missing_fields(self) -> list[FeatureName]:
        """Return every field for which no provider supplied a value."""
        return [field for field in FeatureName if getattr(self, field.value) is None]


class AudioOverride(BaseModel):
    """User-supplied values that replace provider readings without erasing them."""

    model_config = ConfigDict(frozen=True)

    track_id: str = Field(min_length=1)
    tempo: Annotated[float, Field(gt=0)] | None = None
    key: MusicalKey | None = None
    mode: MusicalMode | None = None
    energy: UnitInterval | None = None
    danceability: UnitInterval | None = None
    acousticness: UnitInterval | None = None
    instrumentalness: UnitInterval | None = None
    liveness: UnitInterval | None = None
    loudness: float | None = None
    speechiness: UnitInterval | None = None
    valence: UnitInterval | None = None


class AudioLookupReport(BaseModel):
    """Ordered lookup result with explicit whole-track absence."""

    requested_track_ids: list[str]
    tracks: list[TrackAudioAnalysis]
    missing_track_ids: list[str]
    warnings: list[str] = Field(default_factory=list)


class ProviderConflict(BaseModel):
    """A material field disagreement between explicit provider reads."""

    model_config = ConfigDict(frozen=True)

    field: FeatureName
    left: FeatureObservation
    right: FeatureObservation


class TrackProviderComparison(BaseModel):
    """Comparison evidence for a single requested track."""

    track_id: str
    analyses: list[TrackAudioAnalysis]
    conflicts: list[ProviderConflict]
    missing_providers: list[AudioProvider]
    missing_fields: list[FeatureName]


class AudioComparisonReport(BaseModel):
    """Side-by-side provider results without fallback or hidden synthesis."""

    requested_track_ids: list[str]
    requested_providers: list[AudioProvider]
    tracks: list[TrackProviderComparison]
    warnings: list[str] = Field(default_factory=list)


class AuditedConflict(BaseModel):
    """A conflict associated with its exact recording."""

    track_id: str
    conflict: FeatureConflict


class AudioAuditReport(BaseModel):
    """Coverage and conflict summary for a requested set of recordings."""

    requested_track_ids: list[str]
    coverage: dict[FeatureName, int]
    missing_track_ids: list[str]
    missing_fields_by_track: dict[str, list[FeatureName]]
    conflicts: list[AuditedConflict]
    warnings: list[str] = Field(default_factory=list)


class AudioProviderError(Exception):
    """An auxiliary analysis provider returned an unusable response."""


def audio_values_conflict(field: FeatureName, left: float, right: float) -> bool:
    """Return whether two readings disagree materially for their field."""
    if field is FeatureName.TEMPO:
        candidates = ((left, right), (left * 2, right), (left, right * 2))
        relative_differences = [abs(a - b) / min(a, b) for a, b in candidates if min(a, b) > 0]
        return not relative_differences or min(relative_differences) > 0.03
    if field in {FeatureName.KEY, FeatureName.MODE}:
        return left != right
    if field is FeatureName.LOUDNESS:
        return abs(left - right) > 3
    return abs(left - right) > 0.15


def feature_for(track: TrackAudioAnalysis, field: FeatureName) -> AudioFeature | None:
    """Read one typed feature by its enum name."""
    value = getattr(track, field.value)
    return value if isinstance(value, AudioFeature) else None


def apply_override(
    track: TrackAudioAnalysis,
    override: AudioOverride,
) -> TrackAudioAnalysis:
    """Apply user evidence while retaining the superseded provider observation."""
    updates: dict[str, AudioFeature] = {}
    for field in FeatureName:
        value = getattr(override, field.value)
        if value is None:
            continue
        existing = feature_for(track, field)
        selected_value = (
            int(value) if field in {FeatureName.KEY, FeatureName.MODE} else float(value)
        )
        selected = FeatureObservation(
            value=selected_value,
            provenance=FeatureProvenance(
                provider=AudioProvider.OVERRIDE,
                confidence=1,
                confidence_basis=ConfidenceBasis.USER,
            ),
        )
        conflicts = list(existing.conflicts) if existing else []
        if existing and audio_values_conflict(field, selected.value, existing.selected.value):
            conflicts.append(
                FeatureConflict(
                    field=field,
                    selected=selected,
                    alternative=existing.selected,
                )
            )
        updates[field.value] = AudioFeature(
            selected=selected,
            conflicts=conflicts,
            overridden=existing.selected if existing else None,
        )
    return track.model_copy(update=updates)


def merge_track_analyses(
    primary: TrackAudioAnalysis,
    fallback: TrackAudioAnalysis,
) -> TrackAudioAnalysis:
    """Fill absent primary fields while retaining material fallback disagreements."""
    if primary.track_id != fallback.track_id:
        raise ValueError("Cannot merge analyses for different tracks")

    updates: dict[str, AudioFeature] = {}
    for field in FeatureName:
        selected = feature_for(primary, field)
        alternative = feature_for(fallback, field)
        if selected is None:
            if alternative is not None:
                updates[field.value] = alternative
            continue
        if alternative is None:
            continue
        conflicts = list(selected.conflicts)
        if audio_values_conflict(
            field,
            float(selected.selected.value),
            float(alternative.selected.value),
        ):
            conflicts.append(
                FeatureConflict(
                    field=field,
                    selected=selected.selected,
                    alternative=alternative.selected,
                )
            )
        if conflicts != selected.conflicts:
            updates[field.value] = selected.model_copy(update={"conflicts": conflicts})
    return primary.model_copy(update=updates)


def compare_track_analyses(
    left: TrackAudioAnalysis,
    right: TrackAudioAnalysis,
) -> list[ProviderConflict]:
    """Compare two provider-native analyses without selecting a winner."""
    if left.track_id != right.track_id:
        raise ValueError("Cannot compare analyses for different tracks")
    conflicts: list[ProviderConflict] = []
    for field in FeatureName:
        left_feature = feature_for(left, field)
        right_feature = feature_for(right, field)
        if not left_feature or not right_feature:
            continue
        if audio_values_conflict(field, left_feature.selected.value, right_feature.selected.value):
            conflicts.append(
                ProviderConflict(
                    field=field,
                    left=left_feature.selected,
                    right=right_feature.selected,
                )
            )
    return conflicts
