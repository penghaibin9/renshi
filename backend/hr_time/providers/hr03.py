"""Tenant-bound HR03 adapter for HR11 time-policy eligibility."""

from __future__ import annotations

import uuid

from django.db.models import Q

from hr_staff.models import HrStaffAssignment, HrStaffMaster
from hr_time.providers.base import HrProviderError, PersonProvider, ProviderHealth


class LocalHr03PersonProvider(PersonProvider):
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise HrProviderError("TENANT_CONTEXT_REQUIRED", "tenant_id 必填")
        self.tenant_id = tenant_id

    def get_person(self, *, legacy_employee_id, as_of):
        candidates = HrStaffMaster.objects.filter(tenant_id=self.tenant_id)
        staff = candidates.filter(legacy_employee_id=legacy_employee_id).first()
        if staff is None:
            try:
                staff_uuid = uuid.UUID(str(legacy_employee_id))
            except (TypeError, ValueError, AttributeError):
                staff_uuid = None
            if staff_uuid is not None:
                staff = candidates.filter(id=staff_uuid).first()
        if staff is None:
            raise HrProviderError("TIME_SOURCE_UNAVAILABLE", "HR03 教职工主档不存在")
        relationship = (
            staff.employment_relationships.filter(
                tenant_id=self.tenant_id,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .order_by("-effective_from", "id")
            .first()
        )
        return {
            "staff_master_id": str(staff.id),
            "legacy_employee_id": staff.legacy_employee_id,
            "worker_category": staff.staff_category_code,
            "employment_type": relationship.employment_type if relationship else "",
        }

    def get_assignment(self, *, assignment_id, as_of):
        assignment = (
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                id=assignment_id,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .select_related("employment_relationship_id")
            .first()
        )
        if assignment is None:
            raise HrProviderError("TIME_SOURCE_UNAVAILABLE", "HR03 任职事实不存在或未生效")
        return {
            "assignment_id": str(assignment.id),
            "staff_master_id": str(assignment.employment_relationship_id.staff_id_id),
            "org_id": str(assignment.organization_id_id) if assignment.organization_id_id else None,
            "post_id": str(assignment.position_id_id) if assignment.position_id_id else None,
            "effective_from": assignment.effective_from,
            "effective_to": assignment.effective_to,
        }

    def health(self):
        return ProviderHealth(status="FRESH")
