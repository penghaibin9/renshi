"""
context_processor.py

This module is used to register context processors.
"""

from employee.models import Employee
from payroll.models import tax_models as models
from payroll.models.models import Deduction


def default_currency(request):
    """Return display currency without creating database state during rendering.

    Public pages and fresh tenants may legitimately have no PayrollSettings yet.
    A context processor must remain read-only; creating a tenant-less settings row
    during template rendering can fail and makes unrelated public recruitment pages
    depend on payroll bootstrap state.
    """
    payroll_settings = models.PayrollSettings.objects.first()
    symbol = payroll_settings.currency_symbol if payroll_settings else "$"
    position = payroll_settings.position if payroll_settings else "prefix"
    session = getattr(request, "session", None)
    if session is None:
        return {"currency": symbol, "position": position}
    return {
        "currency": session.get("currency", symbol),
        "position": session.get("position", position),
    }


def host(request):
    """Return current request host and protocol."""
    protocol = "https" if request.is_secure() else "http"
    return {"host": request.get_host(), "protocol": protocol}


def get_deductions(request):
    """Return deductions visible under employee pages."""
    deductions = Deduction.objects.filter(
        only_show_under_employee=False, employer_rate__gt=0
    )
    return {"get_deductions": deductions}


def get_active_employees(request):
    """Return active employees that already participate in payroll."""
    employees = Employee.objects.filter(
        is_active=True, contract_set__isnull=False, payslip__isnull=False
    ).distinct()
    return {"get_active_employees": employees}
