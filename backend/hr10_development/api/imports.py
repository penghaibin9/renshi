"""
hr10_development/api/imports.py

Excel 导入 API（总册 §153）。

upload → async parse → row validation → error workbook → confirm → execute → audit
"""

import json
import hashlib
from datetime import datetime, timezone

from django.core.files.storage import default_storage
from django.http import FileResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode
from hr10_development.legacy.import_job import HrDevelopmentImportJob
from hr10_development.models import HrDevelopmentAuditEvent
from hr10_development.permissions import require_hr10_permission
from hr10_development.services.import_worker import TEMPLATE_SCHEMAS


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _error_workbook_payload(job) -> dict:
    available = bool(job.error_workbook_path)
    return {
        "hasErrorWorkbook": available,
        "errorWorkbookDownloadUrl": (
            f"/api/v1/hr/development/imports/{job.id}/errors/download"
            if available
            else None
        ),
    }


def _validated_error_workbook_path(job) -> str:
    expected = f"hr10/imports/{int(job.tenant_id)}/errors/job-{job.id}.xlsx"
    actual = str(job.error_workbook_path or "")
    if actual != expected or "\\" in actual or ".." in actual.split("/"):
        raise ValueError("ERROR_WORKBOOK_STORAGE_INVALID")
    return actual


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.import.manage")
def upload_import(request):
    """
    POST /api/v1/hr/development/imports/upload

    body (multipart): file + jobType
    返回 jobId 供后续 validate/confirm。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    job_type = request.POST.get("jobType", "EXCEL_PLAN")
    if job_type not in TEMPLATE_SCHEMAS:
        return JsonResponse(error("UNSUPPORTED_JOB_TYPE", "不支持的导入类型"), status=400)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse(error("MISSING_FILE", "缺少上传文件"), status=400)
    if not uploaded_file.name.lower().endswith(".xlsx"):
        return JsonResponse(error("UNSUPPORTED_FILE_TYPE", "仅支持 .xlsx 模板"), status=400)
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        return JsonResponse(error("FILE_TOO_LARGE", "文件不能超过 10MB"), status=413)

    template_version = request.POST.get("templateVersion", "V1").upper()
    if template_version != "V1":
        return JsonResponse(error("UNSUPPORTED_TEMPLATE_VERSION", "仅支持 V1 模板"), status=400)

    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    file_hash = digest.hexdigest()
    uploaded_file.seek(0)

    idempotency_key = hashlib.sha256(
        f"{tenant_id}:{job_type}:{template_version}:{file_hash}".encode("utf-8")
    ).hexdigest()
    existing = HrDevelopmentImportJob.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return JsonResponse(success({
            "jobId": str(existing.id),
            "status": existing.status,
            "fileHash": file_hash[:16],
            "idempotentReplay": True,
        }))

    job = HrDevelopmentImportJob.objects.create(
        tenant_id=tenant_id,
        job_type=job_type,
        file_name=uploaded_file.name,
        source_file=uploaded_file,
        file_hash=file_hash,
        template_version=template_version,
        idempotency_key=idempotency_key,
        status="PENDING",
        total_rows=0,
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )

    return JsonResponse(success({
        "jobId": str(job.id),
        "status": job.status,
        "fileHash": file_hash[:16],
        "message": "上传成功，等待解析",
    }), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.import.manage")
def validate_import(request, job_id):
    """
    POST /api/v1/hr/development/imports/{jobId}/validate
    校验结果（error workbook 可下载）。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    job = HrDevelopmentImportJob.objects.filter(id=job_id, tenant_id=tenant_id).first()
    if not job:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "导入任务不存在"), status=404)

    from hr10_development.services.import_worker import run_import_job

    run_import_job(job.id)
    job.refresh_from_db()

    if job.status == "FAILED":
        return JsonResponse(
            error("IMPORT_PARSE_FAILED", job.result_summary_json.get("error", "导入解析失败")),
            status=422,
        )
    return JsonResponse(success({
        "jobId": str(job.id),
        "status": job.status,
        "errorRows": job.error_rows,
        **_error_workbook_payload(job),
        "result": job.result_summary_json,
    }))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.import.manage")
def confirm_import(request, job_id):
    """
    POST /api/v1/hr/development/imports/{jobId}/confirm
    显式确认后执行导入。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    if not body.get("confirmed"):
        return JsonResponse(error("CONFIRM_REQUIRED", "必须显式确认"), status=400)

    job = HrDevelopmentImportJob.objects.filter(id=job_id, tenant_id=tenant_id).first()
    if not job:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "导入任务不存在"), status=404)

    if job.status != "PREVIEW":
        return JsonResponse(error("IMPORT_NOT_READY", "必须先完成校验并进入 PREVIEW"), status=409)
    if job.error_rows:
        return JsonResponse(error("IMPORT_HAS_ERRORS", "请修复错误行后重新上传"), status=409)

    job.status = "SUCCESS"
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = datetime.now(timezone.utc)
    job.result_summary_json = {
        **job.result_summary_json,
        "confirmed": True,
        "confirmedAt": job.completed_at.isoformat(),
    }
    job.save(update_fields=["status", "started_at", "completed_at", "result_summary_json", "updated_at"])

    job.refresh_from_db()
    return JsonResponse(success({
        "jobId": str(job.id),
        "status": job.status,
        "result": job.result_summary_json,
    }))


@require_http_methods(["GET"])
@require_hr10_permission("hr.development.import.manage")
def get_import_status(request, job_id):
    """GET /api/v1/hr/development/imports/{jobId}"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    job = HrDevelopmentImportJob.objects.filter(id=job_id, tenant_id=tenant_id).first()
    if not job:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "导入任务不存在"), status=404)
    return JsonResponse(success({
        "jobId": str(job.id),
        "jobType": job.job_type,
        "status": job.status,
        "totalRows": job.total_rows,
        "processedRows": job.processed_rows,
        "errorRows": job.error_rows,
        "warningRows": job.warning_rows,
        "resultSummaryJson": job.result_summary_json,
        **_error_workbook_payload(job),
        "createdAt": job.created_at.isoformat(),
    }))


@require_http_methods(["GET"])
@require_hr10_permission("hr.development.import.manage")
def download_error_workbook(request, job_id):
    """Tenant-scoped, audited download without exposing the storage key."""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )
    purpose = str(request.headers.get("X-HR-Access-Reason", "") or "").strip()
    if not purpose:
        return JsonResponse(
            error("DOWNLOAD_PURPOSE_REQUIRED", "请填写下载错误工作簿的用途"),
            status=400,
        )
    job = HrDevelopmentImportJob.objects.filter(
        id=job_id, tenant_id=tenant_id
    ).first()
    if not job:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "导入任务不存在"), status=404
        )
    try:
        storage_path = _validated_error_workbook_path(job)
    except ValueError:
        return JsonResponse(
            error("ERROR_WORKBOOK_STORAGE_INVALID", "错误工作簿存储位置无效"),
            status=500,
        )
    if not default_storage.exists(storage_path):
        return JsonResponse(
            error("ERROR_WORKBOOK_NOT_FOUND", "错误工作簿不存在"), status=404
        )

    stream = default_storage.open(storage_path, "rb")
    try:
        HrDevelopmentAuditEvent.objects.create(
            tenant_id=tenant_id,
            actor_id_id=request.user.id,
            object_type="HrDevelopmentImportJob",
            object_id=str(job.id),
            action="ImportErrorWorkbookDownloaded",
            reason=purpose[:1000],
            request_id=str(
                getattr(request, "request_id", "")
                or request.headers.get("X-Request-ID", "")
            )[:64],
        )
    except Exception:
        stream.close()
        return JsonResponse(
            error("AUDIT_WRITE_FAILED", "下载审计写入失败"), status=500
        )

    response = FileResponse(
        stream,
        as_attachment=True,
        filename=f"教师发展导入错误-{job.id}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response
