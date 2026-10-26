"""Unit tests for PostgreSQL-backed queue state transitions using SQLite semantics."""

from datetime import timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tierlense.db.base import Base
from tierlense.models import InvestigationJob, Organization
from tierlense.services.job_queue import claim_next_job, fail_job, utc_now
from tierlense import models  # noqa: F401


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def _queued_job(factory):
    with factory() as db:
        organization = Organization(name="Queue test organization", identity_status="unverified")
        db.add(organization)
        db.flush()
        job = InvestigationJob(organization_id=organization.id, job_type="initial_scan", status="queued", scheduled_at=utc_now())
        db.add(job)
        db.commit()
        return job.id


def test_claim_marks_job_running_and_increments_attempt():
    engine, factory = _factory()
    try:
        job_id = _queued_job(factory)
        claimed_id = claim_next_job(factory, worker_id="test-worker", lease_seconds=60)
        assert claimed_id == job_id
        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            assert job.status == "running"
            assert job.attempt_count == 1
            assert job.lease_expires_at is not None
            assert job.worker_id == "test-worker"
        assert claim_next_job(factory, worker_id="another-worker", lease_seconds=60) is None
    finally:
        engine.dispose()


def test_retryable_failure_is_requeued_with_backoff():
    engine, factory = _factory()
    try:
        job_id = _queued_job(factory)
        claim_next_job(factory, worker_id="test-worker", lease_seconds=60)
        current = utc_now()
        fail_job(factory, job_id, RuntimeError("temporary upstream failure"), max_attempts=3, retry_base_seconds=10, now=current)
        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            assert job.status == "queued"
            assert job.attempt_count == 1
            assert job.next_attempt_at is not None
            assert job.error_summary.startswith("RuntimeError")
        assert claim_next_job(factory, worker_id="test-worker", now=current + timedelta(seconds=5)) is None
        assert claim_next_job(factory, worker_id="test-worker", now=current + timedelta(seconds=11)) == job_id
    finally:
        engine.dispose()


def test_provider_retry_after_is_honored_in_durable_queue():
    engine, factory = _factory()
    try:
        job_id = _queued_job(factory)
        claim_next_job(factory, worker_id="test-worker", lease_seconds=60)
        current = utc_now()
        fail_job(
            factory,
            job_id,
            RuntimeError("provider rate limit"),
            max_attempts=3,
            retry_base_seconds=15,
            retry_after_seconds=4.2,
            now=current,
        )
        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            assert job.status == "queued"
            scheduled = job.next_attempt_at
            if scheduled.tzinfo is None:  # SQLite drops timezone metadata in tests.
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            assert scheduled == current + timedelta(seconds=5)
        assert claim_next_job(factory, worker_id="test-worker", now=current + timedelta(seconds=4)) is None
        assert claim_next_job(factory, worker_id="test-worker", now=current + timedelta(seconds=6)) == job_id
    finally:
        engine.dispose()


def test_expired_worker_lease_can_be_reclaimed():
    engine, factory = _factory()
    try:
        job_id = _queued_job(factory)
        start = utc_now()
        assert claim_next_job(factory, worker_id="first-worker", lease_seconds=5, now=start) == job_id
        assert claim_next_job(factory, worker_id="second-worker", lease_seconds=30, now=start + timedelta(seconds=6)) == job_id
        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            assert job.status == "running"
            assert job.attempt_count == 2
            assert job.worker_id == "second-worker"
    finally:
        engine.dispose()
