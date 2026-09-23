"""Tenant-scoped HR09 Authority cutover regression tests."""

from django.test import TestCase

from hr_control_center.models import HrAuthorityCutover
from hr_qualification.services.authority_mode_service import (
    QualificationAuthorityMode,
    QualificationAuthorityModeError,
    QualificationAuthorityModeService,
)


class QualificationAuthorityModeTests(TestCase):
    def setUp(self):
        self.service = QualificationAuthorityModeService()
        self.tenant_id = 1001

    def test_missing_cutover_is_explicit_legacy(self):
        self.assertEqual(self.service.get_mode(self.tenant_id), QualificationAuthorityMode.LEGACY)

    def test_authority_cutover_requires_reconciliation_report(self):
        with self.assertRaises(QualificationAuthorityModeError):
            self.service.record_cutover(
                tenant_id=self.tenant_id,
                mode=QualificationAuthorityMode.HR09_AUTHORITY,
                reason="go live",
                cutover_by="qa",
            )

    def test_dual_then_authority_is_persisted_in_shared_ledger(self):
        self.service.record_cutover(
            tenant_id=self.tenant_id,
            mode=QualificationAuthorityMode.DUAL_READ_COMPARE,
            reason="dual read comparison",
            cutover_by="qa",
        )
        self.assertEqual(
            self.service.get_mode(self.tenant_id),
            QualificationAuthorityMode.DUAL_READ_COMPARE,
        )
        self.service.record_cutover(
            tenant_id=self.tenant_id,
            mode=QualificationAuthorityMode.HR09_AUTHORITY,
            reason="comparison accepted",
            cutover_by="qa",
            verification_report_id="HR09-RECON-20260915",
        )
        row = HrAuthorityCutover.objects.get(
            tenant_id=self.tenant_id,
            domain=HrAuthorityCutover.Domain.QUALIFICATION,
        )
        self.assertEqual(row.mode, HrAuthorityCutover.Mode.AUTHORITY_ONLY)
        self.assertEqual(row.verification_report_id, "HR09-RECON-20260915")
        self.assertEqual(self.service.get_mode(self.tenant_id), QualificationAuthorityMode.HR09_AUTHORITY)
