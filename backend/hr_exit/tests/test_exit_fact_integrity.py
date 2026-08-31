from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from hr_exit.models import ExitCase, ExitFact
from hr_exit.services.fact_correction_service import (
    ExitFactCorrectionError,
    ExitFactCorrectionService,
)
from hr_staff.models import HrOutboxEvent


class ExitFactIntegrityTests(TestCase):
    def _sealed_fact(self, *, tenant_id=77, fact_no="EXIT-SEALED-001"):
        fact = ExitFact(
            tenant_id=tenant_id,
            fact_no=fact_no,
            person_id="00000000-0000-0000-0000-000000000201",
            employment_relationship_id="00000000-0000-0000-0000-000000000301",
            source_case_id="00000000-0000-0000-0000-000000000101",
            exit_type=ExitCase.ExitType.RESIGNATION,
            employment_end_date=date(2026, 9, 1),
            last_working_date=date(2026, 8, 31),
            access_end_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
            status=ExitFact.Status.EFFECTIVE,
            effect_receipt_json={"hr03RelationshipStatus": "ENDED"},
            created_by=9,
            updated_by=9,
            sealed_at=timezone.now(),
        )
        fact.content_hash = fact.calculate_content_hash()
        fact.save(force_insert=True)
        return fact

    def test_sealed_fact_rejects_instance_queryset_bulk_update_and_delete(self):
        fact = self._sealed_fact()

        fact.last_working_date = date(2026, 8, 30)
        with self.assertRaisesRegex(ValueError, "EXIT_FACT_IMMUTABLE"):
            fact.save()
        with self.assertRaisesRegex(ValueError, "EXIT_FACT_IMMUTABLE"):
            fact.delete()
        with self.assertRaisesRegex(ValueError, "EXIT_FACT_IMMUTABLE"):
            ExitFact.objects.filter(pk=fact.pk).update(change_reason="tamper")
        with self.assertRaisesRegex(ValueError, "EXIT_FACT_IMMUTABLE"):
            ExitFact.objects.filter(pk=fact.pk).delete()

        stored = ExitFact.objects.get(pk=fact.pk)
        self.assertEqual(stored.last_working_date, date(2026, 8, 31))
        self.assertEqual(stored.content_hash, stored.calculate_content_hash())

    def test_pending_saga_fact_remains_retryable_until_it_is_sealed(self):
        fact = ExitFact.objects.create(
            tenant_id=77,
            fact_no="EXIT-PENDING-001",
            person_id="00000000-0000-0000-0000-000000000201",
            employment_relationship_id="00000000-0000-0000-0000-000000000301",
            source_case_id="00000000-0000-0000-0000-000000000101",
            exit_type=ExitCase.ExitType.RESIGNATION,
            employment_end_date=date(2026, 9, 1),
            status=ExitFact.Status.EFFECT_PENDING,
        )
        ExitFact.objects.filter(pk=fact.pk).update(last_effect_error="retryable")
        fact.refresh_from_db()
        self.assertEqual(fact.last_effect_error, "retryable")
        self.assertIsNone(fact.sealed_at)

    def test_correction_is_sealed_append_only_exact_idempotent_and_outboxed(self):
        source = self._sealed_fact()
        service = ExitFactCorrectionService(
            77, actor_user_id=10, correlation_id="corr-hr16-001"
        )
        revised = service.correct(
            fact_id=source.id,
            fact_no="EXIT-SEALED-001-R1",
            reason_code="DATE_CORRECTION",
            evidence_ref="doc://archive/correction-001",
            changes={"last_working_date": date(2026, 8, 30)},
        )

        self.assertEqual(revised.status, ExitFact.Status.REVISED)
        self.assertEqual(revised.supersedes_fact_id, source.id)
        self.assertEqual(revised.change_reason, "DATE_CORRECTION")
        self.assertEqual(revised.evidence_ref, "doc://archive/correction-001")
        self.assertIsNotNone(revised.sealed_at)
        self.assertEqual(len(revised.content_hash), 64)
        self.assertEqual(revised.content_hash, revised.calculate_content_hash())
        source.refresh_from_db()
        self.assertEqual(source.status, ExitFact.Status.EFFECTIVE)
        self.assertEqual(source.last_working_date, date(2026, 8, 31))

        replay = service.correct(
            fact_id=source.id,
            fact_no="EXIT-SEALED-001-R1",
            reason_code="DATE_CORRECTION",
            evidence_ref="doc://archive/correction-001",
            changes={"last_working_date": date(2026, 8, 30)},
        )
        self.assertEqual(replay.id, revised.id)
        events = HrOutboxEvent.objects.filter(
            tenant_id=77, event_type="hr.exit.exit_fact.revised"
        )
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().payload_json["contentHash"], revised.content_hash)
        self.assertEqual(events.get().correlation_id, "corr-hr16-001")

    def test_chain_cannot_branch_and_revocation_is_a_new_evidence_row(self):
        source = self._sealed_fact()
        service = ExitFactCorrectionService(77, actor_user_id=10)
        revised = service.correct(
            fact_id=source.id,
            fact_no="EXIT-SEALED-001-R1",
            reason_code="DATE_CORRECTION",
            evidence_ref="doc://archive/correction-001",
            changes={"employment_end_date": date(2026, 9, 2)},
        )
        with self.assertRaises(ExitFactCorrectionError) as ctx:
            service.correct(
                fact_id=source.id,
                fact_no="EXIT-SEALED-001-R2",
                reason_code="SECOND_BRANCH",
                evidence_ref="doc://archive/correction-002",
                changes={"employment_end_date": date(2026, 9, 3)},
            )
        self.assertEqual(ctx.exception.code, "EXIT_FACT_ALREADY_SUPERSEDED")

        revoked = service.revoke(
            fact_id=revised.id,
            fact_no="EXIT-SEALED-001-X1",
            reason_code="LEGAL_REVOCATION",
            evidence_ref="decision://revocation/001",
        )
        self.assertEqual(revoked.status, ExitFact.Status.REVOKED)
        self.assertEqual(revoked.supersedes_fact_id, revised.id)
        self.assertEqual(ExitFact.objects.filter(tenant_id=77).count(), 3)
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=77, event_type="hr.exit.exit_fact.revoked"
            ).count(),
            1,
        )

    def test_tenant_scope_fails_closed(self):
        source = self._sealed_fact(tenant_id=77)
        with self.assertRaises(ExitFactCorrectionError) as ctx:
            ExitFactCorrectionService(88).revoke(
                fact_id=source.id,
                fact_no="EXIT-X1",
                reason_code="LEGAL_REVOCATION",
                evidence_ref="decision://revocation/001",
            )
        self.assertEqual(ctx.exception.code, "EXIT_FACT_NOT_FOUND")


class ExitFactMySqlSealMigrationTests(SimpleTestCase):
    def test_migration_installs_conditional_update_and_delete_triggers(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0010_exit_fact_integrity.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TRIGGER hr16_exit_fact_no_update", migration)
        self.assertIn("CREATE TRIGGER hr16_exit_fact_no_delete", migration)
        self.assertIn("IF OLD.sealed_at IS NOT NULL", migration)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)
