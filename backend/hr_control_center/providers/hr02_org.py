"""
hr_control_center/providers/hr02_org.py

HR02 Organization Provider 契约 —— HR01 消费 HR02 组织事实（总册 1.3）。

HR02 已权威化：学院分布/结构维度切到 HR02 组织事实，不再取 Horilla Department。
若 HR02 未就绪 → UNAVAILABLE（不 fallback legacy）。
"""

from __future__ import annotations

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
    ProviderResult,
    provider_ok,
)
from hr_control_center.services.metric_registry import UNAVAILABLE


class Hr02OrganizationProvider:
    """HR02 组织事实 Provider。"""

    provider_key = "hr02_organization"

    def get_org_tree_as_of(self, context: HrRequestContext, as_of=None):
        """权威组织树（HR02）。"""
        from hr_structure.scope import Hr02Scope
        from hr_structure.selectors.organization import OrganizationSelector

        try:
            scope = Hr02Scope("SCHOOL", tenant_id=context.tenant_id)
            selector = OrganizationSelector(scope, as_of=as_of or context.as_of)
            root = selector.get_root()
            if root is None:
                return ProviderResult.unavailable(
                    provider_key=self.provider_key,
                    metric_key="org_tree",
                    reason_code="HR02_ROOT_MISSING",
                    message="学校根组织尚未建立",
                    authority_mode=context.authority_mode,
                )
            return provider_ok(
                {
                    "rootId": root.organization_id_id,
                    "rootName": root.name,
                    "dataBasis": DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
                },
                source=self.provider_key,
                data_basis=DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
                authority_mode=context.authority_mode,
            )
        except Exception:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key="org_tree",
                reason_code="HR02_UNAVAILABLE",
                message="组织事实服务暂不可用",
                authority_mode=context.authority_mode,
            )
