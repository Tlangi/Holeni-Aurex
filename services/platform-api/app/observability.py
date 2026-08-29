from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import time
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

correlation_id_context: ContextVar[str] = ContextVar("correlation_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "correlation_id": getattr(record, "correlation_id", None)
            or correlation_id_context.get()
            or None,
            "tenant_id": getattr(record, "tenant_id", None),
            "trading_account_id": getattr(record, "trading_account_id", None),
            "broker_connection_id": getattr(record, "broker_connection_id", None),
            "worker": getattr(record, "worker", "api"),
            "operation": getattr(record, "operation", record.name),
            "duration_ms": getattr(record, "duration_ms", None),
            "result": getattr(record, "result", None),
            "message": record.getMessage(),
        }
        return json.dumps(event, separators=(",", ":"), ensure_ascii=True)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if any(getattr(handler, "aurex_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.aurex_json = True  # type: ignore[attr-defined]
    # Successful requests and routine worker heartbeats are returned to callers
    # or persisted as status, not repeated in the interactive console.
    handler.setLevel(logging.WARNING)
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


def _correlation_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


class CorrelationLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = _correlation_id(request.headers.get("X-Correlation-ID"))
        request.state.correlation_id = correlation_id
        token = correlation_id_context.set(correlation_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000)
            if status_code >= 400:
                logger = logging.getLogger("aurex.http")
                log = logger.error if status_code >= 500 else logger.warning
                log(
                    "request failed",
                    extra={
                        "correlation_id": correlation_id,
                        "tenant_id": getattr(request.state, "tenant_id", None),
                        "operation": f"{request.method} {request.url.path}",
                        "duration_ms": duration_ms,
                        "result": str(status_code),
                    },
                )
            correlation_id_context.reset(token)
