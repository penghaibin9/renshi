"""Verified further-study milestone service and HR03 writeback boundary."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from hr10_development.constants import (
    DevelopmentEventType,
    MilestoneType,
    VerificationStatus,
)
from hr10_development.models import (
    HrDevelopmentAuditEvent,
    HrDevelopmentOutboxEvent,
    HrFurtherStudyCase,
    HrFurtherStudyMilestone,
)
from hr10_development.providers.base import ProviderStatus


class FurtherStudyVerificationError(Exception):
    code = "FURTHER_STUDY_VERIFICATION_FAILED"


class FurtherStudyWritebackError(Exception):
    code = "HR03_EDUCATION_WRITEBACK_FAILED"


_WRITEBACK_MILESTONES = frozenset(
    {MilestoneType.GRADUATED, MilestoneType.CERTIFICATE_RECEIVED}
)
_TRUSTED_VERIFICATION_STATUSES = frozenset(
    {
        VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
        VerificationStatus.TRAINING_PROVIDER_VERIFIED,
        VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
        VerificationStatus.HR_VERIFIED,
        VerificationStatus.DOCUMENT_VERIFIED,
        VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
        VerificationStatus.MIGRATED_VERIFIED,
    }
)


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _has_document_evidence(evidence: dict) -> bool:
    direct_keys = {
        "document_id",
        "document_ref",
        "evidence_material_id",
        "certificate_document_id",
        "diploma_document_id",
        "degree_document_id",
        "diploma",
        "degree_certificate",
        "certificate",
    }
    if any(evidence.get(key) for key in direct_keys):
        return True
    for key in ("documents", "files", "evidence_documents"):
        value = evidence.get(key)
        if isinstance(value, (list, tuple)) and any(value):
            return True
    return any(
        value
        for key, value in evidence.items()
        if key.endswith(("_document_id", "_document_ref", "_evidence_id"))
    )


def validate_writeback_evidence(milestone, evidence: dict) -> None:
    """Fail closed before any milestone or HR03 fact becomes formal."""

    if milestone.milestone_type not in _WRITEBACK_MILESTONES:
        return
    if not milestone.actual_date:
        raise FurtherStudyVerificationError("毕业/取证里程碑必须填写实际日期")
    if not isinstance(evidence, dict) or not _has_document_evidence(evidence):
        raise FurtherStudyVerificationError("毕业/取证写回必须绑定可追溯文件证据")
    if milestone.milestone_type == MilestoneType.GRADUATED:
        missing = [
            key for key in ("school_name", "education_level") if not evidence.get(key)
        ]
    else:
        missing = [key for key in ("credential_name",) if not evidence.get(key)]
    if missing:
        raise FurtherStudyVerificationError(
            f"写回证据缺少字段: {', '.join(missing)}"
        )


class FurtherStudyService:
    """Verify a milestone only after its required HR03 facts are durable."""

    @staticmethod
    @transaction.atomic
    def verify_milestone(
        milestone,
        verification_status: str,
        evidence_refs: dict | None = None,
        *,
        education_provider=None,
        actor_user_id: int | None = None,
    ) -> dict:
        if verification_status not in _TRUSTED_VERIFICATION_STATUSES:
            raise FurtherStudyVerificationError("该核验状态不能生成 HR03 正式背景事实")

        locked = (
            HrFurtherStudyMilestone.objects.select_for_update()
            .filter(pk=milestone.pk, tenant_id=milestone.tenant_id)
            .first()
        )
        if locked is None:
            raise FurtherStudyVerificationError("进修里程碑不存在或跨学校")
        case = (
            HrFurtherStudyCase.objects.select_for_update()
            .filter(pk=locked.case_id, tenant_id=locked.tenant_id)
            .first()
        )
        if case is None:
            raise FurtherStudyVerificationError("进修案件不存在或与里程碑学校不一致")
        if not case.staff_master_id:
            raise FurtherStudyVerificationError("进修案件缺少 staff_master_id")

        evidence = dict(evidence_refs if evidence_refs is not None else locked.evidence_refs or {})
        validate_writeback_evidence(locked, evidence)
        request_payload = {
            "tenantId": locked.tenant_id,
            "milestoneId": locked.id,
            "caseId": case.id,
            "staffMasterId": str(case.staff_master_id),
            "milestoneType": locked.milestone_type,
            "verificationStatus": verification_status,
            "actualDate": locked.actual_date,
            "evidence": evidence,
        }
        request_hash = _canonical_hash(request_payload)

        if locked.status == "VERIFIED":
            if locked.milestone_type not in _WRITEBACK_MILESTONES:
                return {"status": "ALREADY_VERIFIED"}
            if locked.writeback_status == "SUCCEEDED":
                if locked.writeback_request_hash and locked.writeback_request_hash != request_hash:
                    raise FurtherStudyVerificationError(
                        "已核验里程碑的证据或人员引用发生变化，必须走正式更正"
                    )
                return {
                    "status": "ALREADY_VERIFIED",
                    "hr03_writeback": "OK",
                    "writeback_refs": locked.writeback_refs,
                }

        writeback_refs = {}
        if locked.milestone_type in _WRITEBACK_MILESTONES:
            if education_provider is None:
                from hr10_development.providers.education_writeback_provider import (
                    Hr03EducationWritebackProvider,
                )

                education_provider = Hr03EducationWritebackProvider(
                    actor_user_id=actor_user_id
                )
            result = education_provider.submit_education_record(
                tenant_id=locked.tenant_id,
                # Never substitute the further-study case id for the person reference.
                staff_master_id=str(case.staff_master_id),
                education_data={
                    "milestone_type": locked.milestone_type,
                    "source_business_id": f"FS:{locked.id}",
                    "case_id": case.id,
                    "actual_date": locked.actual_date,
                    "start_date": case.start_date,
                    "planned_end_date": case.planned_end_date,
                    "field_or_major": case.field_or_major,
                    "full_time_or_part_time": case.full_time_or_part_time,
                    "study_type": case.study_type,
                    "host_organization_id": case.host_organization_id,
                    "evidence": evidence,
                },
            )
            if result.status is not ProviderStatus.OK or not isinstance(result.data, dict):
                raise FurtherStudyWritebackError(
                    result.error_message or f"HR03 写回返回 {result.status.value}"
                )
            writeback_refs = dict(result.data)
            expected_ref = (
                "credential_id"
                if locked.milestone_type == MilestoneType.CERTIFICATE_RECEIVED
                else "education_id"
            )
            if not writeback_refs.get(expected_ref):
                raise FurtherStudyWritebackError("HR03 写回未返回正式事实引用")

        before = {
            "status": locked.status,
            "verificationStatus": locked.verification_status,
            "writebackStatus": locked.writeback_status,
        }
        locked.status = "VERIFIED"
        locked.verification_status = verification_status
        locked.evidence_refs = evidence
        locked.writeback_status = (
            "SUCCEEDED" if locked.milestone_type in _WRITEBACK_MILESTONES else "NOT_REQUIRED"
        )
        locked.writeback_refs = writeback_refs
        locked.writeback_request_hash = request_hash
        locked.writeback_error = ""
        locked.writeback_at = (
            timezone.now() if locked.milestone_type in _WRITEBACK_MILESTONES else None
        )
        locked.save(
            update_fields=[
                "status",
                "verification_status",
                "evidence_refs",
                "writeback_status",
                "writeback_refs",
                "writeback_request_hash",
                "writeback_error",
                "writeback_at",
                "updated_at",
            ]
        )

        after = {
            "status": locked.status,
            "verificationStatus": locked.verification_status,
            "writebackStatus": locked.writeback_status,
            "writebackRefs": writeback_refs,
        }
        HrDevelopmentAuditEvent.objects.create(
            tenant_id=locked.tenant_id,
            actor_id_id=actor_user_id,
            object_type="HrFurtherStudyMilestone",
            object_id=str(locked.id),
            action="FurtherStudyMilestoneVerified",
            before_json=before,
            after_json=after,
            revision_ref=request_hash,
        )
        HrDevelopmentOutboxEvent.objects.create(
            tenant_id=locked.tenant_id,
            event_type=DevelopmentEventType.FurtherStudyMilestoneVerified,
            aggregate_type="HrFurtherStudyMilestone",
            aggregate_id=str(locked.id),
            aggregate_version=1,
            correlation_id=str(case.id),
            payload_json={
                "milestone_id": locked.id,
                "case_id": case.id,
                "staff_master_id": str(case.staff_master_id),
                "milestone_type": locked.milestone_type,
                "verification_status": locked.verification_status,
                "writeback_status": locked.writeback_status,
                "writeback_refs": writeback_refs,
            },
        )
        return {
            "status": "VERIFIED",
            "hr03_writeback": (
                "OK" if locked.milestone_type in _WRITEBACK_MILESTONES else "NOT_REQUIRED"
            ),
            "writeback_refs": writeback_refs,
        }
