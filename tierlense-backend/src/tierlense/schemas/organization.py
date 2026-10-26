"""Organization and watch-profile API schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

Criticality = Literal["low", "medium", "high", "critical"]
IdentityStatus = Literal["unverified", "needs_review", "verified"]


class WatchProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dependency_role: str = Field(default="supplier", min_length=1, max_length=100)
    products_services: list[str] = Field(default_factory=list, max_length=100)
    dependency_context: str | None = Field(default=None, max_length=5000)
    criticality: Criticality = "medium"
    identity_clues: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("products_services", "identity_clues")
    @classmethod
    def strip_list_values(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        return cleaned


class WatchProfileRead(WatchProfileInput):
    model_config = ConfigDict(from_attributes=True)
    organization_id: UUID


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    website: AnyHttpUrl | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    description: str | None = Field(default=None, max_length=10000)
    watch_profile: WatchProfileInput = Field(default_factory=WatchProfileInput)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Organization name cannot be blank")
        return value.strip()

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: AnyHttpUrl | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Organization name cannot be blank")
        return value.strip() if value is not None else value

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    website: str | None
    country_code: str | None
    description: str | None
    identity_status: IdentityStatus
    created_at: datetime
    updated_at: datetime
    watch_profile: WatchProfileRead | None = None


class OrganizationList(BaseModel):
    items: list[OrganizationRead]
    total: int
    limit: int
    offset: int
