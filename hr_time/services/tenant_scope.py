"""
hr_time/services/tenant_scope.py

A0 fail-closed 租户闸门服务。

任何 HR11 入口（API/Job/Provider/信号）都必须先经过 guard：
- 无明确 tenant 上下文 → 拒绝（默认 deny）；
- 数据写入必须携带 tenant_id 且与上下文一致；
- 禁止回退到 isnull=True 全校数据。

注意：这是 HR11 自己的边界加固，不改动 legacy HorillaCompanyManager
（避免影响 HR02/HR03/HR15 等存量行为）。
"""

from __future__ import annotations

from typing import Optional

from hr_time.context import HrTimeContextError, HrTimeContext


class TenantGuard:
    """HR11 租户守卫。fail-closed：无法确认上下文即拒绝。"""

    @staticmethod
    def assert_context(ctx: Optional[HrTimeContext]) -> HrTimeContext:
        if ctx is None or not ctx.tenant_id:
            raise HrTimeContextError(
                "TENANT_CONTEXT_REQUIRED", "HR11 需要明确学校上下文（fail-closed）"
            )
        return ctx

    @staticmethod
    def assert_same_tenant(ctx: HrTimeContext, *, tenant_id: int, object_ref: str) -> None:
        TenantGuard.assert_context(ctx)
        if int(ctx.tenant_id) != int(tenant_id):
            raise HrTimeContextError(
                "TENANT_SCOPE_VIOLATION",
                f"租户越权: 目标对象 {object_ref} 不属于当前学校",
            )

    @staticmethod
    def assert_writable(ctx: HrTimeContext, *, tenant_id: int, object_ref: str) -> None:
        """写入前校验：对象归属当前租户。跨校永不自动开放。"""
        TenantGuard.assert_same_tenant(ctx, tenant_id=tenant_id, object_ref=object_ref)
