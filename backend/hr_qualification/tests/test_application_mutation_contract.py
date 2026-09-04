from pathlib import Path

from django.test import SimpleTestCase


class QualificationApplicationMutationContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1] / "api" / "views_application.py"
        ).read_text(encoding="utf-8")

    def test_batch_creation_is_validated_and_atomic(self):
        source = self.source
        section = source[source.index("def batch_create"):source.index("_BATCH_TRANSITIONS")]
        self.assertIn("with transaction.atomic()", section)
        self.assertIn("HrDoubleTeacherRulePackVersion.objects.select_for_update()", section)
        self.assertIn("batch.full_clean()", section)
        self.assertIn("RecognitionLevel.values", section)
        self.assertIn("except IntegrityError", section)

    def test_application_creation_locks_tenant_entities_and_validates(self):
        source = self.source
        section = source[source.index("def application_create"):source.index("def application_detail")]
        self.assertIn("HrDoubleTeacherRecognitionBatch.objects.select_for_update()", section)
        self.assertIn("HrPerson.objects.select_for_update()", section)
        self.assertIn("HrStaffMaster.objects.select_for_update()", section)
        self.assertIn("app.full_clean()", section)
        self.assertIn("ApplicationRoute.values", section)

    def test_mutation_errors_do_not_expose_internal_exception_details(self):
        self.assertNotIn('error_envelope("INTERNAL_ERROR", str(exc))', self.source)
