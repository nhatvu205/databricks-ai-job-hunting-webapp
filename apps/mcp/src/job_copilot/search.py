from datetime import datetime
from typing import Any

from job_copilot.config import Settings
from job_copilot.domain import JobResult, JobSearchFilters, ProfileContext
from job_copilot.workspace import workspace_client


class AiSearch:
    """Small REST client for a Databricks AI Search query endpoint."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def search(
        self, query: str, profile: ProfileContext, filters: JobSearchFilters, limit: int = 8
    ) -> list[JobResult]:
        enhanced_query = " ".join(
            part
            for part in [
                query,
                *profile.target_roles,
                *profile.skills,
                profile.resume_excerpt[:1200],
            ]
            if part
        )
        response = workspace_client(self.settings).vector_search_indexes.query_index(
            index_name=self.settings.vector_search_index,
            query_text=enhanced_query,
            num_results=min(max(limit * 3, 8), 30),
            columns=[
                "posting_id",
                "title",
                "company",
                "location",
                "source_url",
                "tags",
                "search_text",
                "salary_min",
                "salary_max",
                "posted_at",
            ],
        )
        return self._rank(self._decode(response.as_dict()), profile, filters, limit)

    @staticmethod
    def _decode(payload: dict[str, Any]) -> list[JobResult]:
        result = payload.get("result", payload)
        manifest = result.get("manifest", {})
        columns = [
            column.get("name", column) if isinstance(column, dict) else column
            for column in manifest.get("columns", [])
        ]
        rows = result.get("data_array", result.get("data", []))
        decoded: list[JobResult] = []
        for row in rows:
            values = dict(zip(columns, row, strict=False)) if isinstance(row, list) else row
            if not values.get("posting_id"):
                continue
            raw_tags = values.get("tags") or []
            tags = (
                raw_tags
                if isinstance(raw_tags, list)
                else str(raw_tags).replace("[", "").replace("]", "").split(",")
            )
            posted_at = values.get("posted_at")
            try:
                parsed_date = (
                    datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
                    if posted_at
                    else None
                )
            except ValueError:
                parsed_date = None
            decoded.append(
                JobResult(
                    posting_id=str(values["posting_id"]),
                    title=str(values.get("title") or "Untitled role"),
                    company=values.get("company"),
                    location=values.get("location"),
                    url=values.get("source_url"),
                    description=str(values.get("search_text") or ""),
                    tags=[str(tag).strip() for tag in tags if str(tag).strip()],
                    salary_min=_int_or_none(values.get("salary_min")),
                    salary_max=_int_or_none(values.get("salary_max")),
                    posted_at=parsed_date,
                    score=float(values.get("score") or 0),
                )
            )
        return decoded

    @staticmethod
    def _rank(
        candidates: list[JobResult], profile: ProfileContext, filters: JobSearchFilters, limit: int
    ) -> list[JobResult]:
        wanted = {skill.lower() for skill in profile.skills}
        results: list[JobResult] = []
        for job in candidates:
            content = f"{job.title} {' '.join(job.tags)} {job.description}".lower()
            if filters.remote_only and "remote" not in (job.location or "").lower():
                continue
            if filters.location and filters.location.lower() not in (job.location or "").lower():
                continue
            if filters.min_salary and job.salary_max and job.salary_max < filters.min_salary:
                continue
            if (
                filters.posted_after
                and job.posted_at
                and job.posted_at.date() < filters.posted_after
            ):
                continue
            matched = sorted(skill for skill in wanted if skill in content)
            job.matched_skills = matched
            job.missing_evidence = sorted(tag for tag in job.tags if tag.lower() not in wanted)[:5]
            overlap = len(matched) / max(len(wanted), 1)
            preference = (
                1.0
                if profile.remote_preference == "remote"
                and "remote" in (job.location or "").lower()
                else 0.0
            )
            job.score = round(0.7 * job.score + 0.2 * overlap + 0.1 * preference, 3)
            results.append(job)
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

