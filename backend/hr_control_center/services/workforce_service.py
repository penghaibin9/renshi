"""
hr_control_center/services/workforce_service.py

WorkforceService —— HR01-04 队伍结构聚合服务。

按 HR03 权威模式编排 Canonical/Legacy WorkforceProvider + WorkforceSelector，
输出统一合同，不直接查表。
硬合同（总册 12 / 31.4 / 24 节）：
- 每个返回必须带 definitionVersion / dataBasis（LEGACY_CURRENT_SNAPSHOT）/
  computedAt / sourceUpdatedAt / freshnessStatus。
- dimension 白名单校验，禁止任意 group_by。
- UNAVAILABLE / ERROR 绝不 fake zero。
- 禁止 date.today() 直用；一律基于 context（学校时区）的 as_of/today。
"""

from __future__ import annotations

from typing import Optional

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    AUTHORITY_ONLY,
    DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
    DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
    DUAL_READ_COMPARE,
)
from hr_control_center.providers.canonical_workforce import (
    CanonicalWorkforceMetricProvider,
)
from hr_control_center.providers.workforce import LegacyWorkforceProvider
from hr_control_center.selectors.workforce import (
    DISTRIBUTION_DIMENSIONS,
    WorkforceSelector,
)
from hr_control_center.services.metric_registry import (
    OK,
    UNAVAILABLE,
)

# 队伍结构合同定义版本（HR02/HR03 权威模型切换后随公式语义升级）
WORKFORCE_DEFINITION_VERSION = "1.0"


class WorkforceService:
    """HR01-04 队伍结构聚合服务（无状态，context 按请求传入）。"""

    def __init__(self):
        self.provider = LegacyWorkforceProvider()
        self.canonical_provider = CanonicalWorkforceMetricProvider()

    def _provider_for(self, context: HrRequestContext):
        if context.authority_mode in (AUTHORITY_ONLY, DUAL_READ_COMPARE):
            return self.canonical_provider
        return self.provider

    # ---- 对外入口 ---------------------------------------------------------

    def get_summary(self, context: HrRequestContext) -> dict:
        """队伍结构结论卡：在岗人数 + 按人员类别/当前组织/当前岗位等分布的关键结论。"""
        provider = self._provider_for(context)
        gate = self._gates(context, "workforce_summary", provider)
        if gate is not None:
            return gate
        payload = WorkforceSelector(context, provider=provider).summary()
        return self._contract(context, "workforce_summary", payload)

    def get_distribution(self, context: HrRequestContext, dimension: str) -> dict:
        """
        按维度分布。dimension 白名单：
        personnel_category / department / job_position / gender / age_group。
        """
        if dimension not in DISTRIBUTION_DIMENSIONS:
            return self._unavailable_contract(
                context,
                "workforce_distribution",
                reason_code="INVALID_DIMENSION",
                message=(
                    f"非法维度: {dimension}，允许的维度: {sorted(DISTRIBUTION_DIMENSIONS)}"
                ),
            )
        provider = self._provider_for(context)
        gate = self._gates(context, "workforce_distribution", provider)
        if gate is not None:
            return gate
        payload = WorkforceSelector(context, provider=provider).distribution(
            dimension
        )
        return self._contract(context, "workforce_distribution", payload)

    def get_org_comparison(self, context: HrRequestContext) -> dict:
        """学院/部门对比宽表。Legacy 阶段组织以 Department 为准。"""
        provider = self._provider_for(context)
        gate = self._gates(context, "workforce_org_comparison", provider)
        if gate is not None:
            return gate
        payload = WorkforceSelector(context, provider=provider).org_comparison()
        return self._contract(context, "workforce_org_comparison", payload)

    # ---- 门槛（fail-closed） ----------------------------------------------

    def _gates(
        self, context: HrRequestContext, metric_key: str, provider
    ) -> Optional[dict]:
        """
        Legacy 当前快照只允许回答当天；Canonical effective-dated provider 可回答历史。
        """
        if (
            isinstance(provider, LegacyWorkforceProvider)
            and context.as_of != context.today()
        ):
            return self._unavailable_contract(
                context,
                metric_key,
                reason_code="AS_OF_NOT_CURRENT",
                message="当前系统快照仅支持查询学校所在时区的当天数据，无法提供历史或未来日期数据。",
            )
        return None

    # ---- 合同 -------------------------------------------------------------

    def _contract(self, context: HrRequestContext, metric_key: str, payload: dict) -> dict:
        """把 selector DTO 包装成统一合同（总册 31.4 必须字段全覆盖）。"""
        status = payload.get("status") or OK
        data = {
            k: v
            for k, v in payload.items()
            if k
            not in (
                "status",
                "computedAt",
                "sourceUpdatedAt",
                "reasonCode",
                "message",
            )
        }
        return {
            "metricKey": metric_key,
            "status": status,
            "freshnessStatus": status,
            "definitionVersion": WORKFORCE_DEFINITION_VERSION,
            # dataBasis 透传 provider 实际值（HR02 权威时为 AUTHORITATIVE_EFFECTIVE_FACT，
            # legacy 时为 LEGACY_CURRENT_SNAPSHOT）——复审修正：不再固定标 legacy
            "dataBasis": payload.get("dataBasis") or DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
            "computedAt": payload.get("computedAt"),
            "sourceUpdatedAt": payload.get("sourceUpdatedAt"),
            "asOf": context.as_of.isoformat() if context.as_of else None,
            "scope": {
                "type": context.scope.scope_type,
                "id": context.scope.org_id,
            },
            "reasonCode": payload.get("reasonCode"),
            "message": payload.get("message"),
            "data": data,
        }

    def _unavailable_contract(
        self,
        context: HrRequestContext,
        metric_key: str,
        *,
        reason_code: str,
        message: str,
    ) -> dict:
        from django.utils import timezone

        now = timezone.now()
        return {
            "metricKey": metric_key,
            "status": UNAVAILABLE,
            "freshnessStatus": UNAVAILABLE,
            "definitionVersion": WORKFORCE_DEFINITION_VERSION,
            "dataBasis": (
                DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT
                if context.authority_mode in (AUTHORITY_ONLY, DUAL_READ_COMPARE)
                else DATA_BASIS_LEGACY_CURRENT_SNAPSHOT
            ),
            "computedAt": now.isoformat(),
            "sourceUpdatedAt": now.isoformat(),
            "asOf": context.as_of.isoformat() if context.as_of else None,
            "scope": {
                "type": context.scope.scope_type,
                "id": context.scope.org_id,
            },
            "reasonCode": reason_code,
            "message": message,
            "data": None,
        }
