"""Per-investigation provider request accounting persisted on the job record."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from tierlense.models.investigation_job import InvestigationJob

SessionFactory = Callable[[], Session]
_CURRENT_STAGE: ContextVar[str] = ContextVar("tierlense_provider_stage", default="unknown")
_CURRENT_PROVIDER_ATTEMPT: ContextVar[str] = ContextVar("tierlense_provider_attempt", default="primary")
_CURRENT_RECORDER: ContextVar["JobMetricsRecorder | None"] = ContextVar(
    "tierlense_job_metrics_recorder", default=None
)


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class JobMetricsRecorder:
    """Persist counts and provider-reported token usage after every API attempt."""

    def __init__(self, session_factory: SessionFactory, job_id: UUID) -> None:
        self.session_factory = session_factory
        self.job_id = job_id

    def record(
        self,
        *,
        provider: str,
        stage: str,
        success: bool,
        response: Any = None,
        status_code: int | None = None,
        error_code: str | None = None,
        model: str | None = None,
        attempt_kind: str = "primary",
    ) -> None:
        usage = _read(response, "usage") if response is not None else None
        prompt_tokens = int(_read(usage, "prompt_tokens", _read(usage, "input_tokens", 0)) or 0)
        completion_tokens = int(_read(usage, "completion_tokens", _read(usage, "output_tokens", 0)) or 0)
        total_tokens = int(_read(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
        with self.session_factory() as db:
            job = db.get(InvestigationJob, self.job_id)
            if job is None:
                return
            metrics = dict(job.execution_metrics or {})
            providers = dict(metrics.get("providers") or {})
            provider_metrics = dict(providers.get(provider) or {})
            stages = dict(provider_metrics.get("stages") or {})
            stage_metrics = dict(stages.get(stage) or {})
            stage_metrics["requests"] = int(stage_metrics.get("requests", 0)) + 1
            stage_metrics["primary_requests"] = int(stage_metrics.get("primary_requests", 0)) + int(attempt_kind != "fallback")
            stage_metrics["fallback_requests"] = int(stage_metrics.get("fallback_requests", 0)) + int(attempt_kind == "fallback")
            if model:
                models = list(stage_metrics.get("models") or [])
                if model not in models:
                    models.append(model)
                stage_metrics["models"] = models
            stage_metrics["successes"] = int(stage_metrics.get("successes", 0)) + int(success)
            stage_metrics["failures"] = int(stage_metrics.get("failures", 0)) + int(not success)
            stage_metrics["prompt_tokens"] = int(stage_metrics.get("prompt_tokens", 0)) + prompt_tokens
            stage_metrics["completion_tokens"] = int(stage_metrics.get("completion_tokens", 0)) + completion_tokens
            stage_metrics["total_tokens"] = int(stage_metrics.get("total_tokens", 0)) + total_tokens
            if status_code is not None:
                stage_metrics["last_status_code"] = int(status_code)
            if error_code:
                stage_metrics["last_error_code"] = str(error_code)[:100]
            stage_metrics["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
            stages[stage] = stage_metrics
            provider_metrics["stages"] = stages
            providers[provider] = provider_metrics
            totals = dict(metrics.get("totals") or {})
            totals["requests"] = int(totals.get("requests", 0)) + 1
            totals["fallback_requests"] = int(totals.get("fallback_requests", 0)) + int(attempt_kind == "fallback")
            totals["successes"] = int(totals.get("successes", 0)) + int(success)
            totals["failures"] = int(totals.get("failures", 0)) + int(not success)
            totals["prompt_tokens"] = int(totals.get("prompt_tokens", 0)) + prompt_tokens
            totals["completion_tokens"] = int(totals.get("completion_tokens", 0)) + completion_tokens
            totals["total_tokens"] = int(totals.get("total_tokens", 0)) + total_tokens
            metrics["providers"] = providers
            metrics["totals"] = totals
            metrics["queue_attempt_count"] = int(job.attempt_count or 0)
            job.execution_metrics = metrics
            job.updated_at = datetime.now(timezone.utc)
            db.commit()


@contextmanager
def metrics_context(recorder: JobMetricsRecorder) -> Iterator[None]:
    token: Token = _CURRENT_RECORDER.set(recorder)
    try:
        yield
    finally:
        _CURRENT_RECORDER.reset(token)


@contextmanager
def provider_stage(stage: str) -> Iterator[None]:
    token: Token = _CURRENT_STAGE.set(stage)
    try:
        yield
    finally:
        _CURRENT_STAGE.reset(token)


@contextmanager
def provider_attempt(attempt_kind: str) -> Iterator[None]:
    """Label calls made through a non-primary provider as fallback requests."""
    token: Token = _CURRENT_PROVIDER_ATTEMPT.set(attempt_kind)
    try:
        yield
    finally:
        _CURRENT_PROVIDER_ATTEMPT.reset(token)


def record_provider_request(
    provider: str,
    *,
    success: bool,
    response: Any = None,
    status_code: int | None = None,
    error_code: str | None = None,
    stage: str | None = None,
    model: str | None = None,
    attempt_kind: str | None = None,
) -> None:
    recorder = _CURRENT_RECORDER.get()
    if recorder is None:
        return
    recorder.record(
        provider=provider,
        stage=stage or _CURRENT_STAGE.get(),
        success=success,
        response=response,
        status_code=status_code,
        error_code=error_code,
        model=model,
        attempt_kind=attempt_kind or _CURRENT_PROVIDER_ATTEMPT.get(),
    )
