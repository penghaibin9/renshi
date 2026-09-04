"""
hr_external/api/materials.py —— 外聘材料与安全下载 ticket API（B5，总册 §92）。

路由：
- GET  /api/hr/v1/external-teachers/{profile_id}/materials            材料列表
- POST /api/hr/v1/external-teachers/{profile_id}/materials            登记材料（元数据）
- POST /api/hr/v1/external-teachers/materials/{material_id}/upload    上传写入私有存储
- POST /api/hr/v1/external-teachers/materials/{material_id}/download-ticket  签发票据
- GET  /api/hr/v1/external-teachers/file-ticket                       兑换票据（票据仅通过请求头传递）
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.views.decorators.http import require_GET, require_POST

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.models import HrExternalMaterial
from hr_external.permissions import require_hr_external_permission
from hr_external.services.audit_service import write_external_audit
from hr_external.services.material_service import (
    MAX_MATERIAL_SIZE,
    MaterialAccessDenied,
    MaterialFileRejected,
    MaterialInputInvalid,
    MaterialService,
    TicketInvalid,
    validate_material_file,
)
from hr_external.services.storage_backends import get_material_storage

logger = logging.getLogger(__name__)


def _extract_ticket_token(request) -> str:
    """只从 header 取 ticket，禁止 URL/access log/浏览器历史泄漏。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    header = request.headers.get("X-Portal-Token", "")
    if header:
        return header.strip()
    return ""


def _ctx(request):
    try:
        return make_external_context(request), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_hr_external_permission("hr08.profile.view")
def material_collection(request, profile_id):
    """GET/POST /api/hr/v1/external-teachers/{profile_id}/materials"""
    if request.method == "POST":
        return _material_create(request, profile_id)
    if request.method == "GET":
        return _material_list(request, profile_id)
    return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 GET 或 POST", 405)


@require_GET
@require_hr_external_permission("hr08.profile.view")
def _material_list(request, profile_id):
    ctx, err = _ctx(request)
    if err:
        return err
    qs = HrExternalMaterial.objects.filter(
        tenant_id=ctx.tenant_id, external_profile_id_id=profile_id
    ).order_by("-updated_at")
    body = api_root(request)
    body["data"] = {
        "items": [
            {
                "id": str(m.id),
                "category": m.category,
                "title": m.title,
                "sensitivityLevel": m.sensitivity_level,
                "versionNo": m.version_no,
                "status": m.status,
                "originalFilename": m.original_filename,
                "sha256": m.sha256,
                "hasFile": bool(m.storage_ref),
            }
            for m in qs
        ],
        "total": qs.count(),
    }
    return json_response(request, body)


@require_POST
@require_hr_external_permission("hr08.profile.sensitive_view")
def _material_create(request, profile_id):
    """POST .../{profile_id}/materials body: {category, title, sensitivityLevel?}。"""
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        m = MaterialService().create_material(
            tenant_id=ctx.tenant_id,
            external_profile_id=profile_id,
            category=payload.get("category") or "OTHER",
            title=payload.get("title") or "",
            sensitivity_level=payload.get("sensitivityLevel") or "SENSITIVE",
            uploaded_by=ctx.user_id,
        )
    except MaterialInputInvalid as exc:
        return error_response(request, exc.code, str(exc), 400)
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), 404)

    body = api_root(request)
    body["data"] = {"id": str(m.id), "title": m.title, "status": m.status}
    return json_response(request, body, status=201)


@require_POST
@require_hr_external_permission("hr08.profile.sensitive_view")
def material_download_ticket(request, material_id):
    """POST .../materials/{material_id}/download-ticket body: {purpose} → 一次性票据。"""
    ctx, err = _ctx(request)
    if err:
        return err
    material = HrExternalMaterial.objects.filter(
        tenant_id=ctx.tenant_id, id=material_id
    ).first()
    if material is None:
        return error_response(request, "INVALID_REQUEST", "材料不存在", 404)
    try:
        payload = json.loads(request.body or b"{}")
        purpose = str(payload.get("purpose") or "").strip()
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)
    if not purpose:
        return error_response(request, "AUDIT_REASON_REQUIRED", "请填写下载用途", 400)
    if len(purpose) > 512:
        return error_response(request, "INVALID_REQUEST", "下载用途不得超过 512 个字符", 400)

    service = MaterialService()
    token = service.sign_token(tenant_id=ctx.tenant_id, material_id=str(material.id))
    try:
        ticket = service.issue_ticket(
            tenant_id=ctx.tenant_id,
            material=material,
            actor_user_id=ctx.user_id,
            purpose=purpose,
            token=token,  # 保证 hash 与返回给前端的 token 一致
        )
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), 409)
    body = api_root(request)
    body["data"] = {
        "ticket": token,
        "expiresAt": ticket.expires_at.isoformat(),
        "maxUses": ticket.max_uses,
        # 生产级（A32）：downloadUrl 不内嵌 token（避免进日志/历史）；
        # 下载请带 Authorization: Bearer <ticket> 或 X-Portal-Token 头。
        "downloadPath": "/api/v1/hr/external-teachers/file-ticket",
    }
    return json_response(request, body)


@require_POST
@require_hr_external_permission("hr08.profile.sensitive_view")
def material_upload(request, material_id):
    """POST .../materials/{material_id}/upload (multipart: file)
    写入私有存储（0600，不进 /media/ 裸路径），更新 SHA-256/大小/MIME（任务 2）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    material = HrExternalMaterial.objects.filter(
        tenant_id=ctx.tenant_id, id=material_id
    ).first()
    if material is None:
        return error_response(request, "INVALID_REQUEST", "材料不存在", 404)

    uploaded = request.FILES.get("file")
    if uploaded is None:
        return error_response(request, "INVALID_REQUEST", "缺少 file 字段", 400)
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        uploaded, "_malware_scan_complete", False
    ):
        return error_response(
            request, "MALWARE_SCAN_REQUIRED", "材料尚未通过安全检查", 503
        )
    if int(getattr(uploaded, "size", 0) or 0) > MAX_MATERIAL_SIZE:
        return error_response(request, "MATERIAL_FILE_REJECTED", "文件超过 50MB 限制", 400)

    content_buffer = bytearray()
    for chunk in uploaded.chunks():
        content_buffer.extend(chunk)
        if len(content_buffer) > MAX_MATERIAL_SIZE:
            return error_response(request, "MATERIAL_FILE_REJECTED", "文件超过 50MB 限制", 400)
    content = bytes(content_buffer)
    try:
        validate_material_file(
            filename=uploaded.name or "",
            content=content,
            declared_mime=getattr(uploaded, "content_type", "") or "",
        )
    except MaterialFileRejected as exc:
        return error_response(request, exc.code, str(exc), 400)

    storage = get_material_storage()
    old_ref = material.storage_ref
    new_ref = ""
    try:
        with transaction.atomic():
            material = MaterialService().save_material_file(
                material=material,
                tenant_id=ctx.tenant_id,
                content=content,
                original_filename=uploaded.name or "",
                mime_type=getattr(uploaded, "content_type", "") or "",
                storage=storage,
            )
            new_ref = material.storage_ref
            write_external_audit(
                tenant_id=ctx.tenant_id,
                action="ExternalMaterialUploaded",
                actor_user_id=ctx.user_id,
                external_profile_id=material.external_profile_id_id,
                business_type="HR08_MATERIAL",
                business_id=str(material.id),
                source="api",
            )
    except (MaterialAccessDenied, MaterialFileRejected) as exc:
        return error_response(request, exc.code, str(exc), 409)
    except Exception:  # audit/DB fail-closed; rollback leaves old metadata authoritative
        if new_ref and new_ref != old_ref:
            storage.delete(new_ref)
        logger.exception("HR08 material upload transaction failed")
        return error_response(
            request, "MATERIAL_AUDIT_UNAVAILABLE", "材料上传审计暂不可用，请稍后重试", 503
        )
    body = api_root(request)
    body["data"] = {
        "id": str(material.id),
        "hasFile": True,
        "sizeBytes": material.size_bytes,
        "sha256": material.sha256,
        "note": "私有存储，下载需 HMAC ticket（00 §34）",
    }
    return json_response(request, body)


@require_GET
def file_ticket_redeem(request):
    """GET .../file-ticket → 校验一次性票据并流式下载材料。

    ticket 本身即授权（HMAC + 时效 + 次数 + 绑定 tenant），不要求登录/HR 权限——
    外聘本人持有效票据即可下载（§90/§92）；下载动作已审计。
    生产级：token 只从 Authorization: Bearer / X-Portal-Token 头取。
    """
    token = _extract_ticket_token(request)
    if not token:
        return error_response(request, "INVALID_REQUEST", "缺少 token", 400)
    try:
        material = MaterialService().redeem_ticket(token=token)
    except (TicketInvalid, MaterialAccessDenied) as exc:
        return error_response(request, exc.code, str(exc), 403)

    try:
        stream = MaterialService().open_authorized_stream(material)
    except MaterialAccessDenied:
        return error_response(request, "MATERIAL_ACCESS_DENIED", "文件不存在", 404)
    response = FileResponse(
        stream,
        as_attachment=True,
        filename=material.original_filename or material.title,
        content_type=material.mime_type or "application/octet-stream",
    )
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
