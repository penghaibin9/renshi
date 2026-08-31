"""
hr_onboarding/policies/idempotency.py

HR05 写 API 幂等处理器（00 §23 / 05 §47）。

用途：
- HR04 HANDOFF 重复调用 → 返回同一 HR05 case（不生成第二份）；
- Portal 重复提交（资料/材料/意愿）→ 幂等；
- Activate/Report/Task 双完成 → 幂等 + 版本冲突。

S1 阶段提供接口契约与内存实现；S2 起接数据库唯一约束。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24h，真实实现建议落库持久化


class IdempotencyKeyError(Exception):
    """幂等键冲突。"""


class InMemoryIdempotencyStore:
    """
    最小内存幂等存储（S1 契约占位；生产需接 DB 唯一约束 + outbox）。
    """

    def get(self, key: str) -> Optional[dict]:
        return cache.get(f"hr05:idem:{key}")

    def put(self, key: str, payload: dict) -> None:
        cache.set(f"hr05:idem:{key}", payload, timeout=CACHE_TTL)


def normalize_key(raw: Optional[str], namespace: str = "hr05") -> Optional[str]:
    """幂等键规范化：长度受限、禁止空串、带命名空间。"""
    if not raw:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > 128:
        key = hashlib.sha256(key.encode()).hexdigest()
    return f"{namespace}:{key}"


def apply_idempotency(key: Optional[str], store=None) -> Optional[dict]:
    """
    命中则返回先前结果（重放），未命中返回 None。
    调用方负责在业务事务成功后 put 结果。
    """
    if not key:
        return None
    store = store or InMemoryIdempotencyStore()
    return store.get(key)


def store_result(key: Optional[str], payload: dict, store=None) -> None:
    if not key:
        return
    store = store or InMemoryIdempotencyStore()
    store.put(key, payload)
