"""
hr_recruitment/selectors/candidate.py

HR04-03 人才库只读查询（总册 23/48）。
硬规则：WHERE → COUNT → ORDER → 分页；禁止先分页后 Python 过滤。
高敏 exact search（身份证）走单独受控接口，不进普通模糊搜索。
"""

from __future__ import annotations

from django.db.models import Q

from hr_recruitment.labels import (
    APPLICATION_STATUS_LABELS,
    CANDIDATE_STATUS_LABELS,
    status_label,
)
from hr_recruitment.models import HrJobApplication, HrRecruitmentCandidate

# 候选来源（展示层映射，不改机器字段）
SOURCE_LABELS = {
    "PUBLIC_PORTAL": "公开报名",
    "ADMIN_CREATED": "管理员录入",
    "LEGACY_MIGRATION": "历史迁移",
    "TALENT_POOL": "人才库",
    "OTHER": "其他",
}


def list_candidates(
    *,
    tenant_id,
    scope=None,
    keyword=None,
    status=None,
    source=None,
    page=1,
    page_size=20,
    exclude_inactive=True,
):
    qs = HrRecruitmentCandidate.objects.filter(tenant_id=tenant_id)
    if scope:
        from hr_recruitment.selectors.scope_utils import apply_org_scope

        qs = apply_org_scope(
            qs, scope, org_field="applications__recruitment_position_id__organization_id"
        ).distinct()
    if exclude_inactive:
        qs = qs.exclude(status="ANONYMIZED")
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    if keyword:
        qs = qs.filter(
            Q(legal_name__icontains=keyword)
            | Q(candidate_no__icontains=keyword)
            | Q(primary_email__icontains=keyword)
            | Q(primary_mobile__icontains=keyword)
        )
    total = qs.count()
    qs = qs.order_by("-created_at")[(page - 1) * page_size : page * page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_candidate_dto(c) for c in qs],
    }


def get_candidate(*, tenant_id, candidate_id):
    try:
        candidate = HrRecruitmentCandidate.objects.get(
            id=candidate_id, tenant_id=tenant_id
        )
    except HrRecruitmentCandidate.DoesNotExist:
        return None
    applications = HrJobApplication.objects.filter(
        tenant_id=tenant_id, candidate_id=candidate
    ).select_related("recruitment_position_id")
    return {
        **_candidate_dto(candidate),
        "applications": [
            {
                "id": str(a.id),
                "application_no": a.application_no,
                "canonical_status": a.canonical_status,
                "canonical_status_label": status_label(
                    APPLICATION_STATUS_LABELS, a.canonical_status
                ),
                "workflow_stage_name": a.workflow_stage_name,
                "recruitment_position": a.recruitment_position_id.post_catalog_name
                if a.recruitment_position_id
                else "",
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            }
            for a in applications
        ],
    }


def _candidate_dto(c) -> dict:
    return {
        "id": str(c.id),
        "candidate_uid": c.candidate_uid,
        "candidate_no": c.candidate_no,
        "legal_name": c.legal_name,
        "preferred_name": c.preferred_name,
        "primary_email": c.primary_email,
        "primary_mobile_masked": _mask(c.primary_mobile),
        "source": c.source,
        "sourceLabel": SOURCE_LABELS.get(c.source, c.source),
        "status": c.status,
        "statusLabel": status_label(CANDIDATE_STATUS_LABELS, c.status),
        "legalHold": c.legal_hold,
        "retentionUntil": c.retention_until.isoformat() if c.retention_until else None,
        "anonymizedAt": c.anonymized_at.isoformat() if c.anonymized_at else None,
        "talent_tags": c.talent_tags,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _mask(mobile: str) -> str:
    if not mobile:
        return ""
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) < 7:
        return "*" * len(digits) if digits else ""
    return f"{digits[:3]}****{digits[-4:]}"
