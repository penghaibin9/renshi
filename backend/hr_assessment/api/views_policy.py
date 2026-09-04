"""
HR12 Assessment — API 视图（生产级）。

模式：plain Django FBV + require_assessment_permission 装饰器 + context resolution。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import HttpRequest, JsonResponse
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
from hr_assessment.service.evidence import ProviderCollectionOrchestrator

POLICY_DOMAINS = {"ANNUAL", "TERM", "ETHICS", "SPECIAL"}


def _json_body(request: HttpRequest) -> dict | None:
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _get_tenant(request: HttpRequest) -> int:
    t = getattr(request, "tenant_id", None) or resolve_tenant_from_assignment(request)
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
        "scope": "CAPABILITY",
        "providerStatus": ProviderCollectionOrchestrator().capability_status(),
        "evidenceReadiness": "CASE_SCOPED_ONLY",
    }))


# ═══════════════════════════════════════════
# S2 Policy API
# ═══════════════════════════════════════════

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

    body = _json_body(request)
    if body is None:
        return JsonResponse(api_error("INVALID_REQUEST", "请求正文不是有效 JSON", http_status=400), status=400)
    code = str(body.get("code") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    domain = str(body.get("assessment_domain") or "ANNUAL").strip().upper()
    if not code or not name or len(code) > 50 or len(name) > 200 or domain not in POLICY_DOMAINS:
        return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "请填写有效的制度代码、名称和考核域", http_status=400), status=400)
    try:
        pack = PolicyPackService().create_pack(
            tenant_id=tenant,
            code=code,
            name=name,
            assessment_domain=domain,
        )
    except (ValidationError, IntegrityError) as exc:
        return JsonResponse(api_error("ASSESSMENT_POLICY_CONFLICT", str(exc), http_status=409), status=409)
    return JsonResponse(api_success(data={"id": str(pack.id), "code": pack.code}), status=201)


@require_assessment_permission("hr.assessment.policy.admin")
@require_http_methods(["GET", "PUT"])
def policy_detail(request: HttpRequest, policy_id: int) -> JsonResponse:
    from hr_assessment.models.policy import HrAssessmentPolicyPack, HrAssessmentPolicyVersion
    tenant = _get_tenant(request)
    if request.method == "GET":
        try:
            pack = HrAssessmentPolicyPack.objects.get(id=policy_id, tenant_id=tenant)
        except HrAssessmentPolicyPack.DoesNotExist:
            return JsonResponse(api_error("ASSESSMENT_POLICY_NOT_FOUND", "政策未找到", http_status=404), status=404)
        versions = HrAssessmentPolicyVersion.objects.filter(
            policy_pack=pack,
        ).order_by("-version_no").values("id", "version_no", "status", "effective_from", "effective_to")
        return JsonResponse(api_success(data={
            "id": str(pack.id), "code": pack.code, "name": pack.name,
            "versions": list(versions),
        }))

    body = _json_body(request)
    if body is None:
        return JsonResponse(api_error("INVALID_REQUEST", "请求正文不是有效 JSON", http_status=400), status=400)
    with transaction.atomic():
        pack = HrAssessmentPolicyPack.objects.select_for_update().filter(
            id=policy_id, tenant_id=tenant
        ).first()
        if pack is None:
            return JsonResponse(api_error("ASSESSMENT_POLICY_NOT_FOUND", "政策未找到", http_status=404), status=404)
        if "name" in body:
            name = str(body.get("name") or "").strip()
            if not name or len(name) > 200:
                return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "请填写有效的制度名称", http_status=400), status=400)
            pack.name = name
            pack.full_clean()
            pack.save(update_fields=["name", "updated_at"])
    return JsonResponse(api_success(data={"id": str(pack.id)}))


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
    except ValidationError as exc:
        return JsonResponse(api_error("ASSESSMENT_FINALIZATION_BLOCKED", str(exc), http_status=409), status=409)


@require_assessment_permission("hr.assessment.policy.admin")
@require_http_methods(["POST"])
def create_policy_version(request: HttpRequest, policy_id) -> JsonResponse:
    """Create a usable draft policy version and its explicit baseline authorities."""
    from hr_assessment.models.policy import (
        HrExcellentQuotaPolicy,
        HrAssessmentPolicyPack,
        HrAssessmentPolicyVersion,
        HrAssessmentWorkflowVersion,
        HrIndicatorSetVersion,
        HrRatingScaleVersion,
        HrResultRuleVersion,
    )

    tenant = _get_tenant(request)
    body = _json_body(request)
    if body is None:
        return JsonResponse(api_error("INVALID_REQUEST", "请求正文不是有效 JSON", http_status=400), status=400)
    try:
        effective_from = date.fromisoformat(str(body.get("effectiveFrom") or ""))
        effective_to = date.fromisoformat(str(body["effectiveTo"])) if body.get("effectiveTo") else None
    except ValueError:
        return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "请填写有效的生效日期", http_status=400), status=400)
    if effective_to and effective_to < effective_from:
        return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "失效日期不能早于生效日期", http_status=400), status=400)
    try:
        excellent_min = Decimal(str(body.get("excellentMinScore", "90")))
        qualified_min = Decimal(str(body.get("qualifiedMinScore", "60")))
        excellent_ratio = Decimal(str(body.get("excellentRatio", "0.20")))
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "分数线或优秀比例无效", http_status=400), status=400)
    if not (
        Decimal("0") < qualified_min < excellent_min <= Decimal("100")
        and Decimal("0") <= excellent_ratio <= Decimal("1")
    ):
        return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "需满足 0 < 合格线 < 优秀线 ≤ 100，优秀比例在 0% 至 100% 之间", http_status=400), status=400)
    with transaction.atomic():
        pack = HrAssessmentPolicyPack.objects.select_for_update().filter(
            id=policy_id, tenant_id=tenant
        ).first()
        if pack is None:
            return JsonResponse(api_error("ASSESSMENT_POLICY_NOT_FOUND", "制度包未找到", http_status=404), status=404)
        assessment_types = body.get("assessmentTypes") or [pack.assessment_domain]
        if not isinstance(assessment_types, list) or not assessment_types or any(x not in POLICY_DOMAINS for x in assessment_types):
            return JsonResponse(api_error("ASSESSMENT_POLICY_INPUT_INVALID", "考核类型无效", http_status=400), status=400)
        version_no = (HrAssessmentPolicyVersion.objects.filter(
            tenant_id=tenant, policy_pack=pack
        ).aggregate(max_no=Max("version_no"))["max_no"] or 0) + 1
        scale = HrRatingScaleVersion.objects.create(
            tenant_id=tenant,
            version_no=version_no,
            status="PUBLISHED",
            scale_type="SCORE_100",
            min_value=0,
            max_value=100,
            levels=[
                {"code": "EXCELLENT", "min": str(excellent_min), "label": "优秀"},
                {"code": "QUALIFIED", "min": str(qualified_min), "label": "合格"},
                {"code": "UNQUALIFIED", "min": 0, "label": "不合格"},
            ],
            display_labels={"zh-CN": "百分制"},
        )
        indicator_set = HrIndicatorSetVersion.objects.create(
            tenant_id=tenant,
            version_no=version_no,
            status="PUBLISHED",
            name=f"{pack.name}基础指标集",
            total_weight=1,
        )
        workflow = HrAssessmentWorkflowVersion.objects.create(
            tenant_id=tenant,
            version_no=version_no,
            status="PUBLISHED",
            name=f"{pack.name}基础评审流程",
        )
        result_rule = HrResultRuleVersion.objects.create(
            tenant_id=tenant,
            version_no=version_no,
            status="PUBLISHED",
            name=f"{pack.name}结果映射规则",
            score_to_grade_mapping={
                "bands": [
                    {
                        "gradeCode": "EXCELLENT",
                        "minScore": str(excellent_min),
                        "maxScore": "100",
                        "displayGrade": {"zh-CN": "优秀"},
                    },
                    {
                        "gradeCode": "QUALIFIED",
                        "minScore": str(qualified_min),
                        "maxScore": str(excellent_min - Decimal("0.01")),
                        "displayGrade": {"zh-CN": "合格"},
                    },
                    {
                        "gradeCode": "UNQUALIFIED",
                        "minScore": "0",
                        "maxScore": str(qualified_min - Decimal("0.01")),
                        "displayGrade": {"zh-CN": "不合格"},
                    },
                ]
            },
            excellent_quota_rule_json={"enforcement": "BLOCKER"},
        )
        quota_policy = HrExcellentQuotaPolicy.objects.create(
            tenant_id=tenant,
            version_no=version_no,
            status="PUBLISHED",
            name=f"{pack.name}优秀比例政策",
            quota_basis_population="ELIGIBLE_POPULATION",
            max_excellent_ratio=excellent_ratio,
            over_quota_action="BLOCKER",
            rounding_rule="ROUND_DOWN",
            min_eligible_for_quota=5,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        version = HrAssessmentPolicyVersion(
            tenant_id=tenant,
            policy_pack=pack,
            version_no=version_no,
            effective_from=effective_from,
            effective_to=effective_to,
            assessment_types=assessment_types,
            eligibility_rule_json={"scope": "ACTIVE_STAFF"},
            cycle_rule_json={"source": "HR12_WORKBENCH"},
            rating_scale_version_id=scale.id,
            indicator_set_version_id=indicator_set.id,
            workflow_version_id=workflow.id,
            excellent_quota_policy_id=quota_policy.id,
            result_rule_version_id=result_rule.id,
        )
        version.full_clean()
        version.save()
    return JsonResponse(api_success(data={
        "id": str(version.id), "versionNo": version.version_no, "status": version.status,
        "ratingScaleVersionId": str(scale.id),
        "indicatorSetVersionId": str(indicator_set.id),
        "workflowVersionId": str(workflow.id),
        "resultRuleVersionId": str(result_rule.id),
        "excellentQuotaPolicyId": str(quota_policy.id),
    }), status=201)


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
