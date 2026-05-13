"""Thin logging wrapper so callers don't depend directly on `logging`."""
import logging
import os
import sys


_CONFIGURED = False


class _RequestIdFilter(logging.Filter):
    """Inject the current request_id (or '-') onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Imported lazily so importing LoggingHandler doesn't drag in the
        # middleware module — keeps the import graph clean for tests that
        # use the logger without booting the FastAPI app.
        try:
            from app.middleware.request_id import request_id_ctx
            record.request_id = request_id_ctx.get()
        except Exception:
            record.request_id = "-"
        return True


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | rid=%(request_id)s | %(message)s"
        )
    )
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    _CONFIGURED = True


class LoggingHandler:
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        _configure_root()
        return logging.getLogger(name)
