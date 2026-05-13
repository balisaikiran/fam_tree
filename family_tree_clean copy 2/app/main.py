"""
Application entrypoint.

Mirrors bi-dashboards-service/main.py so the two services have identical:
  - rate limiting (SlowAPI, global IP-based, configurable via RATE_LIMIT)
  - CORS configuration (driven by ALLOW_ORIGINS env var)
  - security headers (HSTS, X-Frame-Options, etc.)
  - error envelope on validation and HTTP exceptions
  - /healthcheck shape, port 8080

The single difference from bi-dashboards is that this service connects to
Neo4j on startup (instead of Postgres/SQLModel) and exposes the family-graph
router, guarded by Group.ICP_FAMILY_TREE_DASHBOARD.
"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.common.errors import ErrorCode, get_error_message
from app.core.config import config
from app.core.group import Group
from app.db.neo4j_client import neo4j_client
from app.middleware.authorization import Authorization
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_header import add_security_headers
from app.routes import family
from app.utill.LoggingHandler import LoggingHandler

# Make sure modules that use stdlib `logging.getLogger(__name__)` directly
# (e.g. graph_service.py) still produce output. LoggingHandler-named loggers
# stop propagation, but the unnamed/stdlib ones bubble up to root.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
)

logger = LoggingHandler.get_logger(__name__)

BUILD_VERSION = os.getenv("BUILD_VERSION", "0.1.0")
PATCH_VERSION = os.getenv("PATCH_VERSION", "2026.05.12.01")


def _envelope(code: ErrorCode, params=None) -> dict:
    """Build the standard {"details": {...}} body."""
    return {
        "details": {
            "code": code.value if hasattr(code, "value") else code,
            "message": get_error_message(code),
            "params": params or [],
        }
    }


# --- Lifespan -------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Best-effort Neo4j connect on startup. If the DB is unreachable, log it
    # and continue — /readiness is the single source of truth for "this pod
    # can serve traffic", so an orchestrator polling readiness will keep
    # traffic off the pod until the DB recovers. This avoids crash-looping
    # during a brief Neo4j blip.
    logger.info("startup: connecting to Neo4j")
    try:
        neo4j_client.connect()
        logger.info("startup: neo4j ready")
    except Exception:
        logger.exception("startup: neo4j connect failed — pod will report not-ready")
    try:
        yield
    finally:
        logger.info("shutdown: closing Neo4j driver")
        try:
            neo4j_client.close()
        except Exception:
            logger.exception("shutdown: neo4j close failed")
        logger.info("shutdown: complete")


app = FastAPI(title="ICP Family Graph Service", version=BUILD_VERSION, lifespan=lifespan)


# --- Rate limiting (same pattern as bi-dashboards) -------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{config.rate_limit}/minute"])


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content=_envelope(ErrorCode.RATE_LIMIT_EXCEEDED_001))


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Middleware order ------------------------------------------------------
# Starlette runs middleware in REVERSE order of `add_middleware` calls — the
# LAST added is the OUTERMOST. So:
#   request:  RequestId → SlowAPI → CORS → security headers → routes
#   response: routes → security headers → CORS → SlowAPI → RequestId
# RequestId must be outermost so every downstream layer (and exception
# handlers) can read the contextvar.
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    return await add_security_headers(request, call_next)


# CORS — with Bearer-token auth we don't need credentialed CORS. Browsers
# REJECT `allow_origins=["*"] + allow_credentials=True`, so when ALLOW_ORIGINS
# is `*` we MUST keep credentials off. When explicit origins are configured
# (e.g. ALLOW_ORIGINS=https://icp-dashboard.example.com), credentials can be
# turned on at the discretion of the deployer.
_cors_credentials = "*" not in config.allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allow_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-ID outermost.
app.add_middleware(RequestIdMiddleware)


# --- Health ----------------------------------------------------------------
@app.get("/healthcheck")
async def healthcheck():
    """Liveness — process is up. Does NOT check downstream dependencies."""
    return JSONResponse(
        content={
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "ICP Family Graph Service is running",
            "build_version": BUILD_VERSION,
            "patch_version": PATCH_VERSION,
        },
        status_code=200,
    )


@app.get("/readiness")
async def readiness():
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
            content=_envelope(ErrorCode.INTERNAL_SERVER_ERROR_001, params=[str(exc)]),
        )
    return JSONResponse(status_code=200, content={"status": "ready"})


# --- Exception handlers (envelope identical to bi-dashboards) --------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = exc.errors()
    error_code = ErrorCode.INVALID_INPUT_001
    params = []
    if details and details[0]:
        detail = details[0]
        if "type" in detail:
            if "int_parsing" in detail["type"]:
                error_code = ErrorCode.INVALID_INTEGER_001
            elif "time_parsing" in detail["type"]:
                error_code = ErrorCode.INVALID_TIME_001
            elif "float_parsing" in detail["type"] or "double_parsing" in detail["type"]:
                error_code = ErrorCode.INVALID_FLOAT_001
            elif "date_parsing" in detail["type"]:
                error_code = ErrorCode.INVALID_DATE_001
            elif "datetime_parsing" in detail["type"]:
                error_code = ErrorCode.INVALID_DATETIME_001
            params = [detail["input"]] if "input" in detail else []

    return JSONResponse(status_code=422, content=_envelope(error_code, params=params))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Normalize all HTTPException responses to {"details": {"code","message","params"}}.

    - When the exception was raised by `handle_errors(...)`, `exc.detail` is
      already the inner dict — wrap it under `"details"`.
    - When raised by FastAPI defaults (404, 405, etc.), `exc.detail` is a
      string — build the envelope ourselves so the frontend's response
      parser doesn't choke on a string where it expects an object.
    """
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message", "params"} <= set(detail.keys()):
        body = {"details": detail}
    else:
        # Map common HTTP statuses to specific envelope codes so the frontend
        # doesn't have to inspect the status code AND the body.
        if exc.status_code == 404:
            code = ErrorCode.INVALID_INPUT_001
        elif exc.status_code == 401:
            code = ErrorCode.UNAUTHORIZED_002
        elif exc.status_code == 403:
            code = ErrorCode.FORBIDDEN_001
        else:
            code = ErrorCode.INTERNAL_SERVER_ERROR_001
        body = {
            "details": {
                "code": code.value,
                "message": str(detail) if detail else get_error_message(code),
                "params": [],
            }
        }
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers or {})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all: never leak a Starlette plain-text 500 to the frontend."""
    logger.exception(f"unhandled.exception | {exc!r}")
    return JSONResponse(
        status_code=500,
        content=_envelope(ErrorCode.INTERNAL_SERVER_ERROR_001),
    )


# --- Routers ---------------------------------------------------------------
prefix = "/api/v1"

app.include_router(
    family.router,
    prefix=prefix,
    dependencies=[Depends(Authorization(Group.ICP_FAMILY_TREE_DASHBOARD))],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.port)
