"""HR09 双师认定批次与申报 API。

Tenant is always the selected school. SELF application endpoints derive the
applicant from the authenticated HR03 mapping and never trust person_id from
query/body input. Precheck/submission always use the guarded lifecycle service.
"""

import json
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from hr_qualification.api.access import (
    QualificationAccessError,
    access_error_response,
    api_guard,
    current_person_id_or_raise,
)
from hr_qualification.api.serializers import envelope, error_envelope
from hr_qualification.constants import (
    ApplicationRoute,
    ApplicationStatus,
    BatchStatus,
    RecognitionLevel,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRulePackVersion,
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


def _json_object(request):
    body = json.loads(request.body or b"{}")
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _validation_message(exc):
    if hasattr(exc, "message_dict"):
        return "; ".join(
            f"{field}: {', '.join(messages)}"
            for field, messages in exc.message_dict.items()
        )
    return "; ".join(exc.messages)


def _batch_or_none(batch_id, tenant_id):
    return (
        HrDoubleTeacherRecognitionBatch.objects.select_related("rule_pack_version_id")
        .filter(id=batch_id, tenant_id=tenant_id)
        .first()
    )


def _application_or_none(app_id, tenant_id):
    return (
        HrDoubleTeacherApplication.objects.select_related(
            "batch_id__rule_pack_version_id"
        )
        .filter(id=app_id, tenant_id=tenant_id, batch_id__tenant_id=tenant_id)
        .first()
    )


def _require_self_ownership(request, app):
    try:
        person_id, _staff_id = current_person_id_or_raise(request, request.hr09_tenant_id)
    except QualificationAccessError as exc:
        return access_error_response(exc)
    if str(app.person_id_id) != str(person_id):
        return JsonResponse(
            error_envelope("PERMISSION_DENIED", "只能操作本人的双师申报。"),
            status=403,
        )
    return None


def _batch_accepts_application(batch, target_level):
    today = timezone.localdate()
    if batch.status != BatchStatus.APPLICATION_OPEN:
        return "BATCH_NOT_OPEN", "当前认定批次未开放申报。"
    if batch.rule_pack_version_id.status != RulePackVersionStatus.ACTIVE:
        return "RULE_VERSION_NOT_ACTIVE", "当前批次规则版本尚未正式生效。"
    if batch.application_start and today < batch.application_start:
        return "APPLICATION_NOT_STARTED", "当前认定批次尚未开始申报。"
    if batch.application_end and today > batch.application_end:
        return "APPLICATION_CLOSED", "当前认定批次已超过申报截止日期。"
    if batch.target_levels and target_level not in set(batch.target_levels):
        return "TARGET_LEVEL_NOT_ALLOWED", "目标认定等级不在当前批次开放范围内。"
    return None


@require_http_methods(["GET", "HEAD"])
@api_guard(APP_VIEW, RULE_MANAGE)
def batch_list(request: HttpRequest) -> JsonResponse:
    tenant_id = request.hr09_tenant_id
    status = request.GET.get("status")
    qs = HrDoubleTeacherRecognitionBatch.objects.select_related(
        "rule_pack_version_id__rule_pack_id"
    ).filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    batches = list(qs.order_by("-created_at")[:100])
    items = [
        {
            "id": str(b.id),
            "batch_no": b.batch_no,
            "name": b.name,
            "school_year": b.school_year,
            "application_start": (
                b.application_start.isoformat() if b.application_start else None
            ),
            "application_end": (
                b.application_end.isoformat() if b.application_end else None
            ),
            "rule_pack_version_id": str(b.rule_pack_version_id_id),
            "rule_version_label": (
                f"{b.rule_pack_version_id.rule_pack_id.name}"
                f" · v{b.rule_pack_version_id.version_no}"
            ),
            "status": b.status,
            "target_levels": b.target_levels,
            "application_count": b.applications.filter(tenant_id=tenant_id).count(),
        }
        for b in batches
    ]
    return JsonResponse(envelope({"items": items}))


@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW, RULE_MANAGE)
def batch_create(request: HttpRequest) -> JsonResponse:
    try:
        body = _json_object(request)
        tenant_id = request.hr09_tenant_id
        target_levels = body.get("target_levels")
        if target_levels is not None:
            if not isinstance(target_levels, list) or any(
                value not in RecognitionLevel.values for value in target_levels
            ):
                raise ValueError("target_levels contains an invalid recognition level")
        with transaction.atomic():
            rule_version = (
                HrDoubleTeacherRulePackVersion.objects.select_for_update()
                .select_related("rule_pack_id")
                .filter(
                    id=body["rule_pack_version_id"],
                    status=RulePackVersionStatus.ACTIVE,
                )
                .filter(
                    Q(rule_pack_id__tenant_id=tenant_id)
                    | Q(rule_pack_id__tenant_id__isnull=True)
                )
                .first()
            )
            if rule_version is None:
                return JsonResponse(
                    error_envelope(
                        "RULE_VERSION_NOT_AVAILABLE",
                        "请选择当前学校可用的已生效规则版本。",
                    ),
                    status=400,
                )
            batch = HrDoubleTeacherRecognitionBatch(
                tenant_id=tenant_id,
                batch_no=body["batch_no"],
                name=body["name"],
                school_year=body.get("school_year", ""),
                application_start=body.get("application_start"),
                application_end=body.get("application_end"),
                rule_pack_version_id=rule_version,
                eligible_scope=body.get("eligible_scope"),
                target_levels=target_levels,
                status=BatchStatus.DRAFT,
            )
            batch.full_clean()
            if (
                batch.application_start
                and batch.application_end
                and batch.application_start > batch.application_end
            ):
                raise ValueError("application_start must not be after application_end")
            batch.save()
        return JsonResponse(
            envelope({"id": str(batch.id), "batch_no": batch.batch_no}),
            status=201,
        )
    except ValidationError as exc:
        return JsonResponse(
            error_envelope("INVALID_REQUEST", _validation_message(exc)), status=400
        )
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)
    except IntegrityError:
        return JsonResponse(
            error_envelope("BATCH_ALREADY_EXISTS", "同一学校内批次编号不能重复。"),
            status=409,
        )
    except Exception:
        return JsonResponse(
            error_envelope("INTERNAL_ERROR", "创建认定批次失败，请稍后重试。"),
            status=500,
        )


_BATCH_TRANSITIONS = {
    BatchStatus.DRAFT: BatchStatus.PUBLISHED,
    BatchStatus.PUBLISHED: BatchStatus.APPLICATION_OPEN,
    BatchStatus.APPLICATION_OPEN: BatchStatus.APPLICATION_CLOSED,
    BatchStatus.APPLICATION_CLOSED: BatchStatus.REVIEWING,
    BatchStatus.REVIEWING: BatchStatus.RESULT_PENDING,
    BatchStatus.RESULT_PENDING: BatchStatus.RESULT_PUBLISHED,
    BatchStatus.RESULT_PUBLISHED: BatchStatus.CLOSED,
}


@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW, RULE_MANAGE)
def batch_advance(request: HttpRequest, batch_id: str) -> JsonResponse:
    """Advance one canonical batch step; callers cannot skip review states."""
    with transaction.atomic():
        batch = (
            HrDoubleTeacherRecognitionBatch.objects.select_for_update()
            .select_related("rule_pack_version_id")
            .filter(id=batch_id, tenant_id=request.hr09_tenant_id)
            .first()
        )
        if batch is None:
            return JsonResponse(error_envelope("NOT_FOUND", "Batch not found"), status=404)
        target = _BATCH_TRANSITIONS.get(batch.status)
        if target is None:
            return JsonResponse(
                error_envelope("BATCH_TERMINAL_STATE", "当前批次没有可继续推进的状态。"),
                status=409,
            )
        if batch.status == BatchStatus.DRAFT:
            if batch.rule_pack_version_id.status != RulePackVersionStatus.ACTIVE:
                return JsonResponse(
                    error_envelope("RULE_VERSION_NOT_ACTIVE", "批次规则版本尚未正式生效。"),
                    status=409,
                )
            if not batch.target_levels:
                return JsonResponse(
                    error_envelope("TARGET_LEVEL_REQUIRED", "发布批次前必须选择可申报层级。"),
                    status=409,
                )
        if batch.status == BatchStatus.RESULT_PENDING:
            unfinished = batch.applications.exclude(
                status__in=(
                    ApplicationStatus.RECOGNIZED,
                    ApplicationStatus.NOT_RECOGNIZED,
                    ApplicationStatus.WITHDRAWN,
                    ApplicationStatus.CANCELLED,
                )
            ).exists()
            if unfinished:
                return JsonResponse(
                    error_envelope("APPLICATIONS_UNFINISHED", "仍有申报未形成最终审定结果。"),
                    status=409,
                )
        batch.status = target
        batch.version += 1
        batch.save(update_fields=["status", "version", "updated_at"])
    return JsonResponse(envelope({"id": str(batch.id), "status": batch.status}))


@require_http_methods(["GET", "HEAD"])
@api_guard(APP_VIEW, RULE_MANAGE)
def batch_detail(request: HttpRequest, batch_id: str) -> JsonResponse:
    b = _batch_or_none(batch_id, request.hr09_tenant_id)
    if b is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Batch not found"), status=404)
    apps = list(
        HrDoubleTeacherApplication.objects.select_related(
            "person_id", "staff_master_id"
        ).filter(
            tenant_id=request.hr09_tenant_id,
            batch_id=b,
        ).order_by("-created_at")[:200]
    )
    return JsonResponse(
        envelope(
            {
                "id": str(b.id),
                "batch_no": b.batch_no,
                "name": b.name,
                "status": b.status,
                "applications": [
                    {
                        "id": str(a.id),
                        "application_no": a.application_no,
                        "target_level": a.target_level,
                        "status": a.status,
                        "route": a.route,
                        "person": a.person_id.legal_name,
                        "staff_no": a.staff_master_id.staff_no if a.staff_master_id_id else "",
                    }
                    for a in apps
                ],
            }
        )
    )


@require_http_methods(["POST"])
@api_guard(APP_SELF, FORMAL_REVIEW)
def application_create(request: HttpRequest) -> JsonResponse:
    try:
        body = _json_object(request)
        tenant_id = request.hr09_tenant_id
        target_level = body["target_level"]
        route = body.get("route", ApplicationRoute.NORMAL)
        if target_level not in RecognitionLevel.values:
            raise ValueError("target_level is invalid")
        if route not in ApplicationRoute.values:
            raise ValueError("route is invalid")
        with transaction.atomic():
            batch = (
                HrDoubleTeacherRecognitionBatch.objects.select_for_update()
                .select_related("rule_pack_version_id")
                .filter(id=body["batch_id"], tenant_id=tenant_id)
                .first()
            )
            if batch is None:
                return JsonResponse(
                    error_envelope("NOT_FOUND", "Batch not found"), status=404
                )
            batch_error = _batch_accepts_application(batch, target_level)
            if batch_error:
                code, message = batch_error
                return JsonResponse(error_envelope(code, message), status=409)

            if _has_perm(request, FORMAL_REVIEW):
                person_id = body.get("person_id")
                staff_master_id = body.get("staff_master_id")
                if not person_id:
                    return JsonResponse(
                        error_envelope("INVALID_REQUEST", "person_id is required"),
                        status=400,
                    )
                person = HrPerson.objects.select_for_update().filter(
                    id=person_id, tenant_id=tenant_id
                ).first()
                if person is None:
                    return JsonResponse(
                        error_envelope("NOT_FOUND", "Person not found in tenant"),
                        status=404,
                    )
                if staff_master_id:
                    staff = HrStaffMaster.objects.select_for_update().filter(
                        id=staff_master_id,
                        tenant_id=tenant_id,
                        person_id=person,
                    ).first()
                    if staff is None:
                        return JsonResponse(
                            error_envelope(
                                "NOT_FOUND", "Staff master not found in tenant"
                            ),
                            status=404,
                        )
            else:
                person_id, staff_master_id = current_person_id_or_raise(
                    request, tenant_id
                )

            existing = (
                HrDoubleTeacherApplication.objects.select_for_update()
                .filter(
                    tenant_id=tenant_id,
                    batch_id=batch,
                    person_id_id=person_id,
                    target_level=target_level,
                )
                .exclude(
                    status__in=(
                        ApplicationStatus.WITHDRAWN,
                        ApplicationStatus.CANCELLED,
                    )
                )
                .first()
            )
            if existing is not None:
                return JsonResponse(
                    error_envelope(
                        "APPLICATION_ALREADY_EXISTS",
                        "当前人员在本批次同一目标等级已有有效申报。",
                    ),
                    status=409,
                )

            app_no = f"APP-{tenant_id}-{uuid.uuid4().hex[:10].upper()}"
            app = HrDoubleTeacherApplication(
                tenant_id=tenant_id,
                application_no=app_no,
                batch_id=batch,
                person_id_id=person_id,
                staff_master_id_id=staff_master_id,
                target_level=target_level,
                route=route,
                applicant_statement=body.get("applicant_statement", ""),
                status=ApplicationStatus.DRAFT,
            )
            app.full_clean()
            app.save()
        return JsonResponse(
            envelope(
                {
                    "id": str(app.id),
                    "application_no": app.application_no,
                    "status": app.status,
                }
            ),
            status=201,
        )
    except QualificationAccessError as exc:
        return access_error_response(exc)
    except ValidationError as exc:
        return JsonResponse(
            error_envelope("INVALID_REQUEST", _validation_message(exc)), status=400
        )
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)
    except IntegrityError:
        return JsonResponse(
            error_envelope(
                "APPLICATION_ALREADY_EXISTS",
                "当前人员在本批次已有冲突的有效申报，请刷新后重试。",
            ),
            status=409,
        )
    except Exception:
        return JsonResponse(
            error_envelope("INTERNAL_ERROR", "创建双师申报失败，请稍后重试。"),
            status=500,
        )


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
        HrDoubleTeacherEvidencePackage.objects.filter(application_id=app).order_by(
            "-generated_at"
        )
    )
    return JsonResponse(
        envelope(
            {
                "id": str(app.id),
                "application_no": app.application_no,
                "batch_id": str(app.batch_id_id),
                "person_id": str(app.person_id_id),
                "target_level": app.target_level,
                "route": app.route,
                "status": app.status,
                "submitted_at": (
                    app.submitted_at.isoformat() if app.submitted_at else None
                ),
                "applicant_statement": app.applicant_statement,
                "version": app.version,
                "evidence_packages": [
                    {"id": str(p.id), "status": p.status, "checksum": p.checksum}
                    for p in pkgs
                ],
            }
        )
    )


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

    started = False
    try:
        app = ApplicationService.start_precheck(app)
        started = True
        aggregator = EvidenceAggregationService()
        as_of = timezone.localdate()
        requirements = aggregator.requirements_for_application(app)
        provider_results = aggregator.aggregate(
            person_id=app.person_id_id,
            staff_master_id=app.staff_master_id_id,
            tenant_id=app.tenant_id,
            as_of=as_of,
        )
        package = aggregator.build_package(
            app,
            requirements=requirements,
            as_of=as_of,
            provider_results=provider_results,
        )
        result = PrecheckService.precheck(
            app,
            package,
            provider_results=provider_results,
        )
        app = ApplicationService.complete_precheck(app, result)
        return JsonResponse(
            envelope(
                {
                    "application_id": result.application_id,
                    "application_status": app.status,
                    "evidence_package_id": str(package.id),
                    "evidence_package_checksum": package.checksum,
                    "overall": result.overall,
                    "passed": result.passed,
                    "failed": result.failed,
                    "missing": result.missing,
                    "manual_review": result.manual_review,
                    "source_unavailable": result.source_unavailable,
                    "rule_error": result.rule_error,
                    "items": [
                        {
                            "rule_code": i.rule_code,
                            "dimension_code": i.dimension_code,
                            "result": i.result,
                            "detail": i.detail,
                        }
                        for i in result.items
                    ],
                }
            )
        )
    except ApplicationError as exc:
        if started:
            try:
                ApplicationService.abort_precheck(app)
            except ApplicationError:
                pass
        return JsonResponse(error_envelope(exc.code, str(exc)), status=409)
    except Exception:
        if started:
            try:
                ApplicationService.abort_precheck(app)
            except Exception:
                pass
        return JsonResponse(
            error_envelope("PRECHECK_INTERNAL_ERROR", "预检执行失败，请重新发起预检。"),
            status=500,
        )


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
        app = ApplicationService.submit(app)
        return JsonResponse(
            envelope(
                {
                    "id": str(app.id),
                    "status": app.status,
                    "submitted_at": (
                        app.submitted_at.isoformat() if app.submitted_at else None
                    ),
                }
            )
        )
    except ApplicationError as exc:
        return JsonResponse(error_envelope(exc.code, str(exc)), status=409)


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
    except ApplicationError as exc:
        return JsonResponse(error_envelope(exc.code, str(exc)), status=409)


@require_http_methods(["POST"])
@api_guard(APP_SELF)
def application_resubmit(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    denied = _require_self_ownership(request, app)
    if denied:
        return denied
    try:
        app = ApplicationService.transition(app, ApplicationStatus.RESUBMITTED)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ApplicationError as exc:
        return JsonResponse(error_envelope(exc.code, str(exc)), status=409)


@require_http_methods(["GET", "HEAD"])
@api_guard(APP_SELF)
def my_applications(request: HttpRequest) -> JsonResponse:
    try:
        person_id, _staff_id = current_person_id_or_raise(
            request, request.hr09_tenant_id
        )
    except QualificationAccessError as exc:
        return access_error_response(exc)
    apps = list(
        HrDoubleTeacherApplication.objects.select_related("batch_id")
        .filter(tenant_id=request.hr09_tenant_id, person_id=person_id)
        .order_by("-created_at")[:100]
    )
    return JsonResponse(
        envelope(
            {
                "items": [
                    {
                        "id": str(a.id),
                        "application_no": a.application_no,
                        "target_level": a.target_level,
                        "status": a.status,
                        "batch_name": a.batch_id.name if a.batch_id_id else "",
                    }
                    for a in apps
                ]
            }
        )
    )
