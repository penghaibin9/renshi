"""
hr10_development/api/internal.py

内部 Provider API（总册 §115/§116）。

HR09 Evidence Provider endpoint:
  GET /internal/hr/development/evidence/staff/{staffId}?asOf=&types=

S9 阶段：直接返回格式化数据。生产阶段可增加 service-level auth。
"""

from datetime import date

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import ApiMeta, error, success
from hr10_development.constants import (
    DataFreshnessStatus,
    DevelopmentErrorCode,
    FactType,
)
from hr10_development.providers.qualification_provider import Hr09QualificationEvidenceProvider
from hr10_development.permissions import require_hr10_internal_service


def _parse_iso_date(value, *, field_name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return JsonResponse(
            error(
                DevelopmentErrorCode.INVALID_REQUEST,
                f"{field_name} 必须是 YYYY-MM-DD 格式的合法日期",
            ),
            status=400,
        )


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

    as_of = _parse_iso_date(request.GET.get("asOf"), field_name="asOf")
    if isinstance(as_of, JsonResponse):
        return as_of

    types_str = request.GET.get("types")
    fact_types = (
        [value.strip().upper() for value in types_str.split(",") if value.strip()]
        if types_str
        else None
    )
    invalid_types = sorted(set(fact_types or ()) - set(FactType.values))
    if invalid_types:
        return JsonResponse(
            error(
                DevelopmentErrorCode.INVALID_REQUEST,
                "types 包含不支持的发展事实类型",
                details={"invalidTypes": invalid_types},
            ),
            status=400,
        )

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

    return JsonResponse(
        success(
            result.data,
            meta=ApiMeta(
                source_updated_at=(
                    result.source_updated_at.isoformat()
                    if result.source_updated_at
                    else None
                ),
                data_freshness=freshness,
            ),
        )
    )


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

    period_start = _parse_iso_date(
        request.GET.get("periodStart"), field_name="periodStart"
    )
    if isinstance(period_start, JsonResponse):
        return period_start
    period_end = _parse_iso_date(request.GET.get("periodEnd"), field_name="periodEnd")
    if isinstance(period_end, JsonResponse):
        return period_end
    if period_start is None or period_end is None:
        return JsonResponse(
            error(
                DevelopmentErrorCode.INVALID_REQUEST,
                "periodStart 和 periodEnd 均为必填项",
            ),
            status=400,
        )
    if period_end < period_start:
        return JsonResponse(
            error(
                DevelopmentErrorCode.INVALID_REQUEST,
                "periodEnd 不能早于 periodStart",
            ),
            status=400,
        )
    if (period_end - period_start).days > 366:
        return JsonResponse(
            error(
                DevelopmentErrorCode.INVALID_REQUEST,
                "查询时间范围不能超过 366 天",
            ),
            status=400,
        )

    from hr10_development.providers.time_provider import Hr11DevelopmentTimeProvider
    provider = Hr11DevelopmentTimeProvider()
    result = provider.get_development_time_windows(
        staff_master_id=staff_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    return JsonResponse(success(result.data))
