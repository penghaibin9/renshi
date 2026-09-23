"""
hr_onboarding/api/materials.py

HR05-03 材料核验 API（总册 §12.5/§34）。
"""

from __future__ import annotations

from django.core.files.storage import default_storage
from django.http import FileResponse
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    MaterialDownloadAuditUnavailableError,
    MaterialDownloadTicketError,
    NotFoundError,
)
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
from hr_onboarding.models import (
    HrOnboardingAuditEvent,
    HrOnboardingCase,
    HrOnboardingMaterial,
)
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


def material_fingerprint(material):
    from hr_onboarding.services.idempotency_service import canonical_request_hash
    return canonical_request_hash({
        "id": str(material.id), "case": str(material.case_id), "status": material.status,
        "file": str(material.file_version_id), "updated": material.updated_at.isoformat(),
        "requirement": [str(material.requirement_id), material.requirement.required,
                        material.requirement.verification_required, material.requirement.blocking_phase],
    })


def material_projection(material, user):
    req = material.requirement
    can_review = bool(user.is_superuser or user.has_perm("hr05.material.review"))
    actions = []
    if can_review and material.case.status not in {"CANCELLED", "DECLINED", "PROBATION_FAILED"}:
        if material.status in {"MISSING", "RETURNED", "REJECTED", "EXPIRED"}: actions.append("upload")
        if material.status == "UNDER_REVIEW": actions.extend(["verify", "return"])
        if not req.required and material.status not in {"VERIFIED", "WAIVED"}: actions.append("waive")
    if can_review and material.file_version_id: actions.append("download")
    return {
        "id": str(material.id), "material_type": req.material_type, "label": req.label,
        "blocking_phase": req.blocking_phase, "blockingPhaseLabel": label_for(BLOCKING_PHASE_LABELS, req.blocking_phase),
        "required": req.required, "reuse_policy": req.reuse_policy,
        "reusePolicyLabel": label_for(REUSE_POLICY_LABELS, req.reuse_policy),
        "status": material.status, "statusLabel": label_for(MATERIAL_STATUS_LABELS, material.status),
        "hasFile": bool(material.file_version_id), "source": material.source,
        "expiry_date": material.expiry_date.isoformat() if material.expiry_date else None,
        "fingerprint": material_fingerprint(material), "actions": actions,
        "allowed_formats": req.allowed_formats, "max_size": req.max_size,
    }


def scoped_materials(context, case):
    return HrOnboardingMaterial.objects.filter(tenant_id=context.tenant_id, case_id=case.id,
        requirement__tenant_id=context.tenant_id, requirement__template_version_id=case.template_version_id
    ).select_related("requirement", "case").order_by("requirement__created_at", "id")


@require_GET
@require_hr05_permission("hr05.case.view")
def materials_list(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        rows = list(scoped_materials(context, case))
        from hr_onboarding.models import HrOnboardingMaterialRequirement
        missing = HrOnboardingMaterialRequirement.objects.filter(
            tenant_id=context.tenant_id, template_version_id=case.template_version_id
        ).exclude(id__in=[r.requirement_id for r in rows]).count() if case.template_version_id else 0
        can_init = (request.user.is_superuser or request.user.has_perm("hr05.material.review")) and case.status not in {"CANCELLED", "DECLINED", "PROBATION_FAILED"}
        return api_base.ok(request, {"items": [material_projection(m, request.user) for m in rows],
            "total": len(rows), "missing_requirements": missing, "can_initialize": bool(missing and can_init),
            "case_no": case.case_no, "case_version": case.version, "has_template": bool(case.template_version_id)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_GET
@require_hr05_permission("hr05.case.view")
def material_detail(request, material_id):
    try:
        ctx = api_base.make_hr05_context(request)
        row = _load_material_or_404(ctx, material_id)
        case = _load_case_or_404(ctx, row.case_id)
        row = scoped_materials(ctx, case).filter(pk=material_id).first()
        if row is None: raise NotFoundError("材料所属模板不一致")
        return api_base.ok(request, {"item": material_projection(row, request.user)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.material.review")
def materials_initialize(request, case_id):
    from django.db import transaction
    from hr_onboarding.services.workflow_service import expected_version
    from hr_onboarding.services.idempotency_service import DurableIdempotencyService
    from hr_onboarding.services.material_service import ensure_materials_from_requirements
    from hr_onboarding.api.exceptions import VersionConflictError
    try:
        ctx = api_base.make_hr05_context(request)
        with transaction.atomic():
            case = MaterialService(tenant_id=ctx.tenant_id)._lock_case(case_id)
            version = expected_version(request.headers.get("If-Match", "").strip('"'))
            idem = DurableIdempotencyService(tenant_id=ctx.tenant_id, operation="materials.initialize")
            claim = idem.claim(idempotency_key=api_base.get_idempotency_key(request), request_payload={
                "actor": ctx.user_id, "case": str(case_id), "version": version})
            if claim.is_replay: return api_base.ok(request, {"receipt": claim.record.response_summary, "replayed": True})
            if case.version != version: raise VersionConflictError("入职单已更新，请重读")
            if not case.template_version_id: raise Hr05ApiError("请先绑定本校入职模板")
            created = ensure_materials_from_requirements(case)
            event = HrOnboardingAuditEvent.objects.create(tenant_id=ctx.tenant_id, case_id=case.id,
                actor_user_id=ctx.user_id, action="MATERIALS_INITIALIZED", business_type="MATERIAL",
                business_id=str(case.id), reason="按绑定模板生成材料要求", request_id=api_base._request_id(request))
            receipt = {"id": str(event.id), "created": created, "case_id": str(case.id)}
            idem.succeed(claim.record, authority_type="HrOnboardingCase", authority_id=case.id, response_summary=receipt)
            return api_base.ok(request, {"receipt": receipt, "replayed": False})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


def _material_command(request, material_id, action, case_id=None):
    from django.db import transaction
    from hr_onboarding.api.exceptions import VersionConflictError
    from hr_onboarding.services.idempotency_service import DurableIdempotencyService
    new_file_path = None
    committed = False
    try:
        ctx = api_base.make_hr05_context(request)
        with transaction.atomic():
            existing = _load_material_or_404(ctx, material_id)
            service = MaterialService(tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id)
            material = service._lock_material(existing)  # parent → child lock ordering
            if case_id and str(case_id) != str(material.case_id): raise NotFoundError("材料不属于该入职单")
            fingerprint = request.headers.get("If-Match", "").strip('"')
            if not fingerprint: raise Hr05ApiError("请先读取材料最新版本后提交")
            fields = {k: request.POST.get(k, "").strip() for k in ("reason", "result", "evidence")}
            if any(len(v)>2000 for v in fields.values()): raise Hr05ApiError("说明不得超过2000字")
            upload = request.FILES.get("file") if action == "upload" else None
            payload = {"actor": ctx.user_id, "material": str(material.id), "version": fingerprint, "fields": fields}
            if action == "upload":
                if upload is None: raise Hr05ApiError("缺少文件字段 file")
                try:
                    meta = file_service.validate_upload(upload, allowed_formats=material.requirement.allowed_formats or None,
                        max_size_mb=material.requirement.max_size/(1024*1024) if material.requirement.max_size else None)
                except ValueError as exc: raise Hr05ApiError("文件不符合材料要求：" + str(exc)) from exc
                payload["file"] = meta
            idem = DurableIdempotencyService(tenant_id=ctx.tenant_id, operation="material." + action)
            claim = idem.claim(idempotency_key=api_base.get_idempotency_key(request), request_payload=payload)
            if claim.is_replay:
                return api_base.ok(request, {"material_id": str(material.id), "status": material.status,
                    "item": material_projection(material, request.user), "receipt": claim.record.response_summary, "replayed": True})
            if fingerprint != material_fingerprint(material): raise VersionConflictError("材料已更新，请核对最新文件与状态后再办理")
            if action not in material_projection(material, request.user)["actions"]:
                raise Hr05ApiError("当前材料状态或权限不允许此操作")
            before = material_fingerprint(material)
            if action != "upload" and not fields["reason"]: raise Hr05ApiError("请填写本次办理依据")
            if action == "upload":
                updated = service.submit_material(material.case, material.requirement_id, upload)
                m = updated.file_meta_json
                new_file_path = file_service.material_storage_path(tenant_id=ctx.tenant_id, case_id=material.case_id,
                    material_id=material.id, file_version_id=m["file_version_id"], ext=m["ext"])
            elif action == "verify":
                result = fields["result"] or VerificationResult.VERIFIED
                if result not in VerificationResult.values: raise Hr05ApiError("核验结果不合法")
                if not fields["evidence"]: raise Hr05ApiError("核验须填写依据或凭证编号")
                updated = service.verify_material(material, result=result, reason=fields["reason"], evidence={"evidence": fields["evidence"]})
            elif action == "return": updated = service.return_material(material, reason=fields["reason"])
            elif action == "waive": updated = service.waive_material(material, reason=fields["reason"])
            else: raise Hr05ApiError("不支持此材料动作")
            event = HrOnboardingAuditEvent.objects.create(tenant_id=ctx.tenant_id, case_id=material.case_id,
                actor_user_id=ctx.user_id, action="MATERIAL_" + action.upper(), business_type="MATERIAL", business_id=str(material.id),
                before_snapshot_ref=before, after_snapshot_ref=material_fingerprint(updated),
                reason=fields["reason"], request_id=api_base._request_id(request))
            receipt = {"id": str(event.id), "action": action, "material_id": str(material.id), "status": updated.status,
                "actor_user_id": ctx.user_id, "occurred_at": event.occurred_at.isoformat()}
            idem.succeed(claim.record, authority_type="HrOnboardingMaterial", authority_id=material.id, response_summary=receipt)
            result_data = {"material_id": str(updated.id), "status": updated.status,
                "item": material_projection(updated, request.user), "receipt": receipt, "replayed": False}
        committed = True
        return api_base.ok(request, result_data)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    finally:
        # File storage is not transactional: remove only the newly written file
        # after a DB/audit rollback. Never remove the previous committed version.
        if new_file_path and not committed and default_storage.exists(new_file_path):
            default_storage.delete(new_file_path)


@require_POST
@require_hr05_permission("hr05.material.review")
def material_submit(request, case_id: str, material_id: str):
    return _material_command(request, material_id, "upload", case_id)


@require_POST
@require_hr05_permission("hr05.material.review")
def material_verify(request, material_id: str):
    return _material_command(request, material_id, "verify")


@require_POST
@require_hr05_permission("hr05.material.review")
def material_return(request, material_id: str):
    return _material_command(request, material_id, "return")


@require_POST
@require_hr05_permission("hr05.material.review")
def material_waive(request, material_id: str):
    return _material_command(request, material_id, "waive")


@require_POST
@require_hr05_permission("hr05.material.review")
def material_download_ticket(request, material_id: str):
    try:
        context = api_base.make_hr05_context(request)
        material = _load_material_or_404(context, material_id)
        purpose = str(request.headers.get("X-HR-Access-Reason", "") or "").strip()
        if not purpose:
            raise Hr05ApiError(
                "下载入职材料前请填写查阅事由",
                details={"code": "MATERIAL_DOWNLOAD_PURPOSE_REQUIRED"},
            )
        try:
            ticket = file_service.issue_download_ticket(
                tenant_id=context.tenant_id,
                material=material,
                actor_user_id=context.user_id,
                purpose=purpose,
                request_id=str(request.headers.get("X-Request-ID", "") or ""),
            )
        except ValueError as exc:
            raise Hr05ApiError(
                "当前材料尚无可下载文件或查阅事由无效",
                details={"code": str(exc)},
            ) from exc
        return api_base.ok(request, {"ticket": ticket, "expiresInSeconds": file_service.TICKET_TTL_SECONDS})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_GET
@require_hr05_permission("hr05.material.review")
def material_download(request):
    """从请求头原子消费账号绑定票据并写入正式访问审计。"""
    try:
        context = api_base.make_hr05_context(request)
        ticket = request.headers.get("X-HR-Download-Ticket")
        if not ticket:
            raise MaterialDownloadTicketError("下载票据缺失")
        try:
            ticket_record = file_service.consume_download_ticket(
                ticket=ticket,
                tenant_id=context.tenant_id,
                actor_user_id=context.user_id,
            )
        except ValueError as exc:
            raise MaterialDownloadTicketError("下载票据无效、已过期或已使用") from exc
        material = ticket_record.material
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
        stream = default_storage.open(path, "rb")
        try:
            HrOnboardingAuditEvent.objects.create(
                tenant_id=context.tenant_id,
                case_id=material.case_id,
                actor_user_id=context.user_id,
                action="material.downloaded",
                business_type="MATERIAL",
                business_id=str(material.id),
                after_snapshot_ref=str(meta.get("sha256", "") or "")[:128],
                reason=ticket_record.purpose,
                request_id=ticket_record.request_id,
            )
        except Exception as exc:
            stream.close()
            raise MaterialDownloadAuditUnavailableError(
                "材料访问审计暂时不可用，请稍后重新申请下载票据"
            ) from exc
        response = FileResponse(stream, as_attachment=True, filename=name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
