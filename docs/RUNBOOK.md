# Deploy the AI Job Hunting Copilot

This guide is for a personal **Databricks Free Edition** workspace. Follow it in order and do not run later commands until the stated check succeeds.

## The short version

You will:

1. Sign the Databricks CLI on your WSL computer into your workspace.
2. Tell the project which Unity Catalog catalog and AI Gateway model service to use.
3. Create the catalog and schema, then deploy the Lakebase database and ingestion Job.
4. Run the job once to create the job-data tables.
5. Deploy AI Search and the two Apps.
6. Use the Databricks UI to test and share the frontend.

The CLI creates the resources described by `databricks.yml`. The Databricks UI is where you create or choose the catalog, inspect Jobs and tables, view AI Search and Lakebase, read logs, and open the running App. You do not need a personal-access token, database password, company account, workspace administrator, or Accounts Console.

## Before you begin

### 1. Confirm the Free Edition limits before creating anything

Free Edition has one workspace and one Unity Catalog metastore for your account. It is serverless-only and has these relevant quotas:

- one Lakebase project;
- one AI Search endpoint (one search unit);
- up to three Databricks Apps;
- up to five concurrent Job tasks;
- Apps stop automatically after 24 hours, and you restart them from the Apps page when needed.

This project needs one Lakebase project, one AI Search endpoint, one Job task, and two Apps, so it fits only if you have not already used those one-per-account resources for another project. Free Edition also restricts outbound internet access; the RemoteOK API call may be blocked by the workspace network policy.

Open your personal workspace in the browser. You need these items available in the left navigation or App switcher:

- **Catalog** (Unity Catalog)
- **Workflows** (Jobs)
- **Apps**
- **Serving** (only needed later to confirm the AI Search embedding endpoint)
- **AI Gateway** (Databricks-managed chat models)
- **Lakebase** / Postgres projects
- **AI Search** / Vector Search

If an item is missing, your Free Edition workspace does not currently offer that feature or you have reached a quota. Do not create a second Databricks account or work around it with an access token. See the **If a required item is unavailable** section below.

### 2. Find your workspace URL (`--host`)

While you are already signed in to Databricks in the browser:

1. Look at the browser address bar.
2. Copy only the beginning of the address, from `https://` up to the first `/` after the domain.

Examples:

```text
https://adb-1234567890123456.7.azuredatabricks.net
https://dbc-abc123.cloud.databricks.com
```

Do **not** use:

- an URL ending in `/explore`, `/jobs`, `/apps`, or another page path;
- the Databricks **Accounts Console** URL;
- your company login portal URL.

Call the copied value `WORKSPACE_URL` in the rest of this guide.

### 3. Check the CLI in WSL and sign in

Open your WSL terminal, not Windows PowerShell, and change to this repository:

```bash
cd /mnt/e/NAB/data-engineer-handbook/databricks-ai-bootcamp/capstone_ai_job_huting_copilot
databricks -v
```

The CLI must be version **1.3 or later**. If `databricks: command not found` appears, install the current Databricks CLI in WSL first, then reopen the terminal.

Create a separate CLI profile for this personal workspace. This avoids accidentally using an old profile from another Databricks account. Replace the sample URL with the `WORKSPACE_URL` from the browser:

```bash
databricks auth login \
  --host https://adb-1234567890123456.7.azuredatabricks.net \
  --profile job-copilot-free
```

A browser window opens. Sign in with your normal Databricks account, approve the request, then return to WSL and check the login:

```bash
databricks current-user me --profile job-copilot-free
export DATABRICKS_CONFIG_PROFILE=job-copilot-free
```

You should see your own user record. The `export` command makes this profile apply to every CLI command in the current WSL terminal, so the commands below do not accidentally use your expired `nhatvd` profile. This is OAuth login: credentials are kept by the CLI and refreshed automatically; do not create or paste a PAT.

## Configure the project once

### 4. Create the data container: catalog first, schema second

Databricks stores data in this hierarchy:

```text
catalog → schema → tables
```

For this project, create or choose one personal catalog, then use the schema name `job_copilot` inside it.

#### A. Open Catalog Explorer

1. In the Databricks left sidebar, click **Catalog**.
2. Look at the top-level list on the left.

#### B. If you see a catalog already

Use it only if it belongs to your personal Free Edition workspace. A workspace catalog commonly has a name similar to the workspace name and includes a `default` schema. Click the catalog, open its **Details** tab, and confirm you are its owner or can create schemas.

Copy that catalog name. It will become `<your_catalog>` below.

#### C. If the catalog list is empty, or you want a clean catalog for this capstone

Create one in the UI:

1. In Catalog Explorer, click **Create** or **Create catalog**.
2. Choose a standard managed catalog; do not choose a foreign catalog or external connection.
3. Enter this name:

   ```text
   job_copilot_catalog
   ```

4. Leave the managed storage location at its default. Free Edition manages storage for you.
5. Optional comment: `Personal Databricks Free Edition capstone catalog`.
6. Click **Create** or **Save**.

If you receive `CREATE CATALOG` permission error, do **not** continue with a made-up name. Use the workspace catalog that Free Edition created for you, or use the SQL fallback below.

#### D. Create the project schema

Create this schema now. The remaining bundle assumes that it already exists.

1. Click your chosen catalog.
2. Click **Create schema**.
3. Set the schema name to:

   ```text
   job_copilot
   ```

4. Optional comment: `Tables created by the AI Job Hunting Copilot`.
5. Leave storage options at their defaults and click **Create**.

After this step, your namespace is:

```text
<your_catalog>.job_copilot
```

#### SQL fallback for catalog and schema creation

If the Catalog Explorer create buttons are not visible, create a new **SQL query** or **Notebook** using serverless compute and run:

```sql
CREATE CATALOG IF NOT EXISTS job_copilot_catalog;
CREATE SCHEMA IF NOT EXISTS job_copilot_catalog.job_copilot;
```

If this returns a permission error, use an existing catalog instead. A catalog requires the `CREATE CATALOG` privilege; a schema requires `USE CATALOG` plus `CREATE SCHEMA` on the chosen catalog.

### 5. Record your chosen names

Write these values down before continuing:

```text
catalog: the catalog you chose or created, for example job_copilot_catalog
schema: job_copilot
```

### 6. Choose the chat model service — do not create a Serving endpoint

Databricks changed this UI: a Databricks-managed chat model is now a **Unity AI Gateway model service**, not a classic **Serving endpoint**. The banner you saw is expected.

For this project use this exact name:

```text
system.ai.gemma-3-12b
```

There is nothing to create, select, or copy in the **Create endpoint** dialog. Close that dialog without saving an endpoint. `system.ai.gemma-3-12b` is a Databricks-provided service and is available to account users by default when Unity AI Gateway is available in the workspace.

You may see only **Genie** on the AI Gateway landing page. Genie is a different AI product; it is not the chat model for this application. You do not need to create a Genie space.

If you want to verify the model visually, open **Catalog** and look for catalog `system`, schema `ai`, then `gemma-3-12b`. If the `system` catalog or the model is not available, stop here: this workspace does not currently have Unity AI Gateway model-service access. Do not try to recreate it as a custom endpoint.

Keep the embedding endpoint separate: AI Search uses the preconfigured Foundation Model API endpoint `databricks-bge-large-en`, which is the endpoint form of `system.ai.bge-large-en`. It still uses an endpoint-style name below.

### 7. Check one-per-account resources

Before deployment, inspect these UI pages:

| UI page | What must be available |
| --- | --- |
| Lakebase / Postgres projects | No existing project, or an existing project you deliberately intend to reuse after updating the bundle. |
| AI Search | No existing endpoint, or an existing endpoint you deliberately intend to reuse after updating the variables. |
| Apps | At least two of the three App slots free. |
| Workflows → Jobs | At least one Job-task slot available. |

For a first capstone deployment, use an empty Free Edition workspace. It is the least confusing path.

### 8. Choose your personal resource names

Choose a lowercase unique suffix, such as `nhat`. It prevents collisions in a shared workspace:

- Lakebase project ID: `ai-job-copilot-nhat`
- AI Search endpoint: `job-copilot-vs-nhat`

### 9. Create the local variables file

From the repository root in WSL, run:

```bash
mkdir -p .databricks/bundle/dev
nano .databricks/bundle/dev/variable-overrides.json
```

Paste this JSON and replace the sample values:

```json
{
  "catalog": "job_copilot_catalog",
  "schema": "job_copilot",
  "project_id": "ai-job-copilot-nhat",
  "database_name": "job_copilot",
  "vector_search_endpoint": "job-copilot-vs-nhat",
  "model_service": "system.ai.gemma-3-12b"
}
```

In `nano`, save with `Ctrl+O`, press `Enter`, then exit with `Ctrl+X`.

This file stays on your computer. Do not commit it if it contains workspace-specific values.

### 10. If your embedding endpoint is different

Open [databricks.yml](../databricks.yml) and find:

```yaml
embedding_model_endpoint_name: databricks-gte-large-en
```

Replace only `databricks-bge-large-en` with the embedding endpoint you selected. Save the file. Do not replace it with `system.ai.bge-large-en`: AI Search currently requires an embedding **endpoint** name here, not an AI Gateway model-service name.

## What the first deployment creates

When you run the commands below, the bundle creates these resources for you. You do not need to create them manually in the UI:

| Resource | Name / location |
| --- | --- |
| Unity Catalog schema | Created manually in step 4: `<catalog>.job_copilot` |
| Spark ingestion Job | `dev-job-copilot-ingest-remoteok` |
| Lakebase project | the `project_id` in `variable-overrides.json` |
| Lakebase database | `job_copilot` by default |
| AI Search endpoint | the `vector_search_endpoint` in `variable-overrides.json` |
| Delta Sync AI Search index | `<workspace-catalog>.job_copilot.job_documents_index` |
| Frontend App | `dev-job-copilot` |
| Private MCP App | `mcp-dev-job-copilot` |

The bundle does **not** create a chat-model endpoint. The frontend calls the ready-made AI Gateway model service directly using its dedicated App identity.

## Deploy: first pass — create data infrastructure

AI Search cannot be created until the Spark job has first created the `gold_job_documents` Delta table. This is why deployment has two passes.

### 11. Validate before changing anything

```bash
databricks bundle validate -t dev
databricks bundle plan -t dev
```

Expected result: `validate` succeeds and `plan` lists resources that will be created. If either command fails, do not deploy; copy the full error message for troubleshooting.

### 12. Deploy the Lakebase project and ingestion Job

```bash
databricks bundle deploy -t dev \
  --select postgres_projects.job_copilot_project \
  --select jobs.ingest_remoteok
```

This command creates these resources on serverless compute, the only compute type available in Free Edition:

- a Lakebase project and database for user state;
- a paused Spark Job that reads RemoteOK data.

It does **not** create the Apps or AI Search index yet.

### 13. Run the ingestion Job one time

```bash
databricks bundle run ingest_remoteok -t dev
```

Then use the UI:

1. Go to **Workflows** → **Jobs**.
2. Open the job named `dev-job-copilot-ingest-remoteok`.
3. Open its latest run and wait for **Succeeded**.
4. Go to **Catalog** → `<your catalog>` → `job_copilot` → **Tables**.

Confirm these tables exist and have rows:

- `bronze_remoteok_jobs`
- `silver_job_postings`
- `gold_job_documents`
- `quarantine_job_records`
- `pipeline_runs`

If the job fails, open the task output in the Job UI. The most likely causes are a missing feature/permission, an unavailable cluster runtime, or outbound network access to `remoteok.com` being blocked.

## Deploy: second pass — AI Search and Apps

### 14. Deploy everything

Only continue after `gold_job_documents` exists.

```bash
databricks bundle deploy -t dev
```

This creates the AI Search endpoint and index, the Streamlit frontend App, and the private MCP App. App dependencies are installed from `requirements.txt` inside Databricks; you do not need to install this project as a local Python package to deploy it.

### 15. Start the first AI Search sync

Replace `<catalog>` below with the catalog you chose in step 4:

```bash
databricks vector-search-indexes sync-index <catalog>.job_copilot.job_documents_index
```

In the UI, open **Catalog** → `<catalog>` → `job_copilot` → `job_documents_index`. Wait until the AI Search index is online/ready. This can take several minutes.

### 16. Start both Apps

```bash
databricks bundle run frontend -t dev
databricks bundle run mcp -t dev
```

In the UI, open **Apps**. You should see:

- `dev-job-copilot` — the user-facing Streamlit application.
- `mcp-dev-job-copilot` — the private MCP tool server.

Open `dev-job-copilot`. If it does not start, open **Logs** in the App page and copy the first error, not only the last line.

If the chat feature later reports `403`, `EXECUTE`, or `model service not found`, open **Catalog** → `system` → `ai` → `gemma-3-12b` and use **Permissions** to give the `dev-job-copilot` App service principal `EXECUTE`. In a personal Free Edition workspace this normally is already granted; do this only for that error.

## Test it in the UI

### 17. Frontend smoke test

Open `dev-job-copilot` and complete these actions:

1. In **Profile**, enter target roles and a few skills, then click **Save profile**.
2. In **Find jobs**, search for `remote data engineer Spark`.
3. Open a job source link—it should point to RemoteOK.
4. Select `saved` and click **Save / update**.
5. Open **Pipeline** and confirm the saved job appears.
6. Change it to `applied` and confirm it updates instead of making a duplicate row.
7. Ask the chat a simple advice question. It must not claim it submitted an external application.

### 18. Share the correct App

In **Apps** → `dev-job-copilot` → **Permissions**:

- grant test users or a group **CAN USE**;
- do not give them `CAN MANAGE`.

Leave `mcp-dev-job-copilot` private. It is a backend integration service, not a user interface.

## Turn on the daily schedule after the demo works

The ingestion Job is intentionally paused. After your initial test is successful:

1. In [databricks.yml](../databricks.yml), change:

   ```yaml
   pause_status: PAUSED
   ```

   to:

   ```yaml
   pause_status: UNPAUSED
   ```

2. Redeploy:

   ```bash
   databricks bundle deploy -t dev
   ```

The schedule runs at 07:00 in `Asia/Ho_Chi_Minh`.

## Normal update workflow

After changing code or `databricks.yml`:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run frontend -t dev
databricks bundle run mcp -t dev
```

If you change the ingestion code, also run:

```bash
databricks bundle run ingest_remoteok -t dev
databricks vector-search-indexes sync-index <catalog>.job_copilot.job_documents_index
```

## What to inspect when something fails

| What failed | Start in the UI |
| --- | --- |
| Spark ingestion | Workflows → Job → latest run → task output |
| Missing Delta table | Catalog → chosen catalog → `job_copilot` |
| AI Search has no results | Catalog → `job_documents_index` → sync/status |
| Frontend does not open | Apps → `dev-job-copilot` → Logs |
| MCP does not start | Apps → `mcp-dev-job-copilot` → Logs |
| Profile or application does not persist | Lakebase project/database and frontend App logs |

## Cost and cleanup

- Keep the Job paused unless you need daily fresh postings.
- AI Search uses triggered sync, so synchronize it after successful ingestion rather than continuously.
- Lakebase is configured to suspend after five idle minutes.
- Stop Apps after a demonstration if they are not needed.
- Do **not** run `databricks bundle destroy` until you intentionally want to remove the development resources. Lakebase deletion is normally soft-deleted first, but treat cleanup as a destructive operation.

## If a required item is unavailable

- **RemoteOK ingestion fails with a network error:** Free Edition has restricted outbound networking. Save the Job output and use it as evidence for the capstone; to make the app run, the ingestion source must be changed to an allowed API or a committed fixture must be used for demonstration.
- **Lakebase already has a project:** Free Edition permits one project. Either delete the old personal project only if you no longer need it, or modify this project's variables and bundle to reuse it. Do not delete data merely to retry a deployment.
- **AI Search endpoint already exists:** Free Edition permits one endpoint. Reuse its name by setting `vector_search_endpoint` to that endpoint name, if it is suitable and you understand it will be shared.
- **`system.ai.gemma-3-12b` is absent:** Do not create a classic Serving endpoint. This workspace lacks the required AI Gateway model-service access. The app's search and Lakebase features can still be deployed, but chat cannot work until this Databricks feature is available.
- **Chat returns a permission error:** In Catalog, open `system.ai.gemma-3-12b` and grant the frontend App service principal `EXECUTE`, then restart the frontend App.
- **Apps stop after a day:** This is expected on Free Edition. Open Apps and click Start or redeploy with `databricks bundle run frontend -t dev` and `databricks bundle run mcp -t dev`.

## Why CLI is used here

This repository is a Declarative Automation Bundle: [databricks.yml](../databricks.yml) is the single version-controlled definition for the Job, Lakebase project, AI Search index, and two Apps. The UI is excellent for choosing existing personal resources, checking, testing, starting, and troubleshooting them. The CLI creates the same configuration repeatedly without you having to manually repeat every App permission and resource attachment.

## Free Edition references

- [Databricks Free Edition overview](https://docs.databricks.com/aws/en/getting-started/free-edition)
- [Databricks Free Edition quotas and limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
- [Unity Catalog workspace catalog for Free Edition](https://docs.databricks.com/aws/en/getting-started/import-visualize-data)
