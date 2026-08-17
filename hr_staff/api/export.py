"""
hr_staff/api/export.py —— 权威导出 API（§24.4/§29.3，P1-h）。

POST /api/hr/v1/staff/export  {purpose, staffIds, fields}     创建导出（需 hr.staff.export）
GET  /api/hr/v1/staff/export/{job_id}/download?ticket=...     下载（一次性 ticket）
敏感字段（work_phone/birth_year）需 hr.staff.export_sensitive 权限。
"""

from __future__ import annotations

import json

from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.export_service import (
    ExportJobNotFound,
    ExportPolicyDenied,
    ExportService,
)

SCHEMA_EXPORT = "hr03.export.1"


def _make(request):
    try:
        return make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)


@require_POST
@require_hr_staff_permission("hr.staff.export")
def create_export(request):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        body = {}
    purpose = body.get("purpose", "")
    staff_ids = body.get("staffIds", [])
    fields = body.get("fields", [])
    has_export_sensitive = request.user.has_perm("hr.staff.export_sensitive")

    svc = ExportService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        job = svc.create_export(
            purpose=purpose,
            staff_ids=staff_ids,
            fields=fields,
            has_export_sensitive=has_export_sensitive,
        )
    except ExportPolicyDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_EXPORT
    payload["data"] = {
        "jobId": str(job.id),
        "purpose": job.purpose,
        "fields": job.fields_json,
        "totalRows": job.total_rows,
        "status": job.status,
        "downloadToken": job.download_token,
        "expiresAt": job.expires_at.isoformat(),
    }
    return json_response(request, payload, status=201)


@require_GET
def download_export(request, job_id):
    """下载导出（一次性 ticket；返回 CSV 文件）。"""
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    token = request.GET.get("ticket", "")
    svc = ExportService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        data = svc.consume_download(job_id, token)
    except ExportJobNotFound:
        return error_response(request, "EXPORT_NOT_FOUND", "导出任务不存在", status=404)
    except ExportPolicyDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)

    response = HttpResponse(data["content"], content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="hr03_export_{job_id}.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
