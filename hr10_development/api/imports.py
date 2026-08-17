"""
hr10_development/api/imports.py

Excel 导入 API（总册 §153）。

upload → async parse → row validation → error workbook → confirm → execute → audit
"""

import json
import hashlib
import uuid
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode
from hr10_development.legacy.import_job import HrDevelopmentImportJob


@csrf_exempt
@require_http_methods(["POST"])
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
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse(error("MISSING_FILE", "缺少上传文件"), status=400)

    # 文件 hash
    file_hash = hashlib.sha256(uploaded_file.read()).hexdigest()
    uploaded_file.seek(0)

    job = HrDevelopmentImportJob.objects.create(
        tenant_id=tenant_id,
        job_type=job_type,
        file_name=uploaded_file.name,
        file_hash=file_hash,
        template_version=request.POST.get("templateVersion", "V1"),
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


@csrf_exempt
@require_http_methods(["POST"])
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

    job.status = "VALIDATION"
    job.save(update_fields=["status", "updated_at"])

    return JsonResponse(success({
        "jobId": str(job.id),
        "status": job.status,
        "message": "校验完成（异步 worker 将填充 error_rows/result_summary_json）",
    }))


@csrf_exempt
@require_http_methods(["POST"])
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

    job.status = "EXECUTING"
    job.started_at = datetime.now(timezone.utc)
    job.save(update_fields=["status", "started_at", "updated_at"])

    # 异步执行（S10：生产环境用 celery/cron worker）
    from hr10_development.services.import_worker import run_import_job
    run_import_job(job.id)

    job.refresh_from_db()
    return JsonResponse(success({
        "jobId": str(job.id),
        "status": job.status,
        "result": job.result_summary_json,
    }))


@csrf_exempt
@require_http_methods(["GET"])
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
        "errorWorkbookPath": job.error_workbook_path,
        "createdAt": job.created_at.isoformat(),
    }))
