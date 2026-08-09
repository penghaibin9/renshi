"""
hr10_development/services/further_study_service.py

进修服务（总册 §57/§58/§118）。

过程由 HR10 管；最终学历/学位经核验后写回 HR03 EducationHistory。
"""

from datetime import datetime, timezone

from django.db import transaction

from hr10_development.constants import MilestoneType, VerificationStatus


class FurtherStudyService:
    """进修 Case/Milestone 管理。"""

    @staticmethod
    @transaction.atomic
    def verify_milestone(milestone, verification_status: str, evidence_refs: dict | None = None) -> dict:
        """核验进修里程碑。"""
        if milestone.status == "VERIFIED":
            return {"status": "ALREADY_VERIFIED"}

        milestone.status = "VERIFIED"
        milestone.verification_status = verification_status
        if evidence_refs:
            milestone.evidence_refs = evidence_refs
        milestone.save(update_fields=["status", "verification_status", "evidence_refs", "updated_at"])

        # 毕业/取得学位 → 触发 HR03 Education writeback
        if milestone.milestone_type in (MilestoneType.GRADUATED, MilestoneType.CERTIFICATE_RECEIVED):
            from hr10_development.providers.stub_providers import StubEducationWritebackProvider
            result = StubEducationWritebackProvider().submit_education_record(
                tenant_id=milestone.tenant_id,
                staff_master_id=str(getattr(milestone, "case_id", "")),
                education_data={"milestone": milestone.milestone_type},
            )
            return {"status": "VERIFIED", "hr03_writeback": result.status.value}

        return {"status": "VERIFIED"}
