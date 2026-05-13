"""
FastAPI app factory.

Wires:
* Request-ID + security-headers + CORS middleware
* slowapi rate limiter (default limit from RATE_LIMIT env var, error mapped
  to the standard envelope)
* Standard error envelope on every error path (HTTPException + Pydantic
  validation + everything else)
* Routers: /healthcheck, /readiness, /api/v1/family-tree/*, /api/v1/persons/*
* Neo4j connect on startup, close on shutdown (lifespan context manager)
"""
from contextlib import asynccontextmanager
from typing import Any, Iterable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.errors import ErrorCode, envelope
from app.core.config import config
from app.db.neo4j_client import neo4j_client
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import family_tree as family_tree_router
from app.routers import health as health_router
from app.routers import persons as persons_router
from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)


def _wrap_detail(detail: Any, default_code: ErrorCode) -> dict:
    """
    HTTPException.detail can be:
      - a dict already shaped {"code","message","params"} (handle_errors)
      - a plain string (FastAPI defaults like "Not Found")
      - some other JSON-serialisable thing
    Always normalise to {"details": {"code","message","params"}}.
    """
    if isinstance(detail, dict) and {"code", "message", "params"} <= set(detail.keys()):
        return {"details": detail}
    if isinstance(detail, str):
        return envelope(default_code, message=detail)
    return envelope(default_code, message=str(detail))


# --- Pydantic v2 error type → ErrorCode mapping ---------------------------
_PYDANTIC_TYPE_TO_CODE = {
    "int_parsing": ErrorCode.INVALID_INTEGER_001,
    "int_type": ErrorCode.INVALID_INTEGER_001,
    "int_from_float": ErrorCode.INVALID_INTEGER_001,
    "greater_than_equal": ErrorCode.INVALID_INTEGER_001,
    "less_than_equal": ErrorCode.INVALID_INTEGER_001,
    "greater_than": ErrorCode.INVALID_INTEGER_001,
    "less_than": ErrorCode.INVALID_INTEGER_001,
    "float_parsing": ErrorCode.INVALID_FLOAT_001,
    "float_type": ErrorCode.INVALID_FLOAT_001,
    "date_parsing": ErrorCode.INVALID_DATE_001,
    "date_type": ErrorCode.INVALID_DATE_001,
    "time_parsing": ErrorCode.INVALID_TIME_001,
    "time_type": ErrorCode.INVALID_TIME_001,
    "datetime_parsing": ErrorCode.INVALID_DATETIME_001,
    "datetime_type": ErrorCode.INVALID_DATETIME_001,
    "enum": ErrorCode.INVALID_ENUM_001,
    "string_pattern_mismatch": ErrorCode.INVALID_INPUT_001,
}


def _validation_to_envelope(errors: Iterable[dict]) -> dict:
    errors = list(errors)
    if not errors:
        return envelope(ErrorCode.INVALID_INPUT_001)
    err = errors[0]
    err_type = err.get("type", "")
    code = _PYDANTIC_TYPE_TO_CODE.get(err_type, ErrorCode.INVALID_INPUT_001)
    msg = err.get("msg", "Invalid input")
    raw_input = err.get("input")
    params = [raw_input] if raw_input is not None else []
    return envelope(code, message=msg, params=params)


# --- Lifespan -------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup posture: best-effort connect, log on failure but DO NOT raise.
    # The /readiness probe (app/routers/health.py) is the single source of
    # truth for "this pod can serve traffic". An orchestrator that polls it
    # will hold traffic off until the DB is reachable, so a brief Neo4j
    # outage during boot doesn't crash-loop the container — it just keeps
    # the pod un-ready until things recover.
    try:
        neo4j_client.connect()
    except Exception as exc:
        logger.warning(f"neo4j.connect.failed | {exc!r}")
    try:
        yield
    finally:
        try:
            neo4j_client.close()
        except Exception as exc:
            logger.warning(f"neo4j.close.failed | {exc!r}")


# --- App ------------------------------------------------------------------
app = FastAPI(title="family-tree-backend", openapi_url="/openapi.json", lifespan=lifespan)

# Rate limiter — default limit comes from RATE_LIMIT env var (per minute,
# keyed by remote address). SlowAPIMiddleware applies it to every route
# without per-route decoration.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{config.rate_limit}/minute"],
)
app.state.limiter = limiter

# Middleware order: outermost first. Request-ID must be outermost so every
# downstream layer (security headers, CORS, rate limiter, routes) can read
# the contextvar; security headers and CORS run inside it.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    body = _wrap_detail(exc.detail, default_code=ErrorCode.INTERNAL_SERVER_ERROR_001)
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers or {})


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_validation_to_envelope(exc.errors()))


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=envelope(
            ErrorCode.RATE_LIMIT_EXCEEDED_001,
            message="Rate limit exceeded",
            params=[str(exc.detail)],
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exc_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"unhandled.exception | {exc!r}")
    return JSONResponse(
        status_code=500,
        content=envelope(ErrorCode.INTERNAL_SERVER_ERROR_001, message="Internal server error"),
    )


app.include_router(health_router.router)
app.include_router(family_tree_router.router)
app.include_router(persons_router.router)
