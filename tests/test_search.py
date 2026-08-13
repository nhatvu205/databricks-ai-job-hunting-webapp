from job_copilot.search import AiSearch


def test_decode_vector_search_response_with_top_level_manifest() -> None:
    payload = {
        "manifest": {
            "columns": [
                {"name": "posting_id"},
                {"name": "title"},
                {"name": "company"},
                {"name": "location"},
                {"name": "source_url"},
                {"name": "tags"},
                {"name": "search_text"},
                {"name": "posted_at"},
                {"name": "score"},
            ]
        },
        "result": {
            "data_array": [
                [
                    "remoteok:123",
                    "Data Engineer",
                    "Example Co",
                    "Remote",
                    "https://example.com/jobs/123",
                    ["python", "spark"],
                    "Build data pipelines with Python and Spark.",
                    "2026-08-12T08:00:00Z",
                    0.83,
                ]
            ],
            "row_count": 1,
        },
    }

    jobs = AiSearch._decode(payload)

    assert len(jobs) == 1
    assert jobs[0].posting_id == "remoteok:123"
    assert jobs[0].title == "Data Engineer"
    assert jobs[0].tags == ["python", "spark"]
    assert jobs[0].score == 0.83
