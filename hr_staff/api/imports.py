"""
hr_staff/api/imports.py —— 权威导入 API（§24，P1-i）。

POST /api/hr/v1/staff/import                     上传 CSV → staging（parse+validate）→ 返回预览
POST /api/hr/v1/staff/import/{job_id}/commit      异步 commit（真实 StaffMasterRowApplier）
GET  /api/hr/v1/staff/import/{job_id}             导入进度/结果
"""

from __future__ import annotations

import csv
import io
import json

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.import_service import (
    ImportService,
    StaffMasterRowApplier,
)

SCHEMA_IMPORT = "hr03.import.1"

EXPECTED_COLUMNS = [
    "staff_no",
    "legal_name",
    "gender_code",
    "birth_date",
    "document_number",
    "staff_category_code",
    "relationship_type",
    "effective_from",
    "legacy_department_id",
]


def _make(request):
    try:
        return make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)


@require_POST
@require_hr_staff_permission("hr.staff.import")
def upload_import(request):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    file = request.FILES.get("file")
    if file is None:
        return error_response(request, "INVALID_REQUEST", "缺少上传文件", status=400)
    if not file.name.lower().endswith(".csv"):
        return error_response(request, "INVALID_REQUEST", "仅支持 CSV 文件", status=400)

    try:
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return error_response(request, "INVALID_REQUEST", "文件编码必须是 UTF-8", status=400)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return error_response(request, "INVALID_REQUEST", "CSV 为空", status=400)

    # 列名校验：要求至少包含 legal_name
    if "legal_name" not in reader.fieldnames:
        return error_response(
            request, "INVALID_REQUEST", f"CSV 必须包含 legal_name 列（支持列：{','.join(EXPECTED_COLUMNS)}）", status=400
        )

    svc = ImportService(resp.tenant_id, actor_user_id=request.user.id)
    job = svc.create_job(template_key="staff_master", original_filename=file.name)
    svc.parse_rows(job, rows)
    svc.validate_rows(job, row_validator=_validate_row)

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_IMPORT
    payload["data"] = {
        "jobId": str(job.id),
        "templateKey": job.template_key,
        "totalRows": job.total_rows,
        "validRows": job.valid_rows,
        "failedRows": job.failed_rows,
        "status": job.status,
        "issues": [
            {"rowNo": i.row_no, "field": i.field_code, "error": i.message}
            for i in job.issues.all()[:50]
        ],
    }
    return json_response(request, payload, status=201)


@require_POST
@require_hr_staff_permission("hr.staff.import")
def commit_import(request, job_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    svc = ImportService(resp.tenant_id, actor_user_id=request.user.id)
    job = svc.job_for_id(job_id)
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在", status=404)
    applier = StaffMasterRowApplier(resp.tenant_id, actor_user_id=request.user.id)
    result = svc.commit(job, applier)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_IMPORT
    payload["data"] = result
    return json_response(request, payload)


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_status(request, job_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    from hr_staff.models import HrImportJob

    job = HrImportJob.objects.filter(tenant_id=resp.tenant_id, id=job_id).first()
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_IMPORT
    payload["data"] = {
        "jobId": str(job.id),
        "status": job.status,
        "totalRows": job.total_rows,
        "validRows": job.valid_rows,
        "failedRows": job.failed_rows,
        "committedBy": job.committed_by,
        "committedAt": job.committed_at.isoformat() if job.committed_at else None,
    }
    return json_response(request, payload)


def _validate_row(row: dict) -> dict:
    errors = {}
    if not (row.get("legal_name") or "").strip():
        errors["legal_name"] = "必填"
    return errors