"""HR09 双师认定批次与申报 API。

Tenant is always the selected school. SELF application endpoints derive the
applicant from the authenticated HR03 mapping and never trust person_id from
query/body input.
"""

import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr_qualification.api.access import (
    QualificationAccessError,
    access_error_response,
    api_guard,
    current_person_id_or_raise,
)
from hr_qualification.api.serializers import envelope, error_envelope
from hr_qualification.constants import ApplicationStatus, BatchStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRecognitionBatch,
)
from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.evidence_service import EvidenceAggregationService
from hr_qualification.services.precheck_service import PrecheckService
from hr_staff.models import HrPerson, HrStaffMaster


APP_VIEW = "hr.qualification.application.view"
APP_SELF = "hr.qualification.application.self"
FORMAL_REVIEW = "hr.qualification.application.formal_review"
RULE_MANAGE = "hr.qualification.rule.manage"


def _has_perm(request, code):
    return request.user.is_superuser or request.user.has_perm(code)


def _batch_or_none(batch_id, tenant_id):
    return HrDoubleTeacherRecognitionBatch.objects.filter(id=batch_id, tenant_id=tenant_id).first()


def _application_or_none(app_id, tenant_id):
    return (
        HrDoubleTeacherApplication.objects.select_related("batch_id")
        .filter(id=app_id, tenant_id=tenant_id, batch_id__tenant_id=tenant_id)
        .first()
    )


def _require_self_ownership(request, app):
    try:
        person_id, _staff_id = current_person_id_or_raise(request, request.hr09_tenant_id)
    except QualificationAccessError as exc:
        return access_error_response(exc)
    if str(app.person_id_id) != str(person_id):
        return JsonResponse(error_envelope("PERMISSION_DENIED", "只能操作本人的双师申报。"), status=403)
    return None


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(APP_VIEW, RULE_MANAGE)
def batch_list(request: HttpRequest) -> JsonResponse:
    tenant_id = request.hr09_tenant_id
    status = request.GET.get("status")
    qs = HrDoubleTeacherRecognitionBatch.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    batches = list(qs.order_by("-created_at")[:100])
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
        "application_count": b.applications.filter(tenant_id=tenant_id).count(),
    } for b in batches]
    return JsonResponse(envelope({"items": items}))


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW, RULE_MANAGE)
def batch_create(request: HttpRequest) -> JsonResponse:
    try:
        import json

        body = json.loads(request.body)
        tenant_id = request.hr09_tenant_id
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=tenant_id,
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
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(APP_VIEW, RULE_MANAGE)
def batch_detail(request: HttpRequest, batch_id: str) -> JsonResponse:
    b = _batch_or_none(batch_id, request.hr09_tenant_id)
    if b is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Batch not found"), status=404)
    apps = list(
        HrDoubleTeacherApplication.objects.filter(
            tenant_id=request.hr09_tenant_id,
            batch_id=b,
        ).order_by("-created_at")[:200]
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


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(APP_SELF, FORMAL_REVIEW)
def application_create(request: HttpRequest) -> JsonResponse:
    try:
        import json

        body = json.loads(request.body)
        tenant_id = request.hr09_tenant_id
        batch = _batch_or_none(body["batch_id"], tenant_id)
        if batch is None:
            return JsonResponse(error_envelope("NOT_FOUND", "Batch not found"), status=404)

        # Normal users may only create an application for their own HR03 identity.
        if _has_perm(request, FORMAL_REVIEW):
            person_id = body.get("person_id")
            staff_master_id = body.get("staff_master_id")
            if not person_id:
                return JsonResponse(error_envelope("INVALID_REQUEST", "person_id is required"), status=400)
            person = HrPerson.objects.filter(id=person_id, tenant_id=tenant_id).first()
            if person is None:
                return JsonResponse(error_envelope("NOT_FOUND", "Person not found in tenant"), status=404)
            if staff_master_id:
                staff = HrStaffMaster.objects.filter(
                    id=staff_master_id,
                    tenant_id=tenant_id,
                    person_id=person,
                ).first()
                if staff is None:
                    return JsonResponse(error_envelope("NOT_FOUND", "Staff master not found in tenant"), status=404)
        else:
            person_id, staff_master_id = current_person_id_or_raise(request, tenant_id)

        app_no = f"APP-{tenant_id}-{uuid.uuid4().hex[:10].upper()}"
        app = HrDoubleTeacherApplication.objects.create(
            tenant_id=tenant_id,
            application_no=app_no,
            batch_id=batch,
            person_id_id=person_id,
            staff_master_id_id=staff_master_id,
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
    except QualificationAccessError as exc:
        return access_error_response(exc)
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(APP_VIEW, APP_SELF)
def application_detail(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    if not _has_perm(request, APP_VIEW):
        denied = _require_self_ownership(request, app)
        if denied:
            return denied
    pkgs = list(
        HrDoubleTeacherEvidencePackage.objects.filter(application_id=app).order_by("-generated_at")
    )
    return JsonResponse(envelope({
        "id": str(app.id),
        "application_no": app.application_no,
        "batch_id": str(app.batch_id_id),
        "person_id": str(app.person_id_id),
        "target_level": app.target_level,
        "route": app.route,
        "status": app.status,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "applicant_statement": app.applicant_statement,
        "version": app.version,
        "evidence_packages": [
            {"id": str(p.id), "status": p.status, "checksum": p.checksum}
            for p in pkgs
        ],
    }))


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(APP_VIEW, APP_SELF)
def application_precheck(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    if not _has_perm(request, APP_VIEW):
        denied = _require_self_ownership(request, app)
        if denied:
            return denied
    try:
        package = EvidenceAggregationService().build_package(app, [])
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
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(APP_SELF)
def application_submit(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    denied = _require_self_ownership(request, app)
    if denied:
        return denied
    try:
        app = ApplicationService.transition(app, ApplicationStatus.SUBMITTED)
        return JsonResponse(envelope({
            "id": str(app.id),
            "status": app.status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        }))
    except ApplicationError as e:
        return JsonResponse(error_envelope("APPLICATION_ALREADY_SUBMITTED", str(e)), status=409)


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(APP_SELF)
def application_withdraw(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    denied = _require_self_ownership(request, app)
    if denied:
        return denied
    try:
        app = ApplicationService.transition(app, ApplicationStatus.WITHDRAWN)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ApplicationError as e:
        return JsonResponse(error_envelope("STATUS_ERROR", str(e)), status=409)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(APP_SELF)
def my_applications(request: HttpRequest) -> JsonResponse:
    try:
        person_id, _staff_id = current_person_id_or_raise(request, request.hr09_tenant_id)
    except QualificationAccessError as exc:
        return access_error_response(exc)
    apps = list(
        HrDoubleTeacherApplication.objects.select_related("batch_id")
        .filter(tenant_id=request.hr09_tenant_id, person_id=person_id)
        .order_by("-created_at")[:100]
    )
    return JsonResponse(envelope({"items": [{
        "id": str(a.id),
        "application_no": a.application_no,
        "target_level": a.target_level,
        "status": a.status,
        "batch_name": a.batch_id.name if a.batch_id_id else "",
    } for a in apps]}))
