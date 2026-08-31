"""
hr_external/providers/hr01_adapter.py —— HR08 → HR01 指标 Provider 适配层（任务 1）。

以 hr_control_center.providers.base 的合同为准（ProviderResult / get_metric(metric_key, context)）：
- hr_external/providers/dashboard.py 返回裸 dict；本 adapter 包装为 ProviderResult；
- UNAVAILABLE 不转 0（00 §11）：hr08 模块未安装或查询失败 → UNAVAILABLE；
- authority_mode 语义：HR08 数据即权威事实（HrExternalEngagement 等 authority 表），
  三态下均按 authority 提供；dataBasis=HR08_AUTHORITY。
"""

from __future__ import annotations

from django.apps import apps

from hr_external.providers.dashboard import (
    hr08_dashboard_metrics,
)

# metric_key → (dashboard 字典键)
METRIC_KEY_MAP = {
    "hr08_active_engagements": "activeEngagements",
    "hr08_engagements_expiring": "engagementsExpiring90d",
    "hr08_tasks_overdue": "tasksOverdue",
    "hr08_workload_unverified": "workloadUnverified",
    "hr08_industry_experts": "industryExperts",
    "hr08_renewals_due": "renewalsDue30d",
}


class Hr08DashboardProvider:
    """HR01 消费的 HR08 指标 Provider（适配合同，不改 hr_control_center 已有逻辑）。"""

    provider_key = "hr08_dashboard"
    supported_metric_keys = frozenset(METRIC_KEY_MAP)

    def get_metric(self, metric_key: str, context):
        """返回 hr_control_center 合同 ProviderResult。"""
        from hr_control_center.providers.base import (
            DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
            ProviderResult,
        )
        from hr_control_center.services.metric_registry import (
            OK,
            get_registry,
        )
        from django.utils import timezone

        if metric_key not in self.supported_metric_keys:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="METRIC_NOT_SUPPORTED",
                authority_mode=getattr(context, "authority_mode", "LEGACY_ONLY"),
            )

        definition = get_registry().get(metric_key)
        if not apps.is_installed("hr_external"):
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="MODULE_NOT_AVAILABLE",
                message="HR08 外聘教师模块尚未启用。",
                definition_version=definition.definition_version if definition else None,
                authority_mode=getattr(context, "authority_mode", "LEGACY_ONLY"),
            )

        try:
            data = hr08_dashboard_metrics(
                tenant_id=context.tenant_id,
                ctx=context,
            )
            value = data.get(METRIC_KEY_MAP[metric_key])
            if value is None:
                return ProviderResult.unavailable(
                    provider_key=self.provider_key,
                    metric_key=metric_key,
                    reason_code="METRIC_COMPUTE_FAILED",
                    message="指标计算未返回数值。",
                    definition_version=definition.definition_version if definition else None,
                    authority_mode=getattr(context, "authority_mode", "LEGACY_ONLY"),
                )
            # dataBasis 统一为 hr_control_center 合同值（AUTHORITATIVE_EFFECTIVE_FACT），
            # 不混用 HR08 内部命名（00 §13 Provider 合同）。
            return ProviderResult(
                status=OK,
                data={
                    "value": value,
                    "metricKey": metric_key,
                    "definitionVersion": definition.definition_version if definition else None,
                    "dataBasis": DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
                },
                computed_at=timezone.now(),
                source_updated_at=timezone.now(),
                source=self.provider_key,
                data_basis=DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
                definition_version=definition.definition_version if definition else None,
                authority_mode=getattr(context, "authority_mode", "LEGACY_ONLY"),
            )
        except Exception:  # noqa: BLE001 —— 不转 0，返回 UNAVAILABLE
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="METRIC_QUERY_FAILED",
                message="HR08 指标计算失败。",
                definition_version=definition.definition_version if definition else None,
                authority_mode=getattr(context, "authority_mode", "LEGACY_ONLY"),
            )
