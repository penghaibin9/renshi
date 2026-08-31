"""
hr10_development/api/health.py

HR10 Health Probe。
GET /api/v1/hr/development/health
"""

import uuid
from datetime import datetime, timezone

from django.http import JsonResponse


def health_check(request):
    """健康探针 — 返回模块存活状态与当前时间戳。"""
    return JsonResponse({
        "data": {
            "module": "hr10_development",
            "status": "OK",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "meta": {
            "requestId": str(uuid.uuid4()),
            "dataFreshness": "FRESH",
        },
    })
