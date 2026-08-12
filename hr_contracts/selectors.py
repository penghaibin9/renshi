"""Tenant-scoped HR07 read models for UI/API."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from hr_contracts.models import HrContractAgreement, HrContractCase, HrContractVersion
from hr_staff.models import HrStaffMaster


AGREEMENT_STATUS_ZH = {
    "DRAFT": "草稿",
    "WAITING_SIGNATURE": "待签署",
    "SIGNED_WAITING_EFFECTIVE": "已签署待生效",
    "ACTIVE": "履行中",
    "EXPIRING": "即将到期",
    "RENEWAL_IN_PROGRESS": "续签办理中",
    "TERMINATED": "已解除",
    "EXPIRED": "已到期",
    "ARCHIVED": "已归档",
}
CASE_TYPE_ZH = {"SIGN": "签订", "RENEW": "续签", "CHANGE": "变更", "TERMINATE": "解除/终止"}
CASE_STATUS_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "已提交",
    "RETURNED": "退回修改",
    "APPROVED": "审批通过",
    "REJECTED": "审批不通过",
    "EFFECT_PENDING": "待合同生效",
    "EFFECTIVE": "已生效",
    "CANCELLED": "已取消",
}
VERSION_STATUS_ZH = {
    "DRAFT": "草稿",
    "SIGNED": "已签署",
    "EFFECTIVE": "生效中",
    "SUPERSEDED": "已被新版本替代",
    "TERMINATED": "已终止",
    "EXPIRED": "已到期",
}


def _staff_labels(tenant_id: int, staff_ids) -> dict:
    ids = [x for x in set(staff_ids) if x]
    if not ids:
        return {}
    rows = HrStaffMaster.objects.filter(tenant_id=tenant_id, id__in=ids).select_related("person_id")
    return {
        row.id: f"{row.person_id.legal_name or '未命名人员'} · {row.staff_no}" for row in rows
    }


def contract_dashboard(tenant_id: int) -> dict:
    today = timezone.localdate()
    next_90 = today + timedelta(days=90)

    agreements = HrContractAgreement.objects.filter(tenant_id=tenant_id)
    versions = HrContractVersion.objects.filter(tenant_id=tenant_id)
    cases = HrContractCase.objects.filter(tenant_id=tenant_id)

    active_statuses = ["ACTIVE", "EXPIRING", "RENEWAL_IN_PROGRESS", "SIGNED_WAITING_EFFECTIVE"]
    pending_case_statuses = ["SUBMITTED", "RETURNED", "APPROVED", "EFFECT_PENDING"]

    effective_versions = versions.filter(status="EFFECTIVE")
    expiring_versions = effective_versions.filter(effective_to__gte=today, effective_to__lte=next_90)

    staff_map = _staff_labels(tenant_id, agreements.values_list("staff_id", flat=True))

    agreement_rows = []
    for item in agreements.order_by("status", "agreement_no")[:80]:
        current = (
            versions.filter(agreement=item)
            .order_by("-version_no")
            .first()
        )
        agreement_rows.append({
            "id": str(item.id),
            "agreement_no": item.agreement_no,
            "staff": staff_map.get(item.staff_id, str(item.staff_id)),
            "title": item.agreement_title,
            "type": item.agreement_type,
            "status": AGREEMENT_STATUS_ZH.get(item.status, item.status),
            "status_code": item.status,
            "version_no": item.current_version_no,
            "effective_from": current.effective_from if current else None,
            "effective_to": current.effective_to if current else None,
            "version_status": VERSION_STATUS_ZH.get(current.status, current.status) if current else "暂无版本",
        })

    case_rows = []
    case_qs = cases.select_related("agreement").order_by("-created_at")[:80]
    for item in case_qs:
        case_rows.append({
            "id": str(item.id),
            "case_no": item.case_no,
            "agreement_no": item.agreement.agreement_no,
            "title": item.agreement.agreement_title,
            "staff": staff_map.get(item.agreement.staff_id, str(item.agreement.staff_id)),
            "case_type": CASE_TYPE_ZH.get(item.case_type, item.case_type),
            "case_type_code": item.case_type,
            "status": CASE_STATUS_ZH.get(item.status, item.status),
            "status_code": item.status,
            "requested_effective_from": item.requested_effective_from,
            "requested_effective_to": item.requested_effective_to,
            "reason": item.reason_text or item.reason_code or "—",
            "effect_error": item.last_effect_error,
        })

    version_rows = []
    for item in versions.select_related("agreement").order_by("-created_at")[:80]:
        version_rows.append({
            "id": str(item.id),
            "agreement_no": item.agreement.agreement_no,
            "title": item.agreement.agreement_title,
            "version_no": item.version_no,
            "effective_from": item.effective_from,
            "effective_to": item.effective_to,
            "signed_at": item.signed_at,
            "status": VERSION_STATUS_ZH.get(item.status, item.status),
            "status_code": item.status,
            "source_business_type": item.source_business_type,
        })

    return {
        "today": today,
        "summary": {
            "total": agreements.count(),
            "active": agreements.filter(status__in=active_statuses).count(),
            "pending_cases": cases.filter(status__in=pending_case_statuses).count(),
            "pending_signature": agreements.filter(status="WAITING_SIGNATURE").count(),
            "waiting_effect": agreements.filter(status="SIGNED_WAITING_EFFECTIVE").count(),
            "expiring_90": expiring_versions.count(),
            "renewing": agreements.filter(status="RENEWAL_IN_PROGRESS").count(),
            "effect_errors": cases.exclude(last_effect_error="").exclude(last_effect_error__isnull=True).count(),
        },
        "agreements": agreement_rows,
        "cases": case_rows,
        "versions": version_rows,
    }
