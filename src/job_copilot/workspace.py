from databricks.sdk import WorkspaceClient

from job_copilot.config import Settings


def workspace_client(settings: Settings) -> WorkspaceClient:
    """Use explicit local credentials when supplied, otherwise Apps OAuth discovery."""
    if settings.databricks_host and settings.databricks_token:
        return WorkspaceClient(host=settings.databricks_host, token=settings.databricks_token)
    return WorkspaceClient()


def workspace_bearer_token(settings: Settings) -> tuple[str, str]:
    client = workspace_client(settings)
    headers = client.config.authenticate()
    authorization = headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise RuntimeError("Databricks unified authentication did not provide a bearer token")
    if not client.config.host:
        raise RuntimeError("Databricks host is unavailable")
    return client.config.host, authorization.removeprefix("Bearer ")
