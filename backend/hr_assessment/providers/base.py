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
    """连续失败 N 次后打开电路，冷却 T 秒后半开。"""

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
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_message="Circuit breaker open",
            )

        last_error: Optional[Exception] = None
        last_result: Optional[ProviderResult] = None
        for attempt in range(self.max_retries + 1):
            try:
                result = self._do_fetch(ctx)
            except Exception as exc:
                last_error = exc
                retry_reason = str(exc)
            else:
                if result.status != ProviderStatus.ERROR:
                    # UNAVAILABLE/PARTIAL/STALE are valid provider answers. They
                    # must not trip a transport/runtime circuit breaker.
                    circuit_breaker.record_success(cb_key)
                    return result
                last_result = result
                retry_reason = result.error_message or "provider returned ERROR"

            if attempt < self.max_retries:
                logger.warning(
                    "Provider %s retry %d/%d: %s",
                    self.owner_domain,
                    attempt + 1,
                    self.max_retries,
                    retry_reason,
                )
                time.sleep(self.retry_backoff * (attempt + 1))

        circuit_breaker.record_failure(cb_key)
        if last_result is not None:
            logger.error(
                "Provider %s returned ERROR after %d retries: %s",
                self.owner_domain,
                self.max_retries,
                last_result.error_message,
            )
            return last_result

        logger.error(
            "Provider %s failed after %d retries: %s",
            self.owner_domain,
            self.max_retries,
            last_error,
        )
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=(
                f"{self.owner_domain}: {str(last_error)[:500]}"
                if last_error
                else "Unknown error"
            ),
        )

    def fetch_batch(self, ctx: ProviderContext, batch_size: int = 100) -> List[ProviderResult]:
        """批量分片获取 — 保留完整请求上下文，避免分片后降级安全语义。"""
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        results: List[ProviderResult] = []
        ids = ctx.ids or []
        for i in range(0, len(ids), batch_size):
            batch_ctx = ProviderContext(
                tenant_id=ctx.tenant_id,
                ids=ids[i : i + batch_size],
                as_of=ctx.as_of,
                source_version=ctx.source_version,
                max_stale_seconds=ctx.max_stale_seconds,
                timeout_ms=ctx.timeout_ms,
                sensitivity=ctx.sensitivity,
                request_id=ctx.request_id,
            )
            results.append(self.fetch(batch_ctx))
        return results
