from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class Actor:
    """Server-side identity. Never accept this identifier from a tool argument."""

    user_id: str
    email: str | None = None
    display_name: str | None = None


def actor_from_headers(headers: dict[str, str]) -> Actor:
    lowered = {key.lower(): value for key, value in headers.items()}
    user = lowered.get("x-forwarded-user") or lowered.get("x-forwarded-email")
    if not user:
        raise PermissionError("Databricks authenticated user headers are required")
    # Stable, non-reversible DB key; keep the raw email out of query predicates.
    user_id = sha256(user.strip().lower().encode()).hexdigest()
    return Actor(user_id=user_id, email=lowered.get("x-forwarded-email"), display_name=user)

