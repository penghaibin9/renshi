"""HR05 durable Excel import API.

Flow: template -> upload/stage -> validate -> durable job status/errors -> confirm.
The production API never stores jobs in process memory, so multi-worker routing
and Web restarts do not lose import state.
"""

from __future__ import annotations

import uuid

from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.excel_service import (
    ExcelImportJob,
    ExcelImportStateError,
    confirm_persisted_import,
    get_persisted_import,
    persisted_error_workbook,
    serialize_persisted_import,
    stage_persisted_import,
)


def _context(request):
    try:
        return api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


def _job_id(raw):
    try:
        return uuid.UUID(str(raw or ""))
    except (TypeError, ValueError) as exc:
        raise ExcelImportStateError("EXCEL_JOB_ID_INVALID", "job_id 无效") from exc


def _state_error(request, exc: ExcelImportStateError):
    statuses = {
        "EXCEL_JOB_NOT_FOUND": 404,
        "EXCEL_COMMIT_IN_PROGRESS": 409,
        "EXCEL_VALIDATION_FAILED": 409,
        "EXCEL_COMMIT_FAILED": 409,
        "EXCEL_JOB_STATE_INVALID": 409,
        "EXCEL_FILE_TOO_LARGE": 413,
    }
    return api_base.error(
        request,
        exc.code,
        exc.message,
        statuses.get(exc.code, 422),
        retryable=exc.code == "EXCEL_COMMIT_IN_PROGRESS",
    )


@require_GET
@require_hr05_permission("hr05.case.create")
def excel_template_download(request):
    """Download the canonical import template."""
    context = _context(request)
    if not hasattr(context, "tenant_id"):
        return context
    job = ExcelImportJob(tenant_id=context.tenant_id, uploaded_by=context.user_id or 0)
    xlsx = job.template_bytes()
    if not xlsx:
        return api_base.error(
            request, "EXCEL_DEPENDENCY_MISSING", "缺少 openpyxl 库，无法生成模板", 500
        )
    response = HttpResponse(
        xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status=200,
    )
    response["Content-Disposition"] = 'attachment; filename="hr05-import-template.xlsx"'
    response["Cache-Control"] = "no-store"
    return response


@require_POST
@require_hr05_permission("hr05.case.create")
def excel_upload(request):
    """Stage and validate an XLSX file into the durable database ledger."""
    context = _context(request)
    if not hasattr(context, "tenant_id"):
        return context
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return api_base.error(request, "EXCEL_FILE_REQUIRED", "缺少文件字段 file", 400)
    try:
        job = stage_persisted_import(
            tenant_id=context.tenant_id,
            uploaded_by=context.user_id,
            uploaded_file=uploaded,
        )
    except ExcelImportStateError as exc:
        return _state_error(request, exc)
    return api_base.ok(request, serialize_persisted_import(job), status=201)


@require_GET
@require_hr05_permission("hr05.case.create")
def excel_job_status(request, job_id):
    """Read one import job from MySQL; tenant scope is mandatory."""
    context = _context(request)
    if not hasattr(context, "tenant_id"):
        return context
    job = get_persisted_import(tenant_id=context.tenant_id, job_id=job_id)
    if job is None:
        return api_base.error(request, "EXCEL_JOB_NOT_FOUND", "导入作业不存在", 404)
    return api_base.ok(request, serialize_persisted_import(job))


@require_POST
@require_hr05_permission("hr05.case.create")
def excel_confirm(request):
    """Durably confirm a validated job; a background worker performs row commits."""
    context = _context(request)
    if not hasattr(context, "tenant_id"):
        return context
    try:
        job_id = _job_id(request.POST.get("job_id"))
        job = confirm_persisted_import(
            tenant_id=context.tenant_id,
            job_id=job_id,
            actor_user_id=context.user_id,
        )
    except ExcelImportStateError as exc:
        return _state_error(request, exc)
    return api_base.ok(request, serialize_persisted_import(job), status=202)


@require_GET
@require_hr05_permission("hr05.case.create")
def excel_error_workbook(request):
    """Rebuild the error workbook from persisted row errors."""
    context = _context(request)
    if not hasattr(context, "tenant_id"):
        return context
    try:
        job_id = _job_id(request.GET.get("job_id"))
    except ExcelImportStateError as exc:
        return _state_error(request, exc)
    job = get_persisted_import(tenant_id=context.tenant_id, job_id=job_id)
    if job is None:
        return api_base.error(request, "EXCEL_JOB_NOT_FOUND", "导入作业不存在", 404)
    if not job.error_count:
        return api_base.error(request, "EXCEL_ERRORS_NOT_FOUND", "该作业没有可下载的错误", 404)
    xlsx = persisted_error_workbook(job)
    if not xlsx:
        return api_base.error(request, "EXCEL_DEPENDENCY_MISSING", "缺少 openpyxl 库，无法生成错误表", 500)
    response = HttpResponse(
        xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status=200,
    )
    response["Content-Disposition"] = f'attachment; filename="hr05-errors-{str(job.id)[:8]}.xlsx"'
    response["Cache-Control"] = "no-store"
    return response
