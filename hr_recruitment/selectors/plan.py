"""
hr_recruitment/selectors/plan.py

HR04-01 年度用人计划只读查询。
硬规则：WHERE → COUNT → ORDER → 分页；禁止先分页后 Python 过滤（总册 48）。
"""

from __future__ import annotations

from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanLine, HrHiringPlanRequest


def list_plan_requests(*, tenant_id, status=None, organization_id=None, page=1, page_size=20):
    qs = HrHiringPlanRequest.objects.filter(tenant_id=tenant_id).select_related("cycle_id")
    if status:
        qs = qs.filter(status=status)
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    total = qs.count()
    qs = qs.order_by("-created_at")[(page - 1) * page_size : page * page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_request_dto(r) for r in qs],
    }


def list_plan_cycles(*, tenant_id, year=None, status=None):
    qs = HrHiringPlanCycle.objects.filter(tenant_id=tenant_id)
    if year:
        qs = qs.filter(year=year)
    if status:
        qs = qs.filter(status=status)
    return [_cycle_dto(c) for c in qs.order_by("-year")]


def get_plan_request(*, tenant_id, request_id):
    try:
        req = HrHiringPlanRequest.objects.select_related("cycle_id").get(
            id=request_id, tenant_id=tenant_id
        )
    except HrHiringPlanRequest.DoesNotExist:
        return None
    lines = HrHiringPlanLine.objects.filter(
        request_id=req, tenant_id=tenant_id
    ).order_by("created_at")
    return {**_request_dto(req), "lines": [_line_dto(l) for l in lines]}


def _request_dto(r: HrHiringPlanRequest) -> dict:
    return {
        "id": str(r.id),
        "cycle_id": str(r.cycle_id_id),
        "cycle_title": r.cycle_id.title if r.cycle_id else "",
        "cycle_year": r.cycle_id.year if r.cycle_id else None,
        "organization_id": r.organization_id,
        "organization_name": r.organization_name,
        "requested_by": r.requested_by,
        "status": r.status,
        "total_requested": r.total_requested,
        "total_approved": r.total_approved,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "returned_reason": r.returned_reason,
        "version": r.version,
    }


def _line_dto(l: HrHiringPlanLine) -> dict:
    return {
        "id": str(l.id),
        "post_catalog_id": l.post_catalog_id,
        "post_catalog_name": l.post_catalog_name,
        "position_id": l.position_id,
        "position_pool_id": l.position_pool_id,
        "need_type": l.need_type,
        "requested_headcount": l.requested_headcount,
        "approved_headcount": l.approved_headcount,
        "requested_fte": str(l.requested_fte),
        "approved_fte": str(l.approved_fte),
        "target_onboard_date": l.target_onboard_date.isoformat() if l.target_onboard_date else None,
        "reason": l.reason,
        "qualification_summary": l.qualification_summary,
        "status": l.status,
        "version": l.version,
    }


def _cycle_dto(c: HrHiringPlanCycle) -> dict:
    return {
        "id": str(c.id),
        "year": c.year,
        "title": c.title,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "status": c.status,
        "version": c.version,
        "notes": c.notes,
    }
