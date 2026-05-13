"""Healthcheck (liveness) + readiness probe."""
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.common.errors import ErrorCode, envelope
from app.core.config import config
from app.db.neo4j_client import neo4j_client
from app.utill.LoggingHandler import LoggingHandler

router = APIRouter()
logger = LoggingHandler.get_logger(__name__)


@router.get("/healthcheck")
def healthcheck() -> dict:
    """Liveness — process is up. Does NOT check downstream dependencies."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": f"{config.service_name} is up",
        "build_version": config.build_version,
        "patch_version": config.patch_version,
    }


@router.get("/readiness")
def readiness():
    """
    Readiness — process can serve traffic. Probes Neo4j with a cheap query.
    Returns 503 with the standard envelope on failure so the orchestrator
    stops routing traffic to this pod until the DB recovers.
    """
    try:
        rows = neo4j_client.run("RETURN 1 AS ok")
        if not rows or rows[0].get("ok") != 1:
            raise RuntimeError("neo4j RETURN 1 returned unexpected payload")
    except Exception as exc:
        logger.warning(f"readiness.fail | {exc!r}")
        return JSONResponse(
            status_code=503,
            content=envelope(
                ErrorCode.SERVICE_UNAVAILABLE_001,
                message="neo4j unreachable",
                params=[str(exc)],
            ),
        )
    return {"status": "ready"}
