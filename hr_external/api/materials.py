"""
hr_external/api/materials.py —— 外聘材料与安全下载 ticket API（B5，总册 §92）。

路由：
- GET  /api/hr/v1/external-teachers/{profile_id}/materials            材料列表
- POST /api/hr/v1/external-teachers/{profile_id}/materials            登记材料（元数据）
- POST /api/hr/v1/external-teachers/materials/{material_id}/upload    上传写入私有存储
- POST /api/hr/v1/external-teachers/materials/{material_id}/download-ticket  签发票据
- GET  /api/hr/v1/external-teachers/file-ticket?token=...             兑换票据（流式下载/返回引用）
"""

from __future__ import annotations

import json

from django.http import FileResponse

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.models import HrExternalMaterial
from hr_external.permissions import require_hr_external_permission


def _extract_ticket_token(request) -> str:
    """优先从 header 取 ticket（避免 URL/access log 泄漏），兼容旧 query 参数。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    header = request.headers.get("X-Portal-Token", "")
    if header:
        return header.strip()
    return (request.GET.get("token") or "").strip()
from hr_external.services.material_service import (
    MaterialAccessDenied,
    MaterialService,
    TicketInvalid,
)


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_hr_external_permission("hr08.profile.view")
def material_collection(request, profile_id):
    """GET/POST /api/hr/v1/external-teachers/{profile_id}/materials"""
    if request.method == "POST":
        return _material_create(request, profile_id)
    return _material_list(request, profile_id)


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
            }
            for m in qs
        ],
        "total": qs.count(),
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.sensitive_view")
def _material_create(request, profile_id):
    """POST .../{profile_id}/materials body: {category, title, storageRef?, originalFilename?, mimeType?, sizeBytes?, sha256?}"""
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
            storage_ref=payload.get("storageRef") or "",
            original_filename=payload.get("originalFilename") or "",
            mime_type=payload.get("mimeType") or "",
            size_bytes=payload.get("sizeBytes") or 0,
            sha256=payload.get("sha256") or "",
            sensitivity_level=payload.get("sensitivityLevel") or "SENSITIVE",
            uploaded_by=ctx.user_id,
        )
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), 404)

    body = api_root(request)
    body["data"] = {"id": str(m.id), "title": m.title, "status": m.status}
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.profile.sensitive_view")
def material_download_ticket(request, material_id):
    """POST .../materials/{material_id}/download-ticket body: {purpose?} → 短时效票据。"""
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
        purpose = payload.get("purpose") or ""
    except json.JSONDecodeError:
        purpose = ""

    service = MaterialService()
    token = service.sign_token(tenant_id=ctx.tenant_id, material_id=str(material.id))
    ticket = service.issue_ticket(
        tenant_id=ctx.tenant_id,
        material=material,
        actor_user_id=ctx.user_id,
        purpose=purpose,
        token=token,  # 保证 hash 与返回给前端的 token 一致
    )
    body = api_root(request)
    body["data"] = {
        "ticket": token,
        "expiresAt": ticket.expires_at.isoformat(),
        "maxUses": ticket.max_uses,
        # 生产级（A32）：downloadUrl 不内嵌 token（避免进日志/历史）；
        # 下载请带 Authorization: Bearer <ticket> 或 X-Portal-Token 头。
        "downloadPath": "/api/hr/v1/external-teachers/file-ticket",
    }
    return json_response(request, body)


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

    content = uploaded.read()
    try:
        # 生产级：扩展名 + magic bytes + 大小校验（service 层统一入口）
        from hr_external.services.material_service import (
            MaterialFileRejected,
            validate_material_file,
        )

        validate_material_file(
            filename=uploaded.name or "", content=content
        )
    except MaterialFileRejected as exc:
        return error_response(request, exc.code, str(exc), 400)

    material = MaterialService().save_material_file(
        material=material,
        tenant_id=ctx.tenant_id,
        content=content,
        original_filename=uploaded.name or "",
        mime_type=getattr(uploaded, "content_type", "") or "",
    )
    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalMaterialUploaded",
        actor_user_id=ctx.user_id,
        external_profile_id=material.external_profile_id_id,
        business_type="HR08_MATERIAL",
        business_id=str(material.id),
        source="api",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(material.id),
        "storageRef": material.storage_ref,
        "sizeBytes": material.size_bytes,
        "sha256": material.sha256,
        "note": "私有存储，下载需 HMAC ticket（00 §34）",
    }
    return json_response(request, body)


def file_ticket_redeem(request):
    """GET .../file-ticket → 校验票据并返回材料（有文件则流式下载，否则返回引用）。

    ticket 本身即授权（HMAC + 时效 + 次数 + 绑定 tenant），不要求登录/HR 权限——
    外聘本人持有效票据即可下载（§90/§92）；下载动作已审计。
    生产级：token 优先从 Authorization: Bearer / X-Portal-Token 头取（避免 URL 日志泄漏）。
    """
    token = _extract_ticket_token(request)
    if not token:
        return error_response(request, "INVALID_REQUEST", "缺少 token", 400)
    try:
        material = MaterialService().redeem_ticket(token=token)
    except (TicketInvalid, MaterialAccessDenied) as exc:
        return error_response(request, exc.code, str(exc), 403)

    # 文件存在 → 流式下载（ticket 已校验+已审计）
    if material.storage_ref:
        try:
            stream = MaterialService().open_authorized_stream(material)
        except MaterialAccessDenied:
            return error_response(request, "MATERIAL_ACCESS_DENIED", "文件不存在", 404)
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=material.original_filename or material.title,
        )
        response["Cache-Control"] = "no-store"
        # 生产级：防 MIME sniffing（即使附件下载也加 nosniff）
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    body = api_root(request)
    body["data"] = {
        "materialId": str(material.id),
        "title": material.title,
        "storageRef": material.storage_ref,
        "originalFilename": material.original_filename,
        "mimeType": material.mime_type,
        "sizeBytes": material.size_bytes,
        "sha256": material.sha256,
        "note": "private storage + short signed URL（00 §34）；下载已审计",
    }
    return json_response(request, body)
