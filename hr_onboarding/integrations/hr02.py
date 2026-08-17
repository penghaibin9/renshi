"""
hr_onboarding/integrations/hr02.py

HR02 岗位 Provider 契约（00 §90 / 05 §24）。
HR02 已就绪（hr_structure 注册+migrated+PositionService.reserve/commit/release），
本 Provider 直连 hr_structure.services.position.PositionService。

硬规则：
- 预占未提交不算"占岗成功"（HELD ≠ COMMITTED）；
- 放弃/No-show 必须 RELEASE；
- 超期 reservation 必须 EXPIRED（由调度 job 处理，本层提供查询）；
- reservation 变更写审计。
"""

from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

from hr_structure.scope import Hr02Scope, resolve_scope
from hr_structure.services.position import PositionService, PositionServiceError

logger = logging.getLogger(__name__)


class Hr02PositionProviderError(Exception):
    """HR02 岗位操作失败。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class Hr02PositionProvider:
    """HR05 视角的岗位预占/提交/释放适配层。"""

    def __init__(self, tenant_id: int, *, scope_type: str = "SCHOOL", org_id: Optional[int] = None):
        scope: Hr02Scope = resolve_scope(tenant_id, scope_type=scope_type, org_id=org_id)
        self._service = PositionService(scope=scope, actor="hr05")

    def _wrap(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PositionServiceError as exc:
            raise Hr02PositionProviderError(exc.code, str(exc), retryable=False)

    def reserve(
        self,
        *,
        source_business_id: str,
        position_id: Optional[int] = None,
        position_pool_id: Optional[int] = None,
        count: int = 1,
        fte: float = 1.0,
        idempotency_key: str,
        expires_at=None,
    ):
        """创建预占（HELD）。幂等：同 idempotency_key 返回既有 reservation。"""
        return self._wrap(
            self._service.reserve,
            source_domain="hr05",
            source_business_type="ONBOARDING_CASE",
            source_business_id=source_business_id,
            position_id=position_id,
            position_pool_id=position_pool_id,
            count=count,
            fte=fte,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )

    def commit(self, reservation_id: int):
        """提交预占（HELD→COMMITTED），只在 Activation 成功时调用。"""
        return self._wrap(self._service.commit, reservation_id)

    def release(self, reservation_id: int):
        """释放预占（HELD→RELEASED），放弃/No-show/取消时调用。"""
        return self._wrap(self._service.release, reservation_id)

    def check_valid(self, reservation_id: int) -> bool:
        """查询预占是否仍有效（HELD 且未过期）。"""
        from hr_structure.models import HrPositionReservation

        r = HrPositionReservation.objects.filter(
            id=reservation_id, tenant_id=self._service.scope.tenant_id
        ).first()
        if r is None:
            return False
        if r.status != HrPositionReservation.Status.HELD:
            return False
        if r.expires_at and r.expires_at <= timezone.now():
            return False
        return True
