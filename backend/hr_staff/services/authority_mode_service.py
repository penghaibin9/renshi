"""
hr_staff/services/authority_mode_service.py —— Authority 模式守卫（S12）。

硬合同（总册 §32.3）：
- 进入 HR03_AUTHORITY 后，禁止新 HR03 Provider 故障时自动 fallback 到 Employee/EmployeeWorkInformation；
- Legacy projection 只能作为兼容写出，不再作为权威读源；
- Authority 切换按 tenant 记录（HrAuthorityCutover，复用 hr_control_center）。
"""

from __future__ import annotations

from typing import Optional

from django.db import DatabaseError

from hr_staff.constants import AuthorityMode


class AuthorityModeError(Exception):
    code = "AUTHORITY_UNAVAILABLE"


class AuthorityModeService:
    """读取/守卫学校级 HR03 权威模式。"""

    def _cutover_model(self):
        """懒加载 cutover 模型（隔离对 hr_control_center 的编译期依赖）。"""
        from hr_control_center.models import HrAuthorityCutover

        return HrAuthorityCutover

    def get_mode(self, tenant_id: int) -> str:
        """返回 tenant 当前权威模式；仅“无切换记录”才使用 legacy 默认值。"""
        try:
            model = self._cutover_model()
            cutover = model.objects.filter(tenant_id=tenant_id, domain="STAFF").first()
        except DatabaseError as exc:
            # 数据库不可用不等于尚未切权。静默回退会让已经切到 HR03 的学校
            # 重新读取 legacy，既掩盖事故也可能返回过期事实，因此必须 fail-closed。
            raise AuthorityModeError("HR03 权威模式暂时无法读取") from exc

        if cutover is None:
            return AuthorityMode.LEGACY_STAFF_ONLY
        if cutover.mode not in AuthorityMode.values:
            raise AuthorityModeError(f"未知的 HR03 权威模式: {cutover.mode}")
        return cutover.mode

    def assert_authority_available(self, tenant_id: int, *, require_authority: bool = False):
        """读取权威数据前的守卫：
        - require_authority=True 且模式非 HR03_AUTHORITY → AUTHORITY_UNAVAILABLE（不 fallback legacy）；
        - 模式为 HR03_AUTHORITY → 永远禁止 silent fallback（调用方不得读 legacy 顶替）。
        """
        mode = self.get_mode(tenant_id)
        if require_authority and mode != AuthorityMode.HR03_AUTHORITY:
            raise AuthorityModeError(
                "该学校尚未切换到 HR03 权威模式，禁止以 legacy 顶替权威数据"
            )
        return mode

    def record_cutover(
        self,
        *,
        tenant_id: int,
        mode: str,
        reason: str,
        cutover_by: str = "",
        reconciliation_report_id: str = "",
    ):
        """记录按 tenant 的权威切换（总册 §33.6）；同时写 tenant 级审计（§28.2）。"""
        model = self._cutover_model()
        model.objects.update_or_create(
            tenant_id=tenant_id,
            domain="STAFF",
            defaults={
                "mode": mode,
                "reason": reason,
                "cutover_by": cutover_by,
                "verification_report_id": reconciliation_report_id,
            },
        )
        from hr_staff.services.audit_service import write_audit_event

        write_audit_event(
            tenant_id=tenant_id,
            action="StaffAuthorityModeChanged",
            reason=f"mode={mode} reason={reason[:200]}",
        )
