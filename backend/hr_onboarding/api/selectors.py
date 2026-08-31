"""
hr_onboarding/api/selectors.py

只读查询（tenant→scope→filter→order→page，禁止 Python 后过滤；00 §31）。
"""

from __future__ import annotations

from typing import Optional

from django.core.paginator import Paginator
from django.db.models import Q

from hr_onboarding.api.labels import (
    label_for,
    ACTIVATION_STATUS_LABELS,
    CASE_STATUS_LABELS,
    EMPLOYMENT_TYPE_LABELS,
    PERSON_MATCH_LABELS,
    SOURCE_TYPE_LABELS,
    STAFF_CATEGORY_LABELS,
    VERIFICATION_STATUS_LABELS,
)
from hr_onboarding.models import HrOnboardingCase


def list_cases(
    *,
    tenant_id: int,
    status: Optional[str] = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """待报到/全部 case 列表（DB 层过滤分页）。"""
    qs = HrOnboardingCase.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    if keyword:
        qs = qs.filter(
            Q(case_no__icontains=keyword)
            | Q(source_id__icontains=keyword)
            | Q(hr04_proposed_hire_id__icontains=keyword)
        )
    qs = qs.order_by("-created_at")
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)
    items = [
        {
            "id": str(c.id),
            "case_no": c.case_no,
            "source_type": c.source_type,
            "sourceTypeLabel": label_for(SOURCE_TYPE_LABELS, c.source_type),
            "source_id": c.source_id,
            "status": c.status,
            "statusLabel": label_for(CASE_STATUS_LABELS, c.status),
            "employment_type": c.employment_type,
            "employmentTypeLabel": label_for(EMPLOYMENT_TYPE_LABELS, c.employment_type),
            "staff_category": c.staff_category,
            "staffCategoryLabel": label_for(STAFF_CATEGORY_LABELS, c.staff_category),
            "expected_report_date": c.expected_report_date.isoformat() if c.expected_report_date else None,
            "actual_report_at": c.actual_report_at.isoformat() if c.actual_report_at else None,
            "person_match_status": c.person_match_status,
            "personMatchStatusLabel": label_for(PERSON_MATCH_LABELS, c.person_match_status),
            "hr03_person_id": str(c.hr03_person_id) if c.hr03_person_id else None,
            "hr03_staff_master_id": str(c.hr03_staff_master_id) if c.hr03_staff_master_id else None,
        }
        for c in page_obj
    ]
    return {
        "items": items,
        "page": page_obj.number,
        "pageSize": page_size,
        "total": paginator.count,
        "hasNext": page_obj.has_next(),
    }


def get_case_detail(*, tenant_id: int, case_id: str) -> Optional[dict]:
    """case 详情（含 profile/portal 摘要/冲突，不含高敏明文）。"""
    try:
        case = HrOnboardingCase.objects.filter(tenant_id=tenant_id, id=case_id).first()
    except (ValueError, TypeError):
        return None
    if case is None:
        return None
    profile = getattr(case, "prehire_profile", None)
    return {
        "id": str(case.id),
        "case_no": case.case_no,
        "source_type": case.source_type,
        "sourceTypeLabel": label_for(SOURCE_TYPE_LABELS, case.source_type),
        "source_id": case.source_id,
        "hr04_proposed_hire_id": case.hr04_proposed_hire_id,
        "status": case.status,
        "statusLabel": label_for(CASE_STATUS_LABELS, case.status),
        "current_stage_code": case.current_stage_code,
        "activation_status": case.activation_status,
        "activationStatusLabel": label_for(ACTIVATION_STATUS_LABELS, case.activation_status),
        "person_match_status": case.person_match_status,
        "personMatchStatusLabel": label_for(PERSON_MATCH_LABELS, case.person_match_status),
        "employment_type": case.employment_type,
        "employmentTypeLabel": label_for(EMPLOYMENT_TYPE_LABELS, case.employment_type),
        "staff_category": case.staff_category,
        "staffCategoryLabel": label_for(STAFF_CATEGORY_LABELS, case.staff_category),
        "expected_report_date": case.expected_report_date.isoformat() if case.expected_report_date else None,
        "actual_report_at": case.actual_report_at.isoformat() if case.actual_report_at else None,
        "hr03_person_id": str(case.hr03_person_id) if case.hr03_person_id else None,
        "hr03_staff_master_id": str(case.hr03_staff_master_id) if case.hr03_staff_master_id else None,
        "legal_name": profile.legal_name if profile else "",
        "verification_status": profile.verification_status if profile else "UNVERIFIED",
        "verificationStatusLabel": label_for(VERIFICATION_STATUS_LABELS, profile.verification_status if profile else ""),
        "open_conflicts": (
            case.data_conflicts.filter(resolution="OPEN").count()
            if hasattr(case, "data_conflicts")
            else 0
        ),
    }
