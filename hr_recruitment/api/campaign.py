"""
hr_recruitment/api/campaign.py

HR04-02 招聘项目与岗位 API（总册 9）。

  GET  /api/hr/v1/recruitment/campaigns
  POST /api/hr/v1/recruitment/campaigns
  GET  /api/hr/v1/recruitment/campaigns/{id}
  POST /api/hr/v1/recruitment/campaigns/{id}/publish
  POST /api/hr/v1/recruitment/campaigns/{id}/status      {target}
  POST /api/hr/v1/recruitment/campaigns/{id}/announcements
  POST /api/hr/v1/recruitment/positions
  POST /api/hr/v1/recruitment/positions/{id}/ready
  POST /api/hr/v1/recruitment/positions/{id}/open
  POST /api/hr/v1/recruitment/positions/{id}/cancel
  GET  /api/hr/v1/recruitment/console

硬规则：
- tenant fail-closed 403；权限 hr04.campaign.*。
- READY 必须预占 HR02（make_ready）；预占失败 → POSITION_CAPACITY_CONFLICT。
- 公告发布后不可改（走 amendment）。
"""

from __future__ import annotations

import json
import uuid

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.selectors import campaign as campaign_selector
from hr_recruitment.services.campaign_service import CampaignService, CampaignServiceError


def _service(request):
    ctx = make_hr04_context(request)
    return CampaignService(tenant_id=ctx.tenant_id, actor=str(request.user.id)), ctx


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

    if isinstance(exc, ObjectDoesNotExist):
        return error(request, "NOT_FOUND", "资源不存在", 404)
    if isinstance(exc, (Hr04ApiError, CampaignServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def console(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.view")):
        return error(request, "PERMISSION_DENIED", "无查看招聘控制台权限", 403)
    try:
        return ok(request, campaign_selector.console_summary(tenant_id=ctx.tenant_id))
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def list_campaigns(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.view")):
        return error(request, "PERMISSION_DENIED", "无查看招聘项目权限", 403)
    try:
        return ok(
            request,
            campaign_selector.list_campaigns(
                tenant_id=ctx.tenant_id,
                status=request.GET.get("status"),
                page=int(request.GET.get("page", 1)),
                page_size=int(request.GET.get("page_size", 20)),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_campaign(request):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.manage")):
        return error(request, "PERMISSION_DENIED", "无创建招聘项目权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        campaign = service.create_campaign(
            code=body.get("code"),
            title=body.get("title"),
            campaign_type=body.get("campaign_type", "MULTI_POSITION"),
            plan_cycle_id=body.get("plan_cycle_id"),
            application_open_at=body.get("application_open_at"),
            application_close_at=body.get("application_close_at"),
            timezone=body.get("timezone", "Asia/Shanghai"),
            manager_employee_ids=body.get("manager_employee_ids"),
            description=body.get("description", ""),
        )
        return ok(request, {"id": str(campaign.id), "public_slug": campaign.public_slug}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def campaign_detail(request, campaign_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.view")):
        return error(request, "PERMISSION_DENIED", "无查看招聘项目权限", 403)
    data = campaign_selector.get_campaign(tenant_id=ctx.tenant_id, campaign_id=campaign_id)
    if data is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在", 404)
    return ok(request, data)


@require_http_methods(["POST"])
def campaign_status(request, campaign_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.manage")):
        return error(request, "PERMISSION_DENIED", "无操作招聘项目权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        target = body.get("target")
        campaign = service.transition_campaign(campaign_id, target=target)
        return ok(request, {"id": str(campaign.id), "status": campaign.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def publish_campaign(request, campaign_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.publish")):
        return error(request, "PERMISSION_DENIED", "无发布招聘项目权限", 403)
    try:
        campaign = service.transition_campaign(campaign_id, target="PUBLISHED")
        return ok(request, {"id": str(campaign.id), "status": campaign.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_announcement(request, campaign_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.manage")):
        return error(request, "PERMISSION_DENIED", "无创建公告权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        ann = service.create_announcement(
            campaign_id=campaign_id,
            title=body.get("title"),
            content=body.get("content", ""),
            change_reason=body.get("change_reason", ""),
        )
        return ok(request, {"id": str(ann.id), "version_no": ann.version_no}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_position(request):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.manage")):
        return error(request, "PERMISSION_DENIED", "无创建招聘岗位权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        position = service.create_position(
            campaign_id=body.get("campaign_id"),
            post_catalog_id=body.get("post_catalog_id"),
            post_catalog_name=body.get("post_catalog_name", ""),
            organization_id=body.get("organization_id"),
            organization_name=body.get("organization_name", ""),
            hiring_plan_line_id=body.get("hiring_plan_line_id"),
            position_id=body.get("position_id"),
            position_pool_id=body.get("position_pool_id"),
            planned_headcount=int(body.get("planned_headcount", 1)),
            min_hires=int(body.get("min_hires", 1)),
            max_hires=int(body.get("max_hires", 1)),
            description=body.get("description", ""),
        )
        return ok(request, {"id": str(position.id)}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


def _position_action(request, position_id, action):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.campaign.manage")):
        return error(request, "PERMISSION_DENIED", "无操作招聘岗位权限", 403)
    try:
        if action == "ready":
            position = service.make_ready(position_id)
        elif action == "open":
            position = service.open_position(position_id)
        elif action == "cancel":
            position = service.cancel_position(position_id)
        else:
            return error(request, "INVALID_ACTION", "非法操作", 422)
        return ok(request, {"id": str(position.id), "status": position.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def position_ready(request, position_id):
    return _position_action(request, position_id, "ready")


@require_POST
def position_open(request, position_id):
    return _position_action(request, position_id, "open")


@require_POST
def position_cancel(request, position_id):
    return _position_action(request, position_id, "cancel")
