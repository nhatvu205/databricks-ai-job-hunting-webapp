# Deployment runbook

## What this deploys

The bundle creates a governed Unity Catalog schema, a paused daily Spark job, a Lakebase Autoscaling project and database, a triggered Delta Sync AI Search index, and two Databricks Apps. The frontend is shared with users; the `mcp-` app is kept private for integrations and administrators.

The Spark job uses RemoteOK's public JSON endpoint. It writes append-only bronze raw data, upserts silver postings and gold search documents, then the triggered AI Search index is synchronized after a successful job run. Keep the RemoteOK source link visible in the UI.

## Prerequisites

- Databricks CLI 1.0+ logged into a workspace with Unity Catalog, serverless jobs, Databricks Apps, Lakebase Autoscaling, AI Search, and Foundation Model APIs enabled.
- Permission to create a schema and job in an existing Unity Catalog catalog, manage Lakebase projects, create apps, and use the selected serving endpoint.
- Python 3.11+ with `setuptools` and `wheel` available locally for the wheel build configured in `databricks.yml`.
- A tool-calling chat endpoint and `databricks-gte-large-en` (or a replacement embedding endpoint) available in your workspace.

## Configure

Create `.databricks/bundle/dev/variables.json` locally; it is intentionally not committed:

```json
{
  "catalog": "main",
  "schema": "job_copilot",
  "project_id": "ai-job-copilot-yourname",
  "database_name": "job_copilot",
  "vector_search_endpoint": "job-copilot-vs",
  "model_endpoint": "databricks-claude-sonnet-4-5"
}
```

Use a unique `project_id` and endpoint name if the workspace is shared. Replace the default model endpoint if it is unavailable. Do not put personal-access tokens in bundle YAML, Git, or an app environment variable; apps should use their attached Databricks resources and service-principal identity.

## Deploy in two phases

The AI Search index needs the gold table, which the first pipeline run creates.

1. Check the configuration:

   ```bash
   databricks bundle validate -t dev
   ```

2. Deploy foundational resources only (schema, Lakebase, and ingestion job). If your CLI does not support `--select`, temporarily comment out `vector_search_indexes` and `apps` during this one bootstrap deploy, then restore them immediately:

   ```bash
   databricks bundle deploy -t dev --select resources.schemas.job_copilot,resources.postgres_projects.job_copilot,resources.jobs.ingest_remoteok
   databricks bundle run ingest_remoteok -t dev
   ```

3. Confirm bronze, silver and gold tables are non-empty in Catalog Explorer. Then deploy all resources:

   ```bash
   databricks bundle deploy -t dev
   ```

4. Trigger the initial index sync and wait until the index is online:

   ```bash
   databricks vector-search-indexes sync-index <catalog>.<schema>.job_documents_index
   ```

5. In Apps, open `${bundle.target}-job-copilot`, grant users `CAN USE`, and leave `mcp-${bundle.target}-job-copilot` unshared. Start the daily job by changing `pause_status` from `PAUSED` to `UNPAUSED` once the initial run has succeeded.

## Application configuration and security

Attaching the Lakebase resource injects `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGSSLMODE`; the app builds its connection from these values. The application derives the user solely from Databricks forwarded identity headers and hashes that value before querying Lakebase. User IDs are never model inputs or MCP arguments.

Before demoing, verify that each app service principal has only the Lakebase database resource and `CAN QUERY` access to the selected AI Search and model endpoints. Do not grant the public frontend direct workspace-admin permissions. The model is instructed to treat job descriptions as untrusted text and only mutates Lakebase state after a direct request.

## Smoke checks

- Run the ingestion job and confirm `bronze_remoteok_jobs`, `silver_job_postings`, `gold_job_documents`, and `pipeline_runs` have rows.
- Search for a role in the frontend; job cards should include a RemoteOK source link.
- Save a result, update it to `applied`, add an interview note, and refresh the Pipeline tab.
- Sign in as a second user and confirm their pipeline is empty and cannot expose the first user's records.
- Call the private MCP `health` tool and then `get_profile` as an authenticated user.
- Ask the chat for advice only and confirm no `agent_action_audit` mutation row is added.

## Operations and recovery

- Inspect job run output, app logs, AI Search index state, and `pipeline_runs` first.
- A failed RemoteOK request raises the Spark job and does not mark existing jobs inactive or replace the existing searchable index.
- Re-running a completed save or stage update is idempotent because applications are keyed by `(user_id, posting_id)`.
- For a source outage, leave the last successful gold table and index in place, then retry the job after the source recovers.
- To reduce demo costs, leave the ingestion schedule paused until needed, use triggered index syncs, and stop both apps after the demo. Lakebase's configured 300-second idle suspension applies when the endpoint is idle.
- `databricks bundle destroy -t dev` removes managed resources. Lakebase projects are soft-deleted by default; use a purge command only when you explicitly intend permanent deletion.
