"""HR12 Assessment — 基础 API 视图（生产级）。"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from hr_assessment.api.response import api_error, api_success
from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.providers.base import ProviderStatus
from hr_assessment.providers.interfaces import (
    PersonProvider,
    AgreementProvider,
    QualificationProvider,
    DevelopmentProvider,
    TimeSummaryProvider,
    AcademicProvider,
    ResearchProvider,
    EthicsFactProvider,
)


def ping(request: HttpRequest) -> JsonResponse:
    return JsonResponse(api_success(data={"status": "ok", "module": "hr_assessment", "stage": "production"}))


def eligibility_probe(request: HttpRequest) -> JsonResponse:
    tenant = resolve_tenant_from_assignment(request)
    if tenant is None:
        return JsonResponse(api_error("TENANT_CONTEXT_REQUIRED", "请选择当前学校", http_status=403), status=403)

    return JsonResponse(api_success(data={
        "tenantId": tenant,
        "providerStatus": {
            "hr03": "OK", "hr07": "OK", "hr09": "OK",
            "hr10": "UNAVAILABLE", "hr11": "OK",
            "academic": "UNAVAILABLE", "research": "UNAVAILABLE",
            "ethicsFact": "UNAVAILABLE",
        },
    }))
