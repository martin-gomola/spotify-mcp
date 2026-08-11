"""Environment-backed runtime configuration for the Spotify adapter."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from platformdirs import user_config_path
from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class SpotifyConfigError(ValueError):
    """The persisted local app configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class SpotifyAppConfig:
    """Non-secret Spotify application settings persisted after authentication."""

    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT_URI


def default_app_config_path() -> Path:
    """Return the OS-appropriate non-secret application config path."""

    return user_config_path("spotify-mcp", appauthor=False) / "config.json"


def default_token_path() -> Path:
    """Return the OS-appropriate private token path."""

    return user_config_path("spotify-mcp", appauthor=False) / "tokens.json"


class SpotifySettings(BaseSettings):
    """Spotify credentials and bounded network policy.

    Secrets and tokens are deliberately separate: the app identifier comes from
    the environment while renewable user credentials live in a private file.
    """

    model_config = SettingsConfigDict(
        env_prefix="SPOTIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    client_id: str = Field(min_length=1)
    redirect_uri: str = DEFAULT_REDIRECT_URI
    token_path: Path = Field(default_factory=default_token_path)
    api_base_url: str = "https://api.spotify.com/v1"
    accounts_base_url: str = "https://accounts.spotify.com"
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    max_attempts: int = Field(default=4, ge=1, le=6)
    max_retry_after_seconds: float = Field(default=60.0, ge=0, le=300)

    @field_validator("client_id")
    @classmethod
    def strip_client_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("client_id cannot be blank")
        return stripped

    @field_validator("api_base_url", "accounts_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_loopback_redirect(self) -> Self:
        parsed = urlsplit(self.redirect_uri)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError(
                "redirect_uri must use the literal loopback address, for example "
                f"{DEFAULT_REDIRECT_URI}"
            )
        if parsed.port is None:
            raise ValueError("redirect_uri must include an explicit loopback port")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("redirect_uri must not include credentials, query, or fragment")
        return self


def load_app_config(path: Path | None = None) -> SpotifyAppConfig | None:
    """Load persisted non-secret settings, returning ``None`` before first auth."""

    config_path = path or default_app_config_path()
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SpotifyConfigError(f"Could not read Spotify app config: {exc}") from exc
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError("config document is not an object")
        client_id = payload["client_id"]
        redirect_uri = payload.get("redirect_uri", DEFAULT_REDIRECT_URI)
        if not isinstance(client_id, str) or not isinstance(redirect_uri, str):
            raise TypeError("config fields must be strings")
        validated = SpotifySettings(client_id=client_id, redirect_uri=redirect_uri)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SpotifyConfigError(
            f"Spotify app config at {config_path} is invalid; run `spotify-mcp auth` again."
        ) from exc
    return SpotifyAppConfig(
        client_id=validated.client_id,
        redirect_uri=validated.redirect_uri,
    )


def save_app_config(config: SpotifyAppConfig, path: Path | None = None) -> Path:
    """Atomically persist non-secret settings for later serve/doctor commands."""

    validated = SpotifySettings(client_id=config.client_id, redirect_uri=config.redirect_uri)
    config_path = path or default_app_config_path()
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_owner_only(config_path.parent, 0o700)
    serialized = (
        json.dumps(
            asdict(SpotifyAppConfig(validated.client_id, validated.redirect_uri)),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            text=True,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, config_path)
        _chmod_owner_only(config_path, 0o600)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise SpotifyConfigError(f"Could not save Spotify app config: {exc}") from exc
    return config_path


def load_settings(
    *,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    app_config_path: Path | None = None,
    token_path: Path | None = None,
    dotenv_path: Path | None = Path(".env"),
) -> SpotifySettings:
    """Resolve CLI, environment, then persisted settings in that order.

    CLI values are explicit one-command overrides. Environment values override
    the saved app config, and the saved config makes subsequent commands work
    without retaining ``SPOTIFY_CLIENT_ID`` in the shell.
    """

    try:
        saved = load_app_config(app_config_path)
    except SpotifyConfigError:
        if client_id is None:
            raise
        saved = None
    resolved_client_id = (
        client_id
        or _nonblank_env("SPOTIFY_CLIENT_ID")
        or _nonblank_dotenv("SPOTIFY_CLIENT_ID", dotenv_path)
        or (saved.client_id if saved else None)
    )
    if resolved_client_id is None:
        raise SpotifyConfigError(
            "Spotify client ID is missing; pass --client-id, set SPOTIFY_CLIENT_ID, "
            "or run `spotify-mcp auth`."
        )
    resolved_redirect_uri = (
        redirect_uri
        or _nonblank_env("SPOTIFY_REDIRECT_URI")
        or _nonblank_dotenv("SPOTIFY_REDIRECT_URI", dotenv_path)
        or (saved.redirect_uri if saved else DEFAULT_REDIRECT_URI)
    )
    try:
        if token_path is not None:
            return SpotifySettings(  # type: ignore[call-arg]
                client_id=resolved_client_id,
                redirect_uri=resolved_redirect_uri,
                token_path=token_path,
                _env_file=dotenv_path,
            )
        return SpotifySettings(  # type: ignore[call-arg]
            client_id=resolved_client_id,
            redirect_uri=resolved_redirect_uri,
            _env_file=dotenv_path,
        )
    except ValidationError as exc:
        raise SpotifyConfigError(f"Spotify settings are invalid: {exc}") from exc


def _nonblank_env(name: str) -> str | None:
    value = os.environ.get(name)
    stripped = value.strip() if value else ""
    return stripped or None


def _nonblank_dotenv(name: str, path: Path | None) -> str | None:
    if path is None:
        return None
    value = dotenv_values(path).get(name)
    stripped = value.strip() if value else ""
    return stripped or None


def _chmod_owner_only(path: Path, mode: int) -> None:
    # POSIX modes are not available on every supported filesystem.
    with suppress(OSError):
        path.chmod(mode)
