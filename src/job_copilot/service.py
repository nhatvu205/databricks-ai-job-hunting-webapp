from datetime import datetime

from job_copilot.config import Settings
from job_copilot.domain import (
    ApplicationStage,
    JobResult,
    JobSearchFilters,
    ProfileContext,
    ProfilePatch,
)
from job_copilot.identity import Actor
from job_copilot.repository import JobRepository
from job_copilot.search import AiSearch


class JobCopilotService:
    def __init__(self, repository: JobRepository, search: AiSearch, settings: Settings):
        self.repository = repository
        self.search_client = search
        self.settings = settings

    async def search_jobs(
        self, actor: Actor, query: str, filters: JobSearchFilters | None = None, limit: int = 8
    ) -> list[JobResult]:
        profile = await self.repository.get_profile(actor)
        return self.search_client.search(query, profile, filters or JobSearchFilters(), limit)

    async def update_profile(
        self, actor: Actor, patch: ProfilePatch, skills: list[str]
    ) -> ProfileContext:
        if patch.resume_text and len(patch.resume_text) > self.settings.max_resume_characters * 2:
            raise ValueError("resume text is too long")
        return await self.repository.update_profile(actor, patch, skills)

    async def set_application_stage(
        self,
        actor: Actor,
        job: JobResult,
        stage: ApplicationStage,
        follow_up_at: datetime | None = None,
    ) -> dict:
        return await self.repository.set_application_stage(actor, job, stage, follow_up_at)
