"""Private FastMCP server. Databricks Apps forwards the authenticated user headers."""

import asyncio
import os
from datetime import datetime
from typing import Any

from fastmcp import Context, FastMCP

from job_copilot.domain import ApplicationStage, JobResult, JobSearchFilters, ProfilePatch
from job_copilot.factory import build_service
from job_copilot.identity import Actor, actor_from_headers

mcp = FastMCP("AI Job Hunting Copilot")
service = build_service()


def _actor(context: Context) -> Actor:
    request_context = getattr(context, "request_context", None)
    request = getattr(request_context, "request", None)
    headers: Any = getattr(request, "headers", {})
    return actor_from_headers(dict(headers))


@mcp.tool
async def get_profile(ctx: Context) -> dict:
    """Get the authenticated user's job preferences and skills."""
    return (await service.repository.get_profile(_actor(ctx))).model_dump()


@mcp.tool
async def update_profile(ctx: Context, profile: dict, skills: list[str]) -> dict:
    """Update only the authenticated user's profile."""
    return (
        await service.update_profile(_actor(ctx), ProfilePatch.model_validate(profile), skills)
    ).model_dump()


@mcp.tool
async def search_jobs(
    ctx: Context, query: str, filters: dict | None = None, limit: int = 8
) -> list[dict]:
    """Search AI Search job documents and rank them for the authenticated user."""
    jobs = await service.search_jobs(
        _actor(ctx), query, JobSearchFilters.model_validate(filters or {}), limit
    )
    return [job.model_dump(mode="json") for job in jobs]


@mcp.tool
async def set_application_stage(
    ctx: Context, job: dict, stage: str, follow_up_at: str | None = None
) -> dict:
    """Persist an explicitly requested application-stage update for the authenticated user."""
    parsed_follow_up = datetime.fromisoformat(follow_up_at) if follow_up_at else None
    return await service.set_application_stage(
        _actor(ctx), JobResult.model_validate(job), ApplicationStage(stage), parsed_follow_up
    )


@mcp.tool
async def list_applications(ctx: Context, stage: str | None = None) -> list[dict]:
    """List only the authenticated user's applications."""
    return await service.repository.list_applications(
        _actor(ctx), ApplicationStage(stage) if stage else None
    )


@mcp.tool
async def add_interview_note(
    ctx: Context, posting_id: str, note: str, interview_at: str | None = None
) -> dict:
    """Add an interview note to the authenticated user's saved application."""
    parsed_at = datetime.fromisoformat(interview_at) if interview_at else None
    return await service.repository.add_interview_note(_actor(ctx), posting_id, note, parsed_at)


@mcp.tool
async def list_stale_applications(ctx: Context, days: int = 7) -> list[dict]:
    """Return the authenticated user's active applications that need attention."""
    return await service.repository.list_stale_applications(_actor(ctx), days)


@mcp.tool
async def health() -> dict:
    """Return a non-sensitive health response for deployment smoke checks."""
    return {"status": "ok", "service": "mcp-job-copilot"}


async def main() -> None:
    await service.repository.database.migrate()
    await mcp.run_async(
        transport="http", host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8000"))
    )


if __name__ == "__main__":
    asyncio.run(main())

