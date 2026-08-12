import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; every deploy-specific value can be overridden safely."""

    model_config = SettingsConfigDict(env_prefix="JOB_COPILOT_", env_file=".env", extra="ignore")

    database_url: str = Field(default_factory=lambda: _lakebase_dsn())
    catalog: str = "main"
    schema_name: str = "job_copilot"
    vector_search_endpoint: str = "job-copilot-vs"
    vector_search_index: str = Field(
        default_factory=lambda: os.getenv("VECTOR_SEARCH_INDEX", "main.job_copilot.job_documents_index")
    )
    model_endpoint: str = Field(
        default_factory=lambda: os.getenv("SERVING_ENDPOINT", "databricks-claude-sonnet-4-5")
    )
    databricks_host: str | None = Field(default_factory=lambda: os.getenv("DATABRICKS_HOST"))
    databricks_token: str | None = Field(default=None, repr=False)
    max_resume_characters: int = 6000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _lakebase_dsn() -> str:
    """Databricks Apps inject PG* variables for a Lakebase resource."""
    host = os.getenv("PGHOST")
    if host:
        values = {
            "host": host,
            "port": os.getenv("PGPORT", "5432"),
            "dbname": os.getenv("PGDATABASE", "databricks_postgres"),
            "user": os.getenv("PGUSER", ""),
            "sslmode": os.getenv("PGSSLMODE", "require"),
        }
        return " ".join(f"{key}={value}" for key, value in values.items() if value)
    return "postgresql://postgres:postgres@localhost:5432/job_copilot"
