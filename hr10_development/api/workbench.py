"""Tenant-scoped business choices for the HR10 management workspace."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from hr_staff.models import HrStaffMaster
from hr10_development.api.envelope import error, success
from hr10_development.constants import DevelopmentErrorCode
from hr10_development.models import HrDevelopmentProviderOrganization
from hr10_development.models.learning_program import HrLearningProgram
from hr10_development.models.offering import HrLearningOffering
from hr10_development.models.practice_models import (
    HrEnterprisePracticeAssignment,
    HrEnterprisePracticeMentor,
    HrEnterprisePracticePlacement,
    HrPracticePositionScene,
)
from hr10_development.models.practice_project import HrEnterprisePracticeProject
from hr10_development.models.program_version import HrLearningProgramVersion
from hr10_development.permissions import require_hr10_permission


@csrf_exempt
@require_GET
@require_hr10_permission("hr.development.program.view")
def choices(request):
    """Return labels and opaque values resolved inside the current school only."""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    staff = HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        legacy_employee_id__isnull=False,
    ).select_related("person_id").order_by("person_id__legal_name", "staff_no")[:500]
    staff_items = [
        {
            "value": item.legacy_employee_id,
            "label": f"{item.person_id.legal_name} · {item.staff_no}",
        }
        for item in staff
    ]
    staff_labels = {item["value"]: item["label"] for item in staff_items}

    providers = HrDevelopmentProviderOrganization.objects.filter(
        tenant_id=tenant_id,
    ).order_by("short_name", "legal_name")[:500]
    provider_items = [
        {
            "value": item.id,
            "label": f"{item.short_name or item.legal_name} · {item.provider_code}",
        }
        for item in providers
    ]
    provider_labels = {item["value"]: item["label"] for item in provider_items}

    programs = list(
        HrLearningProgram.objects.filter(tenant_id=tenant_id).order_by("program_code")[:500]
    )
    program_labels = {item.id: f"{item.title} · {item.program_code}" for item in programs}
    versions = HrLearningProgramVersion.objects.filter(
        tenant_id=tenant_id,
        program_id__in=program_labels,
    ).order_by("program_id", "-version_no")[:1000]
    version_items = [
        {
            "value": item.id,
            "programValue": item.program_id,
            "label": f"{program_labels.get(item.program_id, '培训项目')} · v{item.version_no}",
        }
        for item in versions
    ]

    offerings = HrLearningOffering.objects.filter(tenant_id=tenant_id).order_by("-created_at")[:500]
    offering_items = [
        {
            "value": item.id,
            "programVersionValue": item.program_version_id,
            "label": f"{item.offering_no} · {item.get_delivery_mode_display()}",
            "status": item.lifecycle_status,
        }
        for item in offerings
    ]

    projects = list(
        HrEnterprisePracticeProject.objects.filter(tenant_id=tenant_id).order_by("project_no")[:500]
    )
    project_labels = {item.id: f"{item.title} · {item.project_no}" for item in projects}
    project_items = [
        {
            "value": item.id,
            "versionValue": item.current_version_id,
            "label": project_labels[item.id],
        }
        for item in projects
        if item.current_version_id
    ]
    scenes = HrPracticePositionScene.objects.filter(tenant_id=tenant_id).order_by("title")[:500]
    scene_items = [
        {
            "value": item.id,
            "projectVersionValue": item.project_version_id,
            "label": f"{item.title} · {item.real_position_name}",
        }
        for item in scenes
    ]
    scene_labels = {item["value"]: item["label"] for item in scene_items}

    placements = HrEnterprisePracticePlacement.objects.filter(
        tenant_id=tenant_id,
    ).order_by("-start_date")[:500]
    placement_items = [
        {
            "value": item.id,
            "projectValue": item.project_id,
            "projectVersionValue": item.project_version_id,
            "sceneValue": item.scene_id,
            "label": f"{project_labels.get(item.project_id, '企业实践')} · {item.batch_no}",
        }
        for item in placements
    ]
    placement_labels = {item["value"]: item["label"] for item in placement_items}

    mentors = HrEnterprisePracticeMentor.objects.filter(
        tenant_id=tenant_id,
    ).order_by("person_display_name")[:500]
    mentor_items = [
        {
            "value": item.id,
            "providerValue": item.provider_org_id,
            "label": " · ".join(filter(None, [item.person_display_name, item.position_title])),
        }
        for item in mentors
    ]
    assignments = HrEnterprisePracticeAssignment.objects.filter(
        tenant_id=tenant_id,
    ).order_by("-created_at")[:500]
    assignment_items = [
        {
            "value": item.id,
            "projectVersionValue": next(
                (
                    placement["projectVersionValue"]
                    for placement in placement_items
                    if placement["value"] == item.placement_id
                ),
                None,
            ),
            "label": f"{staff_labels.get(item.staff_master_id, '教师')} · {placement_labels.get(item.placement_id, '实践批次')}",
            "status": item.assignment_status,
            "sceneLabel": scene_labels.get(item.assigned_scene_id, "未配置岗位场景"),
        }
        for item in assignments
    ]

    return JsonResponse(success({
        "staff": staff_items,
        "providers": provider_items,
        "programs": [
            {
                "value": item.id,
                "versionValue": item.current_version_id,
                "label": program_labels[item.id],
            }
            for item in programs
        ],
        "programVersions": version_items,
        "offerings": offering_items,
        "practiceProjects": project_items,
        "practiceScenes": scene_items,
        "practicePlacements": placement_items,
        "practiceMentors": mentor_items,
        "practiceAssignments": assignment_items,
        "providerLabels": provider_labels,
    }))
