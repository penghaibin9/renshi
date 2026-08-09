"""
hr_onboarding/services/provisioning_service.py

Provisioning（总册 §15 / 05 §26）：
- 核心 HR activation 成功 ≠ 外部账号成功；账号/SSO 是独立 provisioning；
- PENDING → RUNNING → SUCCESS / FAILED_RETRYABLE / FAILED_TERMINAL；
- retry/dead-letter；reconciliation（external_ref）；
- 不能把"HTTP 200"直接等于业务成功；要接受 external reference。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.constants import ProvisioningStatus
from hr_onboarding.models import HrProvisioningRequest
from hr_onboarding.policies.state_machine import assert_provisioning_transition

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 60


class ProvisioningService:
    def __init__(self, *, tenant_id: int):
        self.tenant_id = tenant_id

    @transaction.atomic
    def request_provisioning(
        self,
        case,
        *,
        target_system: str,
        operation: str,
        payload_version: str = "",
        payload: Optional[dict] = None,
        idempotency_key: str,
    ) -> HrProvisioningRequest:
        """创建 provisioning 请求（幂等：同 idempotency_key 返回既有）。"""
        existing = HrProvisioningRequest.objects.filter(
            idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return existing
        return HrProvisioningRequest.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            target_system=target_system,
            operation=operation,
            idempotency_key=idempotency_key,
            payload_version=payload_version,
            payload_json=payload or {},
            status=ProvisioningStatus.PENDING,
        )

    @transaction.atomic
    def mark_running(self, req: HrProvisioningRequest) -> HrProvisioningRequest:
        req = HrProvisioningRequest.objects.select_for_update().get(id=req.id)
        assert_provisioning_transition(req.status, ProvisioningStatus.RUNNING)
        req.status = ProvisioningStatus.RUNNING
        req.attempt_count += 1
        req.save(update_fields=["status", "attempt_count", "updated_at"])
        return req

    @transaction.atomic
    def mark_success(
        self, req: HrProvisioningRequest, *, external_ref: str = ""
    ) -> HrProvisioningRequest:
        req = HrProvisioningRequest.objects.select_for_update().get(id=req.id)
        assert_provisioning_transition(req.status, ProvisioningStatus.SUCCESS)
        if not external_ref:
            # 外部成功必须带 external reference（00 §69：EXPORTED/SENT != ACCEPTED）
            raise ValueError("external_ref required for SUCCESS")
        req.status = ProvisioningStatus.SUCCESS
        req.external_ref = external_ref
        req.completed_at = timezone.now()
        req.save(update_fields=["status", "external_ref", "completed_at", "updated_at"])
        return req

    @transaction.atomic
    def mark_failed(
        self, req: HrProvisioningRequest, *, error: str, retryable: bool = True
    ) -> HrProvisioningRequest:
        req = HrProvisioningRequest.objects.select_for_update().get(id=req.id)
        if retryable and req.attempt_count < MAX_ATTEMPTS:
            assert_provisioning_transition(req.status, ProvisioningStatus.FAILED_RETRYABLE)
            req.status = ProvisioningStatus.FAILED_RETRYABLE
            req.next_retry_at = timezone.now() + timedelta(
                seconds=RETRY_BASE_SECONDS * (2 ** (req.attempt_count - 1))
            )
        else:
            assert_provisioning_transition(req.status, ProvisioningStatus.FAILED_TERMINAL)
            req.status = ProvisioningStatus.FAILED_TERMINAL
        req.last_error = error[:2000]
        req.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
        return req

    def pending_retryable(self, *, limit: int = 20):
        """待重试请求（next_retry_at <= now 且 FAILED_RETRYABLE）。"""
        now = timezone.now()
        return HrProvisioningRequest.objects.filter(
            tenant_id=self.tenant_id,
            status=ProvisioningStatus.FAILED_RETRYABLE,
            next_retry_at__lte=now,
        ).order_by("next_retry_at")[:limit]

    def reconcile(self, req: HrProvisioningRequest, *, external_ok: bool) -> bool:
        """外部对账：external_ok=False → 标记失败（可重试），返回 False。"""
        if not external_ok:
            self.mark_failed(req, error="reconciliation mismatch", retryable=True)
            return False
        return True
