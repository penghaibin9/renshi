"""
hr_staff/api/imports.py —— 权威导入 API（§24，P1-i）。

POST /api/hr/v1/staff/import                     上传受限 CSV → staging → 校验预览
POST /api/hr/v1/staff/import/{job_id}/commit      显式提交有效行（逐行原子）
GET  /api/hr/v1/staff/import/{job_id}             导入进度/结果
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.constants import RelationshipType, StaffCategoryCode
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.import_service import (
    ImportService,
    ImportStateConflict,
    StaffMasterRowApplier,
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
    filename = (file.name or "").replace("\\", "/").rsplit("/", 1)[-1][:255]
    if not filename.lower().endswith(".csv"):
        return error_response(request, "INVALID_REQUEST", "仅支持 CSV 文件", status=400)
    if getattr(file, "size", 0) > MAX_IMPORT_BYTES:
        return error_response(
            request,
            "INVALID_REQUEST",
            f"文件不能超过 {MAX_IMPORT_BYTES // 1024 // 1024} MB",
            status=400,
        )

    raw = file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        return error_response(request, "INVALID_REQUEST", "上传文件过大", status=400)
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return error_response(request, "INVALID_REQUEST", "文件编码必须是 UTF-8", status=400)

    reader = csv.DictReader(io.StringIO(content))
    fieldnames = [str(name or "").strip() for name in (reader.fieldnames or [])]
    if not fieldnames:
        return error_response(request, "INVALID_REQUEST", "CSV 缺少表头", status=400)
    if len(fieldnames) != len(set(fieldnames)):
        return error_response(request, "INVALID_REQUEST", "CSV 存在重复列名", status=400)
    unknown = [name for name in fieldnames if name not in EXPECTED_COLUMNS]
    if unknown:
        return error_response(
            request,
            "INVALID_REQUEST",
            "CSV 含未支持列：" + ",".join(unknown[:10]),
            status=400,
        )
    if "legal_name" not in fieldnames:
        return error_response(
            request,
            "INVALID_REQUEST",
            f"CSV 必须包含 legal_name 列（支持列：{','.join(EXPECTED_COLUMNS)}）",
            status=400,
        )

    rows = []
    for row in reader:
        if len(rows) >= MAX_IMPORT_ROWS:
            return error_response(
                request,
                "INVALID_REQUEST",
                f"单次导入最多 {MAX_IMPORT_ROWS} 行",
                status=400,
            )
        # DictReader 在多余列时会产生 None key；前面的表头白名单不足以覆盖
        # 行内列数错误，因此这里继续 fail-closed。
        if None in row:
            return error_response(request, "INVALID_REQUEST", "CSV 行列数与表头不一致", status=400)
        rows.append({key: (value or "").strip() for key, value in row.items()})
    if not rows:
        return error_response(request, "INVALID_REQUEST", "CSV 为空", status=400)

    svc = ImportService(resp.tenant_id, actor_user_id=request.user.id)
    job = svc.create_job(template_key="staff_master", original_filename=filename)
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
        "committedBy": job.committed_by,
        "committedAt": job.committed_at.isoformat() if job.committed_at else None,
        "issues": [
            {"rowNo": issue.row_no, "field": issue.field_code, "error": issue.message}
            for issue in job.issues.all()[:50]
        ],
    }
    return json_response(request, payload)


def _validate_row(row: dict) -> dict:
    errors = {}
    legal_name = (row.get("legal_name") or "").strip()
    if not legal_name:
        errors["legal_name"] = "必填"
    elif len(legal_name) > 200:
        errors["legal_name"] = "不能超过 200 个字符"

    staff_no = (row.get("staff_no") or "").strip()
    if len(staff_no) > 64:
        errors["staff_no"] = "不能超过 64 个字符"

    gender = (row.get("gender_code") or "").strip()
    if gender and gender not in {"M", "F", "O", "U"}:
        errors["gender_code"] = "只允许 M/F/O/U"

    category = (row.get("staff_category_code") or "TEACHER").strip()
    if category not in {code for code, _ in StaffCategoryCode.choices}:
        errors["staff_category_code"] = "人员类别代码无效"

    relationship = (row.get("relationship_type") or "REGULAR_EMPLOYMENT").strip()
    if relationship not in {code for code, _ in RelationshipType.choices}:
        errors["relationship_type"] = "聘用关系代码无效"

    for key in ("birth_date", "effective_from"):
        value = (row.get(key) or "").strip()
        if value and not _is_supported_date(value):
            errors[key] = "日期格式应为 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY"

    legacy_department_id = (row.get("legacy_department_id") or "").strip()
    if legacy_department_id:
        try:
            if int(legacy_department_id) <= 0:
                raise ValueError
        except ValueError:
            errors["legacy_department_id"] = "必须是正整数"
    return errors


def _is_supported_date(value: str) -> bool:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False
