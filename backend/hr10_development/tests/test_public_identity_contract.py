"""HR10 public identity and identifier normalization contracts."""

import uuid
from datetime import date

from django.test import TestCase

from hr10_development.public import (
    DevelopmentEvidenceUnavailable,
    get_verified_development_facts,
    get_verified_development_facts_for_person,
)
from hr_staff.models import HrPerson, HrStaffMaster


class Hr10PublicIdentityContractTests(TestCase):
    def setUp(self):
        self.tenant_id = 81123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="HR10 public identity",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"HR10-PUBLIC-{uuid.uuid4().hex}",
            legacy_employee_id=91001,
        )

    def test_string_staff_uuid_is_not_falsely_reported_missing(self):
        evidence = get_verified_development_facts(
            tenant_id=self.tenant_id,
            staff_ids=[str(self.staff.id)],
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(evidence.missing_staff_ids, ())

    def test_person_staff_mismatch_fails_closed(self):
        other = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="other",
        )
        with self.assertRaises(DevelopmentEvidenceUnavailable) as cm:
            get_verified_development_facts_for_person(
                tenant_id=self.tenant_id,
                person_id=other.id,
                staff_id=self.staff.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
