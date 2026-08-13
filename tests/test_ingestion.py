from datetime import UTC, datetime

from job_copilot.ingestion import canonical_job, clean_html


def test_clean_html_unescapes_and_normalizes_spaces() -> None:
    assert clean_html("<p>Spark &amp; <b>Python</b></p>\n") == "Spark & Python"


def test_clean_html_repairs_source_mojibake() -> None:
    assert clean_html("Attributeâ\u0084¢") == "Attribute™"
    assert clean_html("Youâ\u0080\u0099ll build pipelinesâ\u0080\u0094remotely") == "You’ll build pipelines—remotely"


def test_clean_html_drops_truncated_source_sequence() -> None:
    assert clean_html("Sales Development Representative Attributeâ\u0084") == (
        "Sales Development Representative Attribute"
    )


def test_clean_html_preserves_valid_unicode() -> None:
    assert clean_html("Développeur · 東京") == "Développeur · 東京"


def test_canonical_job_has_stable_identifier_and_search_text() -> None:
    row = {
        "id": 42,
        "position": "<b>Data Engineer</b>",
        "company": "Example Co",
        "location": "Remote",
        "description": "<p>Build <em>Spark</em> pipelines</p>",
        "tags": ["Python", "Spark"],
        "salary_min": "100000",
        "date": "2026-08-12T00:00:00Z",
    }
    job = canonical_job(row, datetime(2026, 8, 12, tzinfo=UTC))
    assert job["posting_id"] == "remoteok:42"
    assert job["description"] == "Build Spark pipelines"
    assert job["salary_min"] == 100000
    assert "data engineer" in job["search_text"].lower()
    assert len(job["content_hash"]) == 64
