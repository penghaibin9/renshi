from datetime import date
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.utils import timezone

from hr_data.models import (
    AsOfEvidenceSnapshot,
    ExchangeReceipt,
    ExchangeReconciliation,
    MetricEvaluationSnapshot,
    SubmissionSnapshot,
)
from horilla.hr_domain_models import HrTenantScopedModel


class Hr18EvidenceOrmSealTests(SimpleTestCase):
    def test_append_only_queryset_blocks_update_bulk_update_and_delete(self):
        with self.assertRaisesRegex(ValueError, "HR18_EVIDENCE_IMMUTABLE"):
            AsOfEvidenceSnapshot.objects.all().update(status="PARTIAL")
        with self.assertRaisesRegex(ValueError, "HR18_EVIDENCE_IMMUTABLE"):
            MetricEvaluationSnapshot.objects.bulk_update(
                [MetricEvaluationSnapshot(tenant_id=77)], ["result_json"]
            )
        with self.assertRaisesRegex(ValueError, "HR18_EVIDENCE_IMMUTABLE"):
            ExchangeReceipt.objects.all().delete()

    def test_append_only_instances_block_delete(self):
        with self.assertRaisesRegex(ValueError, "HR18_ASOF_EVIDENCE_IMMUTABLE"):
            AsOfEvidenceSnapshot(tenant_id=77).delete()
        with self.assertRaisesRegex(ValueError, "HR18_METRIC_EVALUATION_IMMUTABLE"):
            MetricEvaluationSnapshot(tenant_id=77).delete()
        with self.assertRaisesRegex(ValueError, "HR18_EXCHANGE_RECEIPT_IMMUTABLE"):
            ExchangeReceipt(tenant_id=77).delete()
        with self.assertRaisesRegex(ValueError, "HR18_EXCHANGE_RECONCILIATION_IMMUTABLE"):
            ExchangeReconciliation(tenant_id=77).delete()

    def test_bulk_create_validates_evidence_hash_before_database_access(self):
        invalid = AsOfEvidenceSnapshot(
            tenant_id=77,
            evidence_no="E-BAD-HASH",
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            status=AsOfEvidenceSnapshot.Status.COMPLETE,
            evidence_hash="not-a-sha256",
        )
        with self.assertRaisesRegex(ValueError, "HR18_ASOF_EVIDENCE_HASH_INVALID"):
            AsOfEvidenceSnapshot.objects.bulk_create([invalid])

    def test_reconciliation_hash_covers_every_formal_fact(self):
        reconciliation = ExchangeReconciliation(
            tenant_id=77,
            job_id=uuid4(),
            receipt_id=uuid4(),
            expected_payload_hash="a" * 64,
            received_payload_hash="a" * 64,
            expected_record_count=5,
            received_record_count=5,
            status=ExchangeReconciliation.Status.MATCHED,
            differences_json={},
            reconciled_at=timezone.now(),
        )
        reconciliation.reconciliation_hash = (
            reconciliation.calculate_reconciliation_hash()
        )
        reconciliation._validate_integrity()

        reconciliation.received_record_count = 4
        with self.assertRaisesRegex(ValueError, "RECONCILIATION_HASH_MISMATCH"):
            reconciliation._validate_integrity()


class Hr18SubmissionStateSealTests(SimpleTestCase):
    def _persisted(self, snapshot, *, status):
        values = {
            field: getattr(snapshot, field)
            for field in (*snapshot._IDENTITY_FIELDS, *snapshot._STATE_FIELDS)
        }
        values["status"] = status
        return values

    def test_queryset_and_delete_paths_cannot_bypass_state_machine(self):
        with self.assertRaisesRegex(ValueError, "HR18_SUBMISSION_SERVICE_REQUIRED"):
            SubmissionSnapshot.objects.all().update(status="ACCEPTED")
        with self.assertRaisesRegex(ValueError, "HR18_SUBMISSION_SERVICE_REQUIRED"):
            SubmissionSnapshot.objects.bulk_update(
                [SubmissionSnapshot(tenant_id=77)], ["status"]
            )
        with self.assertRaisesRegex(ValueError, "HR18_SUBMISSION_IMMUTABLE"):
            SubmissionSnapshot(tenant_id=77).delete()

    def test_instance_rejects_illegal_status_jump(self):
        snapshot = SubmissionSnapshot(
            tenant_id=77,
            submission_no="SUB-SEALED",
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            payload_hash="a" * 64,
            status=SubmissionSnapshot.Status.ACCEPTED,
        )
        persisted = self._persisted(snapshot, status=SubmissionSnapshot.Status.DRAFT)
        query = Mock()
        query.values.return_value.first.return_value = persisted
        with patch.object(SubmissionSnapshot._base_manager, "filter", return_value=query):
            with self.assertRaisesRegex(ValueError, "STATE_TRANSITION_INVALID"):
                snapshot.save(update_fields=["status", "updated_at"])

    def test_instance_allows_service_defined_transition(self):
        snapshot = SubmissionSnapshot(
            tenant_id=77,
            submission_no="SUB-VALID",
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            payload_hash="a" * 64,
            status=SubmissionSnapshot.Status.VALIDATED,
            updated_by=19,
        )
        persisted = self._persisted(snapshot, status=SubmissionSnapshot.Status.DRAFT)
        persisted["updated_by"] = 9
        query = Mock()
        query.values.return_value.first.return_value = persisted
        with (
            patch.object(SubmissionSnapshot._base_manager, "filter", return_value=query),
            patch.object(HrTenantScopedModel, "save", return_value=None) as base_save,
        ):
            snapshot.save(update_fields=["status", "updated_by", "updated_at"])

        base_save.assert_called_once()

    def test_transition_table_keeps_service_lifecycle_and_correction_boundary(self):
        allowed = SubmissionSnapshot._ALLOWED_TRANSITIONS
        self.assertIn(
            (SubmissionSnapshot.Status.DRAFT, SubmissionSnapshot.Status.VALIDATED),
            allowed,
        )
        self.assertIn(
            (SubmissionSnapshot.Status.SUBMITTED, SubmissionSnapshot.Status.ACCEPTED),
            allowed,
        )
        self.assertIn(
            (SubmissionSnapshot.Status.REJECTED, SubmissionSnapshot.Status.CORRECTED),
            allowed,
        )
        self.assertNotIn(
            (SubmissionSnapshot.Status.DRAFT, SubmissionSnapshot.Status.SUBMITTED),
            allowed,
        )


class Hr18EvidenceMysqlTriggerTests(SimpleTestCase):
    def test_migration_installs_update_and_delete_triggers_for_core_evidence(self):
        migration = import_module("hr_data.migrations.0014_evidence_database_seals")
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="mysql"),
            execute=Mock(),
        )

        migration.install_mysql_evidence_seals(None, schema_editor)

        sql = "\n".join(call.args[0] for call in schema_editor.execute.call_args_list)
        for table, _code in migration.APPEND_ONLY_TABLES:
            self.assertIn(f"BEFORE UPDATE ON {table}", sql)
            self.assertIn(f"BEFORE DELETE ON {table}", sql)
        self.assertIn("CREATE TRIGGER hr18_submission_guard_update", sql)
        self.assertIn("HR18_SUBMISSION_STATE_TRANSITION_INVALID", sql)
        self.assertIn("CREATE TRIGGER hr18_submission_no_delete", sql)

    def test_non_mysql_database_does_not_receive_mysql_trigger_sql(self):
        migration = import_module("hr_data.migrations.0014_evidence_database_seals")
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="sqlite"),
            execute=Mock(),
        )

        migration.install_mysql_evidence_seals(None, schema_editor)

        schema_editor.execute.assert_not_called()
