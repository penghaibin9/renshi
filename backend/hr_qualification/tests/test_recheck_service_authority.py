"""HR09 recognition recheck replay and immutability contracts."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    JurisdictionLevel,
    RecognitionLevel,
    RecognitionStatus,
    RecheckDecision,
    RecheckTrigger,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherRecognition,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.recheck_service import RecheckError, RecheckService
from hr_staff.models import HrPerson, HrStaffMaster


class RecheckServiceAuthorityTests(TestCase):
    def setUp(self):
        self.tenant_id = 90123
        today = timezone.localdate()
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Recheck authority",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=f"RECHECK-{uuid.uuid4().hex}",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.tenant_id,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"RECHECK-PACK-{uuid.uuid4().hex}",
            name="Recheck pack",
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=today - timedelta(days=30),
            status=RulePackVersionStatus.ACTIVE,
            checksum="recheck-authority-checksum",
        )
        self.recognition = HrDoubleTeacherRecognition.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_master_id=staff,
            recognition_no=f"DT-RC-{uuid.uuid4().hex[:12]}",
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            rule_pack_version_id=version,
            effective_from=today - timedelta(days=10),
            status=RecognitionStatus.ACTIVE,
        )

    def test_duplicate_open_trigger_reuses_existing_case(self):
        first = RecheckService.open_recheck(
            self.recognition.id,
            RecheckTrigger.CREDENTIAL_REVOKED,
        )
        second = RecheckService.open_recheck(
            self.recognition.id,
            RecheckTrigger.CREDENTIAL_REVOKED,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.recognition.recheck_cases.filter(status="OPEN").count(), 1)
        self.recognition.refresh_from_db()
        self.assertEqual(self.recognition.status, RecognitionStatus.UNDER_REVIEW)

    def test_invalid_trigger_does_not_mutate_recognition(self):
        with self.assertRaises(RecheckError) as ctx:
            RecheckService.open_recheck(self.recognition.id, "TRUST_ME")

        self.assertEqual(ctx.exception.code, "RECHECK_TRIGGER_INVALID")
        self.recognition.refresh_from_db()
        self.assertEqual(self.recognition.status, RecognitionStatus.ACTIVE)

    def test_closed_decision_replay_is_idempotent(self):
        case = RecheckService.open_recheck(
            self.recognition.id,
            RecheckTrigger.AUDIT,
        )
        first = RecheckService.decide(case.id, RecheckDecision.KEEP, decided_by=7)
        second = RecheckService.decide(case.id, RecheckDecision.KEEP, decided_by=7)

        self.assertEqual(first.id, second.id)
        self.recognition.refresh_from_db()
        self.assertEqual(self.recognition.status, RecognitionStatus.ACTIVE)

    def test_closed_case_cannot_be_rewritten_with_different_decision(self):
        case = RecheckService.open_recheck(
            self.recognition.id,
            RecheckTrigger.AUDIT,
        )
        RecheckService.decide(case.id, RecheckDecision.KEEP)

        with self.assertRaises(RecheckError) as ctx:
            RecheckService.decide(case.id, RecheckDecision.REVOKE)

        self.assertEqual(ctx.exception.code, "RECHECK_DECISION_CONFLICT")
        case.refresh_from_db()
        self.assertEqual(case.decision, RecheckDecision.KEEP)

    def test_upgrade_does_not_fake_level_change_on_existing_fact(self):
        case = RecheckService.open_recheck(
            self.recognition.id,
            RecheckTrigger.POLICY_REQUIRED,
        )

        with self.assertRaises(RecheckError) as ctx:
            RecheckService.decide(case.id, RecheckDecision.UPGRADE)

        self.assertEqual(
            ctx.exception.code,
            "RECHECK_LEVEL_CHANGE_REQUIRES_NEW_RECOGNITION",
        )
        case.refresh_from_db()
        self.recognition.refresh_from_db()
        self.assertEqual(case.status, "OPEN")
        self.assertIsNone(case.decision)
        self.assertEqual(self.recognition.level, RecognitionLevel.DOUBLE_TEACHER_JUNIOR)
        self.assertEqual(self.recognition.status, RecognitionStatus.UNDER_REVIEW)

    def test_terminal_recognition_cannot_open_new_recheck(self):
        self.recognition.status = RecognitionStatus.REVOKED
        self.recognition.save(update_fields=["status", "updated_at"])

        with self.assertRaises(RecheckError) as ctx:
            RecheckService.open_recheck(
                self.recognition.id,
                RecheckTrigger.AUDIT,
            )

        self.assertEqual(ctx.exception.code, "RECHECK_TERMINAL_RECOGNITION")
