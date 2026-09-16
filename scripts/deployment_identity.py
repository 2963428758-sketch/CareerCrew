"""Credential-free endpoint identities for protected authority receipts."""
import os
from collections.abc import Mapping
from urllib.parse import parse_qs, unquote, urlsplit


def deployment_identity(database_url: str, qdrant_url: str, *, environ: Mapping[str, str] | None = None) -> dict:
    """Bind an authority receipt to the endpoints the runner will actually use."""
    env = os.environ if environ is None else environ
    routing_keys = {"PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"}
    if any(env.get(key) for key in routing_keys):
        raise ValueError("deployment database environment routing overrides are unsupported")
    database = urlsplit(database_url)
    qdrant = urlsplit(qdrant_url)
    if database.scheme not in {"postgres", "postgresql", "postgresql+psycopg"} or not database.hostname or not database.path.strip("/"):
        raise ValueError("deployment database endpoint is required")
    # libpq accepts alternate routing through query parameters. Reject these
    # rather than attest one host while connecting to a different host/service.
    if set(parse_qs(database.query, keep_blank_values=True)) & {"host", "hostaddr", "port", "dbname", "service", "servicefile", "options"}:
        raise ValueError("deployment database routing overrides are unsupported")
    if qdrant.scheme not in {"http", "https"} or not qdrant.hostname or qdrant.username or qdrant.password or qdrant.query or qdrant.fragment:
        raise ValueError("deployment Qdrant endpoint is invalid")
    host = qdrant.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return {
        "database": {"host": database.hostname.lower(), "port": database.port or 5432, "database": unquote(database.path.lstrip("/"))},
        "qdrant": f"{qdrant.scheme}://{host}:{qdrant.port or (443 if qdrant.scheme == 'https' else 80)}{qdrant.path.rstrip('/')}",
    }
