"""Application settings loaded from the environment with the ``LINGUINI_`` prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """Every runtime knob the self-hoster can set."""

    model_config = SettingsConfigDict(
        env_prefix="LINGUINI_",
        secrets_dir=str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None,
        extra="ignore",
    )

    public_url: HttpUrl = Field(default=HttpUrl("http://localhost:8000"), description="External origin of the app")
    secret_key: SecretStr = Field(description="Key material for encrypting stored third-party tokens")
    data_dir: Path = Field(default=Path("data"), description="Directory holding the SQLite database")
    static_dir: Path | None = Field(default=None, description="Built SPA directory; SPA is not served when unset")

    model: str = Field(default="gpt-4o-mini", description="Model name sent to the OpenAI-compatible server")
    summary_model: str | None = Field(default=None, description="Model used to summarize long threads")
    openai_base_url: HttpUrl | None = Field(
        default=None, description="OpenAI-compatible base URL, e.g. http://ollama:11434/v1"
    )
    openai_api_key: SecretStr = Field(default=SecretStr("unused"), description="API key for the model server")
    model_profile: dict[str, bool] = Field(
        default_factory=dict, description="Model profile overrides for picky servers"
    )
    session_header: str | None = Field(
        default=None, description="Header carrying a stable per-thread id, e.g. x-opencode-session for OpenCode Go"
    )
    guard_model: str = Field(
        default="typesafe/jev-1.14",
        description="Decision model that screens each message for off-topic requests and attacks; empty turns it off",
    )
    decisions_base_url: HttpUrl = Field(
        default=HttpUrl("https://openrouter.ai/api/v1"), description="System One API base URL serving guard_model"
    )
    decisions_api_key: SecretStr | None = Field(
        default=None, description="API key for decisions_base_url; defaults to openai_api_key"
    )

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_extra_audiences: list[str] = Field(default_factory=list)

    apple_team_id: str | None = None
    apple_key_id: str | None = None
    apple_private_key: SecretStr | None = None
    apple_services_id: str | None = None
    apple_bundle_ids: list[str] = Field(default_factory=list)

    kifli_mcp_url: HttpUrl = Field(default=HttpUrl("https://mcp.kifli.hu/mcp"))
    locale: str = "hu-HU"
    history_token_budget: int = 24_000
    session_ttl_days: int = 90
    session_idle_days: int = 14
    otel_endpoint: HttpUrl | None = None

    @field_validator("apple_private_key", mode="before")
    @classmethod
    def _read_key_file(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("file:"):
            return Path(value.removeprefix("file:")).read_text()
        return value

    @property
    def database_path(self) -> Path:
        """Absolute path of the SQLite file."""
        return self.data_dir / "linguini.db"

    @property
    def google_enabled(self) -> bool:
        """Whether Google login is configured."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def apple_enabled(self) -> bool:
        """Whether Apple login is configured."""
        return all((self.apple_team_id, self.apple_key_id, self.apple_private_key, self.apple_services_id))

    @property
    def is_https(self) -> bool:
        """Whether cookies may carry the Secure flag."""
        return self.public_url.scheme == "https"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once."""
    return Settings()
