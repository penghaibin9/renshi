"""HR03 formal personnel decision sealing and lineage contracts."""

from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from hr_staff.models import HrPersonnelDecision
from hr_staff.services.decision_service import (
    PersonnelAuthorityError,
    PersonnelAuthorityService,
)
from hr_staff.tests.factories import make_person, make_staff


class PersonnelDecisionSealStaticContractTests(SimpleTestCase):
    def test_mysql_migration_contains_insert_update_delete_backstops(self):
        migration = (
            Path(__file__).parents[1]
            / "migrations"
            / "0015_personnel_decision_authority_seal.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TRIGGER hr03_personnel_decision_seal_insert", migration)
        self.assertIn("CREATE TRIGGER hr03_personnel_decision_no_update", migration)
        self.assertIn("CREATE TRIGGER hr03_personnel_decision_no_delete", migration)
        self.assertIn("NEW.tenant_id", migration)
        self.assertIn("NEW.staff_id", migration)
        self.assertIn("NEW.supersedes_decision_id", migration)
        self.assertIn("parent.decision_type = NEW.decision_type", migration)

    def test_bulk_queryset_mutations_are_rejected_before_database_access(self):
        queryset = HrPersonnelDecision.objects.none()
        for operation in (
            lambda: queryset.update(title="tampered"),
            lambda: queryset.delete(),
            lambda: queryset.bulk_create([]),
            lambda: queryset.bulk_update([], ["title"]),
        ):
            with self.assertRaisesMessage(
                ValueError, "HR03_PERSONNEL_DECISION_APPEND_ONLY"
            ):
                operation()


class PersonnelDecisionAuthoritySealTests(TestCase):
    tenant_id = 31

    def setUp(self):
        self.person = make_person(self.tenant_id, "封板老师")
        self.staff = make_staff(self.tenant_id, self.person, "SEAL-0031")
        other_person = make_person(self.tenant_id, "另一位老师")
        self.other_staff = make_staff(
            self.tenant_id, other_person, "SEAL-0032"
        )
        self.service = PersonnelAuthorityService(
            self.tenant_id,
            actor_user_id=91,
            correlation_id="hr03-seal-tests",
        )
        self.now = timezone.now()

    def _original(self, *, no="DEC-SEAL-001", effective_from=None):
        return self.service.create_effective_decision(
            decision_no=no,
            staff_id=self.staff.id,
            decision_type=HrPersonnelDecision.DecisionType.TRANSFER,
            title="调岗决定",
            content_snapshot={"post": "P-100"},
            decided_at=self.now,
            effective_from=effective_from or date(2026, 8, 1),
        )

    def test_formal_fact_is_hashed_and_instance_delete_is_forbidden(self):
        row = self._original()
        self.assertTrue(row.verify_content_hash())
        self.assertEqual(len(row.content_hash), 64)
        self.assertIsNotNone(row.sealed_at)
        with self.assertRaisesMessage(ValueError, "delete forbidden"):
            row.delete()

    def test_correction_is_idempotent_and_branching_is_rejected(self):
        original = self._original()
        payload = dict(
            prior_decision_id=original.id,
            decision_no="DEC-SEAL-CORRECT-001",
            title="调岗决定更正",
            content_snapshot={"post": "P-101"},
            decided_at=self.now,
            effective_from=date(2026, 9, 1),
            correction_reason="岗位编码录入错误",
            correction_evidence_ref="material://hr03/correction/1",
        )
        correction = self.service.correct_effective_decision(**payload)
        retry = self.service.correct_effective_decision(**payload)
        self.assertEqual(correction.id, retry.id)
        self.assertTrue(correction.verify_content_hash())
        with self.assertRaises(PersonnelAuthorityError) as error:
            self.service.correct_effective_decision(
                **{**payload, "decision_no": "DEC-SEAL-CORRECT-BRANCH"}
            )
        self.assertEqual(
            error.exception.code, "PERSONNEL_DECISION_ALREADY_SUPERSEDED"
        )

    def test_lineage_rejects_cross_staff_and_type_changes(self):
        original = self._original()
        with self.assertRaises(PersonnelAuthorityError) as staff_error:
            self.service.create_effective_decision(
                decision_no="DEC-SEAL-CROSS-STAFF",
                staff_id=self.other_staff.id,
                decision_type=original.decision_type,
                decision_action=HrPersonnelDecision.DecisionAction.CORRECT,
                title="非法更正",
                content_snapshot={"post": "P-900"},
                decided_at=self.now,
                effective_from=date(2026, 9, 1),
                supersedes_decision_id=original.id,
                correction_reason="测试",
                correction_evidence_ref="material://cross-staff",
            )
        self.assertEqual(
            staff_error.exception.code, "PERSONNEL_DECISION_STAFF_MISMATCH"
        )
        with self.assertRaises(PersonnelAuthorityError) as type_error:
            self.service.create_effective_decision(
                decision_no="DEC-SEAL-CROSS-TYPE",
                staff_id=self.staff.id,
                decision_type=HrPersonnelDecision.DecisionType.PROMOTION,
                decision_action=HrPersonnelDecision.DecisionAction.CORRECT,
                title="非法更正",
                content_snapshot={"post": "P-901"},
                decided_at=self.now,
                effective_from=date(2026, 9, 1),
                supersedes_decision_id=original.id,
                correction_reason="测试",
                correction_evidence_ref="material://cross-type",
            )
        self.assertEqual(
            type_error.exception.code, "PERSONNEL_DECISION_TYPE_MISMATCH"
        )

    def test_as_of_query_resolves_then_revokes_chain(self):
        original = self._original(effective_from=date(2026, 8, 1))
        correction = self.service.correct_effective_decision(
            prior_decision_id=original.id,
            decision_no="DEC-SEAL-CORRECT-QUERY",
            title="调岗决定更正",
            content_snapshot={"post": "P-102"},
            decided_at=self.now,
            effective_from=date(2026, 9, 1),
            correction_reason="编码更正",
            correction_evidence_ref="material://query-correction",
        )
        august = list(
            self.service.effective_decisions(
                staff_id=self.staff.id, as_of=date(2026, 8, 31)
            )
        )
        september = list(
            self.service.effective_decisions(
                staff_id=self.staff.id, as_of=date(2026, 9, 2)
            )
        )
        self.assertEqual([row.id for row in august], [original.id])
        self.assertEqual([row.id for row in september], [correction.id])

        self.service.revoke_effective_decision(
            prior_decision_id=correction.id,
            decision_no="DEC-SEAL-REVOKE-QUERY",
            decided_at=self.now + timedelta(days=1),
            effective_from=date(2026, 10, 1),
            correction_reason="原调岗决定依法撤销",
            correction_evidence_ref="material://query-revocation",
        )
        october = list(
            self.service.effective_decisions(
                staff_id=self.staff.id, as_of=date(2026, 10, 2)
            )
        )
        self.assertEqual(october, [])
