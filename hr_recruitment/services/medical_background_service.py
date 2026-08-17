"""
hr_recruitment/services/medical_background_service.py

体检/考察服务（§12.8 / §39 验收）。

敏感隔离：
- 体检/考察材料 HIGH_SENSITIVE；
- 普通招聘管理员默认只看结论（FIT/UNFIT/PASS/FAIL），不看详细医疗材料；
- 查看敏感材料走 SensitiveCandidateAccessLog 审计。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from hr_recruitment.models import HrBackgroundCheck, HrMedicalCheck


class MedicalBackgroundServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class MedicalBackgroundService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    # ---- 体检 ----

    @transaction.atomic
    def record_medical(
        self,
        *,
        application_id: str,
        result: str,
        scheduled_at=None,
        sensitive_material_id=None,
        verified_by: str = "",
    ) -> HrMedicalCheck:
        """记录体检结论（result ∈ FIT/UNFIT/RECHECK/PENDING）。"""
        check = HrMedicalCheck.objects.filter(
            tenant_id=self.tenant_id, application_id_id=application_id
        ).first()
        if check is None:
            check = HrMedicalCheck.objects.create(
                tenant_id=self.tenant_id,
                application_id_id=application_id,
                status=result,
                scheduled_at=scheduled_at,
            )
        check.result = result
        check.status = result
        check.sensitive_material_id = sensitive_material_id
        check.verified_by = verified_by or self.actor
        check.verified_at = timezone.now()
        check.save(
            update_fields=["result", "status", "sensitive_material_id", "verified_by", "verified_at"]
        )
        from hr_recruitment.services.audit_service import audit_event

        audit_event(
            tenant_id=self.tenant_id,
            event_type="MEDICAL_CHECK_RECORDED",
            business_object="HrJobApplication",
            business_object_id=application_id,
            actor_id=self.actor,
            action=result,
            summary=f"体检结论：{result}",
            after={"result": result},
        )
        return check

    # ---- 考察/政审 ----

    @transaction.atomic
    def record_background(
        self,
        *,
        application_id: str,
        result: str,
        summary: str = "",
        sensitive_material_id=None,
        verified_by: str = "",
    ) -> HrBackgroundCheck:
        """记录考察/政审结论（result ∈ PASS/FAIL/PENDING）。"""
        check = HrBackgroundCheck.objects.filter(
            tenant_id=self.tenant_id, application_id_id=application_id
        ).first()
        if check is None:
            check = HrBackgroundCheck.objects.create(
                tenant_id=self.tenant_id,
                application_id_id=application_id,
                status=result,
            )
        check.result = result
        check.status = result
        check.summary = summary
        check.sensitive_material_id = sensitive_material_id
        check.verified_by = verified_by or self.actor
        check.verified_at = timezone.now()
        check.save(
            update_fields=["result", "status", "summary", "sensitive_material_id", "verified_by", "verified_at"]
        )
        from hr_recruitment.services.audit_service import audit_event

        audit_event(
            tenant_id=self.tenant_id,
            event_type="BACKGROUND_CHECK_RECORDED",
            business_object="HrJobApplication",
            business_object_id=application_id,
            actor_id=self.actor,
            action=result,
            summary=f"考察结论：{result}",
            after={"result": result},
        )
        return check

    # ---- 只读查询（普通管理员只看结论）----

    def get_medical_summary(self, *, application_id: str) -> dict | None:
        """普通管理员视图：只看结论，不含敏感材料明细。"""
        check = HrMedicalCheck.objects.filter(
            tenant_id=self.tenant_id, application_id_id=application_id
        ).first()
        if check is None:
            return None
        return {
            "result": check.result,
            "verified_at": check.verified_at.isoformat() if check.verified_at else None,
            "has_sensitive_material": bool(check.sensitive_material_id),
        }

    def get_background_summary(self, *, application_id: str) -> dict | None:
        check = HrBackgroundCheck.objects.filter(
            tenant_id=self.tenant_id, application_id_id=application_id
        ).first()
        if check is None:
            return None
        return {
            "result": check.result,
            "summary": check.summary,
            "verified_at": check.verified_at.isoformat() if check.verified_at else None,
            "has_sensitive_material": bool(check.sensitive_material_id),
        }
