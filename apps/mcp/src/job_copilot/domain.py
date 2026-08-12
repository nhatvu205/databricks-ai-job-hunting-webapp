from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ApplicationStage(StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"
    OFFER = "offer"


class ProfilePatch(BaseModel):
    target_roles: list[str] = Field(default_factory=list, max_length=10)
    preferred_locations: list[str] = Field(default_factory=list, max_length=10)
    remote_preference: str | None = Field(default=None, max_length=30)
    salary_floor: int | None = Field(default=None, ge=0)
    experience_summary: str | None = Field(default=None, max_length=4000)
    resume_text: str | None = Field(default=None, max_length=12000)


class JobSearchFilters(BaseModel):
    location: str | None = Field(default=None, max_length=100)
    remote_only: bool = False
    min_salary: int | None = Field(default=None, ge=0)
    posted_after: date | None = None


class JobResult(BaseModel):
    posting_id: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    posted_at: datetime | None = None
    score: float = 0.0
    matched_skills: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class ProfileContext(BaseModel):
    skills: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: str | None = None
    salary_floor: int | None = None
    resume_excerpt: str = ""


class ApplicationUpdate(BaseModel):
    posting_id: str = Field(min_length=1, max_length=200)
    stage: ApplicationStage
    follow_up_at: datetime | None = None

    @field_validator("posting_id")
    @classmethod
    def prevent_blank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("posting_id cannot be blank")
        return value.strip()


JSON = dict[str, Any]

