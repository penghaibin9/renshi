"""
hr10_development/api/practice.py

企业实践 API（总册 §134）。
"""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
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


def _body_object(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _invalid(exc):
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse(error("INVALID_REQUEST", message), status=400)


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


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_project(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    if not body.get("projectNo") or not body.get("title") or not body.get("providerOrgId"):
        return JsonResponse(error("MISSING_FIELD", "projectNo/title/providerOrgId 必填"), status=400)
    try:
        with transaction.atomic():
            provider = HrDevelopmentProviderOrganization.objects.select_for_update().filter(
                id=body["providerOrgId"],
                tenant_id=tenant_id,
            ).first()
            if provider is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "企业或实践基地不存在"), status=404)
            p = HrEnterprisePracticeProject(
                tenant_id=tenant_id,
                project_no=str(body["projectNo"]).strip(),
                title=str(body["title"]).strip(),
                specialty_category=str(body.get("specialtyCategory") or "").strip(),
                provider_org_id=provider.id,
                practice_base_ref=str(body.get("practiceBaseRef") or "").strip(),
                owner_org_id=body.get("ownerOrgId"),
                planned_start_date=body.get("plannedStartDate"),
                planned_end_date=body.get("plannedEndDate"),
                capacity=body.get("capacity", 0),
                lifecycle_status=ProjectLifecycleStatus.DRAFT,
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            p.full_clean()
            if p.capacity < 0 or (
                p.planned_start_date and p.planned_end_date and p.planned_end_date < p.planned_start_date
            ):
                raise ValueError("项目容量或计划日期范围无效")
            p.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "项目编号已存在"), status=409)
    return JsonResponse(success(_project_to_dict(p)), status=201)


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


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.publish")
def publish_project(request, project_id):
    """发布项目 → PUBLISHED。"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    with transaction.atomic():
        p = HrEnterprisePracticeProject.objects.select_for_update().filter(
            id=project_id, tenant_id=tenant_id
        ).first()
        if not p:
            return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
        if p.lifecycle_status not in (
            ProjectLifecycleStatus.APPROVED,
            ProjectLifecycleStatus.DRAFT,
            ProjectLifecycleStatus.PUBLISHED,
        ):
            return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "当前状态不能发布"), status=409)
        version = HrEnterprisePracticeProjectVersion.objects.select_for_update().filter(
            id=p.current_version_id,
            project_id=p.id,
            tenant_id=tenant_id,
        ).first()
        if version is None:
            return JsonResponse(error("PRACTICE_VERSION_REQUIRED", "请先创建完整的项目版本"), status=409)
        if p.lifecycle_status == ProjectLifecycleStatus.PUBLISHED and version.published_at:
            return JsonResponse(success(_project_to_dict(p)))
        if not version.published_at:
            version.published_at = timezone.now()
            version.save(update_fields=["published_at", "updated_at"])
        p.lifecycle_status = ProjectLifecycleStatus.PUBLISHED
        p.version += 1
        p.save(update_fields=["lifecycle_status", "version", "updated_at"])
    return JsonResponse(success(_project_to_dict(p)))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_project_version(request, project_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            p = HrEnterprisePracticeProject.objects.select_for_update().filter(
                id=project_id, tenant_id=tenant_id
            ).first()
            if not p:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "项目不存在"), status=404)
            latest = HrEnterprisePracticeProjectVersion.objects.filter(
                project_id=p.id,
                tenant_id=tenant_id,
            ).order_by("-version_no").first()
            next_no = (latest.version_no + 1) if latest else 1
            v = HrEnterprisePracticeProjectVersion(
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
            v.full_clean()
            v.save()
            p.current_version_id = v.id
            p.save(update_fields=["current_version_id", "updated_at"])
    except (ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "项目版本已由其他操作创建"), status=409)
    return JsonResponse(success({"id": str(v.id), "versionNo": v.version_no}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_placement(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            project = HrEnterprisePracticeProject.objects.select_for_update().filter(
                id=body.get("projectId"), tenant_id=tenant_id
            ).first()
            version = HrEnterprisePracticeProjectVersion.objects.filter(
                id=body.get("projectVersionId"), tenant_id=tenant_id,
                project_id=project.id if project else None, published_at__isnull=False,
            ).first()
            scene = HrPracticePositionScene.objects.filter(
                id=body.get("sceneId"), tenant_id=tenant_id,
                project_version_id=version.id if version else None,
            ).first()
            if not project or not version or not scene:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "已发布实践项目版本或岗位场景不存在"), status=404)
            if project.lifecycle_status not in {
                ProjectLifecycleStatus.PUBLISHED,
                ProjectLifecycleStatus.MATCHING,
                ProjectLifecycleStatus.READY_TO_START,
                ProjectLifecycleStatus.ACTIVE,
            }:
                return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "项目尚未发布"), status=409)
            placement = HrEnterprisePracticePlacement(
                tenant_id=tenant_id,
                project_id=project.id,
                project_version_id=version.id,
                scene_id=scene.id,
                batch_no=str(body.get("batchNo") or "B-1").strip(),
                start_date=body["startDate"],
                end_date=body["endDate"],
                capacity=body.get("capacity", 0),
                venue=str(body.get("venue") or "").strip(),
                status="DRAFT",
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            placement.full_clean()
            if placement.capacity < 1 or placement.end_date < placement.start_date:
                raise ValueError("批次容量必须大于零且结束日期不得早于开始日期")
            placement.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    return JsonResponse(success({"id": str(placement.id), "batchNo": placement.batch_no}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def create_assignment(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        staff_id = int(body["staffMasterId"])
        with transaction.atomic():
            placement = HrEnterprisePracticePlacement.objects.select_for_update().filter(
                id=body.get("placementId"), tenant_id=tenant_id
            ).first()
            staff = HrStaffMaster.objects.select_for_update().filter(
                tenant_id=tenant_id, legacy_employee_id=staff_id
            ).first()
            if not placement or not staff:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "实践批次或教师不存在"), status=404)
            scene_id = body.get("assignedSceneId")
            mentor_id = body.get("enterpriseMentorId")
            if not HrPracticePositionScene.objects.filter(
                id=scene_id, tenant_id=tenant_id,
                project_version_id=placement.project_version_id,
            ).exists():
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "岗位场景不存在"), status=404)
            project = HrEnterprisePracticeProject.objects.filter(
                id=placement.project_id, tenant_id=tenant_id
            ).first()
            if not project or not HrEnterprisePracticeMentor.objects.filter(
                id=mentor_id, tenant_id=tenant_id, provider_org_id=project.provider_org_id
            ).exists():
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "企业导师不存在或不属于项目企业"), status=404)
            active_assignments = HrEnterprisePracticeAssignment.objects.filter(
                tenant_id=tenant_id, placement_id=placement.id
            ).exclude(assignment_status__in=[AssignmentStatus.CANCELLED, AssignmentStatus.REJECTED])
            if active_assignments.filter(staff_master_id=staff_id).exists():
                return JsonResponse(error("PRACTICE_ASSIGNMENT_DUPLICATE", "该教师已在此批次中"), status=409)
            if placement.capacity > 0 and active_assignments.count() >= placement.capacity:
                return JsonResponse(error("PRACTICE_CAPACITY_FULL", "实践批次名额已满"), status=409)
            planned_hours = int(body.get("plannedHours", 0))
            planned_days = int(body.get("plannedDays", 0))
            if planned_hours < 0 or planned_days < 0:
                raise ValueError("计划时长不能为负数")
            assignment = HrEnterprisePracticeAssignment(
                tenant_id=tenant_id,
                placement_id=placement.id,
                staff_master_id=staff_id,
                request_id=body.get("requestId"),
                development_need_id=body.get("developmentNeedId"),
                assignment_status=AssignmentStatus.APPROVED,
                assigned_scene_id=scene_id,
                enterprise_mentor_id=mentor_id,
                planned_hours=planned_hours,
                planned_days=planned_days,
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            assignment.full_clean()
            assignment.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    return JsonResponse(success(_assignment_to_dict(assignment)), status=201)


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
    if result["status"] == "PRACTICE_STATE_CONFLICT":
        return JsonResponse(error("PRACTICE_STATE_CONFLICT", "当前状态不能开始实践"), status=409)
    a.refresh_from_db()
    return JsonResponse(success(_assignment_to_dict(a)))


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
    if result["status"] == "SUSPEND_REASON_REQUIRED":
        return JsonResponse(error("SUSPEND_REASON_REQUIRED", "暂停实践必须填写原因"), status=400)
    if result["status"] == "PRACTICE_STATE_CONFLICT":
        return JsonResponse(error("PRACTICE_STATE_CONFLICT", "只有进行中的实践可以暂停"), status=409)
    a.refresh_from_db()
    return JsonResponse(success({"status": result["status"], "assignmentStatus": a.assignment_status}))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.practice.manage")
def resume_assignment(request, assignment_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    a = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not a:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
    result = PracticeProcessService.resume_assignment(a)
    if result["status"] == "PRACTICE_STATE_CONFLICT":
        return JsonResponse(error("PRACTICE_STATE_CONFLICT", "只有已暂停的实践可以恢复"), status=409)
    a.refresh_from_db()
    return JsonResponse(success({"status": "RESUMED", "assignmentStatus": a.assignment_status}))
