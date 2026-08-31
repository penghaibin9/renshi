"""
hr10_development/api/programs.py

培训项目 REST API（总册 §132）。
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode
from hr10_development.models.learning_program import HrLearningProgram
from hr10_development.models.offering import HrLearningOffering
from hr10_development.models.program_version import HrLearningProgramVersion
from hr10_development.models.provider_org import HrDevelopmentProviderOrganization
from hr10_development.permissions import require_hr10_permission


def _program_to_dict(p: HrLearningProgram) -> dict:
    return {
        "id": str(p.id),
        "tenantId": p.tenant_id,
        "programCode": p.program_code,
        "title": p.title,
        "activityType": p.activity_type,
        "ownerOrgId": p.owner_org_id,
        "providerOrgId": p.provider_org_id,
        "targetPopulationRuleId": p.target_population_rule_id,
        "currentVersionId": p.current_version_id,
        "lifecycleStatus": p.lifecycle_status,
        "lifecycleStatusLabel": p.get_lifecycle_status_display(),
        "source": p.source,
        "version": p.version,
        "createdAt": p.created_at.isoformat(),
    }


def _offering_to_dict(o: HrLearningOffering) -> dict:
    return {
        "id": str(o.id),
        "programVersionId": o.program_version_id,
        "offeringNo": o.offering_no,
        "deliveryMode": o.delivery_mode,
        "deliveryModeLabel": o.get_delivery_mode_display(),
        "venue": o.venue,
        "startAt": o.start_at.isoformat() if o.start_at else None,
        "endAt": o.end_at.isoformat() if o.end_at else None,
        "enrollmentOpenAt": o.enrollment_open_at.isoformat() if o.enrollment_open_at else None,
        "enrollmentCloseAt": o.enrollment_close_at.isoformat() if o.enrollment_close_at else None,
        "capacity": o.capacity,
        "waitlistCapacity": o.waitlist_capacity,
        "estimatedCostPerPerson": str(o.estimated_cost_per_person) if o.estimated_cost_per_person else None,
        "lifecycleStatus": o.lifecycle_status,
        "lifecycleStatusLabel": o.get_lifecycle_status_display(),
    }


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.program.view")
def list_programs(request):
    """GET /api/v1/hr/development/programs"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    programs = HrLearningProgram.objects.filter(tenant_id=tenant_id).order_by("-created_at")[:100]
    return JsonResponse(success([_program_to_dict(p) for p in programs]))


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.program.view")
def get_program(request, program_id):
    """GET /api/v1/hr/development/programs/{programId}"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        p = HrLearningProgram.objects.get(id=program_id, tenant_id=tenant_id)
    except HrLearningProgram.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
    return JsonResponse(success(_program_to_dict(p)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.manage")
def create_program(request):
    """POST /api/v1/hr/development/programs"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    if not body.get("programCode") or not body.get("title"):
        return JsonResponse(error("MISSING_FIELD", "programCode 和 title 必填"), status=400)

    provider_org_id = body.get("providerOrgId")
    if provider_org_id and not HrDevelopmentProviderOrganization.objects.filter(
        id=provider_org_id,
        tenant_id=tenant_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "提供机构不存在"), status=404)

    p = HrLearningProgram.objects.create(
        tenant_id=tenant_id,
        program_code=body["programCode"],
        title=body["title"],
        activity_type=body.get("activityType", "INTERNAL_TRAINING"),
        owner_org_id=body.get("ownerOrgId"),
        provider_org_id=provider_org_id,
        target_population_rule_id=body.get("targetPopulationRuleId", ""),
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_program_to_dict(p)), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.manage")
def create_offering(request):
    """POST /api/v1/hr/development/offerings"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    program_version = HrLearningProgramVersion.objects.filter(
        id=body.get("programVersionId"),
        tenant_id=tenant_id,
    ).first()
    if not program_version or not HrLearningProgram.objects.filter(
        id=program_version.program_id,
        tenant_id=tenant_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "培训项目版本不存在"), status=404)

    o = HrLearningOffering.objects.create(
        tenant_id=tenant_id,
        program_version_id=program_version.id,
        offering_no=body["offeringNo"],
        delivery_mode=body.get("deliveryMode", "ONSITE"),
        venue=body.get("venue", ""),
        start_at=body.get("startAt"),
        end_at=body.get("endAt"),
        enrollment_open_at=body.get("enrollmentOpenAt"),
        enrollment_close_at=body.get("enrollmentCloseAt"),
        capacity=body.get("capacity", 0),
        waitlist_capacity=body.get("waitlistCapacity", 0),
        estimated_cost_per_person=body.get("estimatedCostPerPerson"),
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_offering_to_dict(o)), status=201)


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.program.view")
def get_offering(request, offering_id):
    """GET /api/v1/hr/development/offerings/{offeringId}"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        o = HrLearningOffering.objects.get(id=offering_id, tenant_id=tenant_id)
    except HrLearningOffering.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)
    return JsonResponse(success(_offering_to_dict(o)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.manage")
def cancel_offering(request, offering_id):
    """POST /api/v1/hr/development/offerings/{offeringId}/cancel"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        o = HrLearningOffering.objects.get(id=offering_id, tenant_id=tenant_id)
    except HrLearningOffering.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)
    from hr10_development.constants import OfferingStatus
    o.lifecycle_status = OfferingStatus.CANCELLED
    o.save(update_fields=["lifecycle_status", "updated_at"])
    return JsonResponse(success(_offering_to_dict(o)))


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.program.view")
def get_offering_capacity(request, offering_id):
    """GET /api/v1/hr/development/offerings/{offeringId}/capacity"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        o = HrLearningOffering.objects.get(id=offering_id, tenant_id=tenant_id)
    except HrLearningOffering.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)
    from hr10_development.models.enrollment import HrLearningEnrollment
    confirmed = HrLearningEnrollment.objects.filter(
        offering_id=o.id, enrollment_status="CONFIRMED",
    ).count()
    waitlisted = HrLearningEnrollment.objects.filter(
        offering_id=o.id, enrollment_status="WAITLISTED",
    ).count()
    return JsonResponse(success({
        "capacity": o.capacity,
        "waitlistCapacity": o.waitlist_capacity,
        "confirmedCount": confirmed,
        "waitlistedCount": waitlisted,
        "availableSeats": max(o.capacity - confirmed, 0),
        "status": o.lifecycle_status,
    }))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.manage")
def open_enrollment(request, offering_id):
    """POST /api/v1/hr/development/offerings/{offeringId}/open-enrollment"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        o = HrLearningOffering.objects.get(id=offering_id, tenant_id=tenant_id)
    except HrLearningOffering.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)
    from hr10_development.constants import OfferingStatus
    if o.lifecycle_status not in [OfferingStatus.DRAFT, OfferingStatus.FULL, OfferingStatus.CLOSED]:
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "当前状态不能开放报名"), status=409)
    o.lifecycle_status = OfferingStatus.OPEN
    o.save(update_fields=["lifecycle_status", "updated_at"])
    return JsonResponse(success(_offering_to_dict(o)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.manage")
def create_program_version(request, program_id):
    """POST /api/v1/hr/development/programs/{programId}/versions"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    p = HrLearningProgram.objects.filter(id=program_id, tenant_id=tenant_id).first()
    if not p:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)

    from hr10_development.constants import ProgramVersionStatus
    latest = HrLearningProgramVersion.objects.filter(program_id=p.id).order_by("-version_no").first()
    next_no = (latest.version_no + 1) if latest else 1

    v = HrLearningProgramVersion.objects.create(
        tenant_id=tenant_id,
        program_id=p.id,
        version_no=next_no,
        status=ProgramVersionStatus.DRAFT,
        objectives_json=body.get("objectivesJson", {}),
        curriculum_json=body.get("curriculumJson", {}),
        completion_rule_json=body.get("completionRuleJson", {}),
        evaluation_rule_json=body.get("evaluationRuleJson", {}),
        credit_rule_json=body.get("creditRuleJson", {}),
        cost_rule_json=body.get("costRuleJson", {}),
        eligibility_rule_json=body.get("eligibilityRuleJson", {}),
        document_requirement_json=body.get("documentRequirementJson", {}),
        effective_from=body.get("effectiveFrom"),
        effective_to=body.get("effectiveTo"),
    )
    p.current_version_id = v.id
    p.save(update_fields=["current_version_id", "updated_at"])
    return JsonResponse(success({"id": str(v.id), "versionNo": v.version_no, "status": v.status}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.program.publish")
def publish_program(request, program_id):
    """POST /api/v1/hr/development/programs/{programId}/publish"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    p = HrLearningProgram.objects.filter(id=program_id, tenant_id=tenant_id).first()
    if not p:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
    from hr10_development.constants import ProgramLifecycleStatus
    if p.lifecycle_status not in (ProgramLifecycleStatus.DRAFT, ProgramLifecycleStatus.UNDER_REVIEW):
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "当前状态不能发布"), status=409)
    p.lifecycle_status = ProgramLifecycleStatus.PUBLISHED
    p.version += 1
    p.save(update_fields=["lifecycle_status", "version", "updated_at"])
    return JsonResponse(success(_program_to_dict(p)))
