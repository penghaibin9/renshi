"""
hr_staff/api/materials.py —— HR03-05 材料档案 API（S8）。

GET  /api/hr/v1/staff/{staff_id}/materials
GET  /api/hr/v1/staff/{staff_id}/materials/{material_id}/versions
POST /api/hr/v1/staff/{staff_id}/materials/{material_id}/download-ticket
POST /api/hr/v1/staff/{staff_id}/materials/{material_id}/verify

禁止返回 /media/ 裸 URL；下载必须走 ticket。
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
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.selectors.materials import MaterialSelector, StaffNotFound
from hr_staff.services.material_service import MaterialAccessDenied, MaterialService
SCHEMA_MATERIALS = "hr03.materials.1"


def _make(request):
    try:
        return make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)


@require_GET
@require_hr_staff_permission("hr.staff.material.view")
def materials(request, staff_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    try:
        data = MaterialSelector(resp).list_materials(staff_id)
    except StaffNotFound:
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_MATERIALS
    payload["data"] = data
    return json_response(request, payload)


@require_GET
@require_hr_staff_permission("hr.staff.material.view")
def material_versions(request, staff_id, material_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    try:
        data = MaterialSelector(resp).version_history(staff_id, material_id)
    except StaffNotFound:
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_MATERIALS
    payload["data"] = data
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.material.download_sensitive")
def material_download_ticket(request, staff_id, material_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        body = {}
    purpose = body.get("purpose", "")
    svc = MaterialService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        # P1-11：传入 staff_id 做归属校验；sensitive_ok 按材料实际灵敏度由服务层分级检查，
        # 不再恒传 ok（权限装饰器已校验 download_sensitive 权限）。
        ticket = svc.issue_download_ticket(
            staff_id=staff_id,
            material_id=material_id,
            purpose=purpose,
            permission_ok=True,
            sensitive_ok=True,
        )
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_MATERIALS
    payload["data"] = ticket
    return json_response(request, payload)


@require_GET
def material_download(request, staff_id, material_id, ticket):
    """
    GET /api/hr/v1/staff/{staff_id}/materials/{material_id}/download?ticket=...
    消费票据并返回文件（受控存储读取）。不返回 /media/ 裸 URL。
    无票 → 403；票据不属于该 staff/材料 → 403。
    """
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)
    svc = MaterialService(context.tenant_id, actor_user_id=request.user.id)
    try:
        # N7：归属校验传入 URL staff/material，不匹配不烧票
        data = svc.consume_download_ticket(
            ticket,
            expected_staff_id=staff_id,
            expected_material_id=material_id,
        )
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_MATERIALS
    payload["data"] = data
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.material.verify")
def material_verify(request, staff_id, material_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    svc = MaterialService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        # P2：校验 URL staff 归属（与 ticket 路径一致），拒绝跨人员核验
        material = svc.verify_material(material_id=material_id, staff_id=staff_id)
    except MaterialAccessDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_MATERIALS
    payload["data"] = {"id": str(material.id), "verificationStatus": material.verification_status}
    return json_response(request, payload)
