"""HR08 -> HR07 Agreement Provider.

HR07 is the agreement Authority. HR08 stores only scalar references and a
projected lifecycle status. Provider lookups are tenant-scoped, subject-bound,
and fail closed; there is no legacy/payroll fallback.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.db import DatabaseError

from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_external.constants import AgreementProviderStatus
from hr_external.integrations.base import BaseProvider, ProviderResult, ProviderStatus


class AgreementProvider(BaseProvider):
    owner_domain = "HR07"
    sensitivity = "RESTRICTED_HR"

    _STATUS_MAP = {
        HrContractAgreement.Status.DRAFT: AgreementProviderStatus.DRAFT.value,
        HrContractAgreement.Status.WAITING_SIGNATURE: AgreementProviderStatus.WAITING_SIGNATURE.value,
        HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE: AgreementProviderStatus.SIGNED.value,
        HrContractAgreement.Status.ACTIVE: AgreementProviderStatus.ACTIVE.value,
        HrContractAgreement.Status.EXPIRING: AgreementProviderStatus.ACTIVE.value,
        HrContractAgreement.Status.RENEWAL_IN_PROGRESS: AgreementProviderStatus.ACTIVE.value,
        HrContractAgreement.Status.TERMINATED: AgreementProviderStatus.TERMINATED.value,
        HrContractAgreement.Status.EXPIRED: AgreementProviderStatus.TERMINATED.value,
        HrContractAgreement.Status.ARCHIVED: AgreementProviderStatus.TERMINATED.value,
    }

    def resolve_agreement(
        self,
        *,
        tenant_id: int,
        agreement_type_code: str,
        agreement_id: Optional[str] = None,
        subject_reference_type: str = "",
        subject_reference_id: str = "",
        subject_person_id: str = "",
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        if not agreement_id:
            return self.unavailable(
                "PROVIDER_UNAVAILABLE",
                "HR07 agreement reference is required",
            )
        try:
            agreement_uuid = uuid.UUID(str(agreement_id))
        except (TypeError, ValueError, AttributeError):
            return self.unavailable(
                "PROVIDER_UNAVAILABLE",
                "HR07 agreement is unavailable",
            )

        try:
            agreement = (
                HrContractAgreement.objects.filter(
                    id=agreement_uuid,
                    tenant_id=tenant_id,
                    subject_type=HrContractAgreement.SubjectType.EXTERNAL_WORKFORCE,
                )
                .first()
            )
            if agreement is None:
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement is unavailable",
                )
            if subject_reference_type and agreement.subject_reference_type != subject_reference_type:
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement subject is unavailable",
                )
            if subject_reference_id and agreement.subject_reference_id != str(subject_reference_id):
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement subject is unavailable",
                )
            if subject_person_id and str(agreement.subject_person_id) != str(subject_person_id):
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement subject is unavailable",
                )
            if agreement_type_code and agreement.agreement_type != agreement_type_code:
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement type is unavailable",
                )

            version = None
            if agreement.current_version_no:
                version = (
                    HrContractVersion.objects.filter(
                        tenant_id=tenant_id,
                        agreement_id=agreement.id,
                        version_no=agreement.current_version_no,
                    )
                    .first()
                )
                if version is None:
                    return self.unavailable(
                        "PROVIDER_UNAVAILABLE",
                        "HR07 current agreement version is unavailable",
                    )

            status = self._STATUS_MAP.get(
                agreement.status,
                AgreementProviderStatus.UNAVAILABLE.value,
            )
            if status == AgreementProviderStatus.UNAVAILABLE.value:
                return self.unavailable(
                    "PROVIDER_UNAVAILABLE",
                    "HR07 agreement status is unavailable",
                )

            data = {
                "agreementStatus": status,
                "agreementNo": agreement.agreement_no,
                "signedAt": version.signed_at.isoformat() if version and version.signed_at else None,
                "effectiveFrom": (
                    version.effective_from.isoformat() if version and version.effective_from else None
                ),
                "effectiveTo": (
                    version.effective_to.isoformat() if version and version.effective_to else None
                ),
                "reviewDate": None,
            }
            return ProviderResult(
                status=ProviderStatus.OK,
                data=data,
                source_version=str(agreement.current_version_no),
                source_updated_at=(
                    agreement.updated_at.isoformat() if agreement.updated_at else None
                ),
            )
        except DatabaseError:
            return self.unavailable(
                "PROVIDER_UNAVAILABLE",
                "HR07 agreement provider database unavailable",
            )

    def agreement_status_code(self, result: ProviderResult) -> str:
        """Map provider output into the HR08 projection status enum."""
        if result.is_available:
            status = (result.data or {}).get("agreementStatus", "")
            if status in {c.value for c in AgreementProviderStatus}:
                return status
        return AgreementProviderStatus.UNAVAILABLE.value
