"""Application settings, read from environment variables and an optional .env file."""

from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Local development only. Production refuses to start with this value.
DEV_SESSION_SECRET = "insecure-local-session-secret-change-me"  # noqa: S105
MIN_SESSION_SECRET_LENGTH = 32

# The Vite development server, which proxies API calls to the backend.
DEV_FRONTEND_ORIGIN = "http://localhost:5173"
GOOGLE_CALLBACK_PATH = "/api/auth/google/callback"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# The Copilot's model on OpenRouter: a current general model with reliable tool calling at a
# moderate price (chosen from OpenRouter's model list, 2026-09-19). COPILOT_MODEL overrides it.
DEFAULT_COPILOT_MODEL = "google/gemini-3.8-flash"

# The lending rules for holds and renewals (D-27). The services fall back to these when a caller,
# such as a Copilot proposal, passes no setting.
DEFAULT_HOLD_PICKUP_DAYS = 3
DEFAULT_MAX_RENEWALS = 2


def _split_commas(value: object) -> object:
    """Splits "a, b,,c" into ["a", "b", "c"]. A list, from code or tests, is kept as is."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# NoDecode keeps pydantic-settings from reading the value as JSON, so a plain comma-separated
# environment value reaches _split_commas.
CommaSeparated = Annotated[list[str], NoDecode, BeforeValidator(_split_commas)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Keeps raw values, such as secrets, out of validation error messages.
        hide_input_in_errors=True,
    )

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = "postgresql+asyncpg://library:library@127.0.0.1:55432/library"
    log_level: str = "INFO"
    frontend_dist_dir: Path = BACKEND_DIR.parent / "frontend" / "dist"
    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    # A loan is due this many days after it is borrowed, unless staff choose another date.
    loan_period_days: int = Field(default=14, ge=1, le=90)
    # A ready hold waits this many days for pick-up, until the end of the last day (UTC).
    hold_pickup_days: int = Field(default=DEFAULT_HOLD_PICKUP_DAYS, ge=1, le=14)
    # Open holds, waiting or ready, that one member can have at once.
    max_open_holds: int = Field(default=5, ge=1, le=50)
    # How many times one loan can be renewed.
    max_renewals: int = Field(default=DEFAULT_MAX_RENEWALS, ge=0, le=10)
    # How often the holds sweep runs: it expires ready holds past their pick-up date and gives
    # the copies they free to the next member in line. 0 turns it off.
    hold_sweep_seconds: int = Field(default=60, ge=0, le=86400)

    # Sign-in. Unset, DEMO_LOGIN_ENABLED is true everywhere except production.
    demo_login_enabled: bool = True
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # People who sign in with Google for the first time become staff when their address is here.
    staff_emails: CommaSeparated = Field(default_factory=list)
    session_idle_minutes: int = Field(default=720, ge=1)
    session_max_hours: int = Field(default=168, ge=1)
    # The address browsers use to reach the app. Google redirects back to it after sign-in.
    public_base_url: str = "http://localhost:8000"
    # Origins allowed to send state-changing requests. Unset: the public base URL, plus the
    # development server outside production.
    allowed_origins: CommaSeparated = Field(default_factory=list)

    # Copilot. Without an OpenRouter key the assistant shows as unavailable and the rest of the
    # app works as before.
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = OPENROUTER_BASE_URL
    copilot_model: str = DEFAULT_COPILOT_MODEL
    # The whole turn: every model call and lookup of one message together.
    copilot_timeout_seconds: float = Field(default=45, gt=0, le=300)
    copilot_max_tool_rounds: int = Field(default=6, ge=1, le=20)
    copilot_max_output_tokens: int = Field(default=2000, ge=100, le=32000)
    # Messages each user may send per minute.
    copilot_rate_per_minute: int = Field(default=20, ge=1)
    # Development and tests only: an offline stand-in answers instead of a real model, with no
    # key. Production refuses to start with it.
    copilot_fake_model: bool = False

    # The add-book form's ISBN lookup, which asks Open Library. Off, the lookup answers 503 and
    # the form is filled by hand.
    isbn_lookup_enabled: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def copilot_key(self) -> str | None:
        key = self.openrouter_api_key
        return key.get_secret_value() if key and key.get_secret_value() else None

    @property
    def google_enabled(self) -> bool:
        secret = self.google_client_secret
        return bool(self.google_client_id) and bool(secret and secret.get_secret_value())

    @property
    def google_redirect_uri(self) -> str:
        return self.public_base_url + GOOGLE_CALLBACK_PATH

    @property
    def session_idle_timeout(self) -> timedelta:
        return timedelta(minutes=self.session_idle_minutes)

    @property
    def session_lifetime(self) -> timedelta:
        return timedelta(hours=self.session_max_hours)

    @model_validator(mode="after")
    def _environment_defaults(self) -> Self:
        self.public_base_url = self.public_base_url.rstrip("/")
        # Values given explicitly, from the environment or in code, are in model_fields_set.
        if "demo_login_enabled" not in self.model_fields_set:
            self.demo_login_enabled = not self.is_production
        if "allowed_origins" not in self.model_fields_set:
            self.allowed_origins = [self.public_base_url]
            if not self.is_production:
                self.allowed_origins.append(DEV_FRONTEND_ORIGIN)
        return self

    @model_validator(mode="after")
    def _require_strong_secret_in_production(self) -> Self:
        if self.is_production:
            secret = self.session_secret.get_secret_value()
            if secret == DEV_SESSION_SECRET or len(secret) < MIN_SESSION_SECRET_LENGTH:
                raise ValueError(
                    "SESSION_SECRET must be set to a random value of at least "
                    f"{MIN_SESSION_SECRET_LENGTH} characters when APP_ENV is production"
                )
        return self

    @model_validator(mode="after")
    def _refuse_fake_model_in_production(self) -> Self:
        if self.is_production and self.copilot_fake_model:
            raise ValueError("COPILOT_FAKE_MODEL cannot be turned on when APP_ENV is production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
