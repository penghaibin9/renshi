"""HR07 renewal/change/termination write lifecycle.

Formal contract versions are append-only. Renewal and change create a signed
successor version first, then activate it on/after its effective date while
superseding the previous effective version. Termination closes the current
formal version; no path overwrites signed content in place.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_contracts.events import (
    EVENT_AGREEMENT_EFFECTIVE,
    EVENT_AGREEMENT_SIGNED,
    EVENT_AGREEMENT_TERMINATED,
)
from hr_contracts.models import HrContractAgreement, HrContractCase, HrContractVersion
from hr_contracts.services.agreement_service import AgreementService, ContractServiceError


class ContractLifecycleService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ContractServiceError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _subject_event_payload(agreement) -> dict:
        return AgreementService._subject_event_payload(agreement)

    def _agreement(self, agreement_id):
        item = (
            HrContractAgreement.objects.select_for_update()
            .filter(id=agreement_id, tenant_id=self.tenant_id)
            .first()
        )
        if item is None:
            raise ContractServiceError(
                "CONTRACT_NOT_FOUND", "agreement not found inside tenant"
            )
        return item

    def _case(self, case_id):
        item = (
            HrContractCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if item is None:
            raise ContractServiceError(
                "CONTRACT_CASE_NOT_FOUND", "contract case not found inside tenant"
            )
        return item

    def _current_effective_version(self, agreement):
        if not agreement.current_version_no:
            raise ContractServiceError(
                "CONTRACT_FORMAL_VERSION_REQUIRED", "formal contract version is required"
            )
        item = (
            HrContractVersion.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
                version_no=agreement.current_version_no,
            )
            .first()
        )
        if item is None:
            raise ContractServiceError(
                "CONTRACT_VERSION_NOT_FOUND", "current contract version not found"
            )
        return item

    @transaction.atomic
    def create_case(
        self,
        *,
        case_no: str,
        agreement_id,
        case_type: str,
        requested_effective_from: date,
        requested_effective_to: Optional[date] = None,
        reason_code: str = "",
        reason_text: str = "",
    ) -> HrContractCase:
        if case_type not in {
            HrContractCase.CaseType.RENEW,
            HrContractCase.CaseType.CHANGE,
            HrContractCase.CaseType.TERMINATE,
            HrContractCase.CaseType.REVIEW,
        }:
            raise ContractServiceError(
                "CONTRACT_CASE_TYPE_INVALID",
                "only RENEW/CHANGE/TERMINATE/REVIEW are supported",
            )
        case_no = case_no.strip()
        if not case_no:
            raise ContractServiceError("CONTRACT_CASE_NO_REQUIRED", "case_no is required")
        if requested_effective_from is None:
            raise ContractServiceError(
                "CONTRACT_EFFECTIVE_DATE_REQUIRED",
                "requested effective date is required",
            )
        if (
            requested_effective_to is not None
            and requested_effective_to <= requested_effective_from
        ):
            raise ContractServiceError(
                "CONTRACT_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )

        agreement = self._agreement(agreement_id)
        if agreement.status not in {
            HrContractAgreement.Status.ACTIVE,
            HrContractAgreement.Status.EXPIRING,
            HrContractAgreement.Status.RENEWAL_IN_PROGRESS,
            HrContractAgreement.Status.EXPIRED,
        }:
            raise ContractServiceError(
                "CONTRACT_CASE_NOT_ALLOWED",
                f"agreement status {agreement.status} cannot start {case_type}",
            )

        existing = (
            HrContractCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, case_no=case_no)
            .first()
        )
        if existing is not None:
            expected = (
                str(agreement.id),
                case_type,
                requested_effective_from,
                requested_effective_to,
                reason_code or "",
                reason_text or "",
            )
            observed = (
                str(existing.agreement_id),
                existing.case_type,
                existing.requested_effective_from,
                existing.requested_effective_to,
                existing.reason_code,
                existing.reason_text,
            )
            if observed != expected:
                raise ContractServiceError(
                    "CONTRACT_CASE_IDEMPOTENCY_CONFLICT",
                    "case_no already belongs to a different lifecycle request",
                )
            return existing

        item = HrContractCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=case_no,
            agreement=agreement,
            case_type=case_type,
            status=HrContractCase.Status.DRAFT,
            requested_effective_from=requested_effective_from,
            requested_effective_to=requested_effective_to,
            reason_code=reason_code or "",
            reason_text=reason_text or "",
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if case_type == HrContractCase.CaseType.RENEW:
            agreement.status = HrContractAgreement.Status.RENEWAL_IN_PROGRESS
            agreement.updated_by = self.actor_user_id
            agreement.save(update_fields=["status", "updated_by", "updated_at"])
        return item

    @transaction.atomic
    def submit_case(self, *, case_id) -> HrContractCase:
        item = self._case(case_id)
        if item.status == HrContractCase.Status.SUBMITTED:
            return item
        if item.status not in {
            HrContractCase.Status.DRAFT,
            HrContractCase.Status.RETURNED,
        }:
            raise ContractServiceError(
                "CONTRACT_CASE_INVALID_STATE",
                f"case status {item.status} cannot be submitted",
            )
        item.status = HrContractCase.Status.SUBMITTED
        item.updated_by = self.actor_user_id
        item.save(update_fields=["status", "updated_by", "updated_at"])
        return item

    @transaction.atomic
    def approve_case(self, *, case_id) -> HrContractCase:
        item = self._case(case_id)
        if item.status == HrContractCase.Status.APPROVED:
            return item
        if item.status != HrContractCase.Status.SUBMITTED:
            raise ContractServiceError(
                "CONTRACT_CASE_INVALID_STATE",
                f"case status {item.status} cannot be approved",
            )
        item.status = HrContractCase.Status.APPROVED
        item.approved_at = timezone.now()
        item.approved_by = self.actor_user_id
        item.updated_by = self.actor_user_id
        item.save(
            update_fields=[
                "status",
                "approved_at",
                "approved_by",
                "updated_by",
                "updated_at",
            ]
        )
        return item

    @transaction.atomic
    def sign_successor_version(
        self,
        *,
        case_id,
        signed_at: datetime,
        signed_document_ref: str,
        content_snapshot: dict,
    ) -> HrContractVersion:
        case = self._case(case_id)
        if case.case_type not in {
            HrContractCase.CaseType.RENEW,
            HrContractCase.CaseType.CHANGE,
        }:
            raise ContractServiceError(
                "CONTRACT_CASE_TYPE_INVALID",
                "only renewal/change can create successor versions",
            )
        if case.status == HrContractCase.Status.EFFECT_PENDING:
            existing = (
                HrContractVersion.objects.filter(
                    tenant_id=self.tenant_id,
                    agreement_id=case.agreement_id,
                    source_business_type=case.case_type,
                    source_business_id=str(case.id),
                )
                .order_by("-version_no")
                .first()
            )
            if existing is not None:
                return existing
        if case.status != HrContractCase.Status.APPROVED:
            raise ContractServiceError(
                "CONTRACT_CASE_INVALID_STATE",
                "case must be approved before signing",
            )
        if not signed_document_ref.strip():
            raise ContractServiceError(
                "CONTRACT_SIGNED_DOCUMENT_REQUIRED",
                "signed document reference is required",
            )
        if not content_snapshot:
            raise ContractServiceError(
                "CONTRACT_CONTENT_REQUIRED", "signed content snapshot cannot be empty"
            )

        agreement = self._agreement(case.agreement_id)
        previous = self._current_effective_version(agreement)
        if previous.status != HrContractVersion.Status.EFFECTIVE:
            raise ContractServiceError(
                "CONTRACT_VERSION_INVALID_STATE",
                "current formal version must be EFFECTIVE",
            )
        if case.requested_effective_from <= previous.effective_from:
            raise ContractServiceError(
                "CONTRACT_SUCCESSOR_DATE_INVALID",
                "successor effective date must be later than current version effective date",
            )

        next_no = agreement.current_version_no + 1
        version = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            version_no=next_no,
            version_type=(
                HrContractVersion.VersionType.RENEWAL
                if case.case_type == HrContractCase.CaseType.RENEW
                else HrContractVersion.VersionType.AMENDMENT
            ),
            effective_from=case.requested_effective_from,
            effective_to=case.requested_effective_to,
            signed_at=signed_at,
            signed_document_ref=signed_document_ref.strip(),
            content_snapshot_json=content_snapshot,
            content_hash=AgreementService._content_hash(content_snapshot),
            status=HrContractVersion.Status.SIGNED,
            supersedes_version_id=previous.id,
            source_business_type=case.case_type,
            source_business_id=str(case.id),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        agreement.current_version_no = next_no
        agreement.status = HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        agreement.updated_by = self.actor_user_id
        agreement.save(
            update_fields=["current_version_no", "status", "updated_by", "updated_at"]
        )
        case.status = HrContractCase.Status.EFFECT_PENDING
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_SIGNED,
            payload={
                "agreementId": str(agreement.id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "effectiveDate": version.effective_from.isoformat(),
                "contentHash": version.content_hash,
                "sourceCaseId": str(case.id),
                "sourceCaseType": case.case_type,
                **self._subject_event_payload(agreement),
            },
        )
        return version

    @transaction.atomic
    def activate_successor_version(
        self, *, case_id, version_id, as_of: Optional[date] = None
    ) -> HrContractVersion:
        effective_day = as_of or timezone.localdate()
        case = self._case(case_id)
        if case.status == HrContractCase.Status.EFFECTIVE:
            existing = HrContractVersion.objects.filter(
                id=version_id, tenant_id=self.tenant_id
            ).first()
            if existing is not None and existing.status == HrContractVersion.Status.EFFECTIVE:
                return existing
        if case.status != HrContractCase.Status.EFFECT_PENDING:
            raise ContractServiceError(
                "CONTRACT_CASE_INVALID_STATE", "case is not waiting for effect"
            )

        agreement = self._agreement(case.agreement_id)
        version = (
            HrContractVersion.objects.select_for_update()
            .filter(
                id=version_id,
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
            )
            .first()
        )
        if version is None:
            raise ContractServiceError(
                "CONTRACT_VERSION_NOT_FOUND", "successor version not found"
            )
        if (
            version.version_no != agreement.current_version_no
            or version.status != HrContractVersion.Status.SIGNED
        ):
            raise ContractServiceError(
                "CONTRACT_VERSION_CONFLICT",
                "version is not the current signed successor",
            )
        if version.effective_from > effective_day:
            raise ContractServiceError(
                "CONTRACT_NOT_EFFECTIVE_YET",
                "successor effective date has not arrived",
            )
        if not version.supersedes_version_id:
            raise ContractServiceError(
                "CONTRACT_SUPERSEDED_VERSION_REQUIRED",
                "successor does not reference previous version",
            )

        previous = (
            HrContractVersion.objects.select_for_update()
            .filter(
                id=version.supersedes_version_id,
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
            )
            .first()
        )
        if previous is None or previous.status != HrContractVersion.Status.EFFECTIVE:
            raise ContractServiceError(
                "CONTRACT_PREVIOUS_VERSION_CONFLICT",
                "previous effective version is missing or stale",
            )
        if previous.effective_to is None or previous.effective_to > version.effective_from:
            previous.effective_to = version.effective_from
        previous.status = HrContractVersion.Status.SUPERSEDED
        previous.updated_by = self.actor_user_id
        previous.save(
            update_fields=["effective_to", "status", "updated_by", "updated_at"]
        )

        version.status = HrContractVersion.Status.EFFECTIVE
        version.updated_by = self.actor_user_id
        version.save(update_fields=["status", "updated_by", "updated_at"])
        agreement.status = HrContractAgreement.Status.ACTIVE
        agreement.updated_by = self.actor_user_id
        agreement.save(update_fields=["status", "updated_by", "updated_at"])
        case.status = HrContractCase.Status.EFFECTIVE
        case.effect_receipt_json = {
            "result": "EFFECTIVE",
            "versionId": str(version.id),
            "versionNo": version.version_no,
            "effectiveDate": version.effective_from.isoformat(),
        }
        case.last_effect_error = ""
        case.updated_by = self.actor_user_id
        case.save(
            update_fields=[
                "status",
                "effect_receipt_json",
                "last_effect_error",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_EFFECTIVE,
            payload={
                "agreementId": str(agreement.id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "effectiveDate": version.effective_from.isoformat(),
                "sourceCaseId": str(case.id),
                "sourceCaseType": case.case_type,
                **self._subject_event_payload(agreement),
            },
        )
        return version

    @transaction.atomic
    def effect_termination(
        self, *, case_id, as_of: Optional[date] = None
    ) -> HrContractCase:
        effective_day = as_of or timezone.localdate()
        case = self._case(case_id)
        if case.case_type != HrContractCase.CaseType.TERMINATE:
            raise ContractServiceError(
                "CONTRACT_CASE_TYPE_INVALID", "case is not a termination"
            )
        agreement = self._agreement(case.agreement_id)
        if (
            case.status == HrContractCase.Status.EFFECTIVE
            and agreement.status == HrContractAgreement.Status.TERMINATED
        ):
            return case
        if case.status != HrContractCase.Status.APPROVED:
            raise ContractServiceError(
                "CONTRACT_CASE_INVALID_STATE",
                "termination must be approved before effect",
            )
        terminate_on = case.requested_effective_from
        if terminate_on is None:
            raise ContractServiceError(
                "CONTRACT_EFFECTIVE_DATE_REQUIRED",
                "termination effective date is required",
            )
        if terminate_on > effective_day:
            raise ContractServiceError(
                "CONTRACT_NOT_EFFECTIVE_YET",
                "termination effective date has not arrived",
            )

        current = self._current_effective_version(agreement)
        if current.status != HrContractVersion.Status.EFFECTIVE:
            raise ContractServiceError(
                "CONTRACT_VERSION_INVALID_STATE",
                "current formal version must be EFFECTIVE",
            )
        if terminate_on <= current.effective_from:
            raise ContractServiceError(
                "CONTRACT_TERMINATION_DATE_INVALID",
                "termination date must be after version effective date",
            )
        if current.effective_to is None or current.effective_to > terminate_on:
            current.effective_to = terminate_on
        current.status = HrContractVersion.Status.TERMINATED
        current.updated_by = self.actor_user_id
        current.save(
            update_fields=["effective_to", "status", "updated_by", "updated_at"]
        )

        agreement.status = HrContractAgreement.Status.TERMINATED
        agreement.updated_by = self.actor_user_id
        agreement.save(update_fields=["status", "updated_by", "updated_at"])
        case.status = HrContractCase.Status.EFFECTIVE
        case.effect_receipt_json = {
            "result": "TERMINATED",
            "versionId": str(current.id),
            "effectiveDate": terminate_on.isoformat(),
        }
        case.last_effect_error = ""
        case.updated_by = self.actor_user_id
        case.save(
            update_fields=[
                "status",
                "effect_receipt_json",
                "last_effect_error",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_TERMINATED,
            payload={
                "agreementId": str(agreement.id),
                "versionId": str(current.id),
                "versionNo": current.version_no,
                "effectiveDate": terminate_on.isoformat(),
                "sourceCaseId": str(case.id),
                **self._subject_event_payload(agreement),
            },
        )
        return case
