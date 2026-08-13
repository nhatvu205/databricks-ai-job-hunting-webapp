"""Spark pipeline for the RemoteOK public JSON API."""

import hashlib
import html
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx

REMOTEOK_URL = "https://remoteok.com/api"
USER_AGENT = "AI-Job-Hunting-Copilot/0.1 (educational Databricks capstone)"


def fetch_remoteok_rows() -> list[dict[str, Any]]:
    response = httpx.get(REMOTEOK_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("RemoteOK returned an unexpected payload")
    return [row for row in payload if isinstance(row, dict)]


def fetch_remoteok_jobs() -> list[dict[str, Any]]:
    """Compatibility helper returning just source rows that can identify a job."""
    return [row for row in fetch_remoteok_rows() if row.get("id")]


def clean_html(value: str | None) -> str:
    plain = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", _repair_mojibake(html.unescape(plain))).strip()


def _repair_mojibake(value: str) -> str:
    """Recover UTF-8 sequences that the source decoded as Latin-1 or Windows-1252."""
    repaired: list[str] = []
    index = 0
    while index < len(value):
        first = _legacy_byte(value[index])
        width = (
            2
            if first is not None and 0xC2 <= first <= 0xDF
            else 3
            if first is not None and 0xE0 <= first <= 0xEF
            else 4
            if first is not None and 0xF0 <= first <= 0xF4
            else 1
        )
        if width == 1:
            repaired.append(value[index])
            index += 1
            continue

        continuation: list[int] = []
        for offset in range(1, width):
            if index + offset >= len(value):
                break
            byte = _legacy_byte(value[index + offset])
            if byte is None or not 0x80 <= byte <= 0xBF:
                break
            continuation.append(byte)

        if len(continuation) == width - 1:
            repaired.append(bytes([first, *continuation]).decode("utf-8"))
            index += width
        elif continuation and index + 1 + len(continuation) == len(value):
            # RemoteOK occasionally truncates the final byte of a symbol in a title.
            index = len(value)
        else:
            repaired.append(value[index])
            index += 1
    return "".join(repaired)


def _legacy_byte(character: str) -> int | None:
    codepoint = ord(character)
    if codepoint <= 0xFF:
        return codepoint
    try:
        return character.encode("cp1252")[0]
    except UnicodeEncodeError:
        return None


def canonical_job(row: dict[str, Any], ingested_at: datetime) -> dict[str, Any]:
    external_id = str(row["id"])
    description = clean_html(row.get("description"))
    tags = [str(tag).strip().lower() for tag in row.get("tags", []) if str(tag).strip()]
    title = clean_html(row.get("position"))
    company = clean_html(row.get("company"))
    location = clean_html(row.get("location"))
    search_text = "\n".join(filter(None, [title, company, location, " ".join(tags), description]))
    return {
        "posting_id": f"remoteok:{external_id}",
        "external_id": external_id,
        "source": "remoteok",
        "title": title or "Untitled role",
        "company": company or None,
        "location": location or "Remote",
        "source_url": row.get("url") or f"https://remoteok.com/remote-jobs/{external_id}",
        "description": description,
        "tags": tags,
        "salary_min": _as_int(row.get("salary_min")),
        "salary_max": _as_int(row.get("salary_max")),
        "posted_at": _as_datetime(row.get("date")),
        "raw_json": json.dumps(row, ensure_ascii=False),
        "content_hash": hashlib.sha256(search_text.encode()).hexdigest(),
        "search_text": search_text,
        "ingested_at": ingested_at,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def run_spark_pipeline(catalog: str, schema: str) -> None:
    """Execute from the Databricks job. Imports Spark only at run time."""
    from pyspark.sql import SparkSession
    from pyspark.sql.functions import col, lit

    spark = SparkSession.builder.getOrCreate()
    namespace = f"{catalog}.{schema}"
    _create_tables(spark, namespace)
    now = datetime.now(UTC)
    jobs: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for row in fetch_remoteok_rows():
        try:
            if not row.get("id"):
                raise ValueError("missing RemoteOK job id")
            jobs.append(canonical_job(row, now))
        except (KeyError, TypeError, ValueError) as error:
            quarantined.append(
                {
                    "raw_json": json.dumps(row, ensure_ascii=False),
                    "reason": str(error),
                    "quarantined_at": now,
                }
            )
    if not jobs:
        raise RuntimeError("RemoteOK returned no job postings; source tables were left unchanged")
    if quarantined:
        spark.createDataFrame(quarantined).write.mode("append").saveAsTable(
            f"{namespace}.quarantine_job_records"
        )
    frame = spark.createDataFrame(jobs)
    raw = frame.select("posting_id", "external_id", "source", "raw_json", "ingested_at")
    raw.write.mode("append").format("delta").saveAsTable(f"{namespace}.bronze_remoteok_jobs")

    silver = frame.drop("raw_json", "search_text").withColumn("is_active", lit(True))
    silver.createOrReplaceTempView("incoming_jobs")
    spark.sql(
        f"""MERGE INTO {namespace}.silver_job_postings target USING incoming_jobs source
        ON target.posting_id = source.posting_id
        WHEN MATCHED THEN UPDATE SET external_id=source.external_id, source=source.source,
          title=source.title, company=source.company, location=source.location, source_url=source.source_url,
          description=source.description, tags=source.tags, salary_min=source.salary_min,
          salary_max=source.salary_max, posted_at=source.posted_at, content_hash=source.content_hash,
          ingested_at=source.ingested_at, is_active=true, last_seen_at=current_timestamp()
        WHEN NOT MATCHED THEN INSERT (posting_id, external_id, source, title, company, location, source_url,
          description, tags, salary_min, salary_max, posted_at, content_hash, ingested_at, is_active, last_seen_at)
          VALUES (source.posting_id, source.external_id, source.source, source.title, source.company,
          source.location, source.source_url, source.description, source.tags, source.salary_min,
          source.salary_max, source.posted_at, source.content_hash, source.ingested_at, true, current_timestamp())"""
    )
    # A job must be absent from three successful source snapshots before it is hidden.
    spark.sql(
        f"""UPDATE {namespace}.silver_job_postings SET is_active=false
        WHERE is_active=true AND last_seen_at < current_timestamp() - INTERVAL 3 DAYS"""
    )
    gold = frame.select(
        "posting_id",
        "title",
        "company",
        "location",
        "source_url",
        "tags",
        "search_text",
        "content_hash",
        "posted_at",
        "ingested_at",
    )
    gold.createOrReplaceTempView("incoming_documents")
    spark.sql(
        f"""MERGE INTO {namespace}.gold_job_documents target USING incoming_documents source
        ON target.posting_id = source.posting_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *"""
    )
    spark.sql(
        f"""INSERT INTO {namespace}.pipeline_runs
        SELECT current_timestamp(), 'remoteok', {len(jobs)}, {len(quarantined)}, 'succeeded'"""
    )
    # Keep these explicit for observability even though Delta writes already commit atomically.
    spark.table(f"{namespace}.gold_job_documents").where(col("posting_id").isNotNull()).count()


def _create_tables(spark: Any, namespace: str) -> None:
    """Idempotent bootstrap DDL; only the job creates the governed Delta layers."""
    statements = [
        f"""CREATE TABLE IF NOT EXISTS {namespace}.bronze_remoteok_jobs (
          posting_id STRING, external_id STRING, source STRING, raw_json STRING, ingested_at TIMESTAMP)
          USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {namespace}.silver_job_postings (
          posting_id STRING, external_id STRING, source STRING, title STRING, company STRING, location STRING,
          source_url STRING, description STRING, tags ARRAY<STRING>, salary_min INT, salary_max INT,
          posted_at TIMESTAMP, content_hash STRING, ingested_at TIMESTAMP, is_active BOOLEAN,
          last_seen_at TIMESTAMP) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {namespace}.gold_job_documents (
          posting_id STRING, title STRING, company STRING, location STRING, source_url STRING,
          tags ARRAY<STRING>, search_text STRING, content_hash STRING, posted_at TIMESTAMP,
          ingested_at TIMESTAMP) USING DELTA TBLPROPERTIES (delta.enableChangeDataFeed = true)""",
        f"""CREATE TABLE IF NOT EXISTS {namespace}.quarantine_job_records (
          raw_json STRING, reason STRING, quarantined_at TIMESTAMP) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {namespace}.pipeline_runs (
          run_at TIMESTAMP, source STRING, accepted_count BIGINT, rejected_count BIGINT, status STRING)
          USING DELTA""",
    ]
    for statement in statements:
        spark.sql(statement)
