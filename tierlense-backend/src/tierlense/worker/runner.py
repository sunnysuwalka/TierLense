"""Worker loop for the PostgreSQL-backed TierLense investigation queue."""

from __future__ import annotations

import logging
import os
import socket
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from tierlense.core.config import Settings, get_settings
from tierlense.intelligence.errors import NonRetryableInvestigationError, ProviderRateLimitError
from tierlense.intelligence.fetcher import HttpSourceFetcher
from tierlense.intelligence.provider_factory import build_provider_chains
from tierlense.intelligence.pipeline import InvestigationPipeline
from tierlense.services.job_queue import claim_next_job, fail_job

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]


def build_pipeline(session_factory: SessionFactory, settings: Settings | None = None) -> InvestigationPipeline:
    resolved = settings or get_settings()
    discovery, analyzer = build_provider_chains(resolved)
    return InvestigationPipeline(
        session_factory=session_factory,
        discovery=discovery,
        fetcher=HttpSourceFetcher(resolved),
        analyzer=analyzer,
        settings=resolved,
    )


def run_one_job(
    session_factory: SessionFactory,
    pipeline: InvestigationPipeline,
    *,
    worker_id: str,
    settings: Settings | None = None,
) -> UUID | None:
    """Claim and process at most one due job; return its ID, if any was claimed."""
    resolved = settings or get_settings()
    job_id = claim_next_job(
        session_factory,
        worker_id=worker_id,
        lease_seconds=resolved.worker_lease_seconds,
        max_attempts=resolved.worker_max_attempts,
    )
    if job_id is None:
        return None
    try:
        pipeline.process(job_id)
        logger.info("Investigation %s completed", job_id)
    except Exception as exc:  # Worker must persist the job failure, not silently exit.
        retryable = not isinstance(exc, NonRetryableInvestigationError)
        logger.exception("Investigation %s failed (retryable=%s)", job_id, retryable)
        fail_job(
            session_factory,
            job_id,
            exc,
            max_attempts=resolved.worker_max_attempts,
            retry_base_seconds=resolved.worker_retry_base_seconds,
            retryable=retryable,
            retry_after_seconds=(
                exc.retry_after_seconds if isinstance(exc, ProviderRateLimitError) else None
            ),
        )
    return job_id


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"
