"""Fail-closed cutover guards and observability for retired Horilla HR writers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse

RETIRED_LEGACY_HR_APPS = frozenset({"payroll", "offboarding", "report"})
MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LEGACY_WRITE_ATTEMPTS_METRIC = "legacy_write_attempts_total"
LEGACY_WRITE_ATTEMPTS_CACHE_KEY = f"renshi:metrics:{LEGACY_WRITE_ATTEMPTS_METRIC}"

logger = logging.getLogger("renshi.legacy_cutover")


def is_retired_legacy_model_path(model_path: str | None) -> bool:
    """Return True only for model paths owned by retired legacy HR apps."""
    if not model_path:
        return False
    app_label = str(model_path).split(".", 1)[0].strip().lower()
    return app_label in RETIRED_LEGACY_HR_APPS


def record_legacy_write_attempt(request, *, surface: str, model_path: str = "") -> None:
    """Record a blocked/redirected legacy formal-write attempt.

    The structured warning is the production aggregation source of truth.  A
    best-effort shared cache counter gives operators/tests a cheap current
    total when Redis is configured. Observability failure must never turn a
    safely blocked legacy write into a 500.
    """
    method = str(getattr(request, "method", "") or "").upper()
    path = str(getattr(request, "path", "") or "")
    logger.warning(
        "%s=1 surface=%s method=%s path=%s model=%s",
        LEGACY_WRITE_ATTEMPTS_METRIC,
        surface,
        method,
        path,
        model_path or "-",
        extra={
            "metric": LEGACY_WRITE_ATTEMPTS_METRIC,
            "metric_value": 1,
            "surface": surface,
            "http_method": method,
            "request_path": path,
            "legacy_model": model_path or "",
        },
    )
    try:
        if not cache.add(LEGACY_WRITE_ATTEMPTS_CACHE_KEY, 1, timeout=None):
            cache.incr(LEGACY_WRITE_ATTEMPTS_CACHE_KEY)
    except Exception:  # pragma: no cover - structured log above remains authoritative
        pass


def get_legacy_write_attempts_total() -> int:
    """Return the best-effort shared counter for operational checks/tests."""
    try:
        return int(cache.get(LEGACY_WRITE_ATTEMPTS_CACHE_KEY) or 0)
    except Exception:  # pragma: no cover - cache outage must not fail callers
        return 0


def protect_retired_legacy_model_write(
    view: Callable,
    *,
    surface: str,
    block_methods: Collection[str] | None = None,
    write_methods: Collection[str] | None = None,
) -> Callable:
    """Fail closed when a generic endpoint targets a retired HR Authority.

    ``block_methods=None`` blocks every HTTP method for a retired model.
    ``write_methods`` controls which blocked methods increment the write-attempt
    metric; e.g. generic-delete GET confirmation is unavailable after cutover
    but is not counted as a formal write attempt.
    """
    blocked = (
        None
        if block_methods is None
        else frozenset(str(method).upper() for method in block_methods)
    )
    counted = (
        None
        if write_methods is None
        else frozenset(str(method).upper() for method in write_methods)
    )

    @wraps(view)
    def guarded(request, *args, **kwargs):
        model_path = request.GET.get("model") or request.POST.get("model") or ""
        if not is_retired_legacy_model_path(model_path):
            return view(request, *args, **kwargs)

        method = str(request.method or "").upper()
        if blocked is not None and method not in blocked:
            return view(request, *args, **kwargs)

        if counted is None or method in counted:
            record_legacy_write_attempt(
                request,
                surface=surface,
                model_path=model_path,
            )

        response = JsonResponse(
            {
                "error": {
                    "code": "LEGACY_FORMAL_WRITE_FROZEN",
                    "message": "legacy HR authority is read-only after cutover",
                    "model": model_path,
                }
            },
            status=410,
        )
        response["Cache-Control"] = "no-store"
        response["Deprecation"] = "true"
        return response

    return guarded
