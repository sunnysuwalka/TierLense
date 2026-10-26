"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tierlense.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Check process liveness")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Check database readiness")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from exc
    return {"status": "ready", "database": "ok"}
