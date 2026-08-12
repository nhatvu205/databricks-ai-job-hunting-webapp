# AI Job Hunting Copilot

A Databricks capstone that ingests RemoteOK jobs with Spark, makes descriptions searchable with AI Search, and lets an agent save and track applications in Lakebase.

The solution has two Databricks Apps:

- `job-copilot`: Streamlit frontend, profile workflow, semantic job search, and tracked applications.
- `mcp-job-copilot`: private FastMCP server exposing the same user-scoped retrieval and mutation tools.

## Quick start

1. Install dependencies: `pip install -e ".[dev,pipeline]"`.
2. Copy `.env.example` to `.env` and set the local PostgreSQL connection if running services locally.
3. Run tests with `pytest`.
4. Follow [docs/RUNBOOK.md](docs/RUNBOOK.md) to deploy to Databricks.

No application is ever submitted externally. Saved and stage changes only affect the user's Lakebase records.
