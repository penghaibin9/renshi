"""
hr10_development/selectors/record_selector.py

发展档案查询层（HR10-06 聚合视图）。
"""

from hr10_development.models.development_fact import HrDevelopmentFact
from hr10_development.identity import resolve_staff_identity, staff_identity_q


class RecordSelector:
    """教师发展档案聚合查询。"""

    @staticmethod
    def get_staff_overview(tenant_id: int, staff_master_id) -> dict:
        identity = resolve_staff_identity(tenant_id=tenant_id, raw_staff_id=staff_master_id)
        facts = HrDevelopmentFact.objects.effective().filter(
            staff_identity_q(identity), tenant_id=tenant_id,
        )
        verified_facts = facts.filter(
            verification_status__in=[
                "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
                "INTERNAL_INSTRUCTOR_VERIFIED", "HR_VERIFIED",
                "DOCUMENT_VERIFIED", "MANUAL_COMMITTEE_VERIFIED",
            ],
        )

        return {
            "staffMasterId": str(identity.staff_uuid),
            "trainingHours": sum(float(f.verified_hours or 0) for f in verified_facts.filter(fact_type="TRAINING_COMPLETION")[:500]),
            "practiceDays": sum(int(f.verified_days or 0) for f in verified_facts.filter(fact_type="ENTERPRISE_PRACTICE")[:500]),
            "verifiedOutputs": verified_facts.filter(fact_type="DEVELOPMENT_OUTPUT").count(),
            "verifiedFactCount": verified_facts.count(),
            "totalFactCount": facts.count(),
        }

    @staticmethod
    def list_staff_facts(tenant_id: int, staff_master_id, fact_type: str | None = None):
        identity = resolve_staff_identity(tenant_id=tenant_id, raw_staff_id=staff_master_id)
        qs = HrDevelopmentFact.objects.effective().filter(
            staff_identity_q(identity), tenant_id=tenant_id,
        ).order_by("-valid_from")
        if fact_type:
            qs = qs.filter(fact_type=fact_type)
        return qs
