"""PostgreSQL-backed work queue with leasing, retry scheduling, and crash recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Callable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from tierlense.models import InvestigationJob

SessionFactory = Callable[[], Session]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job(
    session_factory: SessionFactory,
    *,
    worker_id: str,
    lease_seconds: int = 900,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> UUID | None:
    """Atomically claim one due job. PostgreSQL SKIP LOCKED permits multiple workers."""
    current = now or utc_now()
    with session_factory() as db:
        stale_statement = select(InvestigationJob).where(
            InvestigationJob.status == "running",
            InvestigationJob.lease_expires_at.is_not(None),
            InvestigationJob.lease_expires_at <= current,
        )
        stale_jobs = list(db.scalars(stale_statement.with_for_update(skip_locked=True)).all())
        for stale in stale_jobs:
            stale.lease_expires_at = None
            stale.worker_id = None
            stale.error_summary = "Worker lease expired before the job finished."
            stale.updated_at = current
            if stale.attempt_count >= max_attempts:
                stale.status = "failed"
                stale.finished_at = current
                stale.progress_message = "Failed after worker lease expired at the attempt limit."
            else:
                stale.status = "queued"
                stale.next_attempt_at = current
                stale.finished_at = None
                stale.progress_message = "Worker lease expired; job returned to the queue."
        db.flush()

        due_retry = or_(
            InvestigationJob.next_attempt_at.is_(None),
            InvestigationJob.next_attempt_at <= current,
        )
        eligible_queued = and_(
            InvestigationJob.status == "queued",
            InvestigationJob.scheduled_at <= current,
            due_retry,
            InvestigationJob.attempt_count < max_attempts,
        )
        statement = (
            select(InvestigationJob)
            .where(eligible_queued)
            .order_by(InvestigationJob.scheduled_at.asc(), InvestigationJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.scalar(statement)
        if job is None:
            db.commit()
            return None

        job.status = "running"
        job.started_at = current
        job.finished_at = None
        job.attempt_count += 1
        job.lease_expires_at = current + timedelta(seconds=lease_seconds)
        job.worker_id = worker_id[:255]
        job.next_attempt_at = None
        job.error_summary = None
        job.progress_percent = 1
        job.progress_message = "Investigation started."
        job.updated_at = current
        job_id = job.id
        db.commit()
        return job_id


def update_job_progress(
    session_factory: SessionFactory,
    job_id: UUID,
    *,
    percent: int,
    message: str,
    lease_seconds: int = 900,
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    with session_factory() as db:
        job = db.get(InvestigationJob, job_id)
        if job is None:
            return
        job.progress_percent = max(0, min(99, percent))
        job.progress_message = message[:500]
        job.updated_at = current
        # Progress updates also extend the lease while a long-running source is processed.
        job.lease_expires_at = current + timedelta(seconds=lease_seconds)
        db.commit()


def complete_job(
    session_factory: SessionFactory,
    job_id: UUID,
    *,
    result_summary: dict,
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    with session_factory() as db:
        job = db.get(InvestigationJob, job_id)
        if job is None:
            return
        job.status = "completed"
        job.progress_percent = 100
        job.progress_message = "Investigation completed."
        job.result_summary = result_summary
        job.finished_at = current
        job.updated_at = current
        job.lease_expires_at = None
        job.next_attempt_at = None
        job.error_summary = None
        from tierlense.services.operations import create_investigation_snapshot
        create_investigation_snapshot(db, job, now=current)
        db.commit()


def fail_job(
    session_factory: SessionFactory,
    job_id: UUID,
    error: Exception,
    *,
    max_attempts: int = 3,
    retry_base_seconds: int = 15,
    retryable: bool = True,
    retry_after_seconds: float | None = None,
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    with session_factory() as db:
        job = db.get(InvestigationJob, job_id)
        if job is None:
            return
        message = f"{type(error).__name__}: {error}"[:4000]
        job.error_summary = message
        job.updated_at = current
        job.lease_expires_at = None
        job.worker_id = None
        if retryable and job.attempt_count < max_attempts:
            if retry_after_seconds is not None:
                # Honor the provider's explicit delay; clamp it to avoid immediate
                # retry loops and accidental multi-day sleeps from malformed headers.
                delay = max(1, min(3600, math.ceil(retry_after_seconds)))
            else:
                delay = retry_base_seconds * (2 ** max(0, job.attempt_count - 1))
            job.status = "queued"
            job.next_attempt_at = current + timedelta(seconds=delay)
            job.finished_at = None
            job.progress_message = f"Attempt failed; retry scheduled in {delay} seconds."[:500]
        else:
            job.status = "failed"
            job.next_attempt_at = None
            job.finished_at = current
            job.progress_message = "Investigation failed; see the error summary."
        db.commit()
