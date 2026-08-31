"""Narrow MySQL transient transaction retry for irreversible service boundaries."""

from __future__ import annotations

import logging
import time
from functools import wraps

from django.db import OperationalError, connection

logger = logging.getLogger(__name__)

MYSQL_RETRYABLE_TRANSACTION_CODES = frozenset({1205, 1213})


def mysql_operational_error_code(exc: BaseException) -> int | None:
    """Extract a MySQL error code without depending on mysqlclient internals."""
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
        current = getattr(current, "__cause__", None)
    return None


def retry_mysql_transaction(
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.05,
    retryable_codes=MYSQL_RETRYABLE_TRANSACTION_CODES,
):
    """
    Retry one *whole* transaction boundary on MySQL deadlock/lock-timeout only.

    Apply this outside ``@transaction.atomic`` so each retry starts a fresh
    transaction. Non-MySQL errors, non-transient database errors, and exhausted
    attempts are re-raised unchanged. The wrapper never retries arbitrary
    business exceptions.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if base_delay_seconds < 0:
        raise ValueError("base_delay_seconds must be >= 0")
    retryable_codes = frozenset(int(code) for code in retryable_codes)

    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as exc:
                    code = mysql_operational_error_code(exc)
                    can_retry = (
                        connection.vendor == "mysql"
                        and code in retryable_codes
                        and attempt < attempts
                    )
                    if not can_retry:
                        raise
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "Retrying MySQL transaction after transient error code=%s "
                        "attempt=%s/%s delay=%.3fs boundary=%s",
                        code,
                        attempt,
                        attempts,
                        delay,
                        func.__qualname__,
                    )
                    if delay:
                        time.sleep(delay)
            raise AssertionError("unreachable retry loop")

        return wrapped

    return decorator
