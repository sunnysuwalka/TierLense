"""Explicit exception types used for retry and source-fetch decisions."""


class InvestigationError(Exception):
    """Base class for investigation pipeline failures."""


class NonRetryableInvestigationError(InvestigationError):
    """A configuration/input problem that retrying will not fix."""


class ProviderConfigurationError(NonRetryableInvestigationError):
    """Required AI provider configuration is missing or invalid."""


class ProviderRequestError(NonRetryableInvestigationError):
    """The provider rejected a request that will not succeed unchanged on retry."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


class ProviderResponseError(InvestigationError):
    """A provider response could not be parsed or validated."""


class SourceFetchError(InvestigationError):
    """A public source could not be fetched or safely processed."""


class ProviderRateLimitError(InvestigationError):
    """Transient provider rate limit with an optional recommended retry delay."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
