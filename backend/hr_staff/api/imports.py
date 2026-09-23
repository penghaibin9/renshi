"""
hr_staff/api/imports.py —— 权威导入 API（§24，P1-i）。

POST /api/hr/v1/staff/import                     上传受限 XLSX/CSV → staging → 校验预览
POST /api/hr/v1/staff/import/{job_id}/commit      显式提交有效行（逐行原子）
GET  /api/hr/v1/staff/import/{job_id}             导入进度/结果
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from django.db import transaction
from django.http import FileResponse, HttpResponse
from hr_staff.import_tabular import read_import_rows, TabularError, COLUMNS
from hr_staff.services.audit_service import write_audit_event

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.constants import StaffScopeType
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.import_service import (
    ImportService,
    ImportStateConflict,
    StaffMasterRowApplier,
)
from hr_staff.services.import_validation import (
    VALUE_ALIASES,
    build_staff_import_row_validator,
    is_supported_import_date,
    validate_staff_import_fields,
)

SCHEMA_IMPORT = "hr03.import.1"
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000

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
        context = make_staff_context(request)
        if context.scope.scope_type != StaffScopeType.SCHOOL:
            return error_response(request, "SCOPE_NOT_ALLOWED", "批量开户导入需由本校具备全校数据范围的授权人事管理员操作", status=403)
        return context
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
        return error_response(request, "INVALID_REQUEST", "请选择 Excel 或 CSV 文件", status=400)
    filename = (file.name or "").replace("\\", "/").rsplit("/", 1)[-1][:255]
    if getattr(file, "size", 0) > MAX_IMPORT_BYTES:
        return error_response(request, "INVALID_REQUEST", "文件不能超过 5 MB", status=400)
    try:
        rows = read_import_rows(file.read(MAX_IMPORT_BYTES + 1), filename)
    except TabularError as exc:
        return error_response(request, "INVALID_REQUEST", str(exc), status=400)
    validator = build_row_validator(resp.tenant_id, rows)
    svc = ImportService(resp.tenant_id, actor_user_id=request.user.id)
    # Parse and preview are one transaction; no orphaned half-preview jobs.
    with transaction.atomic():
        job = svc.create_job(template_key="staff_master", original_filename=filename)
        svc.parse_rows(job, rows)
        svc.validate_rows(job, row_validator=validator)
        write_audit_event(tenant_id=resp.tenant_id, action="IMPORT_PREVIEW",
            actor_user_id=request.user.id, business_type="HR03_IMPORT", business_id=str(job.id), source="HR03")

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
            {"rowNo": issue.row_no, "field": issue.field_code, "error": issue.message}
            for issue in job.issues.all()[:50]
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
    try:
        result = svc.commit(job, applier)
    except ImportStateConflict as exc:
        return error_response(request, exc.code, str(exc), status=409)
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
        **ImportService._result_for_job(job),
        "committedBy": job.committed_by,
        "committedAt": job.committed_at.isoformat() if job.committed_at else None,
        "issues": [
            {"rowNo": issue.row_no, "field": issue.field_code, "error": issue.message}
            for issue in job.issues.all()[:50]
        ],
    }
    return json_response(request, payload)


def _validate_row(row: dict) -> dict:
    """Backward-compatible wrapper around the canonical shared validator."""
    return validate_staff_import_fields(row)


def _is_supported_date(value: str) -> bool:
    return is_supported_import_date(value)


def build_row_validator(tenant_id, rows):
    """Preview and commit share the same canonical business validation module."""
    return build_staff_import_row_validator(tenant_id, rows)


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_template(request):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    path = Path(__file__).resolve().parents[1] / "resources" / "staff_import_template.xlsx"
    response = FileResponse(path.open("rb"), as_attachment=True, filename="HR03_staff_import_template.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_errors(request, job_id):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    svc = ImportService(context.tenant_id, request.user.id)
    job = svc.job_for_id(job_id)
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在", status=404)
    # Never export raw source rows under import permission: no name, ID, birth
    # date or hidden personal columns. Physical row numbers locate the source.
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["原文件行号", "字段", "错误原因", "错误代码"])
    for issue in job.issues.filter(tenant_id=context.tenant_id).order_by("row_no", "field_code").iterator():
        writer.writerow([issue.row_no, safe_csv_cell(COLUMNS.get(issue.field_code, "整行")),
                         safe_csv_cell(issue.message), safe_csv_cell(issue.error_code)])
    write_audit_event(tenant_id=context.tenant_id, action="IMPORT_ERRORS_DOWNLOAD",
        actor_user_id=request.user.id, business_type="HR03_IMPORT", business_id=str(job.id), source="HR03")
    response = HttpResponse("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="HR03_import_errors_{job.id}.csv"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def safe_csv_cell(value):
    value = str(value or "")
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_receipt(request, job_id):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    from hr_staff.models import HrImportJob
    from hr_staff.services.import_receipt_service import migration_receipt, receipt_workbook, ImportReceiptLimit
    try:
        receipt = migration_receipt(tenant_id=context.tenant_id, job_id=job_id)
    except HrImportJob.DoesNotExist:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在", status=404)
    except ImportReceiptLimit:
        return error_response(request, "IMPORT_RECEIPT_LIMIT", "历史导入超出单次核对范围，请联系管理员分批核对", status=409)
    if request.GET.get("format") == "xlsx":
        content = receipt_workbook(receipt, receipt["errorRows"])
        write_audit_event(tenant_id=context.tenant_id, action="IMPORT_RECEIPT_DOWNLOAD", actor_user_id=request.user.id,
            business_type="HR03_IMPORT", business_id=str(job_id), source="HR03", reason="仅导出行号、状态与核对原因，不含原始人员字段")
        response = HttpResponse(content,content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="HR03_migration_receipt_{job_id}.xlsx"'
    else:
        payload = api_root(request); payload["schemaVersion"] = receipt["schemaVersion"]; payload["data"] = receipt
        response = json_response(request, payload)
    response["Cache-Control"] = "no-store"; response["X-Content-Type-Options"] = "nosniff"
    return response
