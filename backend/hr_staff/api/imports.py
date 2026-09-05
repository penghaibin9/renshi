"""HR03 imports: bounded XLSX/CSV -> encrypted staging -> explicit row commit.

Public import URLs are retained. Only confirmed HR02 codes identify placement;
no tenant ID, raw ORM ID or legacy department field selects another authority.
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import api_root, error_response, json_response, make_staff_context
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.import_service import ImportService, ImportStateConflict, StaffMasterRowApplier
from hr_staff.services.import_validation import StaffImportValidator, basic_errors, parse_date
from hr_staff.services.import_workbook import (
    COLUMNS, MAX_IMPORT_BYTES, ImportFileError,
    error_workbook, parse_upload, template_workbook,
)

SCHEMA_IMPORT = "hr03.import.2"
EXPECTED_COLUMNS = list(COLUMNS)


def _make(request):
    try:
        context = make_staff_context(request)
        if not request.user.is_active or context.scope.scope_type != "SCHOOL":
            raise HrStaffContextError("SCOPE_NOT_ALLOWED", "批量建档需要明确的学校级导入授权")
        return context
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=exc.status)


def _owned_job(service, job_id):
    job = service.job_for_id(job_id)
    if job is None:
        return None
    # New transport jobs are uploader-bound. Existing jobs without this marker
    # retain the old permission-only behavior; no new job may omit the marker.
    owner = (job.checkpoint or {}).get("upload_actor_user_id")
    if owner is not None and owner != service.actor_user_id:
        return None
    return job


def _summary(job):
    # Only a stale executor lease is recoverable. This is UI guidance, not an
    # authorization token: commit() rechecks the live lease under its job lock.
    can_resume = job.status == "COMMITTING" and ImportService._commit_lease_is_stale(
        job, dict(job.checkpoint or {}), timezone.now()
    )
    return {
        "jobId": str(job.pk), "templateKey": job.template_key, "status": job.status,
        "totalRows": job.total_rows, "validRows": job.valid_rows, "failedRows": job.failed_rows,
        "canResume": can_resume,
        "pendingRows": job.rows.filter(tenant_id=job.tenant_id, is_valid=True, commit_status="PENDING").count(),
        "committedRows": job.rows.filter(tenant_id=job.tenant_id, commit_status="COMMITTED").count(),
        "committedBy": job.committed_by,
        "committedAt": job.committed_at.isoformat() if job.committed_at else None,
        "issueCount": job.issues.filter(tenant_id=job.tenant_id).count(),
        "issues": [{"rowNo": issue.row_no, "field": issue.field_code, "error": issue.message}
                   for issue in job.issues.filter(tenant_id=job.tenant_id).order_by("row_no", "field_code")[:50]],
        "resultRows": [{"rowNo": row.row_no, "staffId": row.data_json.get("_result_staff_id")}
                       for row in job.rows.filter(tenant_id=job.tenant_id, commit_status="COMMITTED").order_by("row_no")[:50]],
    }


def _download(content, filename):
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_template(request):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    refs = []
    if all(request.user.has_perm(code) for code in ("hr.structure.organization.view", "hr.structure.position.view")):
        from django.db.models import Q
        from hr_structure.models import HrPosition, HrOrganizationVersion
        positions = HrPosition.objects.filter(tenant_id=context.tenant_id, lifecycle_status="ACTIVE",
            organization_id__tenant_id=context.tenant_id, post_catalog_version_id__tenant_id=context.tenant_id,
            validity_from__lte=context.today()).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=context.today()))
        positions = list(positions.select_related("organization_id", "post_catalog_version_id").order_by("position_code")[:2000])
        names, ambiguous = {}, set()
        versions = HrOrganizationVersion.objects.filter(
            tenant_id=context.tenant_id, organization_id_id__in={p.organization_id_id for p in positions},
            status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"), validity_from__lte=context.today()
        ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=context.today()))
        for version in versions:
            if version.organization_id_id in names:
                ambiguous.add(version.organization_id_id)
            names[version.organization_id_id] = version.name
        for position in positions:
            org_id = position.organization_id_id
            if org_id in names and org_id not in ambiguous:
                refs.append((position.organization_id.stable_code, names[org_id], position.position_code,
                             position.post_catalog_version_id.name, context.today().isoformat()))
    return _download(template_workbook(refs), "hr03_staff_import_template.xlsx")


@require_POST
@require_hr_staff_permission("hr.staff.import")
def upload_import(request):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    upload = request.FILES.get("file")
    if upload is None:
        return error_response(request, "INVALID_REQUEST", "缺少上传文件", status=400)
    filename = (upload.name or "").replace("\\", "/").rsplit("/", 1)[-1][:255]
    if getattr(upload, "size", 0) > MAX_IMPORT_BYTES:
        return error_response(request, "INVALID_REQUEST", "文件不能超过 5 MB", status=400)
    raw = upload.read(MAX_IMPORT_BYTES + 1)
    try:
        rows = parse_upload(raw, filename)
    except ImportFileError as exc:
        return error_response(request, "INVALID_REQUEST", str(exc), status=400)
    service = ImportService(context.tenant_id, actor_user_id=request.user.pk)
    validator = StaffImportValidator(context.tenant_id, rows, today=context.today())
    with transaction.atomic():
        job = service.create_job(template_key="staff_master_hr02", original_filename=filename)
        job.checkpoint = {"upload_actor_user_id": request.user.pk, "upload_sha256": hashlib.sha256(raw).hexdigest(),
                          "schema": SCHEMA_IMPORT, "uploaded_at": timezone.now().isoformat()}
        job.save(update_fields=["checkpoint"])
        service.parse_rows(job, rows)
        service.validate_rows(job, row_validator=validator, row_enricher=validator.enrich)
        write_audit_event(tenant_id=context.tenant_id, actor_user_id=request.user.pk,
                         action="StaffImportValidated", business_type="STAFF_IMPORT", business_id=str(job.pk),
                         reason=f"total={job.total_rows} valid={job.valid_rows} failed={job.failed_rows}")
    return json_response(request, {**api_root(request), "schemaVersion": SCHEMA_IMPORT, "data": _summary(job)}, status=201)


@require_POST
@require_hr_staff_permission("hr.staff.import")
def commit_import(request, job_id):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    service = ImportService(context.tenant_id, actor_user_id=request.user.pk)
    job = _owned_job(service, job_id)
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在或不属于当前账号", status=404)
    try:
        result = service.commit(job, StaffMasterRowApplier(context.tenant_id, actor_user_id=request.user.pk, today=context.today()))
    except ImportStateConflict as exc:
        return error_response(request, exc.code, str(exc), status=409)
    job.refresh_from_db()
    return json_response(request, {**api_root(request), "schemaVersion": SCHEMA_IMPORT,
                                   "data": {**result, **_summary(job)}})


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_status(request, job_id):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    job = _owned_job(ImportService(context.tenant_id, actor_user_id=request.user.pk), job_id)
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在或不属于当前账号", status=404)
    return json_response(request, {**api_root(request), "schemaVersion": SCHEMA_IMPORT, "data": _summary(job)})


@require_GET
@require_hr_staff_permission("hr.staff.import")
def import_errors(request, job_id):
    context = _make(request)
    if not hasattr(context, "tenant_id"):
        return context
    job = _owned_job(ImportService(context.tenant_id, actor_user_id=request.user.pk), job_id)
    if job is None:
        return error_response(request, "IMPORT_NOT_FOUND", "导入任务不存在或不属于当前账号", status=404)
    issues = list(job.issues.filter(tenant_id=context.tenant_id).order_by("row_no", "field_code").values_list(
        "row_no", "field_code", "error_code", "message"))
    content = error_workbook(issues)
    write_audit_event(tenant_id=context.tenant_id, actor_user_id=request.user.pk, action="StaffImportIssuesDownloaded",
                     business_type="STAFF_IMPORT", business_id=str(job.pk), reason=f"issues={len(issues)}")
    return _download(content, f"hr03_import_errors_{job.pk}.xlsx")


def _validate_row(row):
    return basic_errors(row)


def _is_supported_date(value):
    return parse_date(value) is not None
