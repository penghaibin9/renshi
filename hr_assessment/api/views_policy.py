"""
HR12 Assessment — API 视图（生产级）。

模式：plain Django FBV + require_assessment_permission 装饰器 + context resolution。
"""

from __future__ import annotations

import json
from typing import Any, Dict

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hr_assessment.api.response import api_error, api_success, paginated_response
from hr_assessment.context import resolve_tenant_from_assignment, build_assessment_context
from hr_assessment.permissions import require_assessment_permission
from hr_assessment.selectors import (
    SelectorContext,
    PolicySelector,
    IndicatorSelector,
    RatingScaleSelector,
)
from hr_assessment.service import PolicyPackService


def _get_tenant(request: HttpRequest) -> int:
    t = resolve_tenant_from_assignment(request)
    if t is None:
        raise PermissionDenied("租户上下文缺失")
    return t


# ═══════════════════════════════════════════
# S1 health / probe
# ═══════════════════════════════════════════

def ping(request: HttpRequest) -> JsonResponse:
    return JsonResponse(api_success(data={"status": "ok", "module": "hr_assessment"}))


def eligibility_probe(request: HttpRequest) -> JsonResponse:
    t = _get_tenant(request)
    return JsonResponse(api_success(data={
        "tenantId": t,
        "providerStatus": {
            "hr03": "OK", "hr07": "OK", "hr09": "OK",
            "hr10": "UNAVAILABLE", "hr11": "OK",
            "academic": "UNAVAILABLE", "research": "UNAVAILABLE",
            "ethicsFact": "UNAVAILABLE",
        },
    }))


# ═══════════════════════════════════════════
# S2 Policy API
# ═══════════════════════════════════════════

@csrf_exempt
@require_assessment_permission("hr.assessment.policy.admin")
@require_http_methods(["GET", "POST"])
def policy_list(request: HttpRequest) -> JsonResponse:
    tenant = _get_tenant(request)
    ctx = build_assessment_context(tenant_id=tenant)
    sc = SelectorContext.from_request_context(ctx)

    if request.method == "GET":
        packs = PolicySelector().list_policy_packs(sc)
        return JsonResponse(api_success(data=[
            {"id": str(p.id), "code": p.code, "name": p.name, "assessment_domain": p.assessment_domain}
            for p in packs
        ]))

    body = json.loads(request.body)
    pack = PolicyPackService().create_pack(
        tenant_id=tenant, code=body["code"], name=body["name"],
        assessment_domain=body.get("assessment_domain", "ANNUAL"),
    )
    return JsonResponse(api_success(data={"id": str(pack.id), "code": pack.code}), status=201)


@csrf_exempt
@require_assessment_permission("hr.assessment.policy.admin")
@require_http_methods(["GET", "PUT"])
def policy_detail(request: HttpRequest, policy_id: int) -> JsonResponse:
    from hr_assessment.models.policy import HrAssessmentPolicyPack, HrAssessmentPolicyVersion
    tenant = _get_tenant(request)
    try:
        pack = HrAssessmentPolicyPack.objects.get(id=policy_id, tenant_id=tenant)
    except HrAssessmentPolicyPack.DoesNotExist:
        return JsonResponse(api_error("ASSESSMENT_POLICY_NOT_FOUND", "政策未找到", http_status=404), status=404)

    if request.method == "GET":
        versions = HrAssessmentPolicyVersion.objects.filter(
            policy_pack=pack,
        ).order_by("-version_no").values("id", "version_no", "status", "effective_from", "effective_to")
        return JsonResponse(api_success(data={
            "id": str(pack.id), "code": pack.code, "name": pack.name,
            "versions": list(versions),
        }))

    body = json.loads(request.body)
    if "name" in body:
        pack.name = body["name"]
        pack.save(update_fields=["name"])
    return JsonResponse(api_success(data={"id": str(pack.id)}))


@csrf_exempt
@require_assessment_permission("hr.assessment.policy.admin")
@require_http_methods(["POST"])
def publish_policy_version(
    request: HttpRequest, policy_id: int, version_id: int,
) -> JsonResponse:
    from hr_assessment.models.policy import HrAssessmentPolicyVersion
    tenant = _get_tenant(request)
    try:
        version = HrAssessmentPolicyVersion.objects.get(
            id=version_id, policy_pack_id=policy_id, tenant_id=tenant,
        )
    except HrAssessmentPolicyVersion.DoesNotExist:
        return JsonResponse(api_error("ASSESSMENT_POLICY_NOT_FOUND", "版本未找到", http_status=404), status=404)

    try:
        PolicyPackService().publish_policy_version(version)
        return JsonResponse(api_success(data={"id": str(version.id), "status": "PUBLISHED"}))
    except Exception as e:
        return JsonResponse(api_error("ASSESSMENT_FINALIZATION_BLOCKED", str(e), http_status=409), status=409)


@require_assessment_permission("hr.assessment.analytics_view")
@require_GET
def indicator_list(request: HttpRequest) -> JsonResponse:
    tenant = _get_tenant(request)
    sc = SelectorContext.from_request_context(build_assessment_context(tenant_id=tenant))
    indicators = IndicatorSelector().list_active_indicators(sc)
    return JsonResponse(api_success(data=[
        {"id": str(i.id), "code": i.code, "name": i.name, "dimension": i.dimension}
        for i in indicators
    ]))


@require_assessment_permission("hr.assessment.analytics_view")
@require_GET
def rating_scale_list(request: HttpRequest) -> JsonResponse:
    tenant = _get_tenant(request)
    sc = SelectorContext.from_request_context(build_assessment_context(tenant_id=tenant))
    scales = RatingScaleSelector().list_scales(sc)
    return JsonResponse(api_success(data=[
        {"id": str(s.id), "scale_type": s.scale_type, "min": float(s.min_value),
         "max": float(s.max_value), "version": s.version_no, "status": s.status}
        for s in scales
    ]))
