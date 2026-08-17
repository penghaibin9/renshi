"""Fail-closed cutover guards and observability for retired Horilla HR writers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.http import JsonResponse

RETIRED_LEGACY_HR_APPS = frozenset({"payroll", "offboarding", "report"})
MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LEGACY_WRITE_ATTEMPT_EVENT = "legacy_write_attempt"
LEGACY_WRITE_ATTEMPTS_METRIC = "legacy_write_attempts_total"
LEGACY_WRITE_ATTEMPTS_CACHE_KEY = f"renshi:metrics:{LEGACY_WRITE_ATTEMPTS_METRIC}"

MODEL_KEYS = (
    "model",
    "model_path",
    "target_model",
    "root_model",
    "model_class",
    "orm_model",
)
APP_LABEL_KEYS = ("app", "app_label", "application")
MODEL_NAME_KEYS = ("model_name", "modelname")
DYNAMIC_FIELD_KEYS = ("field", "dynamic_field")

WRITE_SURFACE_REGISTRY = {
    "generic-delete": {"semantic_write": False},
    "update-kanban-sequence": {"semantic_write": True},
    "update-kanban-item-group": {"semantic_write": True},
    "update-kanban-group-sequence": {"semantic_write": True},
    "history-revert": {"semantic_write": True},
    "generic-history-revert": {"semantic_write": True},
    "dynamic-form": {"semantic_write": True},
    "dynamic-bulk-update": {"semantic_write": True},
    "dynamic-import": {"semantic_write": True},
    "orm-resolved-write": {"semantic_write": True},
}

_DYNAMIC_SURFACE_PREFIXES = (
    ("post-bulk-update-", "dynamic-bulk-update"),
    ("post-import-sheet-", "dynamic-import"),
    ("dynamic-path-", "dynamic-form"),
)

logger = logging.getLogger("renshi.legacy_cutover")


@dataclass(frozen=True)
class ModelResolution:
    model_path: str
    source: str


class LegacyFormalWriteFrozenError(RuntimeError):
    """Raised by the final ORM guard when a retired Authority is about to mutate."""

    def __init__(
        self,
        *,
        model_path: str,
        surface: str,
        model_source: str = "orm-resolved",
        recorded: bool = False,
    ) -> None:
        self.model_path = model_path
        self.surface = surface
        self.model_source = model_source
        self.recorded = recorded
        super().__init__(
            f"legacy HR formal write is frozen: {model_path} via {surface}"
        )


def _model_path_from_value(value: Any, *, app_hint: str = "") -> str:
    """Normalize a string/model/queryset/model-instance into ``app.Model``."""
    if value is None:
        return ""

    meta = getattr(value, "_meta", None)
    if meta is not None:
        app_label = str(getattr(meta, "app_label", "") or "").strip()
        object_name = str(
            getattr(meta, "object_name", "")
            or getattr(meta, "model_name", "")
            or ""
        ).strip()
        if app_label and object_name:
            return f"{app_label}.{object_name}"

    queryset_model = getattr(value, "model", None)
    if queryset_model is not None and queryset_model is not value:
        path = _model_path_from_value(queryset_model)
        if path:
            return path

    if not isinstance(value, str):
        return ""

    path = value.strip()
    if not path:
        return ""
    if app_hint and "." not in path:
        return f"{app_hint.strip()}.{path}"
    return path


def is_retired_legacy_model_path(model_path: Any) -> bool:
    """Return True only for model paths/models owned by retired legacy HR apps."""
    normalized = _model_path_from_value(model_path)
    if not normalized:
        return False
    app_label = normalized.split(".", 1)[0].strip().lower()
    return app_label in RETIRED_LEGACY_HR_APPS


def _append_candidate(
    results: list[ModelResolution],
    seen: set[tuple[str, str]],
    value: Any,
    *,
    source: str,
    app_hint: str = "",
) -> None:
    model_path = _model_path_from_value(value, app_hint=app_hint)
    if not model_path:
        return
    key = (model_path, source)
    if key in seen:
        return
    seen.add(key)
    results.append(ModelResolution(model_path=model_path, source=source))


def _collect_mapping_candidates(
    mapping: Any,
    *,
    source: str,
    results: list[ModelResolution],
    seen: set[tuple[str, str]],
    depth: int = 0,
) -> None:
    if depth > 4 or not isinstance(mapping, Mapping):
        return

    app_hint = ""
    for key in APP_LABEL_KEYS:
        value = mapping.get(key)
        if value:
            app_hint = str(value).strip()
            break

    for key in MODEL_KEYS:
        if key in mapping:
            _append_candidate(
                results,
                seen,
                mapping.get(key),
                source=f"{source}:{key}",
                app_hint=app_hint,
            )

    if app_hint:
        for key in MODEL_NAME_KEYS:
            if mapping.get(key):
                _append_candidate(
                    results,
                    seen,
                    mapping.get(key),
                    source=f"{source}:{key}",
                    app_hint=app_hint,
                )

    # Dynamic/session caches commonly nest the model metadata one or two levels
    # down. Recurse only through structured containers; arbitrary scalar request
    # values are never guessed as model paths.
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            _collect_mapping_candidates(
                value,
                source=f"{source}.{key}",
                results=results,
                seen=seen,
                depth=depth + 1,
            )
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _collect_mapping_candidates(
                        item,
                        source=f"{source}.{key}[{index}]",
                        results=results,
                        seen=seen,
                        depth=depth + 1,
                    )


def _mapping_view(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    items = getattr(value, "items", None)
    if callable(items):
        try:
            return dict(items())
        except Exception:
            return {}
    return {}


def _json_payload(request) -> Mapping[str, Any]:
    content_type = str(getattr(request, "content_type", "") or "")
    if "json" not in content_type.lower():
        return {}
    try:
        body = getattr(request, "body", b"") or b""
        if isinstance(body, bytes):
            body = body.decode(getattr(request, "encoding", None) or "utf-8")
        payload = json.loads(body or "{}")
        return payload if isinstance(payload, Mapping) else {}
    except Exception:
        return {}


def _view_model_candidates(
    view: Any,
    *,
    results: list[ModelResolution],
    seen: set[tuple[str, str]],
) -> None:
    if view is None:
        return

    objects = [view]
    for attr in ("view_class", "cls"):
        candidate = getattr(view, attr, None)
        if candidate is not None:
            objects.append(candidate)

    for obj in objects:
        _append_candidate(
            results,
            seen,
            getattr(obj, "model", None),
            source="view:model",
        )
        queryset = getattr(obj, "queryset", None)
        _append_candidate(
            results,
            seen,
            getattr(queryset, "model", None),
            source="view:queryset.model",
        )
        form_class = getattr(obj, "form_class", None)
        form_meta = getattr(form_class, "_meta", None)
        _append_candidate(
            results,
            seen,
            getattr(form_meta, "model", None),
            source="view:form_class.model",
        )


def resolve_model_candidates(
    request,
    *,
    url_kwargs: Mapping[str, Any] | None = None,
    view: Any = None,
    dynamic_cache: Any = None,
    resolved_model: Any = None,
) -> tuple[ModelResolution, ...]:
    """Resolve model identity from every generic-write source without guessing.

    Source order intentionally mirrors the external-to-internal resolution
    chain: JSON body -> GET -> POST -> URL kwargs -> session/dynamic cache ->
    view metadata -> the final ORM model actually selected by the writer.
    """

    results: list[ModelResolution] = []
    seen: set[tuple[str, str]] = set()

    json_payload = _json_payload(request)
    _collect_mapping_candidates(
        json_payload, source="json", results=results, seen=seen
    )
    _collect_mapping_candidates(
        getattr(request, "GET", {}), source="get", results=results, seen=seen
    )
    _collect_mapping_candidates(
        getattr(request, "POST", {}), source="post", results=results, seen=seen
    )

    resolver_match = getattr(request, "resolver_match", None)
    resolved_kwargs = (
        url_kwargs
        if url_kwargs is not None
        else getattr(resolver_match, "kwargs", None) or {}
    )
    _collect_mapping_candidates(
        resolved_kwargs, source="url_kwargs", results=results, seen=seen
    )

    session = getattr(request, "session", None)
    session_mapping = _mapping_view(session)
    if session_mapping:
        _collect_mapping_candidates(
            session_mapping, source="session", results=results, seen=seen
        )

    if dynamic_cache is not None:
        if isinstance(dynamic_cache, Mapping):
            _collect_mapping_candidates(
                dynamic_cache,
                source="dynamic_cache",
                results=results,
                seen=seen,
            )
        else:
            _append_candidate(
                results,
                seen,
                dynamic_cache,
                source="dynamic_cache:model",
            )

    # Horilla dynamic-create caches are keyed as
    # <session_key>cbv<dynamic_field>. Resolve them when the field is visible
    # anywhere in the request contract.
    field_names: set[str] = set()
    for mapping in (
        json_payload,
        getattr(request, "GET", {}),
        getattr(request, "POST", {}),
        resolved_kwargs,
    ):
        if not isinstance(mapping, Mapping):
            continue
        for key in DYNAMIC_FIELD_KEYS:
            value = mapping.get(key)
            if value:
                field_names.add(str(value))

    session_key = getattr(session, "session_key", None)
    if session_key:
        for field_name in field_names:
            try:
                cached = cache.get(f"{session_key}cbv{field_name}")
            except Exception:
                cached = None
            if isinstance(cached, Mapping):
                _collect_mapping_candidates(
                    cached,
                    source=f"dynamic_cache:{field_name}",
                    results=results,
                    seen=seen,
                )

    resolved_view = view or getattr(resolver_match, "func", None)
    _view_model_candidates(resolved_view, results=results, seen=seen)

    _append_candidate(
        results,
        seen,
        resolved_model,
        source="orm-resolved",
    )
    return tuple(results)


def resolve_retired_legacy_target(
    request,
    *,
    url_kwargs: Mapping[str, Any] | None = None,
    view: Any = None,
    dynamic_cache: Any = None,
    resolved_model: Any = None,
) -> ModelResolution | None:
    """Return a retired target, preferring the final resolved ORM model."""
    retired = [
        candidate
        for candidate in resolve_model_candidates(
            request,
            url_kwargs=url_kwargs,
            view=view,
            dynamic_cache=dynamic_cache,
            resolved_model=resolved_model,
        )
        if is_retired_legacy_model_path(candidate.model_path)
    ]
    if not retired:
        return None
    for candidate in retired:
        if candidate.source == "orm-resolved":
            return candidate
    return retired[0]


def semantic_write_intent(
    request,
    *,
    surface: str,
    resolved_model: Any = None,
) -> bool:
    """Classify writes by surface semantics, not by HTTP verb alone."""
    if resolved_model is not None:
        # The database router calls this only after Django has selected a model
        # for an actual write operation. GET Kanban writes therefore remain
        # writes even though the transport verb looks read-only.
        return True

    policy = WRITE_SURFACE_REGISTRY.get(surface)
    if policy is not None:
        return bool(policy.get("semantic_write"))

    # Compatibility fallback for legacy adapters that predate the registry.
    return str(getattr(request, "method", "") or "").upper() in MUTATING_HTTP_METHODS


def infer_write_surface(request) -> str:
    """Map fixed and runtime-generated generic routes to a stable surface."""
    resolver_match = getattr(request, "resolver_match", None)
    url_name = str(getattr(resolver_match, "url_name", "") or "")
    if url_name in WRITE_SURFACE_REGISTRY:
        return url_name
    for prefix, surface in _DYNAMIC_SURFACE_PREFIXES:
        if url_name.startswith(prefix):
            return surface

    path = str(getattr(request, "path", "") or "").strip("/")
    leaf = path.rsplit("/", 1)[-1] if path else ""
    if leaf in WRITE_SURFACE_REGISTRY:
        return leaf
    for prefix, surface in _DYNAMIC_SURFACE_PREFIXES:
        if leaf.startswith(prefix):
            return surface
    return "orm-resolved-write"


def record_legacy_write_attempt(
    request,
    *,
    surface: str,
    model_path: str = "",
    model_source: str = "",
) -> None:
    """Record one blocked/redirected legacy formal-write attempt."""
    method = str(getattr(request, "method", "") or "").upper()
    path = str(getattr(request, "path", "") or "")
    logger.warning(
        "%s=1 event=%s surface=%s method=%s path=%s model=%s source=%s",
        LEGACY_WRITE_ATTEMPTS_METRIC,
        LEGACY_WRITE_ATTEMPT_EVENT,
        surface,
        method,
        path,
        model_path or "-",
        model_source or "-",
        extra={
            "event": LEGACY_WRITE_ATTEMPT_EVENT,
            "metric": LEGACY_WRITE_ATTEMPTS_METRIC,
            "metric_value": 1,
            "surface": surface,
            "http_method": method,
            "request_path": path,
            "legacy_model": model_path or "",
            "model_source": model_source or "",
        },
    )
    try:
        if not cache.add(LEGACY_WRITE_ATTEMPTS_CACHE_KEY, 1, timeout=None):
            cache.incr(LEGACY_WRITE_ATTEMPTS_CACHE_KEY)
    except Exception:  # pragma: no cover - structured log remains authoritative
        pass


def get_legacy_write_attempts_total() -> int:
    """Return the best-effort shared counter for operational checks/tests."""
    try:
        return int(cache.get(LEGACY_WRITE_ATTEMPTS_CACHE_KEY) or 0)
    except Exception:  # pragma: no cover - cache outage must not fail callers
        return 0


def legacy_formal_write_frozen_response(*, model_path: str = "") -> JsonResponse:
    """Return the stable fail-closed response for retired legacy write surfaces."""
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


def protect_retired_legacy_model_write(
    view: Callable,
    *,
    surface: str,
    block_methods: Collection[str] | None = None,
    write_methods: Collection[str] | None = None,
) -> Callable:
    """Pre-resolution guard for known generic legacy write surfaces.

    This remains the cheap outer guard. The database router below is the final
    inner guard and makes the decision again from the actual ORM model, so a
    decoy request parameter cannot bypass cutover.
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

    def guarded(request, *args, **kwargs):
        target = resolve_retired_legacy_target(
            request,
            url_kwargs=kwargs,
            view=view,
        )
        if target is None:
            return view(request, *args, **kwargs)

        method = str(getattr(request, "method", "") or "").upper()
        if blocked is not None and method not in blocked:
            return view(request, *args, **kwargs)

        should_count = (
            method in counted
            if counted is not None
            else semantic_write_intent(request, surface=surface)
        )
        if should_count:
            record_legacy_write_attempt(
                request,
                surface=surface,
                model_path=target.model_path,
                model_source=target.source,
            )
        return legacy_formal_write_frozen_response(model_path=target.model_path)

    # functools.wraps is intentionally applied after defining the closure so
    # existing URL resolver identity/module behavior stays stable.
    from functools import wraps

    return wraps(view)(guarded)


class LegacyWriteAuthorityRouter:
    """Final request-bound ORM guard for retired legacy Authorities.

    Django consults ``db_for_write`` for save/update/delete/bulk operations.
    Therefore this catches DynamicView, runtime bulk CRUD and GET Kanban writes
    even when every request-level model hint is absent, forged or non-retired.
    It intentionally activates only inside a request context so schema/data
    migrations and explicit offline reconciliation are not mistaken for an
    end-user formal writer.
    """

    def db_for_write(self, model, **hints):
        model_path = _model_path_from_value(model)
        if not is_retired_legacy_model_path(model_path):
            return None

        try:
            from horilla.horilla_middlewares import _thread_locals

            request = getattr(_thread_locals, "request", None)
        except Exception:
            request = None

        if request is None:
            return None

        surface = infer_write_surface(request)
        record_legacy_write_attempt(
            request,
            surface=surface,
            model_path=model_path,
            model_source="orm-resolved",
        )
        raise LegacyFormalWriteFrozenError(
            model_path=model_path,
            surface=surface,
            model_source="orm-resolved",
            recorded=True,
        )


class LegacyWriteAuthorityMiddleware:
    """Translate the final ORM guard into the same stable 410 contract."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, LegacyFormalWriteFrozenError):
            return None
        if not exception.recorded:
            record_legacy_write_attempt(
                request,
                surface=exception.surface,
                model_path=exception.model_path,
                model_source=exception.model_source,
            )
        return legacy_formal_write_frozen_response(
            model_path=exception.model_path
        )
