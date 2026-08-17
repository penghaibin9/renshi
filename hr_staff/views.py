"""
hr_staff/views.py —— HR03 页面 views（S4/S5 落地）。

- /hr/staff/             HR03-01 教职工名册（服务端壳 + fetch 局部加载）
- /hr/staff/{staff_id}   HR03-02 教职工主档
- /hr/staff/{staff_id}/assignments   任职履历（S6 页面壳，数据走 API）
"""

from __future__ import annotations

import uuid

from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from hr_staff.api.base import make_staff_context
from hr_staff.context import HrStaffContextError


def _context_or_403(request):
    try:
        return make_staff_context(request), None
    except HrStaffContextError as exc:
        return None, exc


@ensure_csrf_cookie
def staff_list(request):
    """HR03-01 教职工名册（S4）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(
            request,
            "hr_staff/error.html",
            {"error_code": exc.code, "error_message": exc.message},
            status=403,
        )
    return render(
        request,
        "hr_staff/staff_list.html",
        {
            "tenant_id": context.tenant_id,
            "authority_mode": context.authority_mode,
        },
    )


@ensure_csrf_cookie
def staff_profile(request, staff_id):
    """HR03-02 教职工主档（S5）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(
            request,
            "hr_staff/error.html",
            {"error_code": exc.code, "error_message": exc.message},
            status=403,
        )
    return render(
        request,
        "hr_staff/profile.html",
        {
            "staff_id": str(staff_id),
            "as_of": context.as_of.isoformat() if context.as_of else "",
            "tenant_id": context.tenant_id,
        },
    )


@ensure_csrf_cookie
def assignment_history(request, staff_id):
    """HR03-03 任职与身份履历（S6 页面壳，数据走 /assignments API）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(
            request,
            "hr_staff/error.html",
            {"error_code": exc.code, "error_message": exc.message},
            status=403,
        )
    return render(
        request,
        "hr_staff/assignment_history.html",
        {"staff_id": str(staff_id), "as_of": context.as_of.isoformat()},
    )


@ensure_csrf_cookie
def background_facts(request, staff_id):
    """HR03-04 教育资格履历（S7）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(request, "hr_staff/error.html", {"error_code": exc.code, "error_message": exc.message}, status=403)
    return render(request, "hr_staff/background_facts.html", {"staff_id": str(staff_id)})


@ensure_csrf_cookie
def materials(request, staff_id):
    """HR03-05 人事材料档案（S8）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(request, "hr_staff/error.html", {"error_code": exc.code, "error_message": exc.message}, status=403)
    return render(request, "hr_staff/materials.html", {"staff_id": str(staff_id)})


@ensure_csrf_cookie
def corrections(request, staff_id):
    """HR03-06 信息更正与历史（S9）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(request, "hr_staff/error.html", {"error_code": exc.code, "error_message": exc.message}, status=403)
    return render(request, "hr_staff/corrections.html", {"staff_id": str(staff_id)})


@ensure_csrf_cookie
def data_quality(request):
    """数据质量异常中心（§34）。"""
    context, exc = _context_or_403(request)
    if exc:
        return render(request, "hr_staff/error.html", {"error_code": exc.code, "error_message": exc.message}, status=403)
    return render(request, "hr_staff/data_quality.html", {"tenant_id": context.tenant_id})
