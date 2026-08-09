"""
hr_staff/api/sensitive.py —— 高敏字段 reveal + 身份证 exact 搜索（总册 §29，补接线）。

POST /api/hr/v1/staff/{staff_id}/sensitive-fields/{field_code}/reveal
  {"purpose": "核对入职身份证明"} → {"value","expiresAt","maskAfterSeconds"}
GET  /api/hr/v1/staff/search-by-identity?documentNumber=...  身份证 exact 查人
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import (
    has_sensitive_view,
    require_hr_staff_permission,
)
from hr_staff.services.sensitive_field_service import (
    SensitiveFieldDenied,
    SensitiveFieldNotFound,
    SensitiveFieldService,
)

SCHEMA_REVEAL = "hr03.sensitive-reveal.1"
SCHEMA_SEARCH = "hr03.identity-search.1"


@require_POST
@require_hr_staff_permission("hr.staff.view_sensitive")
def reveal_field(request, staff_id, field_code):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        body = {}
    purpose = body.get("purpose", "")

    # HIGH_SENSITIVE 需要 reveal_high_sensitive 权限
    if field_code == "identity.document_number":
        has_perm = has_sensitive_view(request.user, "HIGH_SENSITIVE")
    else:
        has_perm = has_sensitive_view(request.user, "SENSITIVE")

    svc = SensitiveFieldService(
        context.tenant_id, actor_user_id=request.user.id, context=context
    )
    try:
        data = svc.reveal(
            staff_id=staff_id,
            field_code=field_code,
            purpose=purpose,
            has_permission=has_perm,
        )
    except SensitiveFieldDenied as exc:
        return error_response(request, "SENSITIVE_FIELD_DENIED", str(exc), status=403)
    except SensitiveFieldNotFound as exc:
        return error_response(
            request, "SENSITIVE_FIELD_DENIED", str(exc), status=404
        )
    except Exception as exc:  # N3：跨租户/不存在统一 404，不泄漏存在性
        code = getattr(exc, "code", "")
        if code in ("STAFF_NOT_FOUND", "CROSS_TENANT_REFERENCE", "STAFF_SCOPE_DENIED"):
            return error_response(request, "SENSITIVE_FIELD_DENIED", "无权访问该数据", status=404)
        raise

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_REVEAL
    payload["data"] = data
    return json_response(request, payload)


@require_GET
@require_hr_staff_permission("hr.staff.reveal_high_sensitive")
def search_by_identity(request):
    """
    身份证 exact 查人（普通 keyword 不支持身份证明文模糊搜索）。
    - exact match + fingerprint + permission + purpose + audit。
    """
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    document_number = (request.GET.get("documentNumber") or "").strip()
    purpose = (request.GET.get("purpose") or "").strip()
    if not document_number:
        return error_response(request, "INVALID_REQUEST", "documentNumber 必填", status=400)
    if not purpose:
        return error_response(request, "INVALID_REQUEST", "purpose 必填", status=400)

    from hr_staff.models import HrPersonIdentityDocument, HrStaffMaster
    from hr_staff.services.crypto import document_fingerprint, normalize_document_number

    fp = document_fingerprint(context.tenant_id, normalize_document_number(document_number))
    doc = (
        HrPersonIdentityDocument.objects.filter(
            tenant_id=context.tenant_id, document_number_fingerprint=fp
        )
        .select_related("person_id")
        .first()
    )
    staff = None
    if doc:
        staff = HrStaffMaster.objects.filter(
            tenant_id=context.tenant_id, person_id=doc.person_id
        ).first()
        if staff:
            # §29.2/§43.4：身份证查人也必须服从 data scope（COLLEGE 不可查他院）
            from hr_staff.policies.scope_policy import ScopeEnforcer

            ScopeEnforcer(context).assert_accessible(staff)

    # 审计（无论是否命中都记录，防探测）
    from hr_staff.models import HrSensitiveAccessLog

    HrSensitiveAccessLog.objects.create(
        tenant_id=context.tenant_id,
        staff_id=staff.id if staff else None,
        field_code="identity.search",
        actor_user_id=request.user.id,
        purpose=purpose,
        action="SEARCH",
    )

    if staff is None:
        # P2：命中/未命中统一 200 + null data（防存在性探测）
        payload = api_root(request)
        payload["schemaVersion"] = SCHEMA_SEARCH
        payload["data"] = None
        return json_response(request, payload)

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_SEARCH
    payload["data"] = {
        "staffId": str(staff.id),
        "staffNo": staff.staff_no,
        "legalName": doc.person_id.legal_name,
        "maskedIdentityNo": doc.masked_display,
    }
    return json_response(request, payload)
