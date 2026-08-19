"""Production contracts for source-owned HR02 organization evidence."""

from datetime import date

from django.test import TestCase

from hr_structure.models import HrOrganization, HrOrganizationVersion
from hr_structure.public import (
    PROVIDER_VERSION,
    OrganizationEvidenceUnavailable,
    get_organization_evidence,
)


class OrganizationEvidenceTests(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.organization = HrOrganization.objects.create(
            tenant_id=self.tenant_id,
            stable_code="COLLEGE-A",
        )
        HrOrganizationVersion.objects.create(
            tenant_id=self.tenant_id,
            organization_id=self.organization,
            name="旧学院",
            short_name="旧院",
            org_type=HrOrganizationVersion.OrgType.COLLEGE,
            validity_from=date(2025, 1, 1),
            validity_to=date(2026, 1, 1),
            version_no=1,
            status=HrOrganizationVersion.Status.SUPERSEDED,
        )
        HrOrganizationVersion.objects.create(
            tenant_id=self.tenant_id,
            organization_id=self.organization,
            name="新学院",
            short_name="新院",
            org_type=HrOrganizationVersion.OrgType.COLLEGE,
            validity_from=date(2026, 1, 1),
            version_no=2,
            status=HrOrganizationVersion.Status.EFFECTIVE,
        )

    def test_as_of_reads_historical_version_not_current_projection(self):
        evidence = get_organization_evidence(
            tenant_id=self.tenant_id,
            organization_ids=[self.organization.id],
            as_of=date(2025, 6, 1),
            source_version=PROVIDER_VERSION,
        )

        self.assertEqual(evidence.rows[0].name, "旧学院")
        self.assertEqual(evidence.rows[0].version_no, 1)
        self.assertEqual(evidence.missing_organization_ids, ())

    def test_cross_tenant_identity_is_reported_missing(self):
        other = HrOrganization.objects.create(
            tenant_id=20002,
            stable_code="FOREIGN",
        )
        HrOrganizationVersion.objects.create(
            tenant_id=20002,
            organization_id=other,
            name="外校组织",
            validity_from=date(2025, 1, 1),
            version_no=1,
            status=HrOrganizationVersion.Status.EFFECTIVE,
        )

        evidence = get_organization_evidence(
            tenant_id=self.tenant_id,
            organization_ids=[other.id],
            as_of=date(2026, 6, 1),
        )

        self.assertEqual(evidence.rows, ())
        self.assertEqual(evidence.missing_organization_ids, (other.id,))

    def test_overlapping_formal_versions_fail_closed(self):
        HrOrganizationVersion.objects.create(
            tenant_id=self.tenant_id,
            organization_id=self.organization,
            name="冲突版本",
            validity_from=date(2026, 5, 1),
            version_no=3,
            status=HrOrganizationVersion.Status.APPROVED,
        )

        with self.assertRaises(OrganizationEvidenceUnavailable) as cm:
            get_organization_evidence(
                tenant_id=self.tenant_id,
                organization_ids=[self.organization.id],
                as_of=date(2026, 6, 1),
            )

        self.assertEqual(cm.exception.code, "FORMAL_VERSION_CONFLICT")
