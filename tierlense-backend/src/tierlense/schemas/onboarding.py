"""Responses for onboarding workflows."""

from pydantic import BaseModel

from tierlense.schemas.investigation_job import InvestigationJobRead
from tierlense.schemas.organization import OrganizationRead


class OrganizationOnboardedResponse(BaseModel):
    organization: OrganizationRead
    initial_investigation: InvestigationJobRead
    notice: str
