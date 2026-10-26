"""Ordered provider failover with a shared in-process cooldown registry."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from tierlense.intelligence.metrics import provider_attempt, provider_stage
from tierlense.intelligence.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
)
from tierlense.intelligence.schemas import (
    ExtractedFinding,
    FetchedDocument,
    OrganizationContext,
    RelevanceAssessment,
    SourceCandidate,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
_PROVIDER_FAILURES = (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
)


class ProviderCooldownRegistry:
    """Share provider cooldowns across discovery and analysis in one worker."""
    def __init__(self) -> None:
        self._cooldown_until: dict[str, float] = {}

    def remaining(self, provider_name: str) -> float:
        return max(0.0, self._cooldown_until.get(provider_name, 0.0) - time.monotonic())

    def put(self, provider_name: str, seconds: float) -> None:
        if seconds > 0:
            self._cooldown_until[provider_name] = max(
                self._cooldown_until.get(provider_name, 0.0),
                time.monotonic() + min(float(seconds), 86_400.0),
            )


class _FailoverBase:
    def __init__(self, providers: Sequence[Any], *, cooldowns: ProviderCooldownRegistry | None = None,
                 failure_cooldown_seconds: int = 60, chain_name: str = "provider operation") -> None:
        self.providers = list(providers)
        self.cooldowns = cooldowns or ProviderCooldownRegistry()
        self.failure_cooldown_seconds = max(1, int(failure_cooldown_seconds))
        self.chain_name = chain_name

    @staticmethod
    def _provider_name(provider: Any) -> str:
        return str(getattr(provider, "provider_name", type(provider).__name__))

    def _cooldown_for_error(self, error: Exception) -> float:
        if isinstance(error, ProviderRateLimitError):
            return error.retry_after_seconds or self.failure_cooldown_seconds
        if isinstance(error, ProviderRequestError) and error.status_code in {401, 403}:
            return max(self.failure_cooldown_seconds, 300)
        if isinstance(error, ProviderConfigurationError):
            return max(self.failure_cooldown_seconds, 300)
        return self.failure_cooldown_seconds

    def _run(self, operation: str, invoke: Callable[[Any], T], *, accept_empty: bool = True) -> T:
        if not self.providers:
            raise ProviderConfigurationError(
                "No AI provider is configured. Set GROQ_API_KEY, OPENROUTER_API_KEY, and/or MISTRAL_API_KEY."
            )
        failures: list[tuple[str, Exception]] = []
        skipped_waits: list[float] = []
        successful_empty: T | None = None
        had_success = False

        for provider_index, provider in enumerate(self.providers):
            name = self._provider_name(provider)
            remaining = self.cooldowns.remaining(name)
            if remaining > 0:
                skipped_waits.append(remaining)
                logger.info("Provider %s skipped for %s due to cooldown (%.0f seconds remaining)", name, operation, remaining)
                continue
            try:
                attempt_kind = "primary" if provider_index == 0 else "fallback"
                with provider_attempt(attempt_kind), provider_stage(operation):
                    result = invoke(provider)
                had_success = True
                is_empty = isinstance(result, (list, tuple)) and len(result) == 0
                if is_empty and not accept_empty:
                    successful_empty = result
                    logger.info("Provider %s returned no candidates; trying next discovery provider", name)
                    continue
                logger.info("TierLense %s succeeded with provider %s", operation, name)
                return result
            except _PROVIDER_FAILURES as exc:
                failures.append((name, exc))
                self.cooldowns.put(name, self._cooldown_for_error(exc))
                logger.warning("Provider %s failed during %s (%s); trying next configured provider",
                               name, operation, type(exc).__name__)

        # Empty discovery is valid if at least one configured provider searched successfully.
        if had_success and successful_empty is not None and not failures and not skipped_waits:
            return successful_empty

        if not failures and skipped_waits:
            raise ProviderRateLimitError(
                f"All configured providers are temporarily cooling down for {self.chain_name}.",
                retry_after_seconds=max(1.0, max(skipped_waits)),
            )
        if failures and skipped_waits and any(
            isinstance(error, ProviderRateLimitError) for _, error in failures
        ):
            # At least one provider was skipped because its prior rate-limit
            # cooldown is still active, and every provider we could try failed
            # with at least one additional rate limit. Do not spend another
            # durable-queue attempt on a short backoff that will just hit the
            # same unavailable provider set again.
            delays = list(skipped_waits)
            delays.extend(
                error.retry_after_seconds or self.failure_cooldown_seconds
                for _, error in failures
                if isinstance(error, ProviderRateLimitError)
            )
            names = ", ".join(name for name, _ in failures)
            raise ProviderRateLimitError(
                f"No available provider could complete {self.chain_name}; at least one configured provider "
                f"is still cooling down and another rate-limited ({names}).",
                retry_after_seconds=max(delays, default=float(self.failure_cooldown_seconds)),
            )
        if failures and all(isinstance(error, ProviderRateLimitError) for _, error in failures):
            delays = [error.retry_after_seconds or self.failure_cooldown_seconds
                      for _, error in failures if isinstance(error, ProviderRateLimitError)]
            delays.extend(skipped_waits)
            names = ", ".join(name for name, _ in failures)
            raise ProviderRateLimitError(
                f"All attempted providers are rate-limited for {self.chain_name} ({names}).",
                retry_after_seconds=max(delays, default=float(self.failure_cooldown_seconds)),
            )
        if failures:
            detail = "; ".join(f"{name}: {str(error)[:220]}" for name, error in failures)
            if skipped_waits:
                detail += "; one or more providers remain in cooldown"
            raise ProviderResponseError(f"All available providers failed during {self.chain_name}: {detail}") from None
        if had_success:
            return successful_empty  # type: ignore[return-value]
        raise ProviderRateLimitError(f"No provider was available for {self.chain_name}.",
                                     retry_after_seconds=self.failure_cooldown_seconds)


class FailoverSourceDiscoveryProvider(_FailoverBase):
    """Try public-source discovery providers in configured priority order."""
    def discover(self, organization: OrganizationContext, max_results: int) -> list[SourceCandidate]:
        return self._run("source discovery", lambda provider: provider.discover(organization, max_results),
                         accept_empty=False)


class FailoverIntelligenceProvider(_FailoverBase):
    """Try model providers in priority order while preserving validated outputs."""
    def classify_relevance(self, organization: OrganizationContext, candidate: SourceCandidate) -> RelevanceAssessment:
        return self._run("relevance classification", lambda provider: provider.classify_relevance(organization, candidate))

    def extract_findings(self, organization: OrganizationContext, candidate: SourceCandidate,
                         document: FetchedDocument) -> list[ExtractedFinding]:
        return self._run("finding extraction", lambda provider: provider.extract_findings(organization, candidate, document))
    def classify_relevance_batch(self, organization: OrganizationContext, candidates: list[tuple[str, SourceCandidate]]) -> dict[str, RelevanceAssessment]:
        """Run one relevance batch through one provider at a time, preserving fallback order."""
        def call(provider: Any) -> dict[str, RelevanceAssessment]:
            method = getattr(provider, "classify_relevance_batch", None)
            if callable(method):
                return method(organization, candidates)
            return {source_id: provider.classify_relevance(organization, candidate)
                    for source_id, candidate in candidates}
        return self._run("batch relevance classification", call)

    def extract_findings_batch(self, organization: OrganizationContext,
                               documents: list[tuple[str, SourceCandidate, FetchedDocument]]) -> dict[str, list[ExtractedFinding]]:
        """Extract a bounded document group using the first provider returning validated output."""
        def call(provider: Any) -> dict[str, list[ExtractedFinding]]:
            method = getattr(provider, "extract_findings_batch", None)
            if callable(method):
                return method(organization, documents)
            return {source_id: provider.extract_findings(organization, candidate, document)
                    for source_id, candidate, document in documents}
        return self._run("batch finding extraction", call)

