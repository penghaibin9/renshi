"""Small, dependency-free observability primitives for every process type."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone


_request_id = contextvars.ContextVar("request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_SENSITIVE_HEADER = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"(\s*[:=]\s*)([^\r\n]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(?i)(redis|rediss|mysql)://([^\s/@:]+):([^\s/@]+)@")
_CN_ID_CARD = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[0-9Xx])(?!\d)")


def current_request_id() -> str:
    return _request_id.get()


def redact_log_text(value) -> str:
    text = str(value)
    text = _SENSITIVE_HEADER.sub(r"\1\2[REDACTED]", text)
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    text = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(r"\1://\2:[REDACTED]@", text)
    return _CN_ID_CARD.sub(r"\1********\2", text)


class RequestIdMiddleware:
    """Attach a bounded correlation id to logs and the HTTP response."""

    header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        candidate = request.headers.get(self.header_name, "")
        request_id = candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else uuid.uuid4().hex
        request.request_id = request_id
        token = _request_id.set(request_id)
        try:
            response = self.get_response(request)
            response[self.header_name] = request_id
            return response
        finally:
            _request_id.reset(token)


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = current_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line for container log collectors."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", current_request_id()),
            "message": redact_log_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_log_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
