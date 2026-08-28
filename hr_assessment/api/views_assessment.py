"""HR12 Assessment — 基础 API 视图（生产级）。"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from hr_assessment.api.response import api_error, api_success
from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.provider_snapshot import HrProviderSnapshotSet
from hr_assessment.permissions import require_assessment_permission
from hr_assessment.service.evidence import (
    EvidenceSnapshotError,
    ProviderCollectionOrchestrator,
    ProviderEvidenceSnapshotService,
)


def ping(request: HttpRequest) -> JsonResponse:
    return JsonResponse(api_success(data={"status": "ok", "module": "hr_assessment", "stage": "production"}))


def eligibility_probe(request: HttpRequest) -> JsonResponse:
    tenant = resolve_tenant_from_assignment(request)
    if tenant is None:
        return JsonResponse(api_error("TENANT_CONTEXT_REQUIRED", "请选择当前学校", http_status=403), status=403)

    return JsonResponse(api_success(data={
        "tenantId": tenant,
        "scope": "CAPABILITY",
        "providerStatus": ProviderCollectionOrchestrator().capability_status(),
        "evidenceReadiness": "CASE_SCOPED_ONLY",
    }))


def _snapshot_payload(snapshot: HrProviderSnapshotSet) -> dict:
    return {
        "id": str(snapshot.id),
        "caseId": str(snapshot.case_id),
        "status": snapshot.status,
        "asOf": snapshot.as_of.isoformat(),
        "authority": snapshot.authority_json or {},
        "requiredProviders": snapshot.required_providers_json or [],
        "providerStatus": snapshot.provider_status_json or {},
        "capturedAt": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "requestId": snapshot.request_id or "",
    }


@require_assessment_permission("hr.assessment.hr_reviewer")
@require_http_methods(["GET", "POST"])
def provider_snapshot(request: HttpRequest, case_id) -> JsonResponse:
    tenant = getattr(request, "tenant_id", None)
    request_id = request.headers.get("X-Request-ID", "")
    case = HrAssessmentCase.objects.filter(
        id=case_id,
        tenant_id=tenant,
    ).first()
    if case is None:
        return JsonResponse(
            api_error(
                "ASSESSMENT_CASE_NOT_FOUND",
                "考核 Case 不存在或不属于当前学校",
                request_id=request_id,
                http_status=404,
            ),
            status=404,
        )

    if request.method == "GET":
        if not case.provider_snapshot_set_id:
            return JsonResponse(
                api_success(
                    data={"caseId": str(case.id), "snapshot": None},
                    request_id=request_id,
                )
            )
        snapshot = HrProviderSnapshotSet.objects.filter(
            id=case.provider_snapshot_set_id,
            tenant_id=tenant,
            case_id=case.id,
        ).first()
        if snapshot is None:
            return JsonResponse(
                api_error(
                    "ASSESSMENT_PROVIDER_SNAPSHOT_STATE_DRIFT",
                    "Case 指向的 Provider 快照不存在",
                    details={"snapshotSetId": str(case.provider_snapshot_set_id)},
                    request_id=request_id,
                    http_status=409,
                ),
                status=409,
            )
        return JsonResponse(
            api_success(
                data={"caseId": str(case.id), "snapshot": _snapshot_payload(snapshot)},
                request_id=request_id,
            )
        )

    try:
        snapshot = ProviderEvidenceSnapshotService(tenant).capture_case_from_policy(
            case_id=case.id,
            request_id=request_id,
        )
    except EvidenceSnapshotError as exc:
        status = 404 if exc.code == "ASSESSMENT_CASE_NOT_FOUND" else 409
        return JsonResponse(
            api_error(
                exc.code,
                str(exc),
                request_id=request_id,
                http_status=status,
            ),
            status=status,
        )

    return JsonResponse(
        api_success(
            data={"caseId": str(case.id), "snapshot": _snapshot_payload(snapshot)},
            request_id=request_id,
        )
    )
