from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from hr_data.providers.formal_facts import HR04_SPEC, _provider
from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_data.services.formal_fact_chain_service import (
    FormalFactAsOfEvaluationService,
    _assert_chain_quality,
)


class Round6FrozenEvidenceQualityTests(SimpleTestCase):
    @patch("hr_data.providers.formal_facts._hash_hr04_chain", return_value="f" * 64)
    @patch("hr_data.providers.formal_facts._fact_keys", return_value=({"hiring"}, set()))
    @patch("hr_data.providers.formal_facts._source_domains", return_value={"HR04"})
    @patch("hr_data.providers.formal_facts._required_fields", return_value=({"hiring.candidateId"}, "HR04"))
    @patch("hr_data.providers.formal_facts._definition", return_value=SimpleNamespace())
    @patch("hr_data.providers.round6_chain_quality.quality_provider")
    def test_frozen_evidence_refuses_corrupt_hr04_chain(
        self, quality, _definition, _fields, _domains, _keys, hash_chain
    ):
        quality.return_value = {
            "status": "OK",
            "findings": [{"details": {"issue": "HIRING_REVISION_PARENT_MISSING_OR_FUTURE"}}],
        }
        receipt = _provider(
            spec=HR04_SPEC,
            tenant_id=77,
            source_domain="HR04",
            definition_kind="POPULATION",
            definition_code="HIRED",
            definition_version=1,
            as_of_date=datetime(2026, 8, 1).date(),
        )
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(receipt["evidenceHash"], "")
        hash_chain.assert_not_called()


class Round6AuthorityQualityBridgeTests(SimpleTestCase):
    @patch("hr_data.providers.round6_chain_quality.quality_provider")
    def test_round6_quality_rejects_payroll_reversal_mismatch(self, provider):
        provider.return_value = {
            "status": "OK",
            "findings": [{"details": {"issue": "PAYROLL_REVERSAL_AMOUNT_MISMATCH"}}],
        }
        with self.assertRaises(AsOfEvaluationError) as caught:
            _assert_chain_quality(
                tenant_id=77,
                domain="HR15",
                as_of_date=datetime(2026, 8, 1).date(),
            )
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("PAYROLL_REVERSAL_AMOUNT_MISMATCH", str(caught.exception))


class Round6Hr04CanonicalHistoryTests(SimpleTestCase):
    def setUp(self):
        self.service = FormalFactAsOfEvaluationService(77)
        self.accepted_at = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
        self.base = {
            "tenantId": 77,
            "offerId": str(uuid4()),
            "proposedHireId": str(uuid4()),
            "applicationId": str(uuid4()),
            "candidateId": str(uuid4()),
            "recruitmentPositionId": str(uuid4()),
            "offerNo": "OFFER-1",
            "rank": 1,
            "finalScore": "90.00",
            "employmentType": "FULL_TIME",
            "expectedReportDate": "2026-02-01",
            "acceptedAt": self.accepted_at.isoformat(),
            "approvedAt": None,
            "approvedBy": "",
            "status": "EFFECTIVE",
            "version": 1,
        }
        self.fact = SimpleNamespace(
            id=uuid4(), tenant_id=77, accepted_at=self.accepted_at,
            sealed_at=self.accepted_at, content_hash="a" * 64,
        )
        self.fact.canonical_payload = lambda: dict(self.base)
        self.fact.calculate_content_hash = lambda: self.fact.content_hash

    def _revision(self, *, previous, new, kind, before, after, at):
        revision = SimpleNamespace(
            id=uuid4(), tenant_id=77, fact_id=self.fact.id,
            previous_version=previous, new_version=new, revision_type=kind,
            before_snapshot_json=before, after_snapshot_json=after,
            effective_at=at, sealed_at=at, content_hash="b" * 64,
        )
        revision.calculate_content_hash = lambda: revision.content_hash
        return revision

    def test_correction_reconstructs_without_mutating_base_fact(self):
        after = {**self.base, "rank": 2, "status": "CORRECTED", "version": 2}
        revision = self._revision(
            previous=1, new=2, kind="CORRECTION", before=self.base, after=after,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )
        state = self.service._hr04_state(self.fact, [revision])
        self.assertEqual(state["rank"], 2)
        self.assertEqual(state["status"], "CORRECTED")
        self.assertEqual(self.base["rank"], 1)

    def test_revocation_is_terminal(self):
        revoked = {**self.base, "status": "REVOKED", "version": 2}
        first = self._revision(
            previous=1, new=2, kind="REVOCATION", before=self.base, after=revoked,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )
        illegal = {**revoked, "rank": 2, "status": "CORRECTED", "version": 3}
        second = self._revision(
            previous=2, new=3, kind="CORRECTION", before=revoked, after=illegal,
            at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        )
        with self.assertRaises(AsOfEvaluationError) as caught:
            self.service._hr04_state(self.fact, [first, second])
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("after revocation", str(caught.exception))


class Round6Hr05CanonicalHistoryTests(SimpleTestCase):
    def setUp(self):
        self.service = FormalFactAsOfEvaluationService(77)
        self.activated_at = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
        self.base = {
            "tenantId": 77,
            "caseId": str(uuid4()),
            "activatedAt": self.activated_at.isoformat(),
            "personId": str(uuid4()),
            "staffMasterId": str(uuid4()),
            "employmentId": str(uuid4()),
            "assignmentId": str(uuid4()),
            "staffNo": "T001",
            "organizationId": 11,
            "positionId": 22,
            "sourceType": "HR04_HIRE",
            "sourceId": "src-1",
            "hr04ProposedHireId": str(uuid4()),
            "hr04ApplicationId": str(uuid4()),
            "sourceVersions": {},
        }
        self.snapshot = SimpleNamespace(
            id=uuid4(), tenant_id=77, activated_at=self.activated_at,
            sealed_at=self.activated_at, content_hash="c" * 64,
        )
        self.snapshot.canonical_payload = lambda: dict(self.base)
        self.snapshot.calculate_content_hash = lambda: self.snapshot.content_hash

    def _amendment(self, *, predecessor_id, sequence, action, before, after, at):
        amendment = SimpleNamespace(
            id=uuid4(), tenant_id=77, snapshot_id=self.snapshot.id,
            predecessor_id=predecessor_id, sequence_no=sequence, action=action,
            before_snapshot_json=before, after_snapshot_json=after,
            effective_at=at, sealed_at=at, content_hash="d" * 64,
        )
        amendment.calculate_content_hash = lambda: amendment.content_hash
        return amendment

    def test_correction_then_revocation_reconstructs_terminal_state(self):
        corrected = {**self.base, "organizationId": 12}
        first = self._amendment(
            predecessor_id=None, sequence=1, action="CORRECTION",
            before=self.base, after=corrected,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )
        revoked = {**corrected, "revoked": True, "revocationReason": "invalid activation"}
        second = self._amendment(
            predecessor_id=first.id, sequence=2, action="REVOCATION",
            before=corrected, after=revoked,
            at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        )
        state, is_revoked = self.service._hr05_state(self.snapshot, [first, second])
        self.assertEqual(state["organizationId"], 12)
        self.assertTrue(is_revoked)

    def test_sequence_gap_fails_closed(self):
        changed = {**self.base, "organizationId": 12}
        amendment = self._amendment(
            predecessor_id=None, sequence=2, action="CORRECTION",
            before=self.base, after=changed,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )
        with self.assertRaises(AsOfEvaluationError) as caught:
            self.service._hr05_state(self.snapshot, [amendment])
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("predecessor/sequence", str(caught.exception))
