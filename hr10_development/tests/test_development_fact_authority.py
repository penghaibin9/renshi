import json
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from hr10_development.api.development_records import correct_fact
from hr10_development.models.development_fact import HrDevelopmentFact
from hr10_development.models.outbox import HrDevelopmentOutboxEvent
from hr10_development.services.development_fact_authority_service import (
    DevelopmentFactAuthorityError,
    DevelopmentFactAuthorityService,
)


class DevelopmentFactAuthorityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="hr10-fact-authority", password="x", is_superuser=True
        )
        self.fact = HrDevelopmentFact.objects.create(
            tenant_id=101,
            staff_master_id=9001,
            fact_type="TRAINING_COMPLETION",
            source_case_type="HrLearningCompletion",
            source_case_id=77,
            source_revision_no=0,
            verified_hours="16.0",
            verified_credits="2.0",
            level_or_result="PASS",
            verification_status="HR_VERIFIED",
            evidence_package_hash="sha256:evidence-original",
            generated_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            sealed_by=self.user.id,
        )

    def service(self, tenant_id=101):
        return DevelopmentFactAuthorityService(
            tenant_id=tenant_id, actor_user_id=self.user.id,
            correlation_id="req-hr10-fact",
        )

    def test_new_fact_is_sealed_and_all_orm_mutation_paths_fail(self):
        self.assertEqual(len(self.fact.content_hash), 64)
        self.assertEqual(self.fact.immutable_hash, self.fact.content_hash)
        self.assertTrue(self.fact.verify_content_hash())

        self.fact.verified_hours = "99.0"
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            self.fact.save()
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            HrDevelopmentFact.objects.filter(pk=self.fact.pk).update(
                verified_hours="99.0"
            )
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            HrDevelopmentFact.objects.filter(pk=self.fact.pk).delete()
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            HrDevelopmentFact.objects.bulk_update([self.fact], ["verified_hours"])
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            HrDevelopmentFact.objects.bulk_create([])
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            self.fact.delete()

    def test_correction_is_sealed_successor_and_idempotent(self):
        corrected = self.service().correct(
            fact_id=self.fact.id,
            reason_code="CREDIT_RECOUNT",
            evidence_ref="doc://hr10/correction/001",
            idempotency_key="hr10-correct-001",
            changes={"verified_credits": "3.0", "level_or_result": "PASS-RECOUNTED"},
        )
        self.assertEqual(corrected.supersedes_fact_id, self.fact.id)
        self.assertEqual(corrected.source_revision_no, 1)
        self.assertEqual(corrected.record_kind, "CORRECTION")
        self.assertTrue(corrected.verify_content_hash())
        self.assertEqual(
            list(HrDevelopmentFact.objects.effective().values_list("id", flat=True)),
            [corrected.id],
        )
        replay = self.service().correct(
            fact_id=self.fact.id,
            reason_code="CREDIT_RECOUNT",
            evidence_ref="doc://hr10/correction/001",
            idempotency_key="hr10-correct-001",
            changes={"verified_credits": "3.0"},
        )
        self.assertEqual(replay.id, corrected.id)
        self.assertEqual(
            HrDevelopmentOutboxEvent.objects.filter(
                event_type="hr.development.development_fact.corrected"
            ).count(),
            1,
        )

        with self.assertRaisesRegex(
            DevelopmentFactAuthorityError, "idempotency key belongs"
        ):
            self.service().correct(
                fact_id=self.fact.id,
                reason_code="CREDIT_RECOUNT",
                evidence_ref="doc://hr10/correction/001",
                idempotency_key="hr10-correct-001",
                changes={"verified_credits": "4.0"},
            )

    def test_revocation_removes_chain_from_effective_projection(self):
        revoked = self.service().revoke(
            fact_id=self.fact.id,
            reason_code="EVIDENCE_WITHDRAWN",
            evidence_ref="case://hr10/revocation/001",
            idempotency_key="hr10-revoke-001",
        )
        self.assertEqual(revoked.record_kind, "REVOCATION")
        self.assertTrue(revoked.verify_content_hash())
        self.assertFalse(HrDevelopmentFact.objects.effective().exists())

    def test_cross_tenant_parent_is_not_disclosed_or_written(self):
        with self.assertRaisesRegex(
            DevelopmentFactAuthorityError, "fact not found inside tenant"
        ):
            self.service(tenant_id=202).correct(
                fact_id=self.fact.id,
                reason_code="CREDIT_RECOUNT",
                evidence_ref="doc://cross-tenant",
                idempotency_key="cross-tenant-attempt",
                changes={"verified_credits": "5.0"},
            )
        self.assertEqual(HrDevelopmentFact.objects.count(), 1)

    def test_correction_api_uses_tenant_and_emits_sealed_payload(self):
        request = RequestFactory().post(
            f"/api/v1/hr/development/development-facts/{self.fact.id}/correct",
            data=json.dumps(
                {
                    "reasonCode": "HOURS_RECOUNT",
                    "evidenceRef": "doc://hr10/correction/api",
                    "changes": {"verifiedHours": "20.0"},
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="hr10-api-correct-001",
        )
        # The public contract is snake_case inside changes to prevent ambiguous aliases.
        request._body = json.dumps(
            {
                "reasonCode": "HOURS_RECOUNT",
                "evidenceRef": "doc://hr10/correction/api",
                "changes": {"verified_hours": "20.0"},
            }
        ).encode()
        request.user = self.user
        request.tenant_id = 101
        request._dont_enforce_csrf_checks = True
        response = correct_fact(request, self.fact.id)
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)["data"]
        self.assertEqual(payload["recordKind"], "CORRECTION")
        self.assertEqual(len(payload["contentHash"]), 64)


class DevelopmentFactDatabaseSealContractTests(SimpleTestCase):
    def test_mysql_migration_installs_update_delete_and_tenant_parent_triggers(self):
        from pathlib import Path
        migration = (
            Path(__file__).parents[1]
            / "migrations"
            / "0023_formal_development_fact_seal.py"
        ).read_text(encoding="utf-8")
        self.assertIn("BEFORE UPDATE ON hr_development_fact", migration)
        self.assertIn("BEFORE DELETE ON hr_development_fact", migration)
        self.assertIn("BEFORE INSERT ON hr_development_fact", migration)
        self.assertIn("parent.tenant_id = NEW.tenant_id", migration)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)
