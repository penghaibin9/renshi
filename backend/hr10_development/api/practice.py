"""
hr10_development/api/practice.py

企业实践 API（总册 §134）。
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, ProjectLifecycleStatus, AssignmentStatus
from hr10_development.models.practice_project import (
    HrEnterprisePracticeProject,
    HrEnterprisePracticeProjectVersion,
)
from hr10_development.models.practice_models import (
    HrPracticePositionScene,
    HrEnterprisePracticePlacement,
    HrEnterprisePracticeAssignment,
    HrEnterprisePracticeMentor,
    HrEnterprisePracticePlan,
)
from hr10_development.services.practice_process_service import PracticeProcessService
from hr10_development.models.provider_org import HrDevelopmentProviderOrganization
from hr_staff.models import HrStaffMaster
from hr10_development.permissions import require_hr10_permission


def _project_to_dict(p: HrEnterprisePracticeProject) -> dict:
    return {
        "id": str(p.id),
        "tenantId": p.tenant_id,
        "projectNo": p.project_no,
        "title": p.title,
        "specialtyCategory": p.specialty_category,
        "providerOrgId": p.provider_org_id,
        "ownerOrgId": p.owner_org_id,
        "currentVersionId": p.current_version_id,
        "lifecycleStatus": p.lifecycle_status,
        "lifecycleStatusLabel": p.get_lifecycle_status_display(),
        "capacity": p.capacity,
        "plannedStartDate": str(p.planned_start_date) if p.planned_start_date else None,
        "plannedEndDate": str(p.planned_end_date) if p.planned_end_date else None,
        "version": p.version,
    }


def _assignment_to_dict(a: HrEnterprisePracticeAssignment) -> dict:
    return {
        "id": str(a.id),
        "placementId": a.placement_id,
        "staffMasterId": a.staff_master_id,
        "assignmentStatus": a.assignment_status,
        "assignmentStatusLabel": a.get_assignment_status_display(),
        "assignedSceneId": a.assigned_scene_id,
        "enterpriseMentorId": a.enterprise_mentor_id,
        "plannedHours": a.planned_hours,
        "plannedDays": a.planned_days,
        "actualVerifiedHours": a.actual_verified_hours,
        "actualVerifiedDays": a.actual_verified_days,
        "startedAt": a.started_at.isoformat() if a.started_at else None,
        "version": a.version,
    }


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.practice.view")
def list_projects(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    qs = HrEnterprisePracticeProject.objects.filter(tenant_id=tenant_id).order_by("-created_at")
    status_filter = request.GET.get("status")
    if status_filter:
        qs = qs.filter(lifecycle_status=status_filter)
    return JsonResponse(success([_project_to_dict(p) for p in qs[:100]]))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_project(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    if not body.get("projectNo") or not body.get("title") or not body.get("providerOrgId"):
        return JsonResponse(error("MISSING_FIELD", "projectNo/title/providerOrgId 必填"), status=400)
    if not HrDevelopmentProviderOrganization.objects.filter(
        id=body["providerOrgId"],
        tenant_id=tenant_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "企业或实践基地不存在"), status=404)

    p = HrEnterprisePracticeProject.objects.create(
        tenant_id=tenant_id,
        project_no=body["projectNo"],
        title=body["title"],
        specialty_category=body.get("specialtyCategory", ""),
        provider_org_id=body["providerOrgId"],
        practice_base_ref=body.get("practiceBaseRef", ""),
        owner_org_id=body.get("ownerOrgId"),
        planned_start_date=body.get("plannedStartDate"),
        planned_end_date=body.get("plannedEndDate"),
        capacity=body.get("capacity", 0),
        lifecycle_status=ProjectLifecycleStatus.DRAFT,
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_project_to_dict(p)), status=201)


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.practice.view")
def get_project(request, project_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    p = HrEnterprisePracticeProject.objects.filter(id=project_id, tenant_id=tenant_id).first()
    if not p:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
    return JsonResponse(success(_project_to_dict(p)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.publish")
def publish_project(request, project_id):
    """发布项目 → PUBLISHED。"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    p = HrEnterprisePracticeProject.objects.filter(id=project_id, tenant_id=tenant_id).first()
    if not p:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
    if p.lifecycle_status not in (ProjectLifecycleStatus.APPROVED, ProjectLifecycleStatus.DRAFT):
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "当前状态不能发布"), status=409)
    p.lifecycle_status = ProjectLifecycleStatus.PUBLISHED
    p.version += 1
    p.save(update_fields=["lifecycle_status", "version", "updated_at"])
    return JsonResponse(success(_project_to_dict(p)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_project_version(request, project_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        body = {}
    p = HrEnterprisePracticeProject.objects.filter(id=project_id, tenant_id=tenant_id).first()
    if not p:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)

    latest = HrEnterprisePracticeProjectVersion.objects.filter(project_id=p.id).order_by("-version_no").first()
    next_no = (latest.version_no + 1) if latest else 1

    v = HrEnterprisePracticeProjectVersion.objects.create(
        tenant_id=tenant_id,
        project_id=p.id,
        version_no=next_no,
        objectives_json=body.get("objectivesJson", {}),
        position_scene_requirements_json=body.get("positionSceneRequirementsJson", {}),
        module_task_json=body.get("moduleTaskJson", {}),
        mentor_requirements_json=body.get("mentorRequirementsJson", {}),
        evaluation_rubric_json=body.get("evaluationRubricJson", {}),
        output_requirements_json=body.get("outputRequirementsJson", {}),
        safety_requirements_json=body.get("safetyRequirementsJson", {}),
        confidentiality_ip_requirements_json=body.get("confidentialityIpRequirementsJson", {}),
        completion_rule_json=body.get("completionRuleJson", {}),
        policy_snapshot_json=body.get("policySnapshotJson", {}),
    )
    p.current_version_id = v.id
    p.save(update_fields=["current_version_id", "updated_at"])
    return JsonResponse(success({"id": str(v.id), "versionNo": v.version_no}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_placement(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    project = HrEnterprisePracticeProject.objects.filter(
        id=body.get("projectId"),
        tenant_id=tenant_id,
    ).first()
    version = HrEnterprisePracticeProjectVersion.objects.filter(
        id=body.get("projectVersionId"),
        tenant_id=tenant_id,
        project_id=project.id if project else None,
    ).first()
    scene = HrPracticePositionScene.objects.filter(
        id=body.get("sceneId"),
        tenant_id=tenant_id,
        project_version_id=version.id if version else None,
    ).first()
    if not project or not version or not scene:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "实践项目、版本或岗位场景不存在"), status=404)

    placement = HrEnterprisePracticePlacement.objects.create(
        tenant_id=tenant_id,
        project_id=project.id,
        project_version_id=version.id,
        scene_id=scene.id,
        batch_no=body.get("batchNo", "B-1"),
        start_date=body["startDate"],
        end_date=body["endDate"],
        capacity=body.get("capacity", 0),
        venue=body.get("venue", ""),
        status="DRAFT",
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success({"id": str(placement.id), "batchNo": placement.batch_no}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_assignment(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    placement = HrEnterprisePracticePlacement.objects.filter(
        id=body.get("placementId"),
        tenant_id=tenant_id,
    ).first()
    staff_id = body.get("staffMasterId")
    scene_id = body.get("assignedSceneId")
    mentor_id = body.get("enterpriseMentorId")
    if not placement or not HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        legacy_employee_id=staff_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "实践批次或教师不存在"), status=404)
    if not HrPracticePositionScene.objects.filter(
        id=scene_id,
        tenant_id=tenant_id,
        project_version_id=placement.project_version_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "岗位场景不存在"), status=404)
    if not HrEnterprisePracticeMentor.objects.filter(
        id=mentor_id,
        tenant_id=tenant_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "企业导师不存在"), status=404)

    assignment = HrEnterprisePracticeAssignment.objects.create(
        tenant_id=tenant_id,
        placement_id=placement.id,
        staff_master_id=staff_id,
        request_id=body.get("requestId"),
        development_need_id=body.get("developmentNeedId"),
        assignment_status=AssignmentStatus.APPROVED,
        assigned_scene_id=scene_id,
        enterprise_mentor_id=mentor_id,
        planned_hours=body.get("plannedHours", 0),
        planned_days=body.get("plannedDays", 0),
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_assignment_to_dict(assignment)), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def start_assignment(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/start"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    a = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not a:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)

    result = PracticeProcessService.start_assignment(a)
    if result["status"] == "PREREQUISITE_MISSING":
        return JsonResponse(error(DevelopmentErrorCode.PRACTICE_PREREQUISITE_MISSING, "前置条件未满足"), status=409)
    if result["status"] == "PRACTICE_ALREADY_STARTED":
        return JsonResponse(error(DevelopmentErrorCode.PRACTICE_ALREADY_STARTED, "实践已开始"), status=409)
    a.refresh_from_db()
    return JsonResponse(success(_assignment_to_dict(a)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def suspend_assignment(request, assignment_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    a = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not a:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}
    result = PracticeProcessService.suspend_assignment(a, reason=body.get("reason", ""),
                                                        responsible_party=body.get("responsibleParty", ""))
    a.refresh_from_db()
    return JsonResponse(success({"status": result["status"], "assignmentStatus": a.assignment_status}))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def resume_assignment(request, assignment_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    a = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not a:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
    PracticeProcessService.resume_assignment(a)
    a.refresh_from_db()
    return JsonResponse(success({"status": "RESUMED", "assignmentStatus": a.assignment_status}))
