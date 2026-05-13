"""
Request-ID middleware.

Reads the inbound `X-Request-ID` header (or generates a UUID if absent),
publishes it on a contextvar so log records can carry it, and echoes it
back on the response. Lets ops tie a Cypher call back to the originating
HTTP request when grepping logs.
"""
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_HEADER = "X-Request-ID"

# Default "-" so log records emitted outside a request (startup/shutdown)
# still render cleanly.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(_HEADER) or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers[_HEADER] = rid
        return response
