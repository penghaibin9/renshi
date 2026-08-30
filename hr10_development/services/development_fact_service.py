"""
hr10_development/services/development_fact_service.py

发展事实生成服务（总册 §112）。
Only VERIFIED source → DevelopmentFact。
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from django.db import transaction

from hr10_development.constants import FactType, VerificationStatus


class DevelopmentFactService:
    """发展事实生成与 HR09 索引服务。"""

    @staticmethod
    @transaction.atomic
    def generate_fact_from_completion(completion, tenant_id: int):
        """从 VERIFIED completion 生成 DevelopmentFact。"""
        from hr10_development.models.development_fact import HrDevelopmentFact

        if completion.verification_status not in (
            VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
            VerificationStatus.TRAINING_PROVIDER_VERIFIED,
            VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
            VerificationStatus.HR_VERIFIED,
            VerificationStatus.DOCUMENT_VERIFIED,
            VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
        ):
            return None

        # 幂等检查
        existing = HrDevelopmentFact.objects.filter(
            tenant_id=tenant_id,
            source_case_type="HrLearningCompletion",
            source_case_id=completion.id,
        ).first()
        if existing:
            return existing

        fact = HrDevelopmentFact.objects.create(
            tenant_id=tenant_id,
            staff_master_id=completion.enrollment.staff_master_id,
            fact_type=FactType.TRAINING_COMPLETION,
            source_case_type="HrLearningCompletion",
            source_case_id=completion.id,
            source_revision_no=completion.revision_no,
            verified_hours=completion.verified_hours,
            verified_credits=completion.verified_credits,
            verification_status=completion.verification_status,
            evidence_package_hash=completion.evidence_package_id,
            generated_at=datetime.now(timezone.utc),
            sealed_by=completion.verified_by,
        )
        return fact

    @staticmethod
    def rebuild_hr09_index(tenant_id: int, staff_master_id: Optional[int] = None):
        """重建 HR09 证据索引。生产阶段通过异步 job 执行。"""
        from hr10_development.models.development_fact import HrDevelopmentFact

        qs = HrDevelopmentFact.objects.effective().filter(
            tenant_id=tenant_id,
            verification_status__in=[
                VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
                VerificationStatus.TRAINING_PROVIDER_VERIFIED,
                VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
                VerificationStatus.HR_VERIFIED,
                VerificationStatus.DOCUMENT_VERIFIED,
                VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
            ],
        )
        if staff_master_id:
            qs = qs.filter(staff_master_id=staff_master_id)

        counts = {"TRAINING_COMPLETION": 0, "FURTHER_STUDY": 0,
                   "ENTERPRISE_PRACTICE": 0, "DEVELOPMENT_OUTPUT": 0}
        for f in qs:
            counts[f.fact_type] = counts.get(f.fact_type, 0) + 1

        return counts


def _compute_immutable_hash(obj) -> str:
    raw = json.dumps({
        "id": str(obj.id),
        "completion_status": getattr(obj, "completion_status", ""),
        "verified_hours": str(getattr(obj, "verified_hours", "")),
        "verification_status": getattr(obj, "verification_status", ""),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
