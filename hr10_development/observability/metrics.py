"""
hr10_development/observability/metrics.py

HR10 可观测性指标（总册 §173）。

暴露以下 Prometheus/统计口径指标：
- hr10_request_total
- hr10_enrollment_capacity_conflict_total
- hr10_completion_verification_total
- hr10_practice_active_total
- hr10_provider_failure_total
- hr10_outbox_lag_seconds
- hr10_hr09_provider_latency

S11 阶段：计数器 + 日志输出。生产阶段接入 Prometheus client。
"""

import logging
import time
from functools import wraps

logger = logging.getLogger("hr10.metrics")


class DevelopmentMetrics:
    """HR10 指标收集器。"""

    def __init__(self):
        self._counters: dict[str, int] = {
            "hr10_request_total": 0,
            "hr10_enrollment_capacity_conflict_total": 0,
            "hr10_completion_verification_total": 0,
            "hr10_practice_active_total": 0,
            "hr10_provider_failure_total": 0,
            "hr10_outbox_lag_seconds": 0,
            "hr10_job_failure_total": 0,
            "hr10_hr09_provider_latency_ms": 0,
            "hr10_legacy_drift_total": 0,
        }

    def incr(self, name: str, delta: int = 1):
        if name in self._counters:
            self._counters[name] += delta
        logger.debug("metric incr: %s += %d → %d", name, delta, self._counters.get(name, 0))

    def snapshot(self) -> dict[str, int]:
        return dict(self._counters)


# 全局单例
metrics = DevelopmentMetrics()


def observe_request(view_func):
    """装饰器：统计 API 请求量。"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        metrics.incr("hr10_request_total")
        return view_func(*args, **kwargs)
    return wrapper


def observe_provider_latency(provider_name: str):
    """上下文管理器：记录 Provider 调用延迟。"""
    class _LatencyCtx:
        def __enter__(self):
            self._start = time.perf_counter()
            return self
        def __exit__(self, *args):
            elapsed_ms = (time.perf_counter() - self._start) * 1000
            logger.info("Provider %s latency: %.2f ms", provider_name, elapsed_ms)

    return _LatencyCtx()
