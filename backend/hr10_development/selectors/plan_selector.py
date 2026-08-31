"""
hr10_development/selectors/plan_selector.py

发展计划查询层（read model for UI）。
"""

from hr10_development.models.plan import HrDevelopmentPlan


class PlanSelector:
    """计划列表/详情查询。"""

    @staticmethod
    def list_plans(tenant_id: int, status: str | None = None, plan_type: str | None = None):
        qs = HrDevelopmentPlan.objects.filter(tenant_id=tenant_id).order_by("-created_at")
        if status:
            qs = qs.filter(lifecycle_status=status)
        if plan_type:
            qs = qs.filter(plan_type=plan_type)
        return qs

    @staticmethod
    def get_summary_stats(tenant_id: int) -> dict:
        """首页统计卡。"""
        stats = {
            "in_execution": HrDevelopmentPlan.objects.filter(
                tenant_id=tenant_id, lifecycle_status__in=["ACTIVE", "PUBLISHED"],
            ).count(),
            "pending_review": HrDevelopmentPlan.objects.filter(
                tenant_id=tenant_id, lifecycle_status="UNDER_REVIEW",
            ).count(),
            "closed": HrDevelopmentPlan.objects.filter(
                tenant_id=tenant_id, lifecycle_status="CLOSED",
            ).count(),
        }
        return stats
