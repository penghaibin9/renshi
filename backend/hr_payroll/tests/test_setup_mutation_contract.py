from pathlib import Path

from django.test import SimpleTestCase


class PayrollSetupMutationContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1] / "setup_api.py"
        ).read_text(encoding="utf-8")

    def test_profile_creation_locks_staff_and_existing_profiles(self):
        section = self.source[
            self.source.index("def create_profile"):
            self.source.index("def create_period")
        ]
        self.assertIn("HrStaffMaster.objects.select_for_update()", section)
        self.assertIn("PayrollProfile.objects.select_for_update()", section)
        self.assertIn("profile.full_clean()", section)
        self.assertIn("with transaction.atomic()", section)

    def test_period_overlap_check_and_create_are_one_transaction(self):
        section = self.source[
            self.source.index("def create_period"):
            self.source.index("def freeze_period_input")
        ]
        self.assertIn("PayrollPeriod.objects.select_for_update()", section)
        self.assertIn("period.full_clean()", section)
        self.assertIn("with transaction.atomic()", section)

    def test_validation_and_integrity_errors_are_business_responses(self):
        self.assertIn("except ValidationError", self.source)
        self.assertIn("except IntegrityError", self.source)
