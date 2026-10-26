"""Run the TierLense background worker: python -m tierlense.worker."""

from __future__ import annotations

import argparse
import logging
import time

from tierlense.core.config import get_settings
from tierlense.db.session import SessionLocal
from tierlense.worker.runner import build_pipeline, default_worker_id, run_one_job
from tierlense.services.operations import enqueue_due_scheduled_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TierLense's PostgreSQL-backed investigation worker")
    parser.add_argument("--once", action="store_true", help="Process at most one due job and exit")
    parser.add_argument("--poll-interval", type=float, default=None, help="Override the configured idle polling interval")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    poll_interval = max(0.25, args.poll_interval or settings.worker_poll_interval_seconds)
    pipeline = build_pipeline(SessionLocal, settings)
    worker_id = default_worker_id()
    logging.getLogger(__name__).info("TierLense worker started as %s", worker_id)

    if args.once:
        scheduled = enqueue_due_scheduled_jobs(SessionLocal)
        if scheduled:
            logging.getLogger(__name__).info("Queued %s due scheduled investigation(s)", len(scheduled))
        job_id = run_one_job(SessionLocal, pipeline, worker_id=worker_id, settings=settings)
        if job_id is None:
            logging.getLogger(__name__).info("No due investigation jobs found")
        return 0

    try:
        while True:
            scheduled = enqueue_due_scheduled_jobs(SessionLocal)
            if scheduled:
                logging.getLogger(__name__).info("Queued %s due scheduled investigation(s)", len(scheduled))
            job_id = run_one_job(SessionLocal, pipeline, worker_id=worker_id, settings=settings)
            if job_id is None:
                time.sleep(poll_interval)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Worker stopped by operator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
