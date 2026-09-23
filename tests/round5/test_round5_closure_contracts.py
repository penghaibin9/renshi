import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


class Hr06HistoricalAuthorityTests(unittest.TestCase):
    def test_hr06_is_registered_end_to_end(self):
        asof = text("backend/hr_data/services/asof_service.py")
        guard = text("backend/hr_data/services/formal_fact_evidence_guard.py")
        router = text("backend/hr_data/services/evaluation_router.py")
        runtime = text("backend/hr_data/services/quality_runtime_service.py")
        self.assertIn('"HR06": "hr_data.providers.formal_facts.hr06_asof_provider"', asof)
        self.assertIn('"HR06": hr06_asof_provider', guard)
        self.assertIn('{"HR06", "HR07", "HR12", "HR13", "HR14", "HR16"}', router)
        self.assertIn('"HR06": "hr_data.providers.chain_fact_quality.quality_provider"', runtime)

    def test_hr06_uses_sealed_effective_snapshot_staff_grain(self):
        source = text("backend/hr_data/services/formal_fact_evaluation_service.py")
        self.assertIn('domain="HR06"', source)
        self.assertIn('model_name="HrChangeEffectiveSnapshot"', source)
        self.assertIn('evaluator_version="hr06-change-staff-count-v1"', source)
        self.assertIn('identity_field="change_case_id__staff_master_id"', source)
        self.assertIn('"change.effectiveDate": ("effective_at", "DATE")', source)

    def test_hr06_rescind_only_changes_population_from_receipt_effective_date(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn('kind="ORCHESTRATION_RESCIND"', source)
        self.assertIn('effective_at__date__lte=as_of_date', source)
        self.assertIn('annotate(_hr18_rescinded=Exists(rescinds))', source)
        self.assertIn('filter(_hr18_rescinded=False)', source)

    def test_hr06_historical_count_is_blocked_by_quality_findings(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("def _assert_chain_quality", source)
        self.assertIn('domain="HR06"', source)
        self.assertIn('"HR06_CHANGE_CHAIN_INTEGRITY"', source)

    def test_hr06_evidence_hash_is_asof_chain_not_mutable_case_status(self):
        source = text("backend/hr_data/providers/formal_facts.py")
        section = source[source.index("def _hash_hr06_chain"):source.index("def _hash_hr12_chain")]
        self.assertIn('HrChangeAuthorityReceipt', section)
        self.assertIn('effective_at__date__lte=as_of_date', section)
        self.assertIn('"case_version"', section)
        self.assertIn('"content_hash"', section)
        self.assertNotIn('"status"', section)

    def test_chain_quality_exception_fails_closed(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("authority quality validation failed unexpectedly", source)
        self.assertIn("except Exception as exc", source)

    def test_hr06_quality_gate_recomputes_sealed_hashes(self):
        source = text("backend/hr_data/providers/chain_fact_quality.py")
        self.assertIn("def _hr06_snapshot_hash", source)
        self.assertIn("def _hr06_receipt_hash", source)
        self.assertIn('provider_receipt_hash != expected_provider_receipt_hash', source)
        self.assertIn('row.get("content_hash") != _hr06_snapshot_hash(row)', source)
        self.assertIn('row.get("content_hash") != _hr06_receipt_hash(row)', source)

    def test_hr06_quality_gate_detects_broken_authority_chain(self):
        source = text("backend/hr_data/providers/chain_fact_quality.py")
        self.assertIn('"HR06_CHANGE_CHAIN_INTEGRITY"', source)
        for issue in (
            "CROSS_TENANT_EXECUTION_LINEAGE",
            "CROSS_TENANT_RECEIPT_LINEAGE",
            "RECEIPT_SEQUENCE_GAP",
            "RECEIPT_EXECUTION_SNAPSHOT_REQUIRED",
            "RECEIPT_AFTER_RESCIND",
        ):
            self.assertIn(issue, source)
        self.assertIn('HR06_CANONICAL_HR02_HR03_V1', source)
        self.assertIn('HR03_FORMAL_CORRECTION', source)
        self.assertIn('HR06_ORCHESTRATION_ONLY', source)


class Hr12HistoricalAuthorityTests(unittest.TestCase):
    def test_hr12_is_registered_end_to_end(self):
        asof = text("backend/hr_data/services/asof_service.py")
        guard = text("backend/hr_data/services/formal_fact_evidence_guard.py")
        runtime = text("backend/hr_data/services/quality_runtime_service.py")
        self.assertIn('"HR12": "hr_data.providers.formal_facts.hr12_asof_provider"', asof)
        self.assertIn('"HR12": hr12_asof_provider', guard)
        self.assertIn('"HR12": "hr_data.providers.chain_fact_quality.quality_provider"', runtime)

    def test_hr12_reconstructs_state_only_from_revisions_effective_by_asof(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn('effective_at__date__lte=as_of_date', source)
        self.assertIn('prefetch_related(Prefetch("revisions"', source)
        self.assertIn('if (revision.before_snapshot_json or {}) != state:', source)
        self.assertIn('int(revision.previous_version) != version', source)
        self.assertIn('int(revision.new_version) != version + 1', source)

    def test_hr12_revocation_is_excluded_and_post_revocation_revision_conflicts(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn('if revoked:', source)
        self.assertIn('HR12 revision exists after result revocation', source)
        self.assertIn('if status == "REVOKED":', source)
        self.assertIn('continue', source[source.index('if status == "REVOKED":'):])

    def test_hr12_verifies_result_and_revision_seals(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn('result.content_hash != calculate_result_hash()', source)
        self.assertIn('result.calculation_hash != calculate_calculation_hash()', source)
        self.assertIn('revision.content_hash != calculate_revision_hash()', source)
        self.assertIn('ASOF_EVALUATION_SOURCE_CONFLICT', source)

    def test_hr12_evidence_hash_freezes_result_revision_and_case_identity(self):
        source = text("backend/hr_data/providers/formal_facts.py")
        section = source[source.index("def _hash_hr12_chain"):source.index("def _provider")]
        self.assertIn('HrResultRevision', section)
        self.assertIn('effective_at__date__lte=as_of_date', section)
        self.assertIn('"staff_id"', section)
        self.assertIn('"assessment_type"', section)
        self.assertIn('"cycle_id"', section)

    def test_hr12_historical_count_is_blocked_by_quality_findings(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("def _assert_chain_quality", source)
        self.assertIn('domain="HR12"', source)
        self.assertIn("authority chain failed integrity validation", source)
        self.assertIn("ASOF_EVALUATION_SOURCE_UNAVAILABLE", source)

    def test_hr12_quality_gate_detects_revision_chain_corruption(self):
        source = text("backend/hr_data/providers/chain_fact_quality.py")
        self.assertIn('"HR12_RESULT_REVISION_CHAIN_INTEGRITY"', source)
        for issue in (
            "ASSESSMENT_CASE_MISSING_OR_CROSS_TENANT",
            "REVISION_AFTER_REVOCATION",
            "REVISION_VERSION_CHAIN_BROKEN",
            "REVISION_BEFORE_SNAPSHOT_MISMATCH",
            "REVISION_CONTENT_HASH_INVALID",
        ):
            self.assertIn(issue, source)


class Round5SafetyAndRegressionTests(unittest.TestCase):
    def test_acceptance_runtime_evidence_path_is_release_neutral(self):
        source = text("scripts/run_hr_acceptance_gate.py")
        self.assertIn('"acceptance_evidence" / "acceptance-latest.json"', source)
        self.assertNotIn('"round4_evidence" / "acceptance-latest.json"', source)

    def test_hr06_hr12_evidence_provider_fails_closed_on_quality_findings(self):
        source = text("backend/hr_data/providers/formal_facts.py")
        self.assertIn('if spec.domain in {"HR06", "HR12"}:', source)
        self.assertIn('"HR06_CHANGE_CHAIN_INTEGRITY"', source)
        self.assertIn('"HR12_RESULT_REVISION_CHAIN_INTEGRITY"', source)
        self.assertIn('(quality or {}).get("findings")', source)
        self.assertIn('"status": SourceStatus.ERROR.value', source)

    def test_only_authority_domains_are_newly_enabled(self):
        router = text("backend/hr_data/services/evaluation_router.py")
        self.assertIn('{"HR06", "HR07", "HR12", "HR13", "HR14", "HR16"}', router)
        for domain in ("HR04", "HR05", "HR15"):
            self.assertNotIn(f'"{domain}", "HR13"', router)
        self.assertIn("ASOF_EVALUATION_SOURCE_UNSUPPORTED", router)

    def test_operational_capabilities_describe_hr06_and_hr12(self):
        source = text("backend/hr_data/services/operational_snapshot_service.py")
        self.assertIn('"HR06"', source)
        self.assertIn('"HR12"', source)
        self.assertIn('historicalValueCapabilities', source)
        self.assertIn('personnel', source.lower())
        self.assertIn('assessment', source.lower())

    def test_changed_python_sources_parse(self):
        for relative in (
            "backend/hr_data/services/formal_fact_evaluation_service.py",
            "backend/hr_data/services/formal_fact_chain_service.py",
            "backend/hr_data/providers/formal_facts.py",
            "backend/hr_data/providers/chain_fact_quality.py",
            "backend/hr_data/services/asof_service.py",
            "backend/hr_data/services/formal_fact_evidence_guard.py",
            "backend/hr_data/services/evaluation_router.py",
            "backend/hr_data/services/operational_snapshot_service.py",
            "backend/hr_data/services/quality_runtime_service.py",
        ):
            ast.parse(text(relative), filename=relative)


if __name__ == "__main__":
    unittest.main()
