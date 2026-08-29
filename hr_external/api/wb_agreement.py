"""W-B canonical API bridge for confirming the exact HR07 external agreement."""

from __future__ import annotations

import json

from hr_external.api.base import api_root, error_response, json_response, make_external_context
from hr_external.models import HrExternalHiringCase
from hr_external.permissions import require_hr_external_permission
from hr_external.services.audit_service import write_external_audit
from hr_external.services.hiring_service import AgreementNotReady, HiringService, InvalidHiringState
from hr_external.integrations.hr07 import AgreementProvider


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_hr_external_permission("hr08.hiring.approve")
def hiring_agreement_options(request, case_id):
    """Return HR07 agreements already bound to this exact HR08 hiring case."""
    if request.method != "GET":
        return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 GET", 405)
    ctx, err = _ctx(request)
    if err:
        return err
    case = (
        HrExternalHiringCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id)
        .select_related("category_id", "proposed_person_id")
        .first()
    )
    if case is None:
        return error_response(
            request,
            "EXTERNAL_HIRING_CASE_NOT_FOUND",
            "聘用审批单不存在",
            404,
        )
    if case.proposed_person_id_id is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "候选人档案不可用", 409)

    result = AgreementProvider().list_ready_agreements(
        tenant_id=ctx.tenant_id,
        agreement_type_code=case.category_id.agreement_type_code,
        subject_reference_type="HR08_HIRING_CASE",
        subject_reference_id=str(case.id),
        subject_person_id=str(case.proposed_person_id_id),
    )
    if not result.is_available:
        return error_response(
            request,
            result.error_code or "PROVIDER_UNAVAILABLE",
            result.error_message or "HR07 协议服务暂不可用",
            503,
        )
    body = api_root(request)
    body["data"] = result.data or {"items": []}
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.approve")
def hiring_confirm_agreement(request, case_id):
    """Confirm a tenant/person/case-bound HR07 agreement before HR08 activation."""
    if request.method != "POST":
        return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 POST", 405)

    ctx, err = _ctx(request)
    if err:
        return err

    case = (
        HrExternalHiringCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id)
        .select_related("category_id")
        .first()
    )
    if case is None:
        return error_response(
            request,
            "EXTERNAL_HIRING_CASE_NOT_FOUND",
            "聘用审批单不存在",
            404,
        )

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        ready = HiringService().confirm_agreement(
            case,
            agreement_id=str(payload.get("agreementId") or "").strip(),
        )
    except (InvalidHiringState, AgreementNotReady) as exc:
        return error_response(
            request,
            getattr(exc, "code", "VERSION_CONFLICT"),
            str(exc),
            409,
        )

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalHiringAgreementConfirmed",
        actor_user_id=ctx.user_id,
        business_type="HR08_HIRING",
        business_id=str(ready.id),
        after_snapshot_ref=f"hr07-agreement:{ready.agreement_id}",
        source="api",
    )

    body = api_root(request)
    body["data"] = {
        "caseId": str(ready.id),
        "agreementId": ready.agreement_id,
        "status": ready.status,
    }
    return json_response(request, body)
