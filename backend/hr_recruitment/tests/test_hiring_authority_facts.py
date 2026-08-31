from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from hr_recruitment.authority_registry import (
    CANONICAL_PERMISSION_KEYS,
    EVENT_DEFINITIONS,
    EVENT_HIRING_DECISION_CORRECTED,
    EVENT_HIRING_DECISION_RECORDED,
    EVENT_HIRING_DECISION_REVOKED,
)
from hr_recruitment.models import (
    HrHiringDecisionFact,
    HrHiringDecisionRevision,
    HrJobApplication,
    HrProposedHire,
    HrRecruitmentCampaign,
    HrRecruitmentCandidate,
    HrRecruitmentOffer,
    HrRecruitmentPosition,
)
from hr_recruitment.services.hiring_authority_service import (
    HiringAuthorityError,
    HiringAuthorityService,
    HiringRevisionInput,
    effective_hiring_decision_snapshot,
)
from hr_recruitment.services.offer_service import OfferService
from hr_staff.models import HrOutboxEvent


TENANT = 7040


class HiringAuthorityContractTests(SimpleTestCase):
    def test_permissions_and_events_are_registered(self):
        self.assertIn("hr.recruitment.hiring_decision.correct", CANONICAL_PERMISSION_KEYS)
        self.assertIn("hr.recruitment.hiring_decision.revoke", CANONICAL_PERMISSION_KEYS)
        names = {definition.name for definition in EVENT_DEFINITIONS}
        self.assertTrue(
            {
                EVENT_HIRING_DECISION_RECORDED,
                EVENT_HIRING_DECISION_CORRECTED,
                EVENT_HIRING_DECISION_REVOKED,
            }.issubset(names)
        )

    def test_instance_and_queryset_guards_fail_before_database_access(self):
        fact = HrHiringDecisionFact()
        revision = HrHiringDecisionRevision()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            fact.delete()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            revision.delete()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrHiringDecisionFact.objects.none().update(rank=2)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrHiringDecisionRevision.objects.none().delete()
        with self.assertRaisesRegex(ValueError, "BULK_CREATE_FORBIDDEN"):
            HrHiringDecisionFact.objects.bulk_create([HrHiringDecisionFact()])
        with self.assertRaisesRegex(ValueError, "BULK_CREATE_FORBIDDEN"):
            HrHiringDecisionRevision.objects.bulk_create([HrHiringDecisionRevision()])

    def test_mysql_trigger_contract_covers_seal_lineage_and_terminal_state(self):
        migration = Path(
            __file__,
        ).resolve().parents[1].joinpath(
            "migrations",
            "0012_alter_hrrecruitmentpermissionmeta_options_and_more.py",
        ).read_text(encoding="utf-8")
        for marker in (
            "hr04_hiring_decision_fact_seal_insert",
            "hr04_hiring_decision_revision_seal_insert",
            "HR04_HIRING_PARENT_LINEAGE_INVALID",
            "HR04_HIRING_REVISION_VERSION_CONFLICT",
            "HR04_HIRING_FACT_ALREADY_REVOKED",
            "BEFORE UPDATE ON",
            "BEFORE DELETE ON",
        ):
            self.assertIn(marker, migration)


class HiringAuthorityDatabaseTests(TestCase):
    def setUp(self):
        self.campaign = HrRecruitmentCampaign.objects.create(
            tenant_id=TENANT,
            code="AUTH-2026",
            title="Authority test",
        )
        self.position = HrRecruitmentPosition.objects.create(
            tenant_id=TENANT,
            campaign_id=self.campaign,
            post_catalog_name="Professor",
            max_hires=1,
        )
        self.candidate = HrRecruitmentCandidate.objects.create(
            tenant_id=TENANT,
            candidate_uid="CAND-AUTH-001",
            legal_name="Authority Candidate",
        )
        self.application = HrJobApplication.objects.create(
            tenant_id=TENANT,
            candidate_id=self.candidate,
            recruitment_position_id=self.position,
            application_no="APP-AUTH-001",
            canonical_status="OFFER_ACCEPTED",
        )
        now = timezone.now()
        self.proposed = HrProposedHire.objects.create(
            tenant_id=TENANT,
            application_id=self.application,
            recruitment_position_id=self.position,
            rank=1,
            final_score="91.50",
            decision="APPROVE",
            approval_status="APPROVE",
            approved_by="committee-1",
            approved_at=now,
        )
        self.offer = HrRecruitmentOffer.objects.create(
            tenant_id=TENANT,
            proposed_hire_id=self.proposed,
            offer_no="OFFER-AUTH-001",
            status="ACCEPTED",
            accepted_at=now,
            employment_type="FULL_TIME",
            created_by="hr-1",
        )
        self.service = HiringAuthorityService(
            tenant_id=TENANT,
            actor_id="hr-1",
            correlation_id="corr-hire-1",
        )

    def test_acceptance_seals_exact_parent_chain_and_is_idempotent(self):
        fact = self.service.seal_accepted_offer(offer_id=self.offer.id)
        replay = self.service.seal_accepted_offer(offer_id=self.offer.id)
        self.assertEqual(replay.id, fact.id)
        self.assertEqual(fact.application_id, self.application.id)
        self.assertEqual(fact.candidate_id, self.candidate.id)
        self.assertEqual(fact.recruitment_position_id, self.position.id)
        self.assertEqual(len(fact.content_hash), 64)
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                event_type=EVENT_HIRING_DECISION_RECORDED,
                payload_json__factId=str(fact.id),
            ).count(),
            1,
        )

    def test_offer_acceptance_creates_fact_in_same_service_flow(self):
        self.offer.status = "ISSUED"
        self.offer.accepted_at = None
        self.offer.save(update_fields=["status", "accepted_at"])
        self.application.canonical_status = "OFFERED"
        self.application.save(update_fields=["canonical_status"])
        accepted = OfferService(tenant_id=TENANT, actor="hr-1").accept(
            offer_id=self.offer.id
        )
        self.assertEqual(accepted.status, "ACCEPTED")
        fact = HrHiringDecisionFact.objects.get(offer=accepted)
        self.assertEqual(fact.candidate_id, self.candidate.id)
        self.assertEqual(HrHiringDecisionFact.objects.filter(offer=accepted).count(), 1)

    def test_fact_cannot_be_rewritten_or_deleted_through_orm_paths(self):
        fact = self.service.seal_accepted_offer(offer_id=self.offer.id)
        fact.rank = 2
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            fact.save()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrHiringDecisionFact.objects.filter(id=fact.id).update(rank=2)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            fact.delete()

    def test_correction_is_append_only_idempotent_and_effective(self):
        fact = self.service.seal_accepted_offer(offer_id=self.offer.id)
        payload = HiringRevisionInput(
            correction_no="HIRE-COR-001",
            expected_version=1,
            revision_type="CORRECTION",
            reason="approved evidence corrected the score",
            changes={"finalScore": "92.00", "expectedReportDate": "2026-09-01"},
            evidence_ref="DOC-2026-1",
        )
        revision = self.service.append_revision(fact_id=fact.id, payload=payload)
        replay = self.service.append_revision(fact_id=fact.id, payload=payload)
        self.assertEqual(replay.id, revision.id)
        self.assertEqual(revision.previous_version, 1)
        self.assertEqual(revision.new_version, 2)
        self.assertEqual(len(revision.content_hash), 64)
        effective = effective_hiring_decision_snapshot(fact)
        self.assertEqual(effective["status"], "CORRECTED")
        self.assertEqual(effective["finalScore"], "92.00")
        self.assertEqual(effective["version"], 2)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrHiringDecisionRevision.objects.filter(id=revision.id).update(reason="tamper")
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                event_type=EVENT_HIRING_DECISION_CORRECTED
            ).count(),
            1,
        )

    def test_revocation_is_terminal(self):
        fact = self.service.seal_accepted_offer(offer_id=self.offer.id)
        revoked = self.service.append_revision(
            fact_id=fact.id,
            payload=HiringRevisionInput(
                correction_no="HIRE-REV-001",
                expected_version=1,
                revision_type="REVOCATION",
                reason="formal committee revocation",
                changes={},
                evidence_ref="RESOLUTION-9",
            ),
        )
        self.assertEqual(revoked.after_snapshot_json["status"], "REVOKED")
        with self.assertRaisesRegex(HiringAuthorityError, "cannot receive more revisions"):
            self.service.append_revision(
                fact_id=fact.id,
                payload=HiringRevisionInput(
                    correction_no="HIRE-COR-AFTER-REV",
                    expected_version=2,
                    revision_type="CORRECTION",
                    reason="not allowed",
                    changes={"rank": 2},
                ),
            )
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                event_type=EVENT_HIRING_DECISION_REVOKED
            ).count(),
            1,
        )

    def test_cross_tenant_parent_chain_is_rejected(self):
        self.candidate.tenant_id = TENANT + 1
        self.candidate.save(update_fields=["tenant_id"])
        with self.assertRaisesRegex(HiringAuthorityError, "share a tenant"):
            self.service.seal_accepted_offer(offer_id=self.offer.id)
