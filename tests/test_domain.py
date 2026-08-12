import pytest

from job_copilot.domain import (
    ApplicationStage,
    ApplicationUpdate,
    JobResult,
    JobSearchFilters,
    ProfileContext,
)
from job_copilot.search import AiSearch


def test_application_update_rejects_blank_posting_id() -> None:
    with pytest.raises(ValueError):
        ApplicationUpdate(posting_id="  ", stage=ApplicationStage.SAVED)


def test_rank_prefers_profile_skill_overlap() -> None:
    jobs = [
        JobResult(
            posting_id="a",
            title="Data engineer",
            location="Remote",
            tags=["spark", "python"],
            score=0.5,
        ),
        JobResult(
            posting_id="b", title="Data engineer", location="Remote", tags=["java"], score=0.5
        ),
    ]
    ranked = AiSearch._rank(
        jobs,
        ProfileContext(skills=["spark", "python"], remote_preference="remote"),
        JobSearchFilters(remote_only=True),
        8,
    )
    assert ranked[0].posting_id == "a"
    assert ranked[0].matched_skills == ["python", "spark"]
