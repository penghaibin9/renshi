"""
hr_recruitment/policies/idempotency.py

HR04 写 API 幂等处理器（总册 25/49）。

用途：
- 公开报名重复提交 → 同一 Idempotency-Key 返回同一条 Application；
- HR05 handoff 重复调用 → 返回同一 HR05 case；
- Offer 接受重复点击 → 幂等。

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
        return cache.get(f"hr04:idem:{key}")

    def put(self, key: str, payload: dict) -> None:
        cache.set(f"hr04:idem:{key}", payload, timeout=CACHE_TTL)


def normalize_key(raw: Optional[str]) -> Optional[str]:
    """幂等键规范化：长度受限、禁止空串。"""
    if not raw:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > 128:
        key = hashlib.sha256(key.encode()).hexdigest()
    return f"hr04:{key}"


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
