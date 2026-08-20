"""Reusable authority gate for irreversible HR09 downstream decisions."""

from __future__ import annotations

from hr_qualification.constants import EvidencePackageStatus
from hr_qualification.models import HrDoubleTeacherEvidencePackage
from hr_qualification.services.evidence_service import EvidenceAggregationService
from hr_qualification.services.rule_service import RulePackError, RuleService


class EvidenceAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class EvidenceAuthorityService:
    @classmethod
    def require_frozen_application_evidence(cls, application, *, for_update: bool = False):
        """Return the latest trustworthy FROZEN package for the exact rule authority."""
        rule_version = application.batch_id.rule_pack_version_id
        try:
            RuleService.assert_version_integrity(rule_version)
        except RulePackError as exc:
            raise EvidenceAuthorityError(exc.code, str(exc)) from exc

        qs = HrDoubleTeacherEvidencePackage.objects.filter(
            application_id=application,
            rule_pack_version_id=rule_version,
            status=EvidencePackageStatus.FROZEN,
        ).order_by("-frozen_at", "-generated_at", "-id")
        if for_update:
            qs = qs.select_for_update()
        package = qs.first()
        if package is None:
            raise EvidenceAuthorityError(
                "FROZEN_EVIDENCE_PACKAGE_REQUIRED",
                "formal decision requires a frozen evidence package for the exact rule version",
            )
        observed = EvidenceAggregationService.compute_package_checksum(package)
        if not package.checksum or observed != package.checksum:
            raise EvidenceAuthorityError(
                "EVIDENCE_PACKAGE_CHECKSUM_MISMATCH",
                "frozen evidence package content no longer matches its authority checksum",
            )
        return package
