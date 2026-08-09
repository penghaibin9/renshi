"""
hr10_development/observability/logging.py

HR10 结构化日志（总册 §174）。

所有日志至少包含：
  requestId / traceId / tenantId / actorId / objectType / objectId / action / status / errorCode / latencyMs

禁止记录完整证件号、敏感附件内容、token。
"""

import logging
import uuid
from contextvars import ContextVar

# Context-local request tracking
_request_id_ctx: ContextVar[str] = ContextVar("hr10_request_id", default="")
_tenant_id_ctx: ContextVar[int | None] = ContextVar("hr10_tenant_id", default=None)

logger = logging.getLogger("hr10.structured")


class Hr10StructuredLog:
    """结构化日志辅助。"""

    @staticmethod
    def info(
        action: str,
        object_type: str = "",
        object_id: str = "",
        actor_id: str = "",
        status: str = "OK",
        latency_ms: int = 0,
        **extra,
    ):
        logger.info(
            "action=%s object=%s/%s actor=%s status=%s latency=%dms tenant=%s request=%s extra=%s",
            action,
            object_type,
            object_id,
            actor_id,
            status,
            latency_ms,
            _tenant_id_ctx.get(),
            _request_id_ctx.get(),
            extra,
        )

    @staticmethod
    def error(
        action: str,
        error_code: str,
        object_type: str = "",
        object_id: str = "",
        actor_id: str = "",
        status: str = "ERROR",
        **extra,
    ):
        logger.error(
            "action=%s error=%s object=%s/%s actor=%s status=%s tenant=%s request=%s extra=%s",
            action,
            error_code,
            object_type,
            object_id,
            actor_id,
            status,
            _tenant_id_ctx.get(),
            _request_id_ctx.get(),
            extra,
        )


def set_request_context(request_id: str = "", tenant_id: int | None = None):
    """设置请求级上下文。"""
    _request_id_ctx.set(request_id or str(uuid.uuid4()))
    if tenant_id is not None:
        _tenant_id_ctx.set(tenant_id)


def clear_request_context():
    """清除请求上下文。"""
    _request_id_ctx.set("")
    _tenant_id_ctx.set(None)
