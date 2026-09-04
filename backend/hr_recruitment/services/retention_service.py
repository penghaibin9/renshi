"""Retention expiry and irreversible anonymization for HR04 candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from hr_recruitment.constants import (
    ApplicationCanonicalStatus,
    CampaignStatus,
    CandidateStatus,
)
from hr_recruitment.material_storage import delete_application_material
from hr_recruitment.models import (
    HrApplicationMaterial,
    HrCandidateIdentityMatch,
    HrJobApplication,
    HrRecruitmentAuditEvent,
    HrRecruitmentCandidate,
)


TERMINAL_UNSUCCESSFUL_STATUSES = frozenset(
    {
        ApplicationCanonicalStatus.DISQUALIFIED,
        ApplicationCanonicalStatus.ASSESSMENT_FAILED,
        ApplicationCanonicalStatus.OFFER_DECLINED,
        ApplicationCanonicalStatus.WITHDRAWN,
        ApplicationCanonicalStatus.CANCELLED,
    }
)
TERMINAL_CAMPAIGN_STATUSES = frozenset(
    {CampaignStatus.CLOSED, CampaignStatus.COMPLETED, CampaignStatus.ARCHIVED}
)


class CandidateRetentionError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class CandidateRetentionOutcome:
    status: str
    candidate_uid: str
    materials_purged: int = 0


class CandidateRetentionService:
    def __init__(self, tenant_id: int, *, actor: str = "system:retention"):
        self.tenant_id = int(tenant_id)
        self.actor = actor

    def _applications_are_terminal(self, applications) -> bool:
        for application in applications:
            if application.canonical_status in TERMINAL_UNSUCCESSFUL_STATUSES:
                continue
            campaign_status = application.recruitment_position_id.campaign_id.status
            if (
                application.canonical_status == ApplicationCanonicalStatus.DRAFT
                and campaign_status in TERMINAL_CAMPAIGN_STATUSES
            ):
                continue
            return False
        return True

    @transaction.atomic
    def set_legal_hold(self, candidate_id, *, enabled: bool, reason: str):
        reason = str(reason or "").strip()
        if enabled and not reason:
            raise CandidateRetentionError("LEGAL_HOLD_REASON_REQUIRED", "启用留存冻结必须填写依据")
        candidate = (
            HrRecruitmentCandidate.objects.select_for_update()
            .filter(id=candidate_id, tenant_id=self.tenant_id)
            .first()
        )
        if candidate is None:
            raise CandidateRetentionError("CANDIDATE_NOT_FOUND", "候选人不存在")
        if candidate.status == CandidateStatus.ANONYMIZED:
            raise CandidateRetentionError("CANDIDATE_ANONYMIZED", "已匿名化候选人不能变更留存冻结")
        before = candidate.legal_hold
        candidate.legal_hold = bool(enabled)
        candidate.legal_hold_reason = reason if enabled else ""
        candidate.save(update_fields=["legal_hold", "legal_hold_reason", "updated_at"])
        HrRecruitmentAuditEvent.objects.create(
            tenant_id=self.tenant_id,
            event_type="CANDIDATE_LEGAL_HOLD_CHANGED",
            business_object="HrRecruitmentCandidate",
            business_object_id=str(candidate.id),
            actor_id=self.actor,
            action="ENABLE" if enabled else "DISABLE",
            summary="候选人留存冻结状态已变更",
            before_json={"legalHold": before},
            after_json={"legalHold": bool(enabled), "reasonRecorded": bool(reason)},
        )
        return candidate

    @transaction.atomic
    def anonymize_if_due(
        self, candidate_id, *, as_of: date | None = None
    ) -> CandidateRetentionOutcome:
        as_of = as_of or timezone.localdate()
        candidate = (
            HrRecruitmentCandidate.objects.select_for_update()
            .filter(id=candidate_id, tenant_id=self.tenant_id)
            .first()
        )
        if candidate is None:
            raise CandidateRetentionError("CANDIDATE_NOT_FOUND", "候选人不存在")
        if candidate.status == CandidateStatus.ANONYMIZED:
            return CandidateRetentionOutcome("replayed", candidate.candidate_uid)
        if candidate.status != CandidateStatus.ACTIVE:
            return CandidateRetentionOutcome("blocked_status", candidate.candidate_uid)
        if candidate.legal_hold:
            return CandidateRetentionOutcome("legal_hold", candidate.candidate_uid)
        if candidate.retention_until is None or candidate.retention_until >= as_of:
            return CandidateRetentionOutcome("not_due", candidate.candidate_uid)

        applications = list(
            HrJobApplication.objects.select_for_update()
            .select_related("recruitment_position_id__campaign_id")
            .filter(tenant_id=self.tenant_id, candidate_id=candidate)
            .order_by("id")
        )
        if not self._applications_are_terminal(applications):
            return CandidateRetentionOutcome("active_workflow", candidate.candidate_uid)

        materials = list(
            HrApplicationMaterial.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                application_id__candidate_id=candidate,
                purged_at__isnull=True,
            )
            .order_by("id")
        )
        for material in materials:
            delete_application_material(
                material.file_path,
                tenant_id=self.tenant_id,
                application_id=material.application_id_id,
            )

        now = timezone.now()
        if applications:
            HrJobApplication.objects.filter(
                tenant_id=self.tenant_id, candidate_id=candidate
            ).update(form_snapshot={})
        if materials:
            HrApplicationMaterial.objects.filter(
                tenant_id=self.tenant_id,
                id__in=[material.id for material in materials],
            ).update(
                title="",
                file_name="",
                file_path="",
                sha256="",
                mime_type="",
                file_size_bytes=0,
                rejection_reason="",
                purged_at=now,
            )
        HrCandidateIdentityMatch.objects.filter(
            tenant_id=self.tenant_id,
            source_candidate_id=candidate,
        ).update(match_basis_json={})
        HrCandidateIdentityMatch.objects.filter(
            tenant_id=self.tenant_id,
            target_candidate_id=candidate,
        ).update(match_basis_json={})

        candidate.legal_name = "已匿名化"
        candidate.preferred_name = ""
        candidate.primary_email = ""
        candidate.primary_mobile = ""
        candidate.national_id_cipher = ""
        candidate.national_id_hash = ""
        candidate.talent_tags = []
        candidate.legal_hold_reason = ""
        candidate.status = CandidateStatus.ANONYMIZED
        candidate.anonymized_at = now
        candidate.save(
            update_fields=[
                "legal_name",
                "preferred_name",
                "primary_email",
                "primary_mobile",
                "national_id_cipher",
                "national_id_hash",
                "talent_tags",
                "legal_hold_reason",
                "status",
                "anonymized_at",
                "updated_at",
            ]
        )
        HrRecruitmentAuditEvent.objects.create(
            tenant_id=self.tenant_id,
            event_type="CANDIDATE_RETENTION_ANONYMIZED",
            business_object="HrRecruitmentCandidate",
            business_object_id=str(candidate.id),
            actor_id=self.actor,
            action="ANONYMIZE",
            summary="候选人保留期限届满，已清除结构化个人信息和受控材料",
            after_json={
                "candidateUid": candidate.candidate_uid,
                "retentionUntil": candidate.retention_until.isoformat(),
                "materialsPurged": len(materials),
            },
        )
        return CandidateRetentionOutcome(
            "anonymized", candidate.candidate_uid, len(materials)
        )
