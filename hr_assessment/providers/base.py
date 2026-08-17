"""HR12 — Provider 层生产化：重试/熔断/批量/超时。"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hr_assessment.providers")


class ProviderStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class ProviderContext:
    tenant_id: int
    ids: List[Any] = field(default_factory=list)
    as_of: Optional[datetime] = None
    source_version: str = "v1"
    max_stale_seconds: int = 3600
    timeout_ms: int = 5000
    sensitivity: str = "INTERNAL"
    request_id: str = ""

    def __post_init__(self):
        if self.as_of is None:
            self.as_of = datetime.now(timezone.utc)


@dataclass
class ProviderResult:
    status: ProviderStatus
    data: Any = None
    error_message: str = ""
    source_updated_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_version: str = "v1"
    cached: bool = False


class CircuitBreaker:
    """简单熔断器：连续失败 N 次后打开电路，冷却 T 秒后半开。"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self._failures: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._threshold = failure_threshold
        self._timeout = recovery_timeout

    def is_open(self, key: str) -> bool:
        failures = self._failures.get(key, 0)
        if failures < self._threshold:
            return False
        last = self._last_failure_time.get(key, 0)
        if time.monotonic() - last > self._timeout:
            self._failures[key] = 0
            return False
        return True

    def record_success(self, key: str) -> None:
        self._failures[key] = 0

    def record_failure(self, key: str) -> None:
        self._failures[key] = self._failures.get(key, 0) + 1
        self._last_failure_time[key] = time.monotonic()


# 全局熔断器实例
circuit_breaker = CircuitBreaker()


class BaseAssessmentProvider(ABC):
    """考核 Provider 抽象基类 — 含重试/熔断。"""

    max_retries: int = 2
    retry_backoff: float = 0.5

    @property
    @abstractmethod
    def owner_domain(self) -> str: ...

    @abstractmethod
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult: ...

    def fetch(self, ctx: ProviderContext) -> ProviderResult:
        cb_key = f"{self.owner_domain}:{ctx.tenant_id}"
        if circuit_breaker.is_open(cb_key):
            logger.warning("Circuit open for %s", cb_key)
            return ProviderResult(status=ProviderStatus.ERROR, error_message="Circuit breaker open")

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                result = self._do_fetch(ctx)
                circuit_breaker.record_success(cb_key)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning("Provider %s retry %d/%d: %s", self.owner_domain, attempt + 1, self.max_retries, e)
                    time.sleep(self.retry_backoff * (attempt + 1))

        circuit_breaker.record_failure(cb_key)
        logger.error("Provider %s failed after %d retries: %s", self.owner_domain, self.max_retries, last_error)
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=f"{self.owner_domain}: {str(last_error)[:500]}" if last_error else "Unknown error",
        )

    def fetch_batch(self, ctx: ProviderContext, batch_size: int = 100) -> List[ProviderResult]:
        """批量分片获取 — 避免单次查询数据量过大。"""
        results: List[ProviderResult] = []
        ids = ctx.ids or []
        for i in range(0, len(ids), batch_size):
            batch_ctx = ProviderContext(
                tenant_id=ctx.tenant_id, ids=ids[i:i + batch_size],
                as_of=ctx.as_of, source_version=ctx.source_version,
                timeout_ms=ctx.timeout_ms,
            )
            results.append(self.fetch(batch_ctx))
        return results
