import json
import uuid
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_assessment.api.views_assessment import result_corrections
from hr_assessment.models.base import TenantScopedModel
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultRevision
from hr_assessment.services.result_correction_service import (
    AssessmentResultCorrectionError,
    AssessmentResultCorrectionService,
    ResultCorrectionInput,
    canonical_result_snapshot,
)


class Hr12ResultOrmSealTests(SimpleTestCase):
    def test_queryset_update_bulk_update_and_delete_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_FACT_IMMUTABLE"):
            HrFinalAssessmentResult.objects.all().update(grade_code="EXCELLENT")
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_FACT_IMMUTABLE"):
            HrResultRevision.objects.bulk_update(
                [HrResultRevision(tenant_id=77)], ["reason"]
            )
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_FACT_IMMUTABLE"):
            HrResultRevision.objects.all().delete()

    def test_result_insert_generates_hash_and_seal_but_later_save_is_blocked(self):
        result = HrFinalAssessmentResult(
            tenant_id=77,
            case_id=uuid.uuid4(),
            assessment_type="ANNUAL",
            grade_code="QUALIFIED",
        )
        with patch.object(TenantScopedModel, "save", return_value=None):
            result.save()
        self.assertEqual(len(result.content_hash), 64)
        self.assertIsNotNone(result.sealed_at)

        result._state.adding = False
        result.grade_code = "EXCELLENT"
        with self.assertRaisesRegex(ValueError, "HR12_FINAL_RESULT_IMMUTABLE"):
            result.save()

    def test_bulk_create_rejects_supplied_hash_that_does_not_match_payload(self):
        result = HrFinalAssessmentResult(
            tenant_id=77,
            case_id=uuid.uuid4(),
            assessment_type="TERM",
            grade_code="QUALIFIED",
            content_hash="a" * 64,
        )
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_CONTENT_HASH_MISMATCH"):
            HrFinalAssessmentResult.objects.bulk_create([result])


class Hr12ResultCorrectionServiceTests(TestCase):
    tenant_id = 77

    def setUp(self):
        self.result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id,
            case_id=uuid.uuid4(),
            assessment_type="ANNUAL",
            grade_code="QUALIFIED",
            display_grade_snapshot_json={"zh-CN": "合格"},
            decision_reason="首次审定",
            status="FINALIZED",
        )
        self.actor = uuid.uuid4()
        self.service = AssessmentResultCorrectionService(
            self.tenant_id,
            actor_staff_id=self.actor,
            correlation_id="req-hr12-seal",
        )

    def _payload(self, **overrides):
        values = {
            "correction_no": "COR-2026-0001",
            "expected_version": 1,
            "revision_type": "CORRECTION",
            "reason": "复核证据确认原档次录入错误",
            "changes": {
                "gradeCode": "EXCELLENT",
                "displayGrade": {"zh-CN": "优秀"},
            },
        }
        values.update(overrides)
        return ResultCorrectionInput(**values)

    @patch("hr_assessment.services.result_correction_service.emit_registered_event")
    def test_correction_appends_sealed_fact_without_mutating_source(self, emit):
        source_hash = self.result.content_hash

        revision = self.service.append(
            result_id=self.result.id,
            payload=self._payload(),
        )

        self.result.refresh_from_db()
        self.assertEqual(self.result.grade_code, "QUALIFIED")
        self.assertEqual(self.result.content_hash, source_hash)
        self.assertEqual(revision.previous_version, 1)
        self.assertEqual(revision.new_version, 2)
        self.assertEqual(revision.after_snapshot_json["gradeCode"], "EXCELLENT")
        self.assertEqual(revision.after_snapshot_json["status"], "CORRECTED")
        self.assertEqual(len(revision.content_hash), 64)
        self.assertIsNotNone(revision.sealed_at)
        emit.assert_called_once()
        self.assertEqual(
            emit.call_args.kwargs["event_name"],
            "hr.assessment.assessment_result.corrected",
        )
        self.assertEqual(canonical_result_snapshot(self.result)["version"], 2)

    @patch("hr_assessment.services.result_correction_service.emit_registered_event")
    def test_same_correction_number_is_exact_idempotent(self, emit):
        first = self.service.append(result_id=self.result.id, payload=self._payload())
        replay = self.service.append(result_id=self.result.id, payload=self._payload())

        self.assertEqual(replay.id, first.id)
        self.assertEqual(HrResultRevision.objects.count(), 1)
        emit.assert_called_once()

    @patch("hr_assessment.services.result_correction_service.emit_registered_event")
    def test_revocation_is_append_only_and_terminal(self, emit):
        revoked = self.service.append(
            result_id=self.result.id,
            payload=self._payload(
                correction_no="REV-2026-0001",
                revision_type="REVOCATION",
                changes={},
            ),
        )
        self.assertEqual(revoked.after_snapshot_json["status"], "REVOKED")
        with self.assertRaises(AssessmentResultCorrectionError) as caught:
            self.service.append(
                result_id=self.result.id,
                payload=self._payload(
                    correction_no="COR-AFTER-REVOKE",
                    expected_version=2,
                ),
            )
        self.assertEqual(caught.exception.code, "ASSESSMENT_RESULT_ALREADY_REVOKED")

    @patch("hr_assessment.services.result_correction_service.emit_registered_event")
    def test_expected_version_and_tenant_fail_closed(self, emit):
        with self.assertRaises(AssessmentResultCorrectionError) as version_error:
            self.service.append(
                result_id=self.result.id,
                payload=self._payload(expected_version=9),
            )
        self.assertEqual(
            version_error.exception.code, "ASSESSMENT_RESULT_VERSION_CONFLICT"
        )

        foreign_service = AssessmentResultCorrectionService(88)
        with self.assertRaises(AssessmentResultCorrectionError) as tenant_error:
            foreign_service.append(
                result_id=self.result.id,
                payload=self._payload(correction_no="FOREIGN-CORRECTION"),
            )
        self.assertEqual(tenant_error.exception.code, "ASSESSMENT_RESULT_NOT_FOUND")
        emit.assert_not_called()

    def test_revision_instance_and_queryset_cannot_be_changed(self):
        with patch(
            "hr_assessment.services.result_correction_service.emit_registered_event"
        ):
            revision = self.service.append(
                result_id=self.result.id,
                payload=self._payload(),
            )
        revision.reason = "偷偷修改"
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_REVISION_IMMUTABLE"):
            revision.save()
        with self.assertRaisesRegex(ValueError, "HR12_RESULT_FACT_IMMUTABLE"):
            HrResultRevision.objects.filter(id=revision.id).update(reason="绕过")


class Hr12ResultCorrectionApiTests(TestCase):
    def test_post_uses_tenant_scoped_append_service(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=77,
            case_id=uuid.uuid4(),
            assessment_type="TERM",
            grade_code="QUALIFIED",
        )
        request = RequestFactory().post(
            f"/api/v1/hr/assessments/results/{result.id}/corrections",
            data=json.dumps(
                {
                    "correctionNo": "TERM-COR-001",
                    "expectedVersion": 1,
                    "revisionType": "CORRECTION",
                    "reason": "聘期复核结论",
                    "changes": {"decisionReason": "聘期委员会复核通过"},
                }
            ),
            content_type="application/json",
            HTTP_X_REQUEST_ID="req-api-hr12",
        )
        request.user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=True,
            has_perm=lambda _code: True,
        )
        request.tenant_id = 77
        request.staff_id = uuid.uuid4()
        with patch(
            "hr_assessment.services.result_correction_service.emit_registered_event"
        ):
            response = result_corrections(request, result.id)

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)["data"]["revision"]
        self.assertEqual(payload["correctionNo"], "TERM-COR-001")
        self.assertEqual(payload["newVersion"], 2)
        self.assertEqual(payload["after"]["status"], "CORRECTED")


class Hr12MysqlResultSealMigrationTests(SimpleTestCase):
    def test_migration_installs_insert_update_delete_guards(self):
        migration = import_module(
            "hr_assessment.migrations.0012_result_fact_seals"
        )
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="mysql"),
            execute=Mock(),
        )

        migration.install_mysql_result_seals(None, schema_editor)

        sql = "\n".join(
            call.args[0] for call in schema_editor.execute.call_args_list
        )
        for table, code in migration.SEALED_TABLES:
            self.assertIn(f"BEFORE INSERT ON {table}", sql)
            self.assertIn(f"BEFORE UPDATE ON {table}", sql)
            self.assertIn(f"BEFORE DELETE ON {table}", sql)
            self.assertIn(code, sql)
        self.assertIn("SHA-256", sql)

    def test_non_mysql_database_receives_no_mysql_trigger_sql(self):
        migration = import_module(
            "hr_assessment.migrations.0012_result_fact_seals"
        )
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="sqlite"),
            execute=Mock(),
        )

        migration.install_mysql_result_seals(None, schema_editor)

        schema_editor.execute.assert_not_called()
