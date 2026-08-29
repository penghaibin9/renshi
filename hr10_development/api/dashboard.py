"""
hr10_development/api/dashboard.py

发展 Dashboard API（总册 §123）。
所有数字带 as-of 与口径说明。
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, MetricCode, FactType
from hr10_development.observability.metrics import metrics


@csrf_exempt
@require_http_methods(["GET"])
def plan_metrics(request, plan_id):
    """GET /api/v1/hr/development/plans/{planId}/metrics"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    from hr10_development.models.plan import HrDevelopmentPlan
    plan = HrDevelopmentPlan.objects.filter(id=plan_id, tenant_id=tenant_id).first()
    if not plan:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"), status=404)

    as_of = timezone.localdate().isoformat()
    return JsonResponse(success({
        "planId": plan_id,
        "planNo": plan.plan_no,
        "metrics": [
            {"metricCode": "PLAN_PROGRESS", "label": "计划执行进度", "labelZh": "计划执行进度",
             "value": plan.lifecycle_status, "asOf": as_of},
            {"metricCode": "PLAN_VERSION", "label": "计划版本", "labelZh": "计划版本",
             "value": plan.current_version_id, "asOf": as_of},
        ],
    }))


@csrf_exempt
@require_http_methods(["GET"])
def dashboard(request):
    """GET /api/v1/hr/development/dashboard"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    from hr10_development.models.plan import HrDevelopmentPlan
    from hr10_development.models.learning_program import HrLearningProgram
    from hr10_development.models.practice_project import HrEnterprisePracticeProject
    from hr10_development.models.development_fact import HrDevelopmentFact
    from hr10_development.models.development_fact import HrDevelopmentRiskCase

    active_plans = HrDevelopmentPlan.objects.filter(
        tenant_id=tenant_id, lifecycle_status__in=["ACTIVE", "PUBLISHED"],
    ).count()
    open_programs = HrLearningProgram.objects.filter(
        tenant_id=tenant_id, lifecycle_status__in=["PUBLISHED", "ACTIVE"],
    ).count()
    active_practice = HrEnterprisePracticeProject.objects.filter(
        tenant_id=tenant_id, lifecycle_status="ACTIVE",
    ).count()
    verified_facts = HrDevelopmentFact.objects.filter(
        tenant_id=tenant_id,
        verification_status__in=[
            "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
            "INTERNAL_INSTRUCTOR_VERIFIED", "HR_VERIFIED",
            "DOCUMENT_VERIFIED", "MANUAL_COMMITTEE_VERIFIED",
        ],
    ).count()
    open_risks = HrDevelopmentRiskCase.objects.filter(
        tenant_id=tenant_id, status__in=["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"],
    ).count()

    data = {
        "metrics": [
            {"metricCode": "ACTIVE_PLANS", "value": active_plans, "unit": "COUNT",
             "label": "在执行计划", "labelZh": "在执行计划"},
            {"metricCode": "OPEN_PROGRAMS", "value": open_programs, "unit": "COUNT",
             "label": "开放培训项目", "labelZh": "开放培训项目"},
            {"metricCode": "ACTIVE_PRACTICE_PROJECTS", "value": active_practice, "unit": "COUNT",
             "label": "进行中企业实践项目", "labelZh": "进行中企业实践项目"},
            {"metricCode": "VERIFIED_FACTS", "value": verified_facts, "unit": "COUNT",
             "label": "已核验发展事实", "labelZh": "已核验发展事实"},
            {"metricCode": "OPEN_RISKS", "value": open_risks, "unit": "COUNT",
             "label": "未解决风险", "labelZh": "未解决风险"},
        ],
        "asOf": timezone.localdate().isoformat(),
        "source": "hr10_development",
    }
    return JsonResponse(success(data))


@csrf_exempt
@require_http_methods(["GET"])
def metric_detail(request, metric_code):
    """GET /api/v1/hr/development/metrics/{metricCode}"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    from hr10_development.models.development_fact import HrDevelopmentFact

    if metric_code == MetricCode.TRAINING_COVERAGE_RATE:
        total = HrDevelopmentFact.objects.filter(tenant_id=tenant_id).count()
        verified = HrDevelopmentFact.objects.filter(
            tenant_id=tenant_id,
            verification_status__in=[
                "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
                "INTERNAL_INSTRUCTOR_VERIFIED", "HR_VERIFIED",
                "DOCUMENT_VERIFIED", "MANUAL_COMMITTEE_VERIFIED",
            ],
        ).count()
        value = round((verified / total * 100), 2) if total else None
        available = bool(total)
        denominator = f"当前学校发展事实 {total} 条"
    elif metric_code == MetricCode.AVG_VERIFIED_TRAINING_HOURS:
        from hr10_development.models.development_fact import HrDevelopmentFact
        facts = HrDevelopmentFact.objects.filter(
            tenant_id=tenant_id, fact_type=FactType.TRAINING_COMPLETION,
        )
        total_hours = sum(float(f.verified_hours or 0) for f in facts[:2000])
        staff_count = facts.values("staff_master_id").distinct().count()
        value = round(total_hours / staff_count, 2) if staff_count else None
        available = bool(staff_count)
        denominator = f"有培训完成事实的教师 {staff_count} 人"
    else:
        return JsonResponse(error("UNKNOWN_METRIC", f"未知指标: {metric_code}"), status=404)

    return JsonResponse(success({
        "metricCode": metric_code,
        "metricLabel": dict(MetricCode.choices).get(metric_code, metric_code),
        "value": value,
        "available": available,
        "asOf": timezone.localdate().isoformat(),
        "denominator": denominator,
        "explanation": "暂无适用数据，不能据此计算指标。" if not available else "按当前学校已核验数据计算。",
    }))
