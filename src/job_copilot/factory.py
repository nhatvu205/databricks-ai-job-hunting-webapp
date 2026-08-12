from job_copilot.config import Settings, get_settings
from job_copilot.database import Database
from job_copilot.repository import JobRepository
from job_copilot.search import AiSearch
from job_copilot.service import JobCopilotService


def build_service(settings: Settings | None = None) -> JobCopilotService:
    settings = settings or get_settings()
    return JobCopilotService(
        JobRepository(Database(settings.database_url)), AiSearch(settings), settings
    )
