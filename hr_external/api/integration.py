"""
hr_external/api/integration.py —— HR08-S6 IAM/教务集成 API。

路由（总册 §84/§96/§97）：
- GET  /api/hr/v1/external-teachers/engagements/{id}/access        访问授权列表
- POST /api/hr/v1/external-teachers/engagements/{id}/access/provision  激活后授权下发（§43 step8）
- GET  /api/hr/v1/external-teachers/engagements/{id}/academic      教务身份
- POST /api/hr/v1/external-teachers/reconciliations/run            对账（academic/access）
- GET  /api/hr/v1/external-teachers/engagements/{id}/access/revoke 发起回收（§66）
"""

from __future__ import annotations

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.models import (
    HrExternalAcademicIdentity,
    HrExternalAccessGrant,
    HrExternalEngagement,
)
from hr_external.permissions import require_hr_external_permission
from hr_external.services.access_service import AccessService
from hr_external.services.audit_service import write_external_audit
from hr_external.services.reconciliation_service import ReconciliationService


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


def _get_engagement(request, engagement_id):
    ctx, err = _ctx(request)
    if err:
        return None, None, err
    eng = HrExternalEngagement.objects.filter(
        tenant_id=ctx.tenant_id, id=engagement_id
    ).first()
    if eng is None:
        return None, None, error_response(request, "EXTERNAL_ENGAGEMENT_NOT_FOUND", "聘期不存在", 404)
    return ctx, eng, None


@require_hr_external_permission("hr08.access.view")
def engagement_access(request, engagement_id):
    """GET .../engagements/{id}/access —— 访问授权列表。"""
    ctx, eng, err = _get_engagement(request, engagement_id)
    if err:
        return err
    grants = HrExternalAccessGrant.objects.filter(
        tenant_id=ctx.tenant_id, engagement_id=eng
    ).order_by("target_system")
    body = api_root(request)
    body["data"] = {
        "engagementId": str(eng.id),
        "status": eng.status,
        "statusLabel": engagement_status_label(eng.status),
        "items": [
            {
                "id": str(g.id),
                "targetSystem": g.target_system,
                "targetSystemLabel": _TARGET_SYSTEM_LABELS.get(g.target_system, g.target_system),
                "roleCode": g.role_code,
                "scope": g.scope_json,
                "grantedAt": g.granted_at.isoformat() if g.granted_at else None,
                "expiresAt": g.expires_at.isoformat() if g.expires_at else None,
                "revokedAt": g.revoked_at.isoformat() if g.revoked_at else None,
                "status": g.status,
                "statusLabel": access_grant_status_label(g.status),
            }
            for g in grants
        ],
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.access.manage")
def engagement_access_provision(request, engagement_id):
    """POST .../engagements/{id}/access/provision —— 创建 scoped grants + GRANT requests。"""
    ctx, eng, err = _get_engagement(request, engagement_id)
    if err:
        return err
    grants = AccessService().provision_engagement_access(tenant_id=ctx.tenant_id, engagement=eng)
    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalAccessGranted",
        actor_user_id=ctx.user_id,
        engagement_id=eng.id,
        business_type="HR08_ACCESS",
        business_id=str(eng.id),
        source="api",
    )
    body = api_root(request)
    body["data"] = {
        "engagementId": str(eng.id),
        "grantIds": [str(g.id) for g in grants],
        "note": "IAM Provider # [总控占位] UNAVAILABLE；grant 为 PENDING，由 provisioning/reconciliation 驱动",
    }
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.access.manage")
def engagement_access_revoke(request, engagement_id):
    """POST .../engagements/{id}/access/revoke —— 发起 REVOKE（§66/§105）。"""
    ctx, eng, err = _get_engagement(request, engagement_id)
    if err:
        return err
    grants = AccessService().revoke_engagement_access(tenant_id=ctx.tenant_id, engagement=eng)
    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalAccessRevocationRequested",
        actor_user_id=ctx.user_id,
        engagement_id=eng.id,
        source="api",
    )
    body = api_root(request)
    body["data"] = {"engagementId": str(eng.id), "revoking": [str(g.id) for g in grants]}
    return json_response(request, body, status=202)


@require_hr_external_permission("hr08.access.view")
def engagement_academic(request, engagement_id):
    """GET .../engagements/{id}/academic —— 教务教师身份。"""
    ctx, eng, err = _get_engagement(request, engagement_id)
    if err:
        return err
    ident = HrExternalAcademicIdentity.objects.filter(
        tenant_id=ctx.tenant_id, engagement_id=eng
    ).first()
    body = api_root(request)
    body["data"] = (
        {
            "id": str(ident.id),
            "externalTeacherNo": ident.external_teacher_no,
            "academicTeacherId": ident.academic_teacher_id,
            "validFrom": ident.valid_from.isoformat(),
            "validTo": ident.valid_to.isoformat() if ident.valid_to else None,
            "status": ident.status,
            "lastSyncAt": ident.last_sync_at.isoformat() if ident.last_sync_at else None,
            "driftNote": ident.drift_note,
        }
        if ident
        else None
    )
    return json_response(request, body)


@require_hr_external_permission("hr08.access.manage")
def reconciliation_run(request):
    """POST /api/hr/v1/external-teachers/reconciliations/run —— 对账（academic/access）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    svc = ReconciliationService()
    academic = svc.reconcile_academic_identities(tenant_id=ctx.tenant_id)
    access = svc.reconcile_access_grants(tenant_id=ctx.tenant_id)
    body = api_root(request)
    body["data"] = {
        "academic": {"checked": academic.checked, "driftCount": academic.drift_count},
        "access": {"checked": access.checked, "driftCount": access.drift_count},
    }
    return json_response(request, body)
