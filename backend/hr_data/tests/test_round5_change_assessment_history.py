from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from hr_data.providers.chain_fact_quality import _hr06_receipt_hash, _hr06_snapshot_hash
from hr_data.providers.formal_facts import HR06_SPEC, _provider
from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_data.services.formal_fact_chain_service import (
    FormalFactAsOfEvaluationService,
    _assert_chain_quality,
)


class Round5EvidenceProviderQualityTests(SimpleTestCase):
    @patch("hr_data.providers.formal_facts._hash_hr06_chain", return_value="f" * 64)
    @patch("hr_data.providers.formal_facts._fact_keys", return_value=({"change"}, set()))
    @patch("hr_data.providers.formal_facts._source_domains", return_value={"HR06"})
    @patch("hr_data.providers.formal_facts._required_fields", return_value=({"change.staffId"}, "HR06"))
    @patch("hr_data.providers.formal_facts._definition", return_value=SimpleNamespace())
    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_frozen_evidence_refuses_corrupt_hr06_chain(
        self, quality, _definition, _fields, _domains, _keys, hash_chain
    ):
        quality.return_value = {
            "status": "OK",
            "findings": [{"details": {"issue": "EXECUTION_CONTENT_HASH_INVALID"}}],
        }
        receipt = _provider(
            spec=HR06_SPEC,
            tenant_id=77,
            source_domain="HR06",
            definition_kind="POPULATION",
            definition_code="CHANGES",
            definition_version=1,
            as_of_date=datetime(2026, 8, 1).date(),
        )
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(receipt["evidenceHash"], "")
        hash_chain.assert_not_called()

    @patch("hr_data.providers.formal_facts._hash_hr06_chain", return_value="f" * 64)
    @patch("hr_data.providers.formal_facts._fact_keys", return_value=({"change"}, set()))
    @patch("hr_data.providers.formal_facts._source_domains", return_value={"HR06"})
    @patch("hr_data.providers.formal_facts._required_fields", return_value=({"change.staffId"}, "HR06"))
    @patch("hr_data.providers.formal_facts._definition", return_value=SimpleNamespace())
    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_frozen_evidence_hashes_clean_hr06_chain(
        self, quality, _definition, _fields, _domains, _keys, hash_chain
    ):
        quality.return_value = {"status": "OK", "findings": []}
        receipt = _provider(
            spec=HR06_SPEC,
            tenant_id=77,
            source_domain="HR06",
            definition_kind="POPULATION",
            definition_code="CHANGES",
            definition_version=1,
            as_of_date=datetime(2026, 8, 1).date(),
        )
        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(receipt["evidenceHash"], "f" * 64)
        hash_chain.assert_called_once()


class Round5AuthorityQualityBridgeTests(SimpleTestCase):
    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_chain_quality_accepts_clean_authority(self, provider):
        provider.return_value = {"status": "OK", "findings": []}

        _assert_chain_quality(tenant_id=77, domain="HR06", as_of_date=datetime(2026, 8, 1).date())

        provider.assert_called_once()
        self.assertEqual(provider.call_args.kwargs["rule_code"], "HR06_CHANGE_CHAIN_INTEGRITY")

    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_chain_quality_rejects_findings(self, provider):
        provider.return_value = {
            "status": "OK",
            "findings": [{"details": {"issue": "RECEIPT_SEQUENCE_GAP"}}],
        }

        with self.assertRaises(AsOfEvaluationError) as caught:
            _assert_chain_quality(
                tenant_id=77,
                domain="HR06",
                as_of_date=datetime(2026, 8, 1).date(),
            )
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("RECEIPT_SEQUENCE_GAP", str(caught.exception))

    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_chain_quality_wraps_provider_exception_as_source_conflict(self, provider):
        provider.side_effect = RuntimeError("broken provider")
        with self.assertRaises(AsOfEvaluationError) as caught:
            _assert_chain_quality(
                tenant_id=77,
                domain="HR12",
                as_of_date=datetime(2026, 8, 1).date(),
            )
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("quality validation failed unexpectedly", str(caught.exception))

    @patch("hr_data.providers.chain_fact_quality.quality_provider")
    def test_chain_quality_preserves_unavailable_source(self, provider):
        provider.return_value = {"status": "UNAVAILABLE"}

        with self.assertRaises(AsOfEvaluationError) as caught:
            _assert_chain_quality(
                tenant_id=77,
                domain="HR12",
                as_of_date=datetime(2026, 8, 1).date(),
            )
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_UNAVAILABLE")


class Round5Hr12CanonicalRevisionTests(SimpleTestCase):
    def setUp(self):
        self.service = FormalFactAsOfEvaluationService(77)
        self.finalized_at = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
        self.result = SimpleNamespace(
            id=uuid4(),
            tenant_id=77,
            finalized_at=self.finalized_at,
            sealed_at=self.finalized_at,
            content_hash="a" * 64,
            calculation_hash="b" * 64,
            result_version_no=1,
            status="FINALIZED",
            grade_code="B",
            display_grade_snapshot_json={"name": "良好"},
            calculated_score=85,
            decision_reason="initial",
        )
        self.result.calculate_content_hash = lambda: self.result.content_hash
        self.result.calculate_calculation_hash = lambda: self.result.calculation_hash

    def _revision(self, *, previous, new, kind, before, after, at):
        revision = SimpleNamespace(
            id=uuid4(),
            tenant_id=77,
            result_id=self.result.id,
            previous_version=previous,
            new_version=new,
            revision_type=kind,
            before_snapshot_json=before,
            after_snapshot_json=after,
            effective_at=at,
            sealed_at=at,
            content_hash="c" * 64,
        )
        revision.calculate_content_hash = lambda: revision.content_hash
        return revision

    def test_correction_reconstructs_new_grade_without_mutating_base_result(self):
        before = self.service._hr12_base_snapshot(self.result)
        after = {**before, "version": 2, "status": "CORRECTED", "gradeCode": "A"}
        revision = self._revision(
            previous=1,
            new=2,
            kind="CORRECTION",
            before=before,
            after=after,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )

        state = self.service._hr12_state(self.result, [revision])

        self.assertEqual(state["gradeCode"], "A")
        self.assertEqual(state["status"], "CORRECTED")
        self.assertEqual(self.result.grade_code, "B")
        self.assertEqual(self.result.status, "FINALIZED")

    def test_revocation_is_terminal_for_revision_chain(self):
        before = self.service._hr12_base_snapshot(self.result)
        revoked = {**before, "version": 2, "status": "REVOKED"}
        first = self._revision(
            previous=1,
            new=2,
            kind="REVOCATION",
            before=before,
            after=revoked,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )
        illegal_after = {**revoked, "version": 3, "status": "CORRECTED", "gradeCode": "A"}
        second = self._revision(
            previous=2,
            new=3,
            kind="CORRECTION",
            before=revoked,
            after=illegal_after,
            at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(AsOfEvaluationError) as caught:
            self.service._hr12_state(self.result, [first, second])
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("after result revocation", str(caught.exception))

    def test_revision_before_snapshot_must_match_predecessor(self):
        actual = self.service._hr12_base_snapshot(self.result)
        wrong = {**actual, "gradeCode": "A"}
        after = {**actual, "version": 2, "status": "CORRECTED", "gradeCode": "A"}
        revision = self._revision(
            previous=1,
            new=2,
            kind="CORRECTION",
            before=wrong,
            after=after,
            at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(AsOfEvaluationError) as caught:
            self.service._hr12_state(self.result, [revision])
        self.assertEqual(caught.exception.code, "ASOF_EVALUATION_SOURCE_CONFLICT")
        self.assertIn("before-snapshot", str(caught.exception))


class Round5Hr06SealHashTests(SimpleTestCase):
    def _snapshot_row(self):
        return {
            "tenant_id": 77,
            "change_case_id": uuid4(),
            "change_case_id__staff_master_id": uuid4(),
            "applied_at": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            "effective_at": datetime(2026, 1, 1).date(),
            "before_json": {"org": 1},
            "after_json": {"org": 2},
            "source_fact_ids_json": ["source"],
            "target_fact_ids_json": ["target"],
            "position_changes_json": {},
            "downstream_plan_version": 1,
            "checksum": "",
            "authority_domain": "HR03",
            "authority_contract_version": 1,
            "case_version": 5,
            "approval_snapshot_id": uuid4(),
            "approval_snapshot_hash": "d" * 64,
            "provider_code": "HR06_CANONICAL_HR02_HR03_V1",
            "provider_receipt_json": {"ok": True},
            "provider_receipt_hash": "e" * 64,
            "execution_idempotency_key": "exec-1",
        }

    def test_snapshot_hash_changes_when_sealed_payload_changes(self):
        original = self._snapshot_row()
        mutated = {**original, "after_json": {"org": 999}}
        self.assertNotEqual(_hr06_snapshot_hash(original), _hr06_snapshot_hash(mutated))

    def test_receipt_hash_changes_when_authority_effect_changes(self):
        base = {
            "tenant_id": 77,
            "change_case_id": uuid4(),
            "effective_snapshot_id": uuid4(),
            "sequence_no": 1,
            "kind": "CORRECTION",
            "authority_effect": True,
            "provider_code": "HR03_FORMAL_CORRECTION",
            "provider_case_id": uuid4(),
            "provider_case_version": 2,
            "provider_snapshot_hash": "f" * 64,
            "source_record_id": uuid4(),
            "idempotency_key": "corr-1",
            "payload_json": {"changed": ["name"]},
            "effective_at": datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        }
        mutated = {**base, "authority_effect": False}
        self.assertNotEqual(_hr06_receipt_hash(base), _hr06_receipt_hash(mutated))
