"""
hr_qualification/api/views_application.py —— 双师申报 API（总册 §109）。

端点：
- GET/POST  /api/v1/hr/qualifications/double-teacher/batches
- GET       /api/v1/hr/qualifications/double-teacher/batches/{id}
- POST      /api/v1/hr/qualifications/double-teacher/applications
- GET       /api/v1/hr/qualifications/double-teacher/applications/{id}
- POST      /api/v1/hr/qualifications/double-teacher/applications/{id}/precheck
- POST      /api/v1/hr/qualifications/double-teacher/applications/{id}/submit
- POST      /api/v1/hr/qualifications/double-teacher/applications/{id}/withdraw
"""

import uuid
from datetime import date

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr_qualification.api.serializers import (
    HrRecognitionBatchSerializer,
    HrDoubleTeacherApplicationSerializer,
    envelope,
    error_envelope,
)
from hr_qualification.constants import ApplicationStatus, BatchStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRule,
)
from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.evidence_service import EvidenceAggregationService
from hr_qualification.services.precheck_service import PrecheckService


# ---- Batch ----

@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def batch_list(request: HttpRequest) -> JsonResponse:
    tenant_id = int(request.GET.get("tenant_id", 1))
    status = request.GET.get("status")
    qs = HrDoubleTeacherRecognitionBatch.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    batches = list(qs.order_by("-created_at"))
    items = [{
        "id": str(b.id),
        "batch_no": b.batch_no,
        "name": b.name,
        "school_year": b.school_year,
        "application_start": b.application_start.isoformat() if b.application_start else None,
        "application_end": b.application_end.isoformat() if b.application_end else None,
        "rule_pack_version_id": str(b.rule_pack_version_id_id),
        "status": b.status,
        "target_levels": b.target_levels,
        "application_count": HrDoubleTeacherApplication.objects.filter(batch_id=b).count(),
    } for b in batches]
    return JsonResponse(envelope({"items": items}))


@csrf_exempt
@require_http_methods(["POST"])
def batch_create(request: HttpRequest) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=body["tenant_id"],
            batch_no=body["batch_no"],
            name=body["name"],
            school_year=body.get("school_year", ""),
            application_start=body.get("application_start"),
            application_end=body.get("application_end"),
            rule_pack_version_id_id=body["rule_pack_version_id"],
            eligible_scope=body.get("eligible_scope"),
            target_levels=body.get("target_levels"),
            status=BatchStatus.DRAFT,
        )
        return JsonResponse(envelope({"id": str(batch.id), "batch_no": batch.batch_no}), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
def batch_detail(request: HttpRequest, batch_id: str) -> JsonResponse:
    try:
        b = HrDoubleTeacherRecognitionBatch.objects.get(id=batch_id)
        apps = list(
            HrDoubleTeacherApplication.objects.filter(batch_id=b).order_by("-created_at")
        )
        return JsonResponse(envelope({
            "id": str(b.id),
            "batch_no": b.batch_no,
            "name": b.name,
            "status": b.status,
            "applications": [{
                "id": str(a.id),
                "application_no": a.application_no,
                "target_level": a.target_level,
                "status": a.status,
                "route": a.route,
            } for a in apps],
        }))
    except HrDoubleTeacherRecognitionBatch.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Batch not found"), status=404)


# ---- Application ----

@csrf_exempt
@require_http_methods(["POST"])
def application_create(request: HttpRequest) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        tenant_id = body["tenant_id"]

        # 生成 application_no
        count = HrDoubleTeacherApplication.objects.filter(tenant_id=tenant_id).count()
        app_no = f"APP-{tenant_id}-{count + 1:06d}"

        app = HrDoubleTeacherApplication.objects.create(
            tenant_id=tenant_id,
            application_no=app_no,
            batch_id_id=body["batch_id"],
            person_id_id=body["person_id"],
            staff_master_id_id=body.get("staff_master_id"),
            target_level=body["target_level"],
            route=body.get("route", "NORMAL"),
            applicant_statement=body.get("applicant_statement", ""),
            status=ApplicationStatus.DRAFT,
        )
        return JsonResponse(envelope({
            "id": str(app.id),
            "application_no": app.application_no,
            "status": app.status,
        }), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
def application_detail(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.select_related("batch_id").get(id=app_id)
        pkgs = list(
            HrDoubleTeacherEvidencePackage.objects
            .filter(application_id=app)
            .order_by("-generated_at")
        )
        return JsonResponse(envelope({
            "id": str(app.id),
            "application_no": app.application_no,
            "tenant_id": app.tenant_id,
            "batch_id": str(app.batch_id_id),
            "person_id": str(app.person_id_id),
            "target_level": app.target_level,
            "route": app.route,
            "status": app.status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "applicant_statement": app.applicant_statement,
            "version": app.version,
            "evidence_packages": [{"id": str(p.id), "status": p.status, "checksum": p.checksum} for p in pkgs],
        }))
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def application_precheck(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.select_related("batch_id").get(id=app_id)

        # 聚合证据 + 生成包
        agg_service = EvidenceAggregationService()
        package = agg_service.build_package(app, [])

        # 运行预检
        result = PrecheckService.precheck(app, package)
        return JsonResponse(envelope({
            "application_id": result.application_id,
            "overall": result.overall,
            "passed": result.passed,
            "failed": result.failed,
            "missing": result.missing,
            "manual_review": result.manual_review,
            "source_unavailable": result.source_unavailable,
            "items": [{
                "rule_code": i.rule_code,
                "dimension_code": i.dimension_code,
                "result": i.result,
                "detail": i.detail,
            } for i in result.items],
        }))
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["POST"])
def application_submit(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.select_related("batch_id").get(id=app_id)
        app = ApplicationService.transition(app, ApplicationStatus.SUBMITTED)
        return JsonResponse(envelope({
            "id": str(app.id),
            "status": app.status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        }))
    except ApplicationError as e:
        return JsonResponse(error_envelope("APPLICATION_ALREADY_SUBMITTED", str(e)), status=409)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def application_withdraw(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.get(id=app_id)
        app = ApplicationService.transition(app, ApplicationStatus.WITHDRAWN)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ApplicationError as e:
        return JsonResponse(error_envelope("STATUS_ERROR", str(e)), status=409)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


@csrf_exempt
def my_applications(request: HttpRequest) -> JsonResponse:
    """教职工本人申报列表。"""
    person_id = request.GET.get("person_id")
    if not person_id:
        return JsonResponse(error_envelope("MISSING_PARAM", "person_id required"), status=400)
    apps = list(
        HrDoubleTeacherApplication.objects
        .filter(person_id=person_id)
        .order_by("-created_at")
    )
    return JsonResponse(envelope({"items": [{
        "id": str(a.id),
        "application_no": a.application_no,
        "target_level": a.target_level,
        "status": a.status,
        "batch_name": a.batch_id.name if a.batch_id_id else "",
    } for a in apps]}))
