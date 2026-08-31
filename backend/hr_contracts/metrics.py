"""
hr_contracts/metrics.py

可观测性指标（HR07 §114）：
- hr07_active_agreements / hr07_agreements_expiring / hr07_expired_unresolved
- hr07_signature_failed_total / hr07_generation_failed_total
- hr07_renewal_overdue_total / hr07_future_conflict_total
- hr07_legacy_drift_total / hr07_risk_open_total

V1：内存计数器 + Django management command 导出；生产改接 Prometheus exporter。
"""

from __future__ import annotations

import threading
from collections import defaultdict



class MetricsRegistry:
    """线程安全内存计数器（V1 生产可用；后续改接 django-prometheus）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, int] = defaultdict(int)

    def incr(self, name: str, delta: int = 1):
        with self._lock:
            self._counters[name] += delta

    def set(self, name: str, value: int):
        with self._lock:
            self._gauges[name] = value

    def get(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0) + self._gauges.get(name, 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {**dict(self._counters), **dict(self._gauges)}


registry = MetricsRegistry()


def refresh_gauges(tenant_id: int):
    """从 DB 刷新 gauge 类型指标（定期调用，如 lifecycle scheduler 末尾）。"""
    from hr_contracts.constants import LifecycleStatus
    from hr_contracts.models import HrAgreement, HrAgreementRiskCase

    base = HrAgreement.objects.filter(tenant_id=tenant_id)
    registry.set("hr07_active_agreements", base.filter(lifecycle_status=LifecycleStatus.ACTIVE).count())
    registry.set("hr07_signature_failed_total", base.filter(lifecycle_status=LifecycleStatus.SIGNATURE_FAILED).count())
    registry.set("hr07_risk_open_total", HrAgreementRiskCase.objects.filter(
        tenant_id=tenant_id, status__in=["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"]
    ).count())
