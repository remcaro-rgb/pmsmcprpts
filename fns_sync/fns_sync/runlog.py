"""The import log in the database (pms.fns_sync_log), shown in the website's Admin page: every line
the importer logs, with the hotel and import it belongs to and, for an API call, the request (as a
curl command, without the password) and what the API answered.

Log calls pass the request and answer as extra={"command": ..., "output": ...}; the hotel and the
import come from context(), set while a hotel is imported."""

import contextlib
import contextvars
import logging
from typing import Any

import psycopg

# Characters of an API answer kept: enough to see what went wrong, less for the answers that worked
# (a year of reservations is far longer, and a hotel's imports log about 100 calls a day).
MAX_TEXT = 20_000
MAX_TEXT_INFO = 2_000

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("fns_log_context", default={})


@contextlib.contextmanager
def context(**fields: Any):
    """Log lines inside belong to this hotel (hotel_id) and import (run_id)."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def update(**fields: Any) -> None:
    """Adds to the current context() (e.g. the import's run_id once it has one)."""
    _context.set({**_context.get(), **fields})


def level(levelno: int) -> str:
    return "error" if levelno >= logging.ERROR else "warning" if levelno >= logging.WARNING else "info"


def _clip(text: str | None, limit: int = MAX_TEXT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n… ({len(text) - limit:,} more characters not kept)"


class DatabaseHandler(logging.Handler):
    """Writes each record to pms.fns_sync_log on its own connection (so a line is kept even when the
    import's own transaction fails). A database that can't be written to only loses the line."""

    def __init__(self, dsn: str):
        super().__init__(logging.INFO)
        self.dsn = dsn
        self.conn: psycopg.Connection | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
            ctx = _context.get()
            message = record.getMessage()
            output = getattr(record, "output", None)
            if record.exc_info and record.exc_info[1] is not None:
                trace = logging.Formatter().formatException(record.exc_info)
                output = f"{output}\n\n{trace}" if output else trace
            self.conn.execute(
                "INSERT INTO pms.fns_sync_log (hotel_id, run_id, level, message, command, output) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (ctx.get("hotel_id"), ctx.get("run_id"), level(record.levelno), message[:2000],
                 _clip(getattr(record, "command", None)),
                 _clip(output, MAX_TEXT if record.levelno >= logging.WARNING else MAX_TEXT_INFO)))
        except psycopg.Error:
            if self.conn is not None:
                self.conn.close()
            self.conn = None
        except Exception:  # never break an import over its log
            self.handleError(record)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        super().close()


def install(dsn: str) -> DatabaseHandler | None:
    """Sends the importer's log to the database too (it still goes to the console)."""
    if not dsn:
        return None
    handler = DatabaseHandler(dsn)
    logger = logging.getLogger("fns_sync")
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return handler
