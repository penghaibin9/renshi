from pathlib import Path

from django.test import SimpleTestCase


class AppointmentSetupMutationContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1] / "setup_api.py"
        ).read_text(encoding="utf-8")

    def test_policy_version_creation_is_serialized_and_validated(self):
        section = self.source[
            self.source.index("def create_policy"):
            self.source.index("def setup_options")
        ]
        self.assertIn("AppointmentPolicyVersion.objects.select_for_update()", section)
        self.assertIn("APPOINTMENT_POLICY_EFFECTIVE_OVERLAP", section)
        self.assertIn("policy.full_clean()", section)
        self.assertIn("except IntegrityError", section)

    def test_supply_configuration_locks_batch_and_position(self):
        section = self.source[self.source.index("def configure_supply_quota"):]
        self.assertIn("AppointmentBatch.objects.select_for_update()", section)
        self.assertIn("HrPosition.objects.select_for_update()", section)
        self.assertIn("with transaction.atomic()", section)

    def test_integrity_errors_do_not_leak_database_details(self):
        self.assertNotIn('_error("APPOINTMENT_QUOTA_CONFLICT", str(exc)', self.source)
        self.assertIn("批次岗位或额度发生并发冲突", self.source)
