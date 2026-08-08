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


class OverviewService:
    """
    HR01-01 人事总览聚合服务。
    """

    def __init__(self):
        self.registry = get_registry()
        self.legacy_provider = LegacyEmployeeMetricProvider()

    def _resolve_provider(self, metric_key: str, authority_mode: str):
        """
        Authority Router（总册 30.3 / 16.3）：
        - LEGACY_ONLY            → legacy provider
        - DUAL_READ_COMPARE      → 生产 UI 优先 authority；legacy 仅后台对账
        - AUTHORITY_ONLY         → 仅 authority；legacy 生产调用硬失败
        """
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

    def get_bootstrap(self, context: HrRequestContext) -> dict:
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
            "todoSummary": None,  # S4 接入
            "alertSummary": None,  # S5 接入
            "quickActions": [],  # S7 接入
            "freshnessSummary": {
                "okCount": ok_count,
                "staleCount": stale_count,
                "errorCount": error_count,
            },
            "dataQuality": {},
            "partialSources": [],
            "consistency": overall_status,
        }

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
