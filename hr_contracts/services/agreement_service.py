"""HR07 agreement signing/effect boundaries.

Regular staff contracts remain bound to HR03 Staff + EmploymentRelationship.
External-workforce agreements are first-class HR07 agreements too, but bind to
the shared HrPerson plus an HR08 business reference and never fabricate a
formal employment relationship.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_contracts.events import (
    EVENT_AGREEMENT_CREATED,
    EVENT_AGREEMENT_EFFECTIVE,
    EVENT_AGREEMENT_SIGNED,
)
from hr_contracts.models import HrContractAgreement, HrContractVersion


class ContractServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AgreementService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ContractServiceError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @staticmethod
    def _subject_event_payload(agreement) -> dict:
        payload = {"subjectType": agreement.subject_type}
        if agreement.staff_id:
            payload["staffId"] = str(agreement.staff_id)
        if agreement.employment_relationship_id:
            payload["employmentRelationshipId"] = str(
                agreement.employment_relationship_id
            )
        if agreement.subject_person_id:
            payload["subjectPersonId"] = str(agreement.subject_person_id)
        if agreement.subject_reference_type:
            payload["subjectReferenceType"] = agreement.subject_reference_type
        if agreement.subject_reference_id:
            payload["subjectReferenceId"] = agreement.subject_reference_id
        return payload

    def _validate_staff_relationship(self, *, staff_id, relationship_id, as_of: date):
        from hr_staff.constants import RelationshipStatus
        from hr_staff.models import HrEmploymentRelationship, HrStaffMaster

        staff = HrStaffMaster.objects.filter(id=staff_id, tenant_id=self.tenant_id).first()
        if staff is None:
            raise ContractServiceError(
                "CONTRACT_STAFF_NOT_FOUND",
                "HR03 staff master not found inside tenant",
            )

        relationship = (
            HrEmploymentRelationship.objects.filter(
                id=relationship_id,
                tenant_id=self.tenant_id,
                staff_id_id=staff.id,
                status=RelationshipStatus.ACTIVE,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .first()
        )
        if relationship is None:
            raise ContractServiceError(
                "CONTRACT_RELATIONSHIP_MISMATCH",
                "active HR03 relationship does not belong to staff inside tenant",
            )
        return staff, relationship

    def _validate_external_person(self, *, person_id):
        from hr_staff.models import HrPerson

        person = HrPerson.objects.filter(id=person_id, tenant_id=self.tenant_id).first()
        if person is None:
            raise ContractServiceError(
                "CONTRACT_EXTERNAL_PERSON_NOT_FOUND",
                "HR03 person identity not found inside tenant",
            )
        return person

    @transaction.atomic
    def create_agreement(
        self,
        *,
        agreement_no: str,
        staff_id,
        employment_relationship_id,
        agreement_title: str,
        agreement_type: str,
        legacy_contract_id: Optional[int] = None,
        as_of: Optional[date] = None,
    ) -> HrContractAgreement:
        """Create an idempotent regular-employment agreement after HR03 validation."""
        effective_day = as_of or date.today()
        self._validate_staff_relationship(
            staff_id=staff_id,
            relationship_id=employment_relationship_id,
            as_of=effective_day,
        )

        existing = (
            HrContractAgreement.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, agreement_no=agreement_no)
            .first()
        )
        if existing is not None:
            expected = (
                HrContractAgreement.SubjectType.STAFF_EMPLOYMENT,
                str(staff_id),
                str(employment_relationship_id),
                agreement_title,
                agreement_type,
                legacy_contract_id,
            )
            observed = (
                existing.subject_type,
                str(existing.staff_id),
                str(existing.employment_relationship_id),
                existing.agreement_title,
                existing.agreement_type,
                existing.legacy_contract_id,
            )
            if observed != expected:
                raise ContractServiceError(
                    "CONTRACT_IDEMPOTENCY_CONFLICT",
                    "agreement_no already belongs to a different contract payload",
                )
            return existing

        agreement = HrContractAgreement.objects.create(
            tenant_id=self.tenant_id,
            agreement_no=agreement_no,
            subject_type=HrContractAgreement.SubjectType.STAFF_EMPLOYMENT,
            staff_id=staff_id,
            employment_relationship_id=employment_relationship_id,
            agreement_title=agreement_title,
            agreement_type=agreement_type,
            status=HrContractAgreement.Status.DRAFT,
            current_version_no=0,
            legacy_contract_id=legacy_contract_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_CREATED,
            payload={
                "agreementId": str(agreement.id),
                "agreementNo": agreement.agreement_no,
                **self._subject_event_payload(agreement),
            },
        )
        return agreement

    @transaction.atomic
    def create_external_agreement(
        self,
        *,
        agreement_no: str,
        person_id,
        subject_reference_type: str,
        subject_reference_id: str,
        agreement_title: str,
        agreement_type: str,
    ) -> HrContractAgreement:
        """Create an HR08 agreement without inventing HR03 staff/employment facts."""
        self._validate_external_person(person_id=person_id)
        subject_reference_type = (subject_reference_type or "").strip()
        subject_reference_id = str(subject_reference_id or "").strip()
        if not subject_reference_type or not subject_reference_id:
            raise ContractServiceError(
                "CONTRACT_EXTERNAL_SUBJECT_REFERENCE_REQUIRED",
                "external agreement requires a source business reference",
            )

        existing = (
            HrContractAgreement.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, agreement_no=agreement_no)
            .first()
        )
        if existing is not None:
            expected = (
                HrContractAgreement.SubjectType.EXTERNAL_WORKFORCE,
                str(person_id),
                subject_reference_type,
                subject_reference_id,
                agreement_title,
                agreement_type,
            )
            observed = (
                existing.subject_type,
                str(existing.subject_person_id),
                existing.subject_reference_type,
                existing.subject_reference_id,
                existing.agreement_title,
                existing.agreement_type,
            )
            if observed != expected:
                raise ContractServiceError(
                    "CONTRACT_IDEMPOTENCY_CONFLICT",
                    "agreement_no already belongs to a different contract payload",
                )
            return existing

        agreement = HrContractAgreement.objects.create(
            tenant_id=self.tenant_id,
            agreement_no=agreement_no,
            subject_type=HrContractAgreement.SubjectType.EXTERNAL_WORKFORCE,
            staff_id=None,
            employment_relationship_id=None,
            subject_person_id=person_id,
            subject_reference_type=subject_reference_type,
            subject_reference_id=subject_reference_id,
            agreement_title=agreement_title,
            agreement_type=agreement_type,
            status=HrContractAgreement.Status.DRAFT,
            current_version_no=0,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_CREATED,
            payload={
                "agreementId": str(agreement.id),
                "agreementNo": agreement.agreement_no,
                **self._subject_event_payload(agreement),
            },
        )
        return agreement

    @staticmethod
    def _content_hash(content_snapshot: dict) -> str:
        payload = json.dumps(
            content_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @transaction.atomic
    def sign_initial_version(
        self,
        *,
        agreement_id,
        effective_from: date,
        effective_to: Optional[date],
        signed_at: datetime,
        signed_document_ref: str,
        content_snapshot: dict,
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrContractVersion:
        """Freeze the first signed contract version; no overwrite/re-sign in place."""
        agreement = (
            HrContractAgreement.objects.select_for_update()
            .filter(id=agreement_id, tenant_id=self.tenant_id)
            .first()
        )
        if agreement is None:
            raise ContractServiceError("CONTRACT_NOT_FOUND", "agreement not found inside tenant")
        if agreement.current_version_no != 0:
            raise ContractServiceError(
                "CONTRACT_INITIAL_VERSION_ALREADY_EXISTS",
                "initial formal version already exists; use change/renewal flow",
            )
        if agreement.status not in (
            HrContractAgreement.Status.DRAFT,
            HrContractAgreement.Status.WAITING_SIGNATURE,
        ):
            raise ContractServiceError(
                "CONTRACT_INVALID_STATE",
                f"agreement status {agreement.status} cannot be initially signed",
            )
        if effective_to is not None and effective_to <= effective_from:
            raise ContractServiceError(
                "CONTRACT_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )
        if not signed_document_ref.strip():
            raise ContractServiceError(
                "CONTRACT_SIGNED_DOCUMENT_REQUIRED",
                "signed document reference is required",
            )
        if not content_snapshot:
            raise ContractServiceError(
                "CONTRACT_CONTENT_REQUIRED",
                "signed content snapshot cannot be empty",
            )

        version = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            version_no=1,
            effective_from=effective_from,
            effective_to=effective_to,
            signed_at=signed_at,
            signed_document_ref=signed_document_ref,
            content_snapshot_json=content_snapshot,
            content_hash=self._content_hash(content_snapshot),
            status=HrContractVersion.Status.SIGNED,
            source_business_type=source_business_type,
            source_business_id=source_business_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        agreement.current_version_no = 1
        agreement.status = HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        agreement.updated_by = self.actor_user_id
        agreement.save(
            update_fields=["current_version_no", "status", "updated_by", "updated_at"]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_SIGNED,
            payload={
                "agreementId": str(agreement.id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "effectiveDate": version.effective_from.isoformat(),
                "contentHash": version.content_hash,
                **self._subject_event_payload(agreement),
            },
        )
        return version

    @transaction.atomic
    def activate_initial_version(
        self,
        *,
        agreement_id,
        version_id,
        as_of: Optional[date] = None,
    ) -> HrContractVersion:
        """Publish ACTIVE only when the frozen signed version is currently effective."""
        effective_day = as_of or timezone.localdate()
        agreement = (
            HrContractAgreement.objects.select_for_update()
            .filter(id=agreement_id, tenant_id=self.tenant_id)
            .first()
        )
        if agreement is None:
            raise ContractServiceError("CONTRACT_NOT_FOUND", "agreement not found inside tenant")

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
                "CONTRACT_VERSION_NOT_FOUND",
                "contract version not found inside tenant/agreement",
            )
        if (
            agreement.status == HrContractAgreement.Status.ACTIVE
            and version.status == HrContractVersion.Status.EFFECTIVE
        ):
            return version
        if agreement.current_version_no != version.version_no:
            raise ContractServiceError(
                "CONTRACT_VERSION_CONFLICT",
                "version is not the agreement current version",
            )
        if version.status != HrContractVersion.Status.SIGNED:
            raise ContractServiceError(
                "CONTRACT_VERSION_INVALID_STATE",
                f"version status {version.status} cannot become effective",
            )
        if version.effective_from > effective_day:
            raise ContractServiceError(
                "CONTRACT_NOT_EFFECTIVE_YET",
                "signed contract effective date has not arrived",
            )
        if version.effective_to is not None and version.effective_to <= effective_day:
            raise ContractServiceError(
                "CONTRACT_ALREADY_EXPIRED",
                "signed contract is already outside its effective interval",
            )

        version.status = HrContractVersion.Status.EFFECTIVE
        version.updated_by = self.actor_user_id
        version.save(update_fields=["status", "updated_by", "updated_at"])

        agreement.status = HrContractAgreement.Status.ACTIVE
        agreement.updated_by = self.actor_user_id
        agreement.save(update_fields=["status", "updated_by", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_EFFECTIVE,
            payload={
                "agreementId": str(agreement.id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "effectiveDate": version.effective_from.isoformat(),
                **self._subject_event_payload(agreement),
            },
        )
        return version
