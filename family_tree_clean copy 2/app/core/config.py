"""
Centralized application config.

Mirrors bi-dashboards-service/core/config.py: load everything from env at
import time, fail fast with a clear error when something required is missing.
"""
import os

from pydantic import BaseModel

from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)


class Config(BaseModel):
    # Service
    port: int
    log_folder: str
    allow_origins: list[str]
    rate_limit: int

    # Neo4j
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_db: str

    # Keycloak (used to validate access-token signatures via JWKS)
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_verify_signature: bool


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise EnvironmentError(f"{name} environment variable is required.")
    return val


def load_config() -> Config:
    return Config(
        port=int(os.getenv("PORT", 8080)),
        log_folder=os.getenv("LOG_DIR", "/app/logs"),
        allow_origins=[o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()],
        rate_limit=int(os.getenv("RATE_LIMIT", 50)),

        neo4j_uri=_required("NEO4J_URI"),
        neo4j_user=_required("NEO4J_USER"),
        neo4j_password=_required("NEO4J_PASSWORD"),
        neo4j_db=os.getenv("NEO4J_DB", "neo4j"),

        keycloak_url=_required("KEYCLOAK_URL"),
        keycloak_realm=_required("KEYCLOAK_REALM"),
        keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID", "icp-frontend"),
        # Off by default to match bi-dashboards-service behaviour; flip to "true"
        # in environments where this service is exposed without a gateway that
        # already verifies tokens. JWKS rotation is handled in auth_bearer.
        keycloak_verify_signature=os.getenv("KEYCLOAK_VERIFY_SIGNATURE", "false").lower() == "true",
    )


try:
    config = load_config()
except EnvironmentError as e:
    logger.error(str(e))
    raise SystemExit(str(e))
