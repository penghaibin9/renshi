"""
hr_recruitment/api/views.py

HR04 API 健康/契约探针（S1）。

hr04-api-health：验证 tenant fail-closed 合同（无学校上下文 → 403）。
hr04-api-contract：返回冻结枚举与权限码清单（契约自检）。
"""

from __future__ import annotations

from django.views.decorators.http import require_GET

from hr_recruitment import constants
from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import HR04_PERMISSIONS


@require_GET
def hr04_api_health(request):
    """GET /api/hr/v1/recruitment/health —— 验证 envelope + tenant fail-closed。"""
    try:
        make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code, exc.details)
    return ok(
        request,
        {"status": "ok", "authority_mode": request.GET.get("authority_mode", "LEGACY_RECRUITING_ONLY")},
    )


@require_GET
def hr04_api_contract(request):
    """GET /api/hr/v1/recruitment/contract —— 契约自检（S1 骨架）。"""
    return ok(
        request,
        {
            "apiVersion": "v1",
            "schemaVersion": "hr04.1",
            "permissions": list(HR04_PERMISSIONS),
            "applicationCanonicalStatuses": list(
                constants.ApplicationCanonicalStatus.values
            ),
            "campaignStatuses": list(constants.CampaignStatus.values),
            "positionStatuses": list(constants.RecruitmentPositionStatus.values),
        },
    )
