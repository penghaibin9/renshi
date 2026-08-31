"""HR12 Assessment — API 错误与响应信封（生产级）。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ProviderStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def api_success(
    data: Any,
    request_id: str = "",
    api_version: str = "v1",
    schema_version: str = "1.0",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "apiVersion": api_version,
        "schemaVersion": schema_version,
        "requestId": request_id,
        "data": data,
        "meta": meta or {},
    }


def api_error(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    request_id: str = "",
    retryable: bool = False,
    http_status: int = 400,
) -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
        },
        "requestId": request_id,
        "httpStatus": http_status,
    }


def paginated_response(
    items: list,
    total: int,
    page: int,
    page_size: int,
    has_next: bool,
    request_id: str = "",
) -> Dict[str, Any]:
    return api_success(
        data=items, request_id=request_id,
        meta={"total": total, "page": page, "pageSize": page_size, "hasNext": has_next},
    )
