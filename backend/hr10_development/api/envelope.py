"""
hr10_development/api/envelope.py

统一 API 响应信封（对齐 00 §28/§29、总册 §130）。

成功/错误均使用标准化格式；前端不得解析数据库/英文异常文本决定业务。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ApiMeta:
    """成功响应 meta 区块。"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_updated_at: str | None = None
    calculated_at: str | None = None
    data_freshness: str = "FRESH"  # FRESH / STALE / SOURCE_UNAVAILABLE


@dataclass
class ApiError:
    """错误响应 error 区块。"""
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False


def success(data: Any, meta: ApiMeta | None = None) -> dict[str, Any]:
    """构建成功响应信封。"""
    if meta is None:
        meta = ApiMeta()
    return {
        "data": data,
        "meta": {
            "requestId": meta.request_id,
            "sourceUpdatedAt": meta.source_updated_at,
            "calculatedAt": meta.calculated_at,
            "dataFreshness": meta.data_freshness,
        },
    }


def error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """构建错误响应信封（对齐总册 §130：requestId 在 error 对象内）。"""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "requestId": str(uuid.uuid4()),
        },
    }
