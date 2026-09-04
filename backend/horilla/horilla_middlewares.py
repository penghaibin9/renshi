"""
horilla_middlewares.py

Shared request + tenant context primitives.

The HR takeover treats a school/company as the tenant root. Web requests set
it in CompanyMiddleware; background jobs/providers must use tenant_context().
No tenant context is a valid state, but tenant-aware managers must fail closed.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseNotAllowed
from django.shortcuts import render

from horilla.config import logger

_request_var = ContextVar("request", default=None)
current_company_id = ContextVar("current_company_id", default=None)
_thread_local_state = ContextVar("thread_local_state", default=None)


class _ThreadLocalProxy:
    def __getattr__(self, name):
        if name == "request":
            return _request_var.get()
        state = _thread_local_state.get() or {}
        if name in state:
            return state[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "request":
            _request_var.set(value)
        else:
            state = dict(_thread_local_state.get() or {})
            state[name] = value
            _thread_local_state.set(state)


_thread_locals = _ThreadLocalProxy()


class ThreadLocalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_token = _request_var.set(request)
        try:
            return self.get_response(request)
        finally:
            _request_var.reset(request_token)


class MethodNotAllowedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if isinstance(response, HttpResponseNotAllowed):
            return render(request, "405.html", status=405)
        return response


class SVGSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith(".svg") and response.status_code == 200:
            response["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline';"
            )
            response["X-Content-Type-Options"] = "nosniff"
        return response


class MissingParameterMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, KeyError):
            missing_key = str(exception).strip("'")
            message = f"Required parameter '{missing_key}' is missing from the request."
            logger.error(message)
            if not settings.DEBUG:
                messages.error(request, message)
                return render(request, "went_wrong.html", status=400)
        return None


def set_selected_company(company_id):
    """Set the current tenant id and mirror concrete web scope onto the request."""
    token = current_company_id.set(company_id)

    # CompanyMiddleware owns the canonical browser tenant decision. A number of
    # HR APIs intentionally read request.tenant_id so that they can fail closed
    # when no concrete school is selected. Keep that compatibility surface in
    # sync with the canonical context rather than forcing each HR module to
    # invent its own session lookup. The explicit ``all`` scope must never turn
    # into a cross-tenant API id, so mirror it as None.
    request = _request_var.get()
    if request is not None:
        request.tenant_id = None if company_id in (None, "", "all") else int(company_id)
    return token


def get_selected_company():
    """Return the current tenant id, ``all`` for an explicitly scoped union, or None."""
    return current_company_id.get()


def tenant_fail_closed_enabled():
    return bool(getattr(settings, "TENANT_FAIL_CLOSED", True))


def require_selected_company(*, allow_all=False):
    """
    Return the explicit tenant id or raise.

    Use at command/provider/job boundaries so missing tenant propagation cannot
    silently turn into a cross-school operation.
    """
    company_id = get_selected_company()
    if company_id is None or (company_id == "all" and not allow_all):
        raise ImproperlyConfigured(
            "Tenant context is required for this operation. "
            "Web requests must pass CompanyMiddleware; background work must use tenant_context(company_id)."
        )
    return company_id


@contextmanager
def tenant_context(company_id):
    """
    Explicit tenant scope for jobs, providers, commands and integration tests.

    The previous request and company contexts are restored even on failure,
    preventing tenant bleed between worker jobs.
    """
    if company_id in (None, "", "all"):
        raise ValueError("tenant_context requires one concrete company id")
    company_token = current_company_id.set(company_id)
    request_token = _request_var.set(None)
    try:
        yield company_id
    finally:
        _request_var.reset(request_token)
        current_company_id.reset(company_token)
