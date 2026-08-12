import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from databricks.sdk import WorkspaceClient
from psycopg import AsyncConnection
from psycopg.rows import dict_row

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE SCHEMA IF NOT EXISTS job_copilot AUTHORIZATION CURRENT_USER;
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY,
      email TEXT,
      display_name TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS profiles (
      user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      target_roles JSONB NOT NULL DEFAULT '[]',
      preferred_locations JSONB NOT NULL DEFAULT '[]',
      remote_preference TEXT,
      salary_floor INTEGER,
      experience_summary TEXT,
      resume_text TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS skills (
      user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      skill TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, skill)
    );
    CREATE TABLE IF NOT EXISTS job_postings (
      posting_id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      company TEXT,
      location TEXT,
      source_url TEXT,
      description TEXT NOT NULL DEFAULT '',
      tags JSONB NOT NULL DEFAULT '[]',
      salary_min INTEGER,
      salary_max INTEGER,
      posted_at TIMESTAMPTZ,
      cached_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS applications (
      user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      posting_id TEXT NOT NULL REFERENCES job_postings(posting_id),
      stage TEXT NOT NULL CHECK (stage IN ('saved','applied','interviewing','rejected','offer')),
      follow_up_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, posting_id)
    );
    CREATE TABLE IF NOT EXISTS interview_notes (
      note_id BIGSERIAL PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      posting_id TEXT NOT NULL,
      note TEXT NOT NULL,
      interview_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      FOREIGN KEY (user_id, posting_id) REFERENCES applications(user_id, posting_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS agent_action_audit (
      audit_id BIGSERIAL PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      action TEXT NOT NULL,
      posting_id TEXT,
      metadata JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS applications_user_stage_idx ON applications(user_id, stage);
    CREATE INDEX IF NOT EXISTS applications_follow_up_idx ON applications(user_id, follow_up_at);
    """,
)


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        connection_kwargs = {"row_factory": dict_row}
        endpoint_name = os.getenv("LAKEBASE_ENDPOINT_NAME")
        if endpoint_name:
            workspace = WorkspaceClient()
            credential = await asyncio.to_thread(
                workspace.postgres.generate_database_credential,
                endpoint=endpoint_name,
            )
            connection_kwargs["password"] = credential.token

        async with await AsyncConnection.connect(self.dsn, **connection_kwargs) as connection:
            await connection.execute("SET search_path TO job_copilot")
            yield connection

    async def migrate(self) -> None:
        async with self.connection() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(7412026)")
                for statement in MIGRATIONS:
                    await connection.execute(statement)
