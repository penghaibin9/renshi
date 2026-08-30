"""
hr10_development/api/internal.py

内部 Provider API（总册 §115/§116）。

HR09 Evidence Provider endpoint:
  GET /internal/hr/development/evidence/staff/{staffId}?asOf=&types=

S9 阶段：直接返回格式化数据。生产阶段可增加 service-level auth。
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, DataFreshnessStatus
from hr10_development.providers.qualification_provider import Hr09QualificationEvidenceProvider
from hr10_development.permissions import require_hr10_internal_service


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_internal_service("HR09")
def get_hr09_evidence(request, staff_id):
    """
    GET /internal/hr/development/evidence/staff/{staffId}
    ?asOf=2026-01-01
    &types=ENTERPRISE_PRACTICE,TRAINING_COMPLETION,DEVELOPMENT_OUTPUT

    HR09 消费此接口获取 VERIFIED 培训/企业实践事实作为双师认定证据。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    as_of_str = request.GET.get("asOf")
    as_of = None
    if as_of_str:
        from datetime import date
        as_of = date.fromisoformat(as_of_str)

    types_str = request.GET.get("types")
    fact_types = types_str.split(",") if types_str else None

    provider = Hr09QualificationEvidenceProvider()
    result = provider.get_evidence(
        staff_master_id=staff_id,
        tenant_id=tenant_id,
        as_of=as_of,
        fact_types=fact_types,
    )

    if result.status.value == "OK":
        freshness = DataFreshnessStatus.FRESH
    else:
        freshness = DataFreshnessStatus.SOURCE_UNAVAILABLE

    return JsonResponse(success(result.data, meta={
        "sourceUpdatedAt": result.source_updated_at.isoformat() if result.source_updated_at else None,
        "dataFreshness": freshness,
    }))


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_internal_service("HR11")
def get_development_time_windows(request, staff_id):
    """
    GET /internal/hr/development/time-windows/staff/{staffId}?periodStart=&periodEnd=

    HR11 消费此接口获取培训/实践时间窗口，用于创建排班异常。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    from datetime import date
    period_start = date.fromisoformat(request.GET.get("periodStart", "2026-01-01"))
    period_end = date.fromisoformat(request.GET.get("periodEnd", "2026-12-31"))

    from hr10_development.providers.time_provider import Hr11DevelopmentTimeProvider
    provider = Hr11DevelopmentTimeProvider()
    result = provider.get_development_time_windows(
        staff_master_id=staff_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    return JsonResponse(success(result.data))
