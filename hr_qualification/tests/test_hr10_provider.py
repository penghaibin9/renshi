from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr10_development.constants import FactType, VerificationStatus
from hr10_development.models.development_fact import HrDevelopmentFact
from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.hr10 import (
    PROVIDER_VERSION,
    Hr10EnterprisePracticeProvider,
    Hr10TrainingProvider,
)
from hr_staff.models import HrPerson, HrStaffMaster


class Hr10QualificationProviderTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=77, legal_name="HR10证据教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="T-HR10-001",
            legacy_employee_id=501,
        )

    def _fact(
        self,
        *,
        fact_type=FactType.TRAINING_COMPLETION,
        status=VerificationStatus.HR_VERIFIED,
        valid_from=date(2026, 1, 1),
        valid_to=None,
        supersedes_fact_id=None,
        legacy_staff_id=501,
    ):
        return HrDevelopmentFact.objects.create(
            tenant_id=77,
            staff_master_id=legacy_staff_id,
            fact_type=fact_type,
            source_case_type="TEST",
            source_case_id=1001,
            source_revision_no=1,
            activity_type="ENTERPRISE_PRACTICE"
            if fact_type == FactType.ENTERPRISE_PRACTICE
            else "TEACHING_SKILL",
            start_date=valid_from,
            end_date=valid_from,
            verified_hours=Decimal("18.0"),
            verified_days=3,
            verified_credits=Decimal("1.5"),
            level_or_result="PASS",
            verification_status=status,
            evidence_package_hash="a" * 64,
            generated_at=timezone.now(),
            valid_from=valid_from,
            valid_to=valid_to,
            supersedes_fact_id=supersedes_fact_id,
            immutable_hash="b" * 64,
        )

    def test_training_provider_reads_only_trusted_asof_hr10_facts(self):
        trusted = self._fact()
        self._fact(status=VerificationStatus.SELF_REPORTED)
        self._fact(valid_from=date(2027, 1, 1))
        self._fact(legacy_staff_id=999)

        result = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.provider_version, PROVIDER_VERSION)
        self.assertEqual([item.source_object_id for item in result.items], [str(trusted.id)])
        self.assertEqual(result.items[0].verification_status, VerificationStatus.HR_VERIFIED)
        self.assertEqual(result.items[0].quantitative_value, 18.0)
        self.assertEqual(result.items[0].snapshot_json["verifiedCredits"], "1.5")

    def test_enterprise_practice_provider_uses_verified_days(self):
        fact = self._fact(fact_type=FactType.ENTERPRISE_PRACTICE)

        result = Hr10EnterprisePracticeProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].source_object_id, str(fact.id))
        self.assertEqual(result.items[0].quantitative_value, 3.0)

    def test_effective_successor_suppresses_predecessor_without_hiding_history_early(self):
        root = self._fact(valid_from=date(2026, 1, 1))
        successor = self._fact(
            valid_from=date(2026, 7, 1),
            supersedes_fact_id=root.id,
        )

        before = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 6, 30),
        )
        after = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual([item.source_object_id for item in before.items], [str(root.id)])
        self.assertEqual([item.source_object_id for item in after.items], [str(successor.id)])

    def test_missing_canonical_to_legacy_mapping_is_unavailable_not_fake_empty(self):
        self.staff.legacy_employee_id = None
        self.staff.save(update_fields=["legacy_employee_id"])

        result = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
        self.assertEqual(result.items, [])

    def test_cross_tenant_or_wrong_person_mapping_is_unavailable(self):
        result = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=88,
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

        other_person = HrPerson.objects.create(tenant_id=77, legal_name="另一位教师")
        result = Hr10TrainingProvider().provide(
            person_id=other_person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_unknown_source_version_fails_closed(self):
        result = Hr10TrainingProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
            source_version="legacy-placeholder-v0",
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_VERSION_UNSUPPORTED")
