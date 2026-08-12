from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from job_copilot.database import Database
from job_copilot.domain import ApplicationStage, JobResult, ProfileContext, ProfilePatch
from job_copilot.identity import Actor


class JobRepository:
    """Lakebase persistence with an actor predicate on every user-owned query."""

    def __init__(self, database: Database):
        self.database = database

    async def ensure_user(self, actor: Actor) -> None:
        async with self.database.connection() as connection, connection.transaction():
            await connection.execute(
                """INSERT INTO users (user_id, email, display_name) VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET email = EXCLUDED.email,
                   display_name = EXCLUDED.display_name, updated_at = now()""",
                (actor.user_id, actor.email, actor.display_name),
            )

    async def get_profile(self, actor: Actor) -> ProfileContext:
        await self.ensure_user(actor)
        async with self.database.connection() as connection:
            profile = await (
                await connection.execute(
                    "SELECT * FROM profiles WHERE user_id = %s", (actor.user_id,)
                )
            ).fetchone()
            rows = await (
                await connection.execute(
                    "SELECT skill FROM skills WHERE user_id = %s ORDER BY skill", (actor.user_id,)
                )
            ).fetchall()
        if not profile:
            return ProfileContext(skills=[row["skill"] for row in rows])
        return ProfileContext(
            skills=[row["skill"] for row in rows],
            target_roles=profile["target_roles"],
            preferred_locations=profile["preferred_locations"],
            remote_preference=profile["remote_preference"],
            salary_floor=profile["salary_floor"],
            resume_excerpt=(profile["resume_text"] or "")[:6000],
        )

    async def update_profile(
        self, actor: Actor, patch: ProfilePatch, skills: list[str]
    ) -> ProfileContext:
        await self.ensure_user(actor)
        normalized_skills = sorted({skill.strip().lower() for skill in skills if skill.strip()})
        async with self.database.connection() as connection, connection.transaction():
            await connection.execute(
                """INSERT INTO profiles (user_id, target_roles, preferred_locations, remote_preference,
                   salary_floor, experience_summary, resume_text)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET target_roles = EXCLUDED.target_roles,
                   preferred_locations = EXCLUDED.preferred_locations,
                   remote_preference = EXCLUDED.remote_preference, salary_floor = EXCLUDED.salary_floor,
                   experience_summary = EXCLUDED.experience_summary, resume_text = EXCLUDED.resume_text,
                   updated_at = now()""",
                (
                    actor.user_id,
                    Jsonb(patch.target_roles),
                    Jsonb(patch.preferred_locations),
                    patch.remote_preference,
                    patch.salary_floor,
                    patch.experience_summary,
                    patch.resume_text,
                ),
            )
            await connection.execute("DELETE FROM skills WHERE user_id = %s", (actor.user_id,))
            for skill in normalized_skills:
                await connection.execute(
                    "INSERT INTO skills (user_id, skill) VALUES (%s, %s)", (actor.user_id, skill)
                )
            await self._audit(
                connection,
                actor.user_id,
                "update_profile",
                None,
                {"skills": len(normalized_skills)},
            )
        return await self.get_profile(actor)

    async def cache_job(self, job: JobResult) -> None:
        async with self.database.connection() as connection, connection.transaction():
            await connection.execute(
                """INSERT INTO job_postings (posting_id,title,company,location,source_url,description,tags,
                   salary_min,salary_max,posted_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (posting_id) DO UPDATE SET title=EXCLUDED.title, company=EXCLUDED.company,
                   location=EXCLUDED.location, source_url=EXCLUDED.source_url, description=EXCLUDED.description,
                   tags=EXCLUDED.tags, salary_min=EXCLUDED.salary_min, salary_max=EXCLUDED.salary_max,
                   posted_at=EXCLUDED.posted_at, cached_at=now()""",
                (
                    job.posting_id,
                    job.title,
                    job.company,
                    job.location,
                    job.url,
                    job.description,
                    Jsonb(job.tags),
                    job.salary_min,
                    job.salary_max,
                    job.posted_at,
                ),
            )

    async def set_application_stage(
        self,
        actor: Actor,
        job: JobResult,
        stage: ApplicationStage,
        follow_up_at: datetime | None = None,
    ) -> dict[str, Any]:
        await self.ensure_user(actor)
        await self.cache_job(job)
        async with self.database.connection() as connection, connection.transaction():
            row = await (
                await connection.execute(
                    """INSERT INTO applications (user_id, posting_id, stage, follow_up_at)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (user_id, posting_id) DO UPDATE SET stage=EXCLUDED.stage,
                       follow_up_at=COALESCE(EXCLUDED.follow_up_at, applications.follow_up_at), updated_at=now()
                       RETURNING user_id, posting_id, stage, follow_up_at, updated_at""",
                    (actor.user_id, job.posting_id, stage.value, follow_up_at),
                )
            ).fetchone()
            await self._audit(
                connection,
                actor.user_id,
                "set_application_stage",
                job.posting_id,
                {"stage": stage.value},
            )
        return dict(row)

    async def list_applications(
        self, actor: Actor, stage: ApplicationStage | None = None
    ) -> list[dict[str, Any]]:
        await self.ensure_user(actor)
        query = """SELECT a.posting_id, a.stage, a.follow_up_at, a.updated_at, j.title, j.company, j.location,
                   j.source_url FROM applications a JOIN job_postings j ON j.posting_id=a.posting_id
                   WHERE a.user_id=%s"""
        params: list[Any] = [actor.user_id]
        if stage:
            query += " AND a.stage=%s"
            params.append(stage.value)
        query += " ORDER BY a.updated_at DESC"
        async with self.database.connection() as connection:
            rows = await (await connection.execute(query, params)).fetchall()
        return [dict(row) for row in rows]

    async def add_interview_note(
        self, actor: Actor, posting_id: str, note: str, interview_at: datetime | None = None
    ) -> dict[str, Any]:
        await self.ensure_user(actor)
        if not note.strip():
            raise ValueError("note cannot be blank")
        async with self.database.connection() as connection, connection.transaction():
            row = await (
                await connection.execute(
                    """INSERT INTO interview_notes (user_id,posting_id,note,interview_at) VALUES (%s,%s,%s,%s)
                       RETURNING note_id, posting_id, note, interview_at, created_at""",
                    (actor.user_id, posting_id, note.strip(), interview_at),
                )
            ).fetchone()
            await self._audit(connection, actor.user_id, "add_interview_note", posting_id, {})
        return dict(row)

    async def list_stale_applications(self, actor: Actor, days: int = 7) -> list[dict[str, Any]]:
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self.database.connection() as connection:
            rows = await (
                await connection.execute(
                    """SELECT a.posting_id, a.stage, a.follow_up_at, a.updated_at, j.title, j.company
                       FROM applications a JOIN job_postings j ON j.posting_id=a.posting_id
                       WHERE a.user_id=%s AND a.stage IN ('saved','applied','interviewing')
                       AND a.updated_at < %s ORDER BY a.updated_at ASC""",
                    (actor.user_id, cutoff),
                )
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _audit(
        connection: Any, user_id: str, action: str, posting_id: str | None, metadata: dict[str, Any]
    ) -> None:
        await connection.execute(
            "INSERT INTO agent_action_audit (user_id, action, posting_id, metadata) VALUES (%s,%s,%s,%s)",
            (user_id, action, posting_id, Jsonb(metadata)),
        )
