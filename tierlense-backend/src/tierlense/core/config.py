"""Central application and intelligence-worker configuration."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TierLense API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://tierlense:replace-this-local-password@"
        "localhost:5432/tierlense"
    )
    cors_origins: list[str] = ["http://localhost:5173"]

    # Enable only for the local presentation; requires the exact synthetic organization name.
    enable_pds4_demo_scenario: bool = False

    # Provider order is fixed in the worker: Groq -> OpenRouter -> Mistral.
    # Fallback keys are optional; unconfigured providers are skipped.
    groq_api_key: SecretStr | None = None
    groq_search_model: str = "openai/gpt-oss-20b"
    groq_analysis_model: str = "openai/gpt-oss-120b"

    openrouter_api_key: SecretStr | None = None
    openrouter_search_model: str = "openrouter/free"
    openrouter_analysis_model: str = "openrouter/free"

    mistral_api_key: SecretStr | None = None
    mistral_search_model: str = "mistral-small-latest"
    mistral_analysis_model: str = "mistral-small-latest"
    provider_failure_cooldown_seconds: int = 60

    worker_poll_interval_seconds: float = 2.0
    worker_max_attempts: int = 3
    worker_lease_seconds: int = 900
    worker_retry_base_seconds: int = 15
    max_sources_per_investigation: int = 8
    min_relevance_score: float = 0.45

    # Batched inference reduces API calls while keeping input/reserved-output
    # budgets bounded for quota-limited providers. Discovery stays separate.
    max_relevance_batch_size: int = 8
    groq_relevance_max_completion_tokens: int = 1_200
    groq_extraction_max_input_chars: int = 8_000
    groq_extraction_max_completion_tokens: int = 2_200
    max_extraction_batch_input_chars: int = 18_000
    max_extraction_sources_per_batch: int = 3

    source_fetch_timeout_seconds: float = 15.0
    source_fetch_max_bytes: int = 4_000_000
    source_document_max_chars: int = 120_000
    source_fetch_max_redirects: int = 3
    groq_request_timeout_seconds: float = 90.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @staticmethod
    def _secret_value(value: SecretStr | None) -> str | None:
        """Return a configured API key without exposing it in settings reprs."""
        if value is None:
            return None
        extracted = value.get_secret_value().strip()
        return extracted or None

    def get_groq_api_key(self) -> str | None:
        return self._secret_value(self.groq_api_key)

    def get_openrouter_api_key(self) -> str | None:
        return self._secret_value(self.openrouter_api_key)

    def get_mistral_api_key(self) -> str | None:
        return self._secret_value(self.mistral_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings object for the application process."""
    return Settings()
