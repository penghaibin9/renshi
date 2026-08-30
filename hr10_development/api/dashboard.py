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
    from hr10_development.models.practice_models import HrEnterprisePracticeAssignment
    from hr10_development.models.development_fact import HrDevelopmentFact
    from hr10_development.models.development_fact import HrDevelopmentRiskCase
    from hr10_development.models.training_request import HrTrainingRequest

    current_year = timezone.localdate().year
    annual_plans = HrDevelopmentPlan.objects.filter(
        tenant_id=tenant_id,
        cycle_type="ANNUAL",
        start_date__year=current_year,
    ).count()
    open_programs = HrLearningProgram.objects.filter(
        tenant_id=tenant_id, lifecycle_status__in=["PUBLISHED", "ACTIVE"],
    ).count()
    pending_requests = HrTrainingRequest.objects.filter(
        tenant_id=tenant_id,
        lifecycle_status__in=[
            "SUBMITTED", "UNDER_MANAGER_REVIEW", "UNDER_COLLEGE_REVIEW",
            "UNDER_HR_REVIEW", "UNDER_BUDGET_REVIEW", "COMPLETION_REVIEW",
        ],
    ).count()
    active_practice = HrEnterprisePracticeAssignment.objects.filter(
        tenant_id=tenant_id, assignment_status__in=["IN_PROGRESS", "SUSPENDED"],
    ).count()
    verified_statuses = [
        "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
        "INTERNAL_INSTRUCTOR_VERIFIED", "HR_VERIFIED", "DOCUMENT_VERIFIED",
        "MANUAL_COMMITTEE_VERIFIED", "MIGRATED_VERIFIED",
    ]
    facts = HrDevelopmentFact.objects.filter(tenant_id=tenant_id)
    verified_facts = facts.filter(verification_status__in=verified_statuses).count()
    total_facts = facts.count()
    pending_facts = facts.exclude(verification_status__in=verified_statuses).count()
    completion_rate = round(verified_facts / total_facts * 100) if total_facts else None
    open_risks = HrDevelopmentRiskCase.objects.filter(
        tenant_id=tenant_id, status__in=["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"],
    ).count()

    data = {
        "metrics": [
            {"metricCode": "ANNUAL_PLANS", "value": annual_plans, "unit": f"{current_year} 年",
             "label": "年度计划", "labelZh": "年度计划"},
            {"metricCode": "OPEN_PROGRAMS", "value": open_programs, "unit": "个",
             "label": "进行中项目", "labelZh": "进行中项目"},
            {"metricCode": "PENDING_REQUESTS", "value": pending_requests, "unit": "待办理",
             "label": "申请待批", "labelZh": "申请待批"},
            {"metricCode": "ACTIVE_PRACTICE", "value": active_practice, "unit": "教师",
             "label": "企业实践中", "labelZh": "企业实践中"},
            {"metricCode": "PENDING_FACTS", "value": pending_facts, "unit": "待核验",
             "label": "成果待核验", "labelZh": "成果待核验"},
            {"metricCode": "ANNUAL_COMPLETION", "value": completion_rate, "unit": "%" if completion_rate is not None else "暂无口径",
             "label": "年度完成度", "labelZh": "年度完成度", "available": completion_rate is not None},
        ],
        "attention": [
            {"label": "培训申请待审批", "count": pending_requests, "route": "/hr/development/requests"},
            {"label": "发展成果待核验", "count": pending_facts, "route": "/hr/development/enterprise-practice/results"},
            {"label": "发展风险待处理", "count": open_risks, "route": "/hr/development/dashboard"},
        ],
        "asOf": timezone.localdate().isoformat(),
        "source": "教师发展业务台账",
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
