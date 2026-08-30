"""
hr_control_center/services/overview_service.py

OverviewService —— 只编排 provider，不直接查 Employee/LeaveRequest/Contract 表。

硬合同（总册 9.6 / 24 节）：
- 一个 provider 挂掉 → PARTIAL，不允许整页 500。
- UNAVAILABLE/ERROR/STALE 绝不转 0。
- 所有指标共享 context 的 tenant/scope/asOf/period/schoolTimezone/requestSnapshotAt。
"""

from __future__ import annotations

from typing import Optional

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    DUAL_READ_COMPARE,
    LEGACY_ONLY,
    AUTHORITY_ONLY,
    ProviderResult,
)
from hr_control_center.providers.legacy_employee import LegacyEmployeeMetricProvider
from hr_control_center.services.metric_registry import (
    OK,
    PARTIAL,
    STALE,
    UNAVAILABLE,
    ERROR,
    get_registry,
)

# 首屏 6 个核心 KPI（总册 8.1）
CORE_METRIC_KEYS = (
    "active_headcount",
    "full_time_teacher",
    "double_teacher_valid",
    "new_join_ytd",
    "departure_ytd",
    "open_risk_count",
)

# HR08 外聘指标（总册 §132）：由 Hr08DashboardProvider 提供，metrics 端点一并返回。
HR08_METRIC_KEYS = (
    "hr08_active_engagements",
    "hr08_engagements_expiring",
    "hr08_tasks_overdue",
    "hr08_workload_unverified",
    "hr08_industry_experts",
    "hr08_renewals_due",
)


class OverviewService:
    """
    HR01-01 人事总览聚合服务。
    """

    def __init__(
        self,
        *,
        todo_service_factory=None,
        alert_service_factory=None,
        quick_action_service_factory=None,
    ):
        self.registry = get_registry()
        self.legacy_provider = LegacyEmployeeMetricProvider()
        self.todo_service_factory = todo_service_factory or self._make_todo_service
        self.alert_service_factory = alert_service_factory or self._make_alert_service
        self.quick_action_service_factory = (
            quick_action_service_factory or self._make_quick_action_service
        )

    @staticmethod
    def _make_todo_service():
        from hr_control_center.services.todo_service import TodoService

        return TodoService()

    @staticmethod
    def _make_alert_service():
        from hr_control_center.services.alert_service import AlertService

        return AlertService()

    @staticmethod
    def _make_quick_action_service():
        from hr_control_center.services.quick_action_service import QuickActionService

        return QuickActionService()

    def _resolve_provider(self, metric_key: str, authority_mode: str):
        """
        Authority Router（总册 30.3 / 16.3）：
        - LEGACY_ONLY            → legacy provider
        - DUAL_READ_COMPARE      → 生产 UI 优先 authority；legacy 仅后台对账
        - AUTHORITY_ONLY         → 仅 authority；legacy 生产调用硬失败

        HR08 指标（hr08_*）是 HR08 authority 事实，三态下均优先 HR08 Provider；
        hr_external 未安装时返回 None → OverviewService 输出 UNAVAILABLE（不转 0）。
        """
        if metric_key.startswith("hr08_"):
            from django.apps import apps

            if not apps.is_installed("hr_external"):
                return None
            from hr_external.providers.hr01_adapter import Hr08DashboardProvider

            return Hr08DashboardProvider()

        if authority_mode == AUTHORITY_ONLY:
            # 后续 HR02/HR03 authority provider 就绪后在此路由。
            # 当前阶段没有 authority provider，直接返回不可用（不允许 fallback）。
            return None
        if authority_mode == DUAL_READ_COMPARE:
            # 暂同 legacy（对账阶段由 cutover 服务负责比对），后续切换。
            return self.legacy_provider
        return self.legacy_provider  # LEGACY_ONLY

    def get_metric(self, metric_key: str, context: HrRequestContext) -> dict:
        """返回单个 metric 的完整合同 dict（含状态/新鲜度/钻取）。"""
        definition = self.registry.get(metric_key)
        if definition is None:
            return self._unknown_metric(metric_key, context)

        # open_risk_count（K06）由预警中心提供，非 legacy provider
        if metric_key == "open_risk_count":
            return self._open_risk_count(context, definition)

        provider = self._resolve_provider(metric_key, context.authority_mode)

        if provider is None:
            return self._to_contract(
                ProviderResult.unavailable(
                    provider_key="authority",
                    metric_key=metric_key,
                    reason_code="AUTHORITY_SOURCE_UNAVAILABLE",
                    message="数据暂不可用（权威事实服务异常）",
                    definition_version=definition.definition_version,
                    authority_mode=context.authority_mode,
                ),
                context,
                definition.key,
            )

        if hasattr(provider, "get_metric"):
            result = provider.get_metric(metric_key, context)
        else:
            result = ProviderResult.unavailable(
                provider_key=getattr(provider, "provider_key", "?") or "?",
                metric_key=metric_key,
                reason_code="PROVIDER_CONTRACT_VIOLATION",
                definition_version=definition.definition_version,
                authority_mode=context.authority_mode,
            )

        return self._to_contract(result, context, definition.key)

    def get_bootstrap(self, context: HrRequestContext, user=None) -> dict:
        """
        首屏 bootstrap 聚合（单请求返回 6 KPI + freshnessSummary）。
        """
        metrics = []
        ok_count = 0
        stale_count = 0
        error_count = 0

        for key in CORE_METRIC_KEYS:
            contract = self.get_metric(key, context)
            metrics.append(contract)
            status = contract.get("status")
            if status == OK:
                ok_count += 1
            elif status == STALE:
                stale_count += 1
            elif status in (ERROR, UNAVAILABLE):
                error_count += 1

        # 整页状态：全部 OK → CONSISTENT；存在不可用 → PARTIAL
        overall_status = OK if ok_count == len(CORE_METRIC_KEYS) else PARTIAL
        if error_count:
            overall_status = PARTIAL

        todo_summary = self._todo_summary(context, user)
        alert_summary = self._alert_summary(context, user)
        quick_actions = self._quick_actions(context, user)
        partial_sources = []
        if todo_summary.get("status") in ("PARTIAL", "UNAVAILABLE", "ERROR"):
            partial_sources.append("todos")
        if alert_summary.get("status") in ("PARTIAL", "UNAVAILABLE", "ERROR"):
            partial_sources.append("alerts")

        return {
            "context": {
                "tenantId": context.tenant_id,
                "timezone": context.school_timezone,
                "asOf": context.as_of.isoformat() if context.as_of else None,
                "period": {
                    "from": (
                        context.period_from.isoformat()
                        if context.period_from
                        else None
                    ),
                    "to": context.period_to.isoformat() if context.period_to else None,
                },
                "scope": {
                    "type": context.scope.scope_type,
                    "id": context.scope.org_id,
                },
                "scopeFingerprint": context.scope_fingerprint(),
                "requestSnapshotAt": (
                    context.request_snapshot_at.isoformat()
                    if context.request_snapshot_at
                    else None
                ),
                "authorityMode": context.authority_mode or LEGACY_ONLY,
            },
            "metrics": metrics,
            "todoSummary": todo_summary,
            "alertSummary": alert_summary,
            "quickActions": quick_actions,
            "freshnessSummary": {
                "okCount": ok_count,
                "staleCount": stale_count,
                "errorCount": error_count,
            },
            "dataQuality": {},
            "partialSources": partial_sources,
            "consistency": PARTIAL if partial_sources else overall_status,
        }

    @staticmethod
    def _has_permission(user, code: str) -> bool:
        if user is None:
            return False
        return bool(getattr(user, "is_superuser", False) or user.has_perm(code))

    def _todo_summary(self, context: HrRequestContext, user) -> dict:
        if not self._has_permission(user, "hr.dashboard.todo.view"):
            return {"status": "FILTERED", "items": None}
        try:
            return self.todo_service_factory().get_summary(context, user=user)
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "overdue": None,
                "today": None,
                "week": None,
                "total": None,
                "asOf": context.as_of.isoformat(),
                "reasonCode": "TODO_SERVICE_UNAVAILABLE",
            }

    def _alert_summary(self, context: HrRequestContext, user) -> dict:
        if not self._has_permission(user, "hr.dashboard.alert.view"):
            return {"status": "FILTERED", "items": None}
        try:
            summary = self.alert_service_factory().get_summary(context)
            summary["status"] = "OK"
            return summary
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "critical": None,
                "high": None,
                "medium": None,
                "low": None,
                "info": None,
                "asOf": context.as_of.isoformat(),
                "reasonCode": "ALERT_SERVICE_UNAVAILABLE",
            }

    def _quick_actions(self, context: HrRequestContext, user) -> list:
        if not self._has_permission(user, "hr.dashboard.quick_action.use"):
            return []
        try:
            return self.quick_action_service_factory().get_catalog(context, user)
        except Exception:
            return []

    # ---- 内部工具 ---------------------------------------------------------

    def _open_risk_count(self, context: HrRequestContext, definition) -> dict:
        """
        K06 待处理风险 = 当前用户有权限看到，严重度 HIGH/CRITICAL 且 OPEN 的预警数。
        由 AlertService 提供；预警中心未就绪时 → UNAVAILABLE（不 fake zero）。
        """
        from hr_control_center.services.alert_service import AlertService
        from hr_control_center.services.metric_registry import (
            OK as OK_STATE,
            UNAVAILABLE as UNAVAILABLE_STATE,
        )

        try:
            count = AlertService().open_risk_count(context)
        except Exception:
            return self._to_contract(
                ProviderResult.unavailable(
                    provider_key="alert",
                    metric_key=definition.key,
                    reason_code="ALERT_SERVICE_UNAVAILABLE",
                    message="预警中心数据暂时无法计算。",
                    definition_version=definition.definition_version,
                    authority_mode=context.authority_mode,
                ),
                context,
                definition.key,
            )
        if count is None:
            return self._to_contract(
                ProviderResult.unavailable(
                    provider_key="alert",
                    metric_key=definition.key,
                    reason_code="ALERT_NOT_RUN_YET",
                    message="预警规则尚未运行，暂无风险统计。",
                    definition_version=definition.definition_version,
                    authority_mode=context.authority_mode,
                ),
                context,
                definition.key,
            )
        from django.utils import timezone

        result = ProviderResult(
            status=OK_STATE,
            data={"value": count},
            computed_at=timezone.now(),
            source_updated_at=timezone.now(),
            source="alert",
            data_basis="LEGACY_CURRENT_SNAPSHOT",
            definition_version=definition.definition_version,
            authority_mode=context.authority_mode,
        )
        return self._to_contract(result, context, definition.key)

    def _to_contract(
        self, result: ProviderResult, context: HrRequestContext, metric_key: str
    ) -> dict:
        definition = self.registry.get(metric_key)
        data = result.data or {}
        value = data.get("value") if isinstance(data, dict) else None

        contract = {
            "metricKey": metric_key,
            "value": value,
            "status": result.status,
            "asOf": context.as_of.isoformat() if context.as_of else None,
            "period": {
                "from": (
                    context.period_from.isoformat() if context.period_from else None
                ),
                "to": context.period_to.isoformat() if context.period_to else None,
            },
            "scope": {
                "type": context.scope.scope_type,
                "id": context.scope.org_id,
            },
            "definitionVersion": (
                definition.definition_version if definition else result.definition_version
            ),
            "dataBasis": result.data_basis,
            "computedAt": (
                result.computed_at.isoformat() if result.computed_at else None
            ),
            "sourceUpdatedAt": (
                result.source_updated_at.isoformat()
                if result.source_updated_at
                else None
            ),
            "freshUntil": None,
            "maxStaleSeconds": (
                definition.max_stale_seconds if definition else result.max_stale_seconds
            ),
            "staleReason": result.stale_reason,
            "reasonCode": result.reason_code,
            "message": result.message,
            "drilldown": {
                "route": self._drilldown_route(metric_key),
                "contractVersion": "1",
            },
        }

        if isinstance(data, dict) and "period" in data:
            contract["period"] = data["period"]

        return contract

    @staticmethod
    def _drilldown_route(metric_key: str) -> str:
        routes = {
            "active_headcount": "/hr/workforce",
            "full_time_teacher": "/hr/workforce",
            "double_teacher_valid": "/hr/workforce",
            "new_join_ytd": "/employee/employee-view-new/",
            "departure_ytd": "/employee/employee-view-new/",
            "open_risk_count": "/hr/alerts",
        }
        if metric_key.startswith("hr08_"):
            return "/hr/external-teachers"
        return routes.get(metric_key, "/hr/overview")

    @staticmethod
    def _unknown_metric(metric_key: str, context: HrRequestContext) -> dict:
        return {
            "metricKey": metric_key,
            "value": None,
            "status": UNAVAILABLE,
            "reasonCode": "UNKNOWN_METRIC",
            "message": "未注册的指标",
            "asOf": context.as_of.isoformat() if context.as_of else None,
            "definitionVersion": None,
            "dataBasis": None,
        }
