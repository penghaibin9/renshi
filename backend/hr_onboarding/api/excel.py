"""
hr_onboarding/api/excel.py

Excel 导入 API（总册 §42 · V1 最小实现）：
- GET  /template → 下载空白模板
- POST /upload → 上传 → staging → 校验 → error workbook / ready
- POST /confirm → 异步执行（幂等逐行建 case）
"""

from __future__ import annotations

from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.excel_service import ExcelImportJob

# In-memory job registry（生产应落库或 cache；V1 最小实现会话期内有效）
_jobs: dict[str, ExcelImportJob] = {}


@require_GET
@require_hr05_permission("hr05.case.create")
def excel_template_download(request):
    """下载空白导入模板。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    job = ExcelImportJob(tenant_id=context.tenant_id, uploaded_by=context.user_id or 0)
    xlsx = job.template_bytes()
    if not xlsx:
        return api_base.error(request, "EXCEL_DEPENDENCY_MISSING", "缺少 openpyxl 库，无法生成模板", 500)
    response = HttpResponse(
        xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status=200,
    )
    response["Content-Disposition"] = 'attachment; filename="hr05-import-template.xlsx"'
    return response


@require_POST
@require_hr05_permission("hr05.case.create")
def excel_upload(request):
    """上传 Excel 并校验。返回 job_id + 校验结果/error workbook。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise Hr05ApiError("缺少文件字段 file")

    job = ExcelImportJob(tenant_id=context.tenant_id, uploaded_by=context.user_id or 0)
    count = job.parse(uploaded)
    ok = job.validate()

    _jobs[job.job_id] = job
    if ok:
        return api_base.ok(request, {
            "job_id": job.job_id,
            "rows": count,
            "status": job.status,
            "errors": 0,
        })
    else:
        error_xlsx = job.error_workbook()
        return api_base.ok(request, {
            "job_id": job.job_id,
            "rows": count,
            "status": job.status,
            "errors": len(job.errors),
            "error_workbook_available": True,
        })


@require_POST
@require_hr05_permission("hr05.case.create")
def excel_confirm(request):
    """确认执行导入（幂等逐行建 case，不绕过 Activation Service）。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    job_id = request.POST.get("job_id")
    if not job_id or job_id not in _jobs:
        raise Hr05ApiError("job_id 无效或不存在")

    job = _jobs[job_id]
    result = job.commit_async()
    return api_base.ok(request, {
        "job_id": job_id,
        "status": job.status,
        "created": result["created"],
        "skipped": result["skipped"],
        "errors": len(result["errors"]),
    })


@require_GET
@require_hr05_permission("hr05.case.create")
def excel_error_workbook(request):
    """下载校验错误工作簿。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    job_id = request.GET.get("job_id")
    if not job_id or job_id not in _jobs:
        raise Hr05ApiError("job_id 无效或不存在")

    job = _jobs[job_id]
    xlsx = job.error_workbook()
    if not xlsx:
        return api_base.error(request, "NO_ERRORS", "无校验错误", 404)
    response = HttpResponse(
        xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status=200,
    )
    response["Content-Disposition"] = f'attachment; filename="hr05-errors-{job_id[:8]}.xlsx"'
    return response
