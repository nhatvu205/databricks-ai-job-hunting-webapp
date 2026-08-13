# AI Job Hunting Copilot

An end-to-end Databricks application that turns public job listings into a personalized, searchable job-hunting workspace. It combines a Spark ingestion pipeline, Delta Lake, Databricks AI Search, Lakebase, a Streamlit frontend, a tool-using chat agent, and a private Model Context Protocol (MCP) server.

The application helps a signed-in user:

- describe target roles, preferred locations, work preferences, and skills;
- search job descriptions semantically instead of relying only on keywords;
- rank results using both vector relevance and the user's profile;
- save jobs and move them through `saved`, `applied`, `interviewing`, `rejected`, and `offer` stages;
- find applications that have not been updated recently;
- use the same capabilities from the web UI or an MCP-compatible coding agent.

It is a tracking and decision-support application. It never submits an application to an employer, and every profile or pipeline mutation is stored only in the authenticated user's Lakebase records.

![AI Job Hunting Copilot search page showing ranked RemoteOK results and pipeline controls](docs/img/search-job-page.png)

## Why this project exists

Job boards usually optimize for browsing, while an individual job search is a stateful workflow. A candidate needs to combine an evolving profile, unstructured job descriptions, semantic discovery, application stages, interview notes, and follow-up reminders. This project demonstrates how those concerns can be separated into the Databricks services best suited to each one:

- **Spark and Delta Lake** build a governed, repeatable job-data pipeline.
- **AI Search** retrieves relevant unstructured job descriptions.
- **Lakebase** stores transactional, user-owned profile and application state.
- **Unity AI Gateway** provides the model used by the in-app conversational agent.
- **Databricks Apps** hosts the human-facing Streamlit app and the machine-facing MCP server.
- **Databricks Asset Bundles** define and deploy the complete system.

## Architecture

```mermaid
flowchart LR
    R[RemoteOK JSON API] --> J[Serverless Spark ingestion job]
    J --> B[(Bronze Delta table)]
    J --> S[(Silver Delta table)]
    J --> G[(Gold job documents)]
    G --> V[Delta Sync AI Search index]

    U[Signed-in user] --> P[Databricks Apps authentication proxy]
    P --> F[Streamlit frontend app]
    P --> M[Private FastMCP app]
    C[MCP client, such as Codex] --> P

    F --> X[Shared JobCopilotService]
    M --> X
    X --> V
    X --> L[(Lakebase PostgreSQL)]
    F --> A[JobAgent]
    A --> Q[Unity AI Gateway model service]
    A --> X
```

The architecture has two deliberately different data planes:

| Data plane | Storage | Contents | Access pattern |
| --- | --- | --- | --- |
| Search corpus | Unity Catalog Delta tables and AI Search | Public RemoteOK jobs, normalized text, tags, timestamps, and embedding source text | Shared read-only corpus searched by all users |
| User state | Lakebase PostgreSQL | Profiles, skills, saved jobs, application stages, interview notes, and action audit records | Transactional reads and writes scoped to one authenticated user |

This split prevents user-specific operational data from being mixed into the shared embedding index and keeps application-stage updates strongly consistent.

## End-to-end flows

### 1. Job ingestion

1. The scheduled Databricks Job calls the public RemoteOK JSON API.
2. `ingestion.py` removes HTML, normalizes whitespace, repairs source encoding errors, standardizes tags and timestamps, and creates a stable `remoteok:<id>` posting identifier.
3. Invalid source rows are written to `quarantine_job_records`; a completely empty valid result fails the run instead of replacing good data.
4. The job appends raw payloads to the bronze table, merges canonical records into silver, and merges search-ready documents into gold.
5. A job remains active until it has been absent from three successful daily snapshots.
6. The Delta Sync index embeds `gold_job_documents.search_text` and makes it available to AI Search.

```text
RemoteOK API
    -> bronze_remoteok_jobs       raw source history
    -> silver_job_postings        canonical, deduplicated job records
    -> gold_job_documents         compact documents for semantic retrieval
    -> job_documents_index        managed embeddings and vector search
```

### 2. Personalized search

1. The frontend or MCP tool sends a natural-language query and optional filters.
2. `JobCopilotService` loads the current user's profile from Lakebase.
3. `AiSearch` enriches the query with target roles, skills, and a bounded resume excerpt.
4. AI Search returns a larger candidate set from the shared job index.
5. The application applies deterministic filters and re-ranks candidates:

```text
final score = 70% vector-search score
            + 20% profile skill overlap
            + 10% remote-work preference match
```

The response includes matched skills and a short list of job tags for which the profile has no evidence. Search itself does not write user data.

### 3. Pipeline mutation

1. A user explicitly selects a stage in the UI or asks an agent to change it.
2. The selected job is cached in the Lakebase `job_postings` table.
3. The `(user_id, posting_id)` application record is inserted or updated transactionally.
4. The write is recorded in `agent_action_audit`.

The in-app agent adds an extra guard: it can save only a job returned by `search_jobs` during the same conversation, and the system prompt prohibits implicit application changes.

### 4. MCP request

1. An MCP client connects to the private Databricks App at `https://<mcp-app-url>/mcp` using Streamable HTTP.
2. Databricks authenticates the caller and forwards the signed-in user headers to the App.
3. `mcp_server.py` derives the actor from those headers; the MCP arguments never accept a user ID.
4. The selected tool calls the same service and repository used by the frontend.
5. Results are returned as structured MCP tool output.

![Codex calling the deployed MCP search_jobs tool and receiving structured job results](docs/img/mcp-search-job.png)

## Application surfaces

### Streamlit frontend

The `frontend` Databricks App is the interactive product surface. It exposes three tabs:

| Tab | Responsibility |
| --- | --- |
| **Find jobs** | Semantic search, optional remote-only filtering, match explanations, source links, application-stage updates, and conversational assistance |
| **Profile** | Target roles, preferred locations, skills, work preference, and experience/resume context |
| **Pipeline** | Current applications and a warning for active records not updated in the last seven days |

At startup the App runs the idempotent Lakebase migration, then launches Streamlit. The embedded `JobAgent` calls the configured `system.ai.gemma-3-12b` Unity AI Gateway model service and gives it four tools: search jobs, set application stage, list applications, and list stale applications.

### Private MCP server

The `mcp` Databricks App exposes the domain as reusable tools for Codex and other MCP clients:

| Tool | Type | Role |
| --- | --- | --- |
| `health` | Read | Non-sensitive deployment smoke check |
| `get_profile` | Read | Return the authenticated user's profile and skills |
| `update_profile` | Write | Replace the authenticated user's profile fields and normalized skill set |
| `search_jobs` | Read | Query AI Search and apply profile-aware ranking |
| `set_application_stage` | Write | Save a job or update its pipeline stage and optional follow-up date |
| `list_applications` | Read | List the caller's pipeline, optionally filtered by stage |
| `add_interview_note` | Write | Attach a note and optional interview timestamp to a saved application |
| `list_stale_applications` | Read | Find active applications older than a configurable number of days |

The MCP server is a second interface over the same business service, not a separate implementation of the job-copilot logic.

## Data model

### Unity Catalog and Delta Lake

The Spark pipeline owns these governed tables:

| Table | Layer | Purpose |
| --- | --- | --- |
| `bronze_remoteok_jobs` | Bronze | Append-only source identifiers, raw JSON, and ingestion timestamps |
| `silver_job_postings` | Silver | Canonical jobs with normalized fields, content hashes, activity state, and last-seen timestamps |
| `gold_job_documents` | Gold | Search-oriented documents with `search_text`; Change Data Feed is enabled for Delta Sync |
| `quarantine_job_records` | Quality | Source rows that could not be canonicalized and the rejection reason |
| `pipeline_runs` | Operations | Accepted/rejected counts and run status for ingestion observability |

`job_documents_index` is a triggered Delta Sync AI Search index keyed by `posting_id`. It generates embeddings from `search_text` with the configured Databricks embedding endpoint.

### Lakebase

The application migration creates the `job_copilot` PostgreSQL schema and these tables:

| Table | Purpose |
| --- | --- |
| `users` | Stable application identity plus display metadata from Databricks headers |
| `profiles` | Target roles, locations, remote preference, salary floor, experience summary, and resume text |
| `skills` | Normalized per-user skills |
| `job_postings` | Transactional cache of jobs referenced by an application |
| `applications` | Per-user job stage, follow-up timestamp, and lifecycle timestamps |
| `interview_notes` | Notes attached to a user's saved application |
| `agent_action_audit` | Audit trail for profile and pipeline mutations |

Migrations are idempotent and protected by a PostgreSQL advisory transaction lock so simultaneous App starts do not race.

## Module guide

The canonical Python package is under `src/job_copilot/`.

| Module | Responsibility |
| --- | --- |
| `app.py` | Streamlit entry point; renders search, profile, and pipeline workflows and starts chat turns |
| `mcp_server.py` | FastMCP entry point; exposes authenticated tools over Streamable HTTP |
| `agent.py` | Unity AI Gateway chat loop, tool schemas, tool dispatch, safe mutation rules, and maximum tool-call limit |
| `service.py` | Application service layer that coordinates profile loading, search, validation, and repository writes |
| `search.py` | Databricks AI Search client, SDK response decoding, filtering, and profile-aware re-ranking |
| `repository.py` | All Lakebase queries and transactions; enforces the actor predicate on user-owned data |
| `database.py` | Lakebase connections, short-lived Databricks database credentials, schema search path, and migrations |
| `identity.py` | Converts trusted Databricks forwarded headers into a stable, hashed `Actor` identifier |
| `domain.py` | Pydantic request/response models, search filters, profile models, and the application-stage enum |
| `factory.py` | Dependency composition for `Database`, `JobRepository`, `AiSearch`, and `JobCopilotService` |
| `workspace.py` | Databricks SDK authentication and bearer-token discovery for AI Search and Unity AI Gateway |
| `config.py` | Environment-backed runtime settings for Lakebase, AI Search, model service, and local credentials |
| `ingestion.py` | RemoteOK HTTP client, text normalization, canonical mapping, quarantine handling, and Spark bronze/silver/gold writes |
| `pipeline_job.py` | CLI adapter for the Databricks Python wheel task; parses catalog/schema and starts ingestion |
| `migrate.py` | Async command that applies the Lakebase schema before the frontend starts |
| `__init__.py` | Package marker |

### Deployment copies

Databricks Apps deploy from `apps/frontend/` and `apps/mcp/`, not from the root wheel:

```text
apps/
├── frontend/
│   ├── app.yaml
│   ├── requirements.txt
│   └── src/job_copilot/    # frontend App's self-contained package copy
└── mcp/
    ├── app.yaml
    ├── requirements.txt
    └── src/job_copilot/    # MCP App's self-contained package copy
```

The root `src/job_copilot/` package is used by local development, tests, and the wheel installed by the Spark Job. The two App source trees are deployment copies. When shared runtime logic changes, keep the relevant files synchronized across all three package trees before deployment. The App copies are intentionally self-contained because each App is uploaded from its own `source_code_path`.

## Repository map

| Path | Role |
| --- | --- |
| `databricks.yml` | Asset Bundle definition for the Spark Job, Lakebase resources, AI Search endpoint/index, permissions, and both Apps |
| `pyproject.toml` | Python package metadata, dependencies, wheel entry point, pytest settings, and Ruff rules |
| `requirements.txt` | Convenience dependency set for the repository environment |
| `apps/frontend/app.yaml` | Standalone frontend App command and resource-backed environment variables |
| `apps/mcp/app.yaml` | Standalone MCP App command and resource-backed environment variables |
| `tests/` | Unit tests for domain validation, ingestion cleanup/encoding repair, and AI Search decoding/ranking |
| `docs/RUNBOOK.md` | Step-by-step deployment and operations guide for Databricks Free Edition |
| `docs/img/` | Screenshots used by this README |
| `CAPSTONE.md` | Original bootcamp capstone brief and alternative project ideas |

## Identity, authorization, and safety

- Databricks Apps authenticates the browser or MCP client before requests reach application code.
- `identity.py` accepts only `X-Forwarded-User` or `X-Forwarded-Email` supplied by Databricks. Missing identity headers stop the request.
- The database key is a SHA-256 hash of the normalized forwarded identity; clients cannot supply or override it.
- Every query for profiles, skills, applications, notes, and audits includes the actor's `user_id`.
- Retrieved job descriptions are treated as untrusted data, not model instructions.
- The chat agent cannot claim to apply externally and cannot mutate the pipeline without an explicit request.
- Resume text is bounded before persistence and only a bounded excerpt is added to search queries.
- Lakebase credentials are generated dynamically from the Databricks App identity when `LAKEBASE_ENDPOINT_NAME` is present.
- App resource permissions are least-purpose: both Apps can connect to Lakebase and read the AI Search securable; they do not receive arbitrary workspace privileges.

## Databricks resources

The bundle defines the following deployable resources:

| Resource | Default role |
| --- | --- |
| `ingest_remoteok` Job | Daily 07:00 Asia/Ho_Chi_Minh serverless ingestion; initially paused |
| Lakebase project/branch/role/database | PostgreSQL 17 transactional store with autoscaling and automatic suspension |
| AI Search endpoint | Standard vector-search endpoint |
| `job_documents_index` | Triggered Delta Sync index over the gold table |
| `frontend` App | Streamlit UI, database migration, and in-app agent |
| `mcp` App | Private FastMCP tool server |

The deployment is intentionally performed in two passes: the ingestion Job must create `gold_job_documents` before Databricks can create the Delta Sync index that references it. See the [deployment runbook](docs/RUNBOOK.md) for the exact sequence and Free Edition constraints.

## Local development

### Prerequisites

- Python 3.11 or newer
- a Databricks workspace and current Databricks CLI for integration/deployment work
- PostgreSQL when exercising Lakebase-backed features locally
- Java/Spark only when running the Spark pipeline locally

### Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,pipeline]"
```

Without Databricks-injected `PG*` variables, the default development DSN is:

```text
postgresql://postgres:postgres@localhost:5432/job_copilot
```

Settings use the `JOB_COPILOT_` prefix, while resource bindings supplied by Databricks use their platform names:

| Variable | Purpose |
| --- | --- |
| `JOB_COPILOT_DATABASE_URL` | Override the Lakebase/local PostgreSQL DSN |
| `JOB_COPILOT_CATALOG` | Unity Catalog name used by local settings |
| `JOB_COPILOT_SCHEMA_NAME` | Unity Catalog schema name |
| `VECTOR_SEARCH_INDEX` | Fully qualified AI Search index, usually injected from the App resource |
| `MODEL_SERVICE` | Unity AI Gateway model service used by `JobAgent` |
| `DATABRICKS_HOST`, `JOB_COPILOT_DATABRICKS_TOKEN` | Optional explicit local Databricks authentication; deployed Apps use unified authentication |
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE` | Lakebase connection fields injected by Databricks Apps |
| `LAKEBASE_ENDPOINT_NAME` | Enables generation of short-lived Lakebase credentials |
| `DATABRICKS_APP_PORT` | Port assigned to a Databricks App |

Apply the local database schema and start Streamlit with:

```bash
python -m job_copilot.migrate
streamlit run src/job_copilot/app.py
```

The full UI requires Databricks forwarded identity headers, so its normal execution environment is Databricks Apps. Local runs are mainly useful for module-level development unless an equivalent authenticated proxy is provided.

## Tests and quality checks

```bash
pytest
ruff check src apps tests
```

The current unit suite verifies:

- application-stage input validation;
- profile-aware search ranking;
- HTML cleanup and Unicode/mojibake repair for RemoteOK text;
- stable canonical posting IDs and search document construction;
- decoding of the Databricks AI Search response shape.

Integration behavior—Databricks App identity, AI Search sync, Unity AI Gateway calls, Lakebase credentials, and MCP OAuth—must be smoke-tested in the deployed workspace.

## Testing the deployed MCP server

After the MCP App is running, connect an authenticated MCP client to:

```text
https://<mcp-app-url>/mcp
```

For Codex with Databricks `ucode`, an authenticated local proxy can be registered as a stdio MCP server:

```bash
codex mcp add databricks-app-job-copilot -- \
  /path/to/ucode mcp-proxy \
  --url https://<mcp-app-url>/mcp \
  --host https://<your-workspace-host> \
  --profile <databricks-cli-profile>

codex mcp list
```

Run read-only checks first:

1. Call `health` to verify MCP transport.
2. Call `get_profile` to verify user identity and Lakebase access.
3. Call `search_jobs` to verify identity, AI Search access, response decoding, and ranking.
4. Test write tools only after the read path succeeds, using a non-critical saved job.

## Current scope and limitations

- RemoteOK is the only job source currently implemented.
- Search quality depends on the freshness and breadth of the RemoteOK snapshot and the user's profile.
- The ranker is deliberately transparent and heuristic; it is not a learned recommendation model.
- The frontend supports profile editing and pipeline stages, while interview-note creation is currently exposed through MCP rather than a dedicated UI form.
- The system does not submit applications, contact employers, scrape protected sites, or claim actions outside Lakebase.
- Databricks Free Edition quotas and automatic App suspension affect availability; operational recovery steps are documented in the runbook.

## Deployment

Use [docs/RUNBOOK.md](docs/RUNBOOK.md) for the complete deployment procedure. At a high level:

```bash
databricks bundle validate -t dev
databricks bundle plan -t dev

# First pass: create Lakebase and the ingestion Job, then materialize Delta tables.
databricks bundle deploy -t dev \
  --select postgres_projects.job_copilot_project \
  --select jobs.ingest_remoteok
databricks bundle run ingest_remoteok -t dev

# Second pass: deploy AI Search and both Apps after gold_job_documents exists.
databricks bundle deploy -t dev
```

Before deploying, configure the catalog, schema, Lakebase project/database, vector-search endpoint, and model service in `.databricks/bundle/dev/variable-overrides.json` as described in the runbook.

---

This repository was built as a Databricks AI/Data Engineering capstone: a compact reference architecture for combining batch ingestion, unstructured retrieval, transactional application state, authenticated agents, and MCP tools in one deployable system.
