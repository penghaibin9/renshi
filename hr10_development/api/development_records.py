"""
hr10_development/api/development_records.py

教师发展档案 API（总册 §136）。
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode
from hr10_development.models.development_fact import (
    HrDevelopmentFact,
    HrDevelopmentMetricLedger,
    HrDevelopmentRiskCase,
)
from hr10_development.services.compliance_service import ComplianceService


@csrf_exempt
@require_http_methods(["GET"])
def get_record_summary(request, staff_id):
    """
    GET /api/v1/hr/development/development-records/{staffId}
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    facts = HrDevelopmentFact.objects.filter(tenant_id=tenant_id, staff_master_id=staff_id)
    summary = {
        "staffMasterId": staff_id,
        "totalFacts": facts.count(),
        "trainingCompletions": facts.filter(fact_type="TRAINING_COMPLETION").count(),
        "furtherStudies": facts.filter(fact_type="FURTHER_STUDY").count(),
        "enterprisePractices": facts.filter(fact_type="ENTERPRISE_PRACTICE").count(),
        "developmentOutputs": facts.filter(fact_type="DEVELOPMENT_OUTPUT").count(),
        "totalVerifiedHours": sum(float(f.verified_hours or 0) for f in facts[:500]),
        "totalVerifiedDays": sum(int(f.verified_days or 0) for f in facts[:500]),
    }
    return JsonResponse(success(summary))


@csrf_exempt
@require_http_methods(["GET"])
def get_facts(request, staff_id):
    """GET /api/v1/hr/development/development-records/{staffId}/facts"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    qs = HrDevelopmentFact.objects.filter(tenant_id=tenant_id, staff_master_id=staff_id).order_by("-valid_from")
    fact_type = request.GET.get("factType")
    if fact_type:
        qs = qs.filter(fact_type=fact_type)

    data = [{
        "id": str(f.id),
        "factType": f.fact_type,
        "factTypeLabel": f.get_fact_type_display(),
        "activityType": f.activity_type,
        "startDate": str(f.start_date) if f.start_date else None,
        "endDate": str(f.end_date) if f.end_date else None,
        "verifiedHours": float(f.verified_hours) if f.verified_hours else None,
        "verifiedDays": f.verified_days,
        "verificationStatus": f.verification_status,
        "evidencePackageHash": f.evidence_package_hash,
        "validFrom": str(f.valid_from) if f.valid_from else None,
    } for f in qs[:200]]
    return JsonResponse(success(data))


@csrf_exempt
@require_http_methods(["GET"])
def get_ledger(request, staff_id):
    """GET /api/v1/hr/development/development-records/{staffId}/ledger"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    entries = HrDevelopmentMetricLedger.objects.filter(tenant_id=tenant_id, staff_master_id=staff_id)
    metric_code = request.GET.get("metricCode")
    if metric_code:
        entries = entries.filter(metric_code=metric_code)

    data = [{
        "id": str(e.id),
        "metricCode": e.metric_code,
        "rawValue": float(e.raw_value),
        "rawUnit": e.raw_unit,
        "normalizedValue": float(e.normalized_value) if e.normalized_value else None,
        "normalizedUnit": e.normalized_unit,
        "conversionRuleVersion": e.conversion_rule_version,
        "windowKey": e.window_key,
    } for e in entries[:200]]
    return JsonResponse(success(data))


@csrf_exempt
@require_http_methods(["GET"])
def get_compliance(request, staff_id):
    """GET /api/v1/hr/development/development-records/{staffId}/compliance"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    from datetime import date
    as_of = request.GET.get("asOf")
    as_of_date = date.fromisoformat(as_of) if as_of else None

    results = ComplianceService.evaluate_compliance(
        staff_master_id=int(staff_id),
        tenant_id=tenant_id,
        as_of=as_of_date,
    )
    return JsonResponse(success(results))


@csrf_exempt
@require_http_methods(["GET"])
def get_risks(request, staff_id):
    """GET /api/v1/hr/development/development-records/{staffId}/risks"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    risks = HrDevelopmentRiskCase.objects.filter(
        tenant_id=tenant_id, staff_master_id=staff_id,
    ).order_by("-detected_at")

    data = [{
        "id": str(r.id),
        "riskType": r.risk_type,
        "riskTypeLabel": r.get_risk_type_display(),
        "severity": r.severity,
        "status": r.status,
        "statusLabel": r.get_status_display(),
        "detectedAt": r.detected_at.isoformat(),
        "dueAt": r.due_at.isoformat() if r.due_at else None,
    } for r in risks[:100]]
    return JsonResponse(success(data))
