"""Formal HR12 result delivery, acknowledgement and archive workflows.

Every state transition is tenant-scoped, idempotent and writes its registered
business event in the same database transaction. External delivery is never
reported as successful without an explicit receipt reference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_assessment.models import HrAssessmentCase
from hr_assessment.models.result import (
    HrAcknowledgement,
    HrAssessmentArchivePackage,
    HrAssessmentObjection,
    HrFinalAssessmentResult,
    HrResultNotice,
)
from hr_assessment.services.result_correction_service import canonical_result_snapshot


class AssessmentResultLifecycleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ResultVersionState:
    version: int
    status: str
    snapshot: dict


class AssessmentResultLifecycleService:
    DELIVERY_CHANNELS = {"SYSTEM", "EMAIL", "SMS", "PAPER"}
    ACKNOWLEDGEMENT_STATUSES = {
        "RECEIVED_AGREE",
        "RECEIVED_RESERVATION",
        "RECEIVED_DISAGREE",
    }

    def __init__(self, tenant_id: int, actor_staff_id=None, correlation_id: str = ""):
        if not tenant_id:
            raise AssessmentResultLifecycleError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_staff_id = actor_staff_id
        self.correlation_id = str(correlation_id or "")

    def _result(self, result_id, *, lock: bool = True) -> HrFinalAssessmentResult:
        queryset = HrFinalAssessmentResult.objects
        if lock:
            queryset = queryset.select_for_update()
        result = queryset.filter(id=result_id, tenant_id=self.tenant_id).first()
        if result is None:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_RESULT_NOT_FOUND",
                "formal result not found inside tenant",
            )
        return result

    @staticmethod
    def _version_state(result: HrFinalAssessmentResult) -> ResultVersionState:
        snapshot = canonical_result_snapshot(result)
        version = int(snapshot.get("version") or 0)
        status = str(snapshot.get("status") or "").upper()
        if version < 1 or not status:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_RESULT_VERSION_STATE_INVALID",
                "formal result version chain is invalid",
            )
        if status == "REVOKED":
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_RESULT_REVOKED",
                "a revoked result cannot be notified, acknowledged or archived",
            )
        return ResultVersionState(version=version, status=status, snapshot=snapshot)

    @transaction.atomic
    def issue_notice(
        self,
        *,
        result_id,
        notice_no: str,
        delivery_channel: str = "SYSTEM",
        generated_document_id=None,
    ) -> HrResultNotice:
        result = self._result(result_id)
        state = self._version_state(result)
        notice_no = str(notice_no or "").strip()
        if not notice_no:
            year = (result.finalized_at or timezone.now()).year
            notice_no = f"KHJG-{year}-{str(result.id).replace('-', '')[:8].upper()}-V{state.version}"
        channel = str(delivery_channel or "").strip().upper()
        if len(notice_no) > 50:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_NOTICE_NO_INVALID",
                "noticeNo is required and must not exceed 50 characters",
            )
        if channel not in self.DELIVERY_CHANNELS:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_NOTICE_CHANNEL_INVALID",
                "deliveryChannel must be SYSTEM, EMAIL, SMS or PAPER",
            )

        existing = HrResultNotice.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
        ).first()
        if existing is not None:
            if (
                existing.notice_no != notice_no
                or existing.delivery_channel != channel
                or existing.generated_document_id != generated_document_id
            ):
                raise AssessmentResultLifecycleError(
                    "ASSESSMENT_NOTICE_IDEMPOTENCY_CONFLICT",
                    "the current result version already has a different notice",
                )
            return existing

        return HrResultNotice.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            notice_no=notice_no,
            result_version=state.version,
            generated_document_id=generated_document_id,
            delivery_channel=channel,
            delivery_status="PENDING",
        )

    @transaction.atomic
    def confirm_delivery(
        self,
        *,
        notice_id,
        delivery_receipt_ref: str,
        delivered_at=None,
    ) -> HrResultNotice:
        notice = HrResultNotice.objects.select_for_update().filter(
            id=notice_id,
            tenant_id=self.tenant_id,
        ).select_related("result").first()
        if notice is None:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_NOTICE_NOT_FOUND", "result notice not found inside tenant"
            )
        state = self._version_state(notice.result)
        if notice.result_version != state.version:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_NOTICE_VERSION_STALE",
                "a corrected result must be delivered with a new version notice",
            )
        receipt = str(delivery_receipt_ref or "").strip()
        if not receipt or len(receipt) > 200:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_DELIVERY_RECEIPT_REQUIRED",
                "a real delivery receipt reference is required",
            )
        delivered_at = delivered_at or timezone.now()
        if notice.delivery_status == "DELIVERED":
            if notice.delivery_receipt_ref != receipt:
                raise AssessmentResultLifecycleError(
                    "ASSESSMENT_DELIVERY_IDEMPOTENCY_CONFLICT",
                    "notice was already delivered with another receipt",
                )
            return notice
        if notice.delivery_status != "PENDING":
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_NOTICE_INVALID_STATE",
                f"notice status {notice.delivery_status} cannot be delivered",
            )
        notice.delivery_status = "DELIVERED"
        notice.delivery_receipt_ref = receipt
        notice.delivered_at = delivered_at
        notice.save(
            update_fields=[
                "delivery_status",
                "delivery_receipt_ref",
                "delivered_at",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_result.notified",
            payload={
                "resultId": str(notice.result_id),
                "noticeId": str(notice.id),
                "resultVersion": notice.result_version,
                "deliveryChannel": notice.delivery_channel,
                "deliveryReceiptRef": receipt,
                "deliveredAt": notice.delivered_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return notice

    @transaction.atomic
    def acknowledge(
        self,
        *,
        result_id,
        acknowledgement_status: str,
        employee_opinion: str = "",
    ) -> HrAcknowledgement:
        result = self._result(result_id)
        state = self._version_state(result)
        case = HrAssessmentCase.objects.select_for_update().filter(
            id=result.case_id,
            tenant_id=self.tenant_id,
        ).first()
        if case is None:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_RESULT_CASE_NOT_FOUND", "assessment case is missing inside tenant"
            )
        if not self.actor_staff_id or str(case.staff_id) != str(self.actor_staff_id):
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ACK_SELF_SCOPE_REQUIRED",
                "only the assessed employee may acknowledge this result",
            )
        notice = HrResultNotice.objects.filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
            delivery_status="DELIVERED",
            delivered_at__isnull=False,
        ).first()
        if notice is None:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_RESULT_NOT_DELIVERED",
                "the current result version has no verified delivery receipt",
            )
        status = str(acknowledgement_status or "").strip().upper()
        opinion = str(employee_opinion or "").strip()
        if status not in self.ACKNOWLEDGEMENT_STATUSES:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ACK_STATUS_INVALID",
                "acknowledgementStatus must be RECEIVED_AGREE, RECEIVED_RESERVATION or RECEIVED_DISAGREE",
            )
        if status in {"RECEIVED_RESERVATION", "RECEIVED_DISAGREE"} and not opinion:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ACK_OPINION_REQUIRED",
                "employeeOpinion is required for a reserved or disagreeing acknowledgement",
            )

        existing = HrAcknowledgement.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
        ).first()
        if existing is not None:
            if (
                existing.acknowledgement_status != status
                or existing.employee_opinion != opinion
            ):
                raise AssessmentResultLifecycleError(
                    "ASSESSMENT_ACK_IDEMPOTENCY_CONFLICT",
                    "the current result version already has a different acknowledgement",
                )
            return existing

        now = timezone.now()
        acknowledgement = HrAcknowledgement.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            result_version=state.version,
            received_at=notice.delivered_at,
            acknowledgement_status=status,
            employee_opinion=opinion,
            confirmed_at=now,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_result.acknowledged",
            payload={
                "resultId": str(result.id),
                "acknowledgementId": str(acknowledgement.id),
                "staffId": str(case.staff_id),
                "resultVersion": state.version,
                "acknowledgementStatus": status,
                "confirmedAt": now.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return acknowledgement

    @transaction.atomic
    def archive(self, *, result_id, document_refs=None) -> HrAssessmentArchivePackage:
        result = self._result(result_id)
        state = self._version_state(result)
        notice = HrResultNotice.objects.filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
            delivery_status="DELIVERED",
            delivered_at__isnull=False,
        ).first()
        acknowledgement = HrAcknowledgement.objects.filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
            confirmed_at__isnull=False,
        ).first()
        if notice is None or acknowledgement is None:
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ARCHIVE_DELIVERY_ACK_REQUIRED",
                "verified delivery and employee acknowledgement are required before archive",
            )
        if HrAssessmentObjection.objects.filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
        ).exclude(status="CLOSED").exists():
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ARCHIVE_OBJECTION_OPEN",
                "all result objections must be closed before archive",
            )

        refs = sorted({str(value).strip() for value in (document_refs or []) if str(value).strip()})
        if any(len(value) > 200 for value in refs):
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ARCHIVE_DOCUMENT_REF_INVALID",
                "archive document references must not exceed 200 characters",
            )
        latest_revision = result.revisions.order_by(
            "-new_version", "-effective_at", "-id"
        ).first()
        current_fact_hash = (
            latest_revision.content_hash if latest_revision else result.content_hash
        )
        manifest = {
            "schemaVersion": "hr12-archive-v1",
            "tenantId": self.tenant_id,
            "resultId": str(result.id),
            "resultVersion": state.version,
            "resultContentHash": current_fact_hash,
            "canonicalResult": state.snapshot,
            "notice": {
                "noticeId": str(notice.id),
                "noticeNo": notice.notice_no,
                "deliveryChannel": notice.delivery_channel,
                "deliveryReceiptRef": notice.delivery_receipt_ref,
                "deliveredAt": notice.delivered_at.isoformat(),
            },
            "acknowledgement": {
                "acknowledgementId": str(acknowledgement.id),
                "status": acknowledgement.acknowledgement_status,
                "confirmedAt": acknowledgement.confirmed_at.isoformat(),
            },
            "documentRefs": refs,
        }
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        content_hash = hashlib.sha256(encoded).hexdigest()
        package_id = f"HR12-{self.tenant_id}-{result.id}-{state.version}"
        existing = HrAssessmentArchivePackage.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=state.version,
        ).first()
        if existing is not None:
            if existing.content_hash != content_hash:
                raise AssessmentResultLifecycleError(
                    "ASSESSMENT_ARCHIVE_IDEMPOTENCY_CONFLICT",
                    "the current result version is already archived with another manifest",
                )
            return existing

        now = timezone.now()
        archive = HrAssessmentArchivePackage.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            archive_package_id=package_id,
            result_version=state.version,
            document_refs_json=refs,
            manifest_json=manifest,
            content_hash=content_hash,
            archive_status="ARCHIVED",
            archived_at=now,
            sealed_at=now,
            archive_provider_ref=f"hr12://archive/{content_hash}",
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_result.archived",
            payload={
                "resultId": str(result.id),
                "archivePackageId": archive.archive_package_id,
                "resultVersion": state.version,
                "contentHash": content_hash,
                "archivedAt": now.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return archive
