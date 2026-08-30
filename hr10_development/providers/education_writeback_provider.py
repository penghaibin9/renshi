"""Real in-process HR10 -> HR03 education authority boundary."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction

from hr10_development.constants import MilestoneType
from hr10_development.providers.base import (
    EducationWritebackProvider,
    ProviderResult,
    ProviderStatus,
)


SOURCE_DOMAIN = "HR10_FURTHER_STUDY"


class Hr03EducationWritebackProvider(EducationWritebackProvider):
    """Write verified further-study outcomes through HR03 BackgroundService."""

    def __init__(self, *, actor_user_id: int | None = None):
        self.actor_user_id = actor_user_id

    def submit_education_record(
        self,
        tenant_id: int,
        staff_master_id: str,
        education_data: dict,
    ) -> ProviderResult:
        try:
            return self._submit_atomic(
                tenant_id=int(tenant_id),
                staff_master_id=staff_master_id,
                education_data=dict(education_data or {}),
            )
        except Exception as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                data={"code": getattr(exc, "code", "HR03_EDUCATION_WRITEBACK_FAILED")},
                error_message=str(exc),
            )

    @transaction.atomic
    def _submit_atomic(self, *, tenant_id: int, staff_master_id, education_data: dict):
        from hr_staff.constants import SourceCategory, VerificationStatus
        from hr_staff.models import (
            HrCredential,
            HrDegreeRecord,
            HrEducationExperience,
            HrStaffMaster,
        )
        from hr_staff.services.background_service import BackgroundService

        staff = self._resolve_staff(HrStaffMaster, tenant_id, staff_master_id)
        milestone_type = education_data.get("milestone_type")
        source_business_id = str(education_data.get("source_business_id") or "").strip()
        if not source_business_id or len(source_business_id) > 48:
            raise ValueError("HR10_SOURCE_BUSINESS_ID_INVALID")
        evidence = dict(education_data.get("evidence") or {})
        actual_date = education_data.get("actual_date")
        service = BackgroundService(
            tenant_id,
            actor_user_id=self.actor_user_id,
            has_manage_perm=True,
        )
        common = {
            "verification_status": VerificationStatus.VERIFIED,
            "verified_by": self.actor_user_id,
            "source": SourceCategory.BUSINESS_PROCESS,
            "source_domain": SOURCE_DOMAIN,
        }

        if milestone_type == MilestoneType.GRADUATED:
            education_source_id = f"{source_business_id}:EDU"
            degree_source_id = f"{source_business_id}:DEG"
            education = HrEducationExperience.objects.filter(
                tenant_id=tenant_id,
                source_domain=SOURCE_DOMAIN,
                source_business_id=education_source_id,
            ).first()
            degree = HrDegreeRecord.objects.filter(
                tenant_id=tenant_id,
                source_domain=SOURCE_DOMAIN,
                source_business_id=degree_source_id,
            ).first()
            replayed = education is not None and degree is not None
            if education is None:
                education = service.add_education(
                    staff_id=staff,
                    school_name=evidence["school_name"],
                    education_level=evidence["education_level"],
                    major_name=evidence.get("major_name")
                    or education_data.get("field_or_major", ""),
                    country_region=evidence.get("country_region", "CN"),
                    study_type=evidence.get("study_type")
                    or education_data.get("full_time_or_part_time", ""),
                    start_date=education_data.get("start_date"),
                    end_date=actual_date,
                    is_highest_education=bool(evidence.get("is_highest_education", False)),
                    source_business_id=education_source_id,
                    **common,
                )
            if degree is None:
                degree_level = evidence.get("degree_level") or self._derive_degree_level(
                    evidence["education_level"]
                )
                degree = service.add_degree(
                    staff_id=staff,
                    degree_level=degree_level,
                    degree_name=evidence.get("degree_name", ""),
                    granting_institution=evidence.get("granting_institution")
                    or evidence["school_name"],
                    major=evidence.get("major_name")
                    or education_data.get("field_or_major", ""),
                    awarded_date=actual_date,
                    source_business_id=degree_source_id,
                    **common,
                )
            return ProviderResult(
                status=ProviderStatus.OK,
                data={
                    "education_id": str(education.id),
                    "degree_id": str(degree.id),
                    "replayed": replayed,
                },
            )

        if milestone_type == MilestoneType.CERTIFICATE_RECEIVED:
            credential_source_id = f"{source_business_id}:CERT"
            credential = HrCredential.objects.filter(
                tenant_id=tenant_id,
                source_domain=SOURCE_DOMAIN,
                source_business_id=credential_source_id,
            ).first()
            replayed = credential is not None
            if credential is None:
                credential = service.add_credential(
                    staff_id=staff,
                    credential_type=evidence.get("credential_type", "OTHER"),
                    credential_name=evidence["credential_name"],
                    credential_no=evidence.get("credential_no", ""),
                    issuing_authority=evidence.get("issuing_authority", ""),
                    issue_date=actual_date,
                    expiry_date=evidence.get("expiry_date"),
                    level=evidence.get("level", ""),
                    source_business_id=credential_source_id,
                    **common,
                )
            return ProviderResult(
                status=ProviderStatus.OK,
                data={"credential_id": str(credential.id), "replayed": replayed},
            )

        raise ValueError("HR10_MILESTONE_NOT_WRITEBACK_ELIGIBLE")

    @staticmethod
    def _resolve_staff(model, tenant_id: int, staff_master_id):
        """Resolve the HR10 stable reference as HR03 UUID or legacy employee mapping."""

        raw = str(staff_master_id or "").strip()
        if not raw:
            raise ValueError("HR10_STAFF_MASTER_ID_REQUIRED")
        staff = None
        try:
            parsed = UUID(raw)
        except (TypeError, ValueError, AttributeError):
            parsed = None
        if parsed is not None:
            staff = model.objects.select_for_update().filter(
                tenant_id=tenant_id, id=parsed
            ).first()
        elif raw.isdigit():
            staff = model.objects.select_for_update().filter(
                tenant_id=tenant_id,
                legacy_employee_id=int(raw),
            ).first()
        if staff is None:
            raise ValueError("HR10_HR03_STAFF_NOT_FOUND_OR_CROSS_TENANT")
        return staff

    @staticmethod
    def _derive_degree_level(education_level: str) -> str:
        value = (education_level or "").strip()
        mapping = (
            (("博士", "DOCTOR"), "博士"),
            (("硕士", "MASTER"), "硕士"),
            (("本科", "BACHELOR"), "学士"),
        )
        upper = value.upper()
        for tokens, degree in mapping:
            if any(token in value or token in upper for token in tokens):
                return degree
        raise ValueError("HR10_DEGREE_LEVEL_REQUIRED")
