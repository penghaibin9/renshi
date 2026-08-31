"""Runtime contracts for HR09 final-decision command idempotency."""

import uuid
from datetime import date

from django.db import DatabaseError, connection, transaction
from django.test import TestCase, skipUnlessDBFeature
from django.utils import timezone

from hr_qualification.constants import (
    ApplicationStatus,
    BatchStatus,
    FinalDecisionType,
    JurisdictionLevel,
    RecognitionLevel,
    RecognitionStatus,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherFinalDecisionAmendment,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.final_decision_authority_service import (
    FinalDecisionAuthorityError,
    FinalDecisionAuthorityService,
)
from hr_staff.models import HrPerson, HrStaffMaster


class FinalDecisionIdempotencyRuntimeTests(TestCase):
    tenant_id = 91123

    def setUp(self):
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Final decision idempotency",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=f"HR09-IDEM-{uuid.uuid4().hex}",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.tenant_id,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"IDEM-{uuid.uuid4().hex}",
            name="Idempotency pack",
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=date(2026, 1, 1),
            status=RulePackVersionStatus.ACTIVE,
            checksum="sealed-rule-version",
        )
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=f"IDEM-B-{uuid.uuid4().hex}",
            name="Idempotency batch",
            rule_pack_version_id=version,
            target_levels=[RecognitionLevel.DOUBLE_TEACHER_JUNIOR],
            status=BatchStatus.RESULT_PUBLISHED,
        )
        self.application = HrDoubleTeacherApplication.objects.create(
            tenant_id=self.tenant_id,
            application_no=f"IDEM-A-{uuid.uuid4().hex}",
            batch_id=batch,
            person_id=person,
            staff_master_id=staff,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            status=ApplicationStatus.RECOGNIZED,
        )
        self.decision = HrDoubleTeacherFinalDecision(
            application_id=self.application,
            decision=FinalDecisionType.RECOGNIZE,
            recognized_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            effective_from=date(2026, 9, 1),
            decision_authority="School committee",
            meeting_ref="MEETING-IDEM-1",
            published_at=timezone.now(),
        )
        FinalDecisionAuthorityService.seal_initial(
            self.decision,
            actor_user_id=71,
        )
        HrDoubleTeacherRecognition.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_master_id=staff,
            recognition_no=f"DT-IDEM-{uuid.uuid4().hex}",
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            rule_pack_version_id=version,
            batch_id=batch,
            application_id=self.application,
            effective_from=date(2026, 9, 1),
            status=RecognitionStatus.ACTIVE,
            recognition_authority="School committee",
        )
        self.service = FinalDecisionAuthorityService(self.tenant_id, actor_user_id=72)

    def _correct(self, *, reason="clerical correction", level=None):
        replacement = {"meetingRef": "MEETING-IDEM-2"}
        if level is not None:
            replacement["recognizedLevel"] = level
        return self.service.correct(
            self.decision.id,
            idempotency_key="idem-command-1",
            reason=reason,
            authority_ref="COMMITTEE-RESOLUTION-2",
            replacement=replacement,
            evidence={"documentRef": "DOC-2"},
        )

    def test_exact_command_replay_returns_same_append_only_fact(self):
        first = self._correct()
        second = self._correct()

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.amendment.id, second.amendment.id)
        self.assertEqual(
            len(first.amendment.authority_receipt_json["commandHash"]),
            64,
        )
        self.assertEqual(HrDoubleTeacherFinalDecisionAmendment.objects.count(), 1)

    def test_same_key_with_changed_payload_is_conflict_and_has_no_second_effect(self):
        self._correct()
        self.application.refresh_from_db()
        version_after_first = self.application.version

        with self.assertRaises(FinalDecisionAuthorityError) as caught:
            self._correct(
                reason="different command body",
                level=RecognitionLevel.DOUBLE_TEACHER_INTERMEDIATE,
            )

        self.assertEqual(
            caught.exception.code,
            "FINAL_DECISION_IDEMPOTENCY_CONFLICT",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.version, version_after_first)
        self.assertEqual(HrDoubleTeacherFinalDecisionAmendment.objects.count(), 1)

    def test_wrong_tenant_cannot_replay_or_discover_command(self):
        self._correct()
        other_tenant = FinalDecisionAuthorityService(
            self.tenant_id + 1,
            actor_user_id=73,
        )
        with self.assertRaises(FinalDecisionAuthorityError) as caught:
            other_tenant.correct(
                self.decision.id,
                idempotency_key="idem-command-1",
                reason="clerical correction",
                authority_ref="COMMITTEE-RESOLUTION-2",
                replacement={"meetingRef": "MEETING-IDEM-2"},
                evidence={"documentRef": "DOC-2"},
            )
        self.assertEqual(caught.exception.code, "FINAL_DECISION_NOT_FOUND")

    @skipUnlessDBFeature("supports_transactions")
    def test_mysql_database_triggers_reject_direct_fact_mutation(self):
        if connection.vendor != "mysql":
            self.skipTest("MySQL trigger contract")
        amendment = self._correct().amendment

        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE hr_qualification_hrdoubleteacherfinaldecision "
                    "SET meeting_ref = %s WHERE id = %s",
                    ["TAMPERED", self.decision.id.hex],
                )

        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE hr_qualification_hrdoubleteacherfinaldecisionamendment "
                    "SET reason = %s WHERE id = %s",
                    ["TAMPERED", amendment.id.hex],
                )
