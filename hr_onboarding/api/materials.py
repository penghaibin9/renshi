"""
hr_onboarding/api/materials.py

HR05-03 材料核验 API（总册 §12.5/§34）。
"""

from __future__ import annotations

from django.core.files.storage import default_storage
from django.http import FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.api.labels import (
    label_for,
    BLOCKING_LEVEL_LABELS,
    BLOCKING_PHASE_LABELS,
    MATERIAL_STATUS_LABELS,
    REUSE_POLICY_LABELS,
    RESPONSIBLE_ROLE_LABELS,
    TASK_STATUS_LABELS,
)
from hr_onboarding.constants import MaterialStatus, VerificationResult
from hr_onboarding.models import HrOnboardingCase, HrOnboardingMaterial
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services import file_service
from hr_onboarding.services.material_service import MaterialService


def _load_case_or_404(context, case_id: str):
    try:
        case = HrOnboardingCase.objects.filter(
            tenant_id=context.tenant_id, id=case_id
        ).first()
    except (ValueError, TypeError):
        case = None
    if case is None:
        raise NotFoundError("case 不存在或无权访问")
    return case


def _load_material_or_404(context, material_id: str):
    try:
        material = HrOnboardingMaterial.objects.filter(
            tenant_id=context.tenant_id, id=material_id
        ).first()
    except (ValueError, TypeError):
        material = None
    if material is None:
        raise NotFoundError("材料不存在或无权访问")
    return material


@require_GET
@require_hr05_permission("hr05.case.view")
def materials_list(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        # 按模板版本实例化材料清单（幂等；case 未绑定模板时为空）
        from hr_onboarding.services.material_service import ensure_materials_from_requirements

        ensure_materials_from_requirements(case)
        qs = HrOnboardingMaterial.objects.filter(case=case).select_related("requirement")
        items = [
            {
                "id": str(m.id),
                "material_type": m.requirement.material_type,
                "label": m.requirement.label,
                "blocking_phase": m.requirement.blocking_phase,
                "blockingPhaseLabel": label_for(BLOCKING_PHASE_LABELS, m.requirement.blocking_phase),
                "required": m.requirement.required,
                "reuse_policy": m.requirement.reuse_policy,
                "reusePolicyLabel": label_for(REUSE_POLICY_LABELS, m.requirement.reuse_policy),
                "status": m.status,
                "statusLabel": label_for(MATERIAL_STATUS_LABELS, m.status),
                "source": m.source,
                "expiry_date": m.expiry_date.isoformat() if m.expiry_date else None,
            }
            for m in qs
        ]
        return api_base.ok(request, {"items": items, "total": len(items)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
@csrf_exempt
def material_submit(request, case_id: str, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        material = _load_material_or_404(context, material_id)
        # 纵深防御：material 必须属于该 case（跨 case 提交拒绝）
        if str(material.case_id) != str(case.id):
            raise NotFoundError("材料不属于该 case")
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise Hr05ApiError("缺少文件字段 file")
        service = MaterialService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        updated = service.submit_material(case, material.requirement_id, uploaded)
        return api_base.ok(request, {"material_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
@csrf_exempt
def material_verify(request, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        material = _load_material_or_404(context, material_id)
        result = request.POST.get("result", VerificationResult.VERIFIED)
        if result not in VerificationResult.values:
            raise Hr05ApiError("result 非法")
        service = MaterialService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        updated = service.verify_material(
            material,
            result=result,
            reason=request.POST.get("reason", ""),
            evidence={"evidence": request.POST.get("evidence", "")},
        )
        return api_base.ok(request, {"material_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
@csrf_exempt
def material_return(request, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        material = _load_material_or_404(context, material_id)
        service = MaterialService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        updated = service.return_material(material, reason=request.POST.get("reason", ""))
        return api_base.ok(request, {"material_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
@csrf_exempt
def material_waive(request, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        material = _load_material_or_404(context, material_id)
        service = MaterialService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        updated = service.waive_material(material, reason=request.POST.get("reason", ""))
        return api_base.ok(request, {"material_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
@csrf_exempt
def material_download_ticket(request, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        material = _load_material_or_404(context, material_id)
        ticket = file_service.issue_download_ticket(
            tenant_id=context.tenant_id, material_id=str(material.id)
        )
        return api_base.ok(request, {"ticket": ticket, "expiresInSeconds": file_service.TICKET_TTL_SECONDS})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_GET
def material_download(request):
    """消费下载 ticket（短时效一次性；不暴露存储路径）。"""
    try:
        ticket = request.GET.get("ticket")
        if not ticket:
            raise NotFoundError("missing ticket")
        info = file_service.resolve_download_ticket(ticket)
        if info is None:
            raise Hr05ApiError("ticket 无效或已过期", details={"code": "TICKET_EXPIRED"})
        # 一次性：消费即失效（防 ticket 复用/转嫁）
        file_service.consume_download_ticket(ticket)
        material = HrOnboardingMaterial.objects.filter(
            tenant_id=info["tenant_id"], id=info["material_id"]
        ).first()
        if material is None:
            raise NotFoundError("材料不存在")
        meta = material.file_meta_json or {}
        file_version_id = meta.get("file_version_id")
        ext = meta.get("ext", "")
        if not file_version_id or not ext:
            raise NotFoundError("文件元数据缺失")
        path = file_service.material_storage_path(
            tenant_id=material.tenant_id,
            case_id=material.case_id,
            material_id=str(material.id),
            file_version_id=file_version_id,
            ext=ext,
        )
        if not default_storage.exists(path):
            raise NotFoundError("文件不存在")
        name = meta.get("original_name", "document")
        response = FileResponse(default_storage.open(path), as_attachment=True, filename=name)
        return response
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
