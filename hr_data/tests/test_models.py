from django.test import SimpleTestCase

from hr_data.models import DataQualityFinding, MetricDefinitionVersion, SubmissionSnapshot


class Hr18ModelContractTests(SimpleTestCase):
    def test_metric_definition_requires_as_of_by_default(self):
        metric = MetricDefinitionVersion(
            tenant_id=1,
            metric_code="HEADCOUNT",
            name="Headcount",
            value_type="INTEGER",
            population_code="ACTIVE_STAFF",
            expression="count(staff)",
        )
        assert metric.as_of_required is True

    def test_quality_finding_can_only_record_source_fix_state(self):
        assert "FIXED_AT_SOURCE" in DataQualityFinding.Status.values
        assert "EDITED_IN_HR18" not in DataQualityFinding.Status.values

    def test_submission_keeps_receipt_and_correction_chain(self):
        fields = {field.name for field in SubmissionSnapshot._meta.fields}
        assert "receipt_ref" in fields
        assert "parent_submission_id" in fields
        assert "CORRECTED" in SubmissionSnapshot.Status.values

    def test_tenant_is_fail_closed_before_database_write(self):
        snapshot = SubmissionSnapshot(
            tenant_id=None,
            submission_no="SUB-1",
            definition_code="EDU-REPORT",
            definition_version=1,
            as_of_date="2026-08-10",
            payload_hash="0" * 64,
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            snapshot.save()
