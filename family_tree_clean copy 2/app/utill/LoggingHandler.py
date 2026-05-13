"""
Logger factory — copied from bi-dashboards-service/utill/LoggingHandler.py
so the two services emit logs in the same shape (a log aggregator parser
written for one will work for the other).

Adds a request-ID filter so every log line carries `rid=<uuid>` when emitted
inside an HTTP request (and `rid=-` outside one).
"""
import logging
import os
from logging.handlers import RotatingFileHandler


class _RequestIdFilter(logging.Filter):
    """Inject the current request_id (or '-') onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Lazy import so importing LoggingHandler doesn't drag in middleware
        # — keeps the import graph clean for tests that use the logger
        # without booting the FastAPI app.
        try:
            from app.middleware.request_id import request_id_ctx
            record.request_id = request_id_ctx.get()
        except Exception:
            record.request_id = "-"
        return True


class LoggingHandler:
    @staticmethod
    def get_logger(name: str):
        logger = logging.getLogger(name)

        if logger.hasHandlers():
            logger.handlers.clear()

        logger.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.addFilter(_RequestIdFilter())

        class ConditionalFormatter(logging.Formatter):
            def format(self, record):
                base_message = (
                    "%(asctime)s - %(name)s - [%(levelname)s] -"
                    " rid=%(request_id)s - %(message)s"
                )

                if record.levelno >= logging.WARNING:
                    base_message += (
                        " [ErrorCode: %(error_code)s, StatusCode: %(status_code)s,"
                        " ErrorMessage: %(error_message)s, Exception: %(exception)s,"
                        " Input: %(input)s, Resolution: %(resolution)s]"
                    )

                base_message += (
                    " [CallerFile: %(pathname)s, CallerFunction: %(funcName)s,"
                    " CallerLine: %(lineno)d]"
                )

                self._style._fmt = base_message

                record.error_code = getattr(record, "error_code", "N/A")
                record.status_code = getattr(record, "status_code", "N/A")
                record.error_message = getattr(record, "error_message", "N/A")
                record.input = getattr(record, "input", "N/A")
                record.exception = getattr(record, "exception", "N/A")
                record.resolution = getattr(record, "resolution", "N/A")
                record.request_id = getattr(record, "request_id", "-")

                return super().format(record)

        console_handler.setFormatter(ConditionalFormatter())
        logger.addHandler(console_handler)

        log_dir = os.getenv("LOG_DIR", "/app/logs")
        log_file = os.path.join(log_dir, "app.log")
        try:
            os.makedirs(log_dir, exist_ok=True)
            rotating_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            rotating_handler.setLevel(logging.INFO)
            rotating_handler.addFilter(_RequestIdFilter())
            rotating_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s -"
                    " rid=%(request_id)s - %(message)s"
                )
            )
            logger.addHandler(rotating_handler)
        except (PermissionError, OSError):
            # If LOG_DIR isn't writable (e.g. running locally without the
            # /app/logs path), fall back to console-only. Don't crash
            # imports — the orchestrator collects stdout anyway.
            pass

        logger.propagate = False

        return logger
