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


app = FastAPI(title="ICP Family Graph Service", version=BUILD_VERSION)

# --- Rate limiting (same pattern as bi-dashboards) -------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{config.rate_limit}/minute"])


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": ErrorCode.RATE_LIMIT_EXCEEDED_001,
                "message": get_error_message(ErrorCode.RATE_LIMIT_EXCEEDED_001),
                "params": [],
            },
        },
    )


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# --- CORS -------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Security headers ------------------------------------------------------
@app.middleware("http")
async def security_headers_middleware(request, call_next):
    return await add_security_headers(request, call_next)


# --- Startup / shutdown ----------------------------------------------------
@app.on_event("startup")
def on_startup():
    logger.info("startup: connecting to Neo4j")
    neo4j_client.connect()
    logger.info("startup: ready")


@app.on_event("shutdown")
def on_shutdown():
    logger.info("shutdown: closing Neo4j driver")
    neo4j_client.close()
    logger.info("shutdown: complete")


# --- Health ----------------------------------------------------------------
@app.get("/healthcheck")
async def healthcheck():
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

    return JSONResponse(
        status_code=422,
        content={
            "details": {
                "code": error_code,
                "message": get_error_message(error_code),
                "params": params,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"details": exc.detail})


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
