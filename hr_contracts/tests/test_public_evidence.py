"""Production contracts for source-owned HR07 agreement evidence."""

from datetime import date, datetime, timezone

from django.test import TestCase

from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.public import (
    AgreementEvidenceUnavailable,
    get_formal_agreement_evidence,
)


class AgreementEvidenceTests(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.staff_id = "11111111-1111-1111-1111-111111111111"
        self.relationship_id = "22222222-2222-2222-2222-222222222222"
        self.agreement = HrContractAgreement.objects.create(
            tenant_id=self.tenant_id,
            agreement_no="HT-001",
            staff_id=self.staff_id,
            employment_relationship_id=self.relationship_id,
            agreement_title="教师聘用合同",
            agreement_type="EMPLOYMENT",
            status=HrContractAgreement.Status.ACTIVE,
            current_version_no=2,
        )
        self.old = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=self.agreement,
            version_no=1,
            effective_from=date(2025, 1, 1),
            effective_to=date(2026, 1, 1),
            signed_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            signed_document_ref="doc-v1",
            content_snapshot_json={"salary": "old"},
            content_hash="a" * 64,
            status=HrContractVersion.Status.SUPERSEDED,
        )
        self.current = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=self.agreement,
            version_no=2,
            effective_from=date(2026, 1, 1),
            signed_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            signed_document_ref="doc-v2",
            content_snapshot_json={"salary": "new"},
            content_hash="b" * 64,
            status=HrContractVersion.Status.EFFECTIVE,
            supersedes_version_id=self.old.id,
        )

    def test_as_of_returns_superseded_version_that_was_formal_then(self):
        evidence = get_formal_agreement_evidence(
            tenant_id=self.tenant_id,
            staff_ids=[self.staff_id],
            as_of=date(2025, 6, 1),
        )

        self.assertEqual(len(evidence.rows), 1)
        self.assertEqual(evidence.rows[0].version_id, self.old.id)
        self.assertEqual(evidence.rows[0].version_no, 1)
        self.assertEqual(evidence.missing_staff_ids, ())

    def test_cross_tenant_contract_is_reported_missing(self):
        evidence = get_formal_agreement_evidence(
            tenant_id=20002,
            staff_ids=[self.staff_id],
            as_of=date(2026, 6, 1),
        )

        self.assertEqual(evidence.rows, ())
        self.assertEqual(evidence.missing_staff_ids, (self.staff_id,))

    def test_overlapping_formal_versions_fail_closed(self):
        HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=self.agreement,
            version_no=3,
            effective_from=date(2026, 5, 1),
            signed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            signed_document_ref="doc-conflict",
            content_snapshot_json={"salary": "conflict"},
            content_hash="c" * 64,
            status=HrContractVersion.Status.EFFECTIVE,
            supersedes_version_id=self.current.id,
        )

        with self.assertRaises(AgreementEvidenceUnavailable) as cm:
            get_formal_agreement_evidence(
                tenant_id=self.tenant_id,
                staff_ids=[self.staff_id],
                as_of=date(2026, 6, 1),
            )

        self.assertEqual(cm.exception.code, "FORMAL_VERSION_CONFLICT")
