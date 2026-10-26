"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tierlense import __version__
from tierlense.api.routes import health, investigation_jobs, investigation_results, operations, organizations, supply_chain
from tierlense.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "TierLense backend with organization onboarding, a PostgreSQL-backed investigation queue, "
        "public-source discovery, evidence storage, an evidence-backed supply-chain graph, disruption events and AI-assisted claim extraction. "
        "Run `python -m tierlense.worker` in a separate process to execute investigations."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(organizations.router, prefix=settings.api_v1_prefix)
app.include_router(investigation_jobs.router, prefix=settings.api_v1_prefix)
app.include_router(investigation_results.router, prefix=settings.api_v1_prefix)
app.include_router(supply_chain.router, prefix=settings.api_v1_prefix)
app.include_router(operations.router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["service"], summary="Service information")
def service_info() -> dict[str, str]:
    return {"service": "TierLense API", "version": __version__, "status": "running"}
