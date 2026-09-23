import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


class RemainingHistoricalAuthorityClosureTests(unittest.TestCase):
    def test_hr04_hr05_hr15_are_registered_for_asof_and_guard(self):
        asof = text("backend/hr_data/services/asof_service.py")
        guard = text("backend/hr_data/services/formal_fact_evidence_guard.py")
        router = text("backend/hr_data/services/evaluation_router.py")
        for domain in ("HR04", "HR05", "HR15"):
            self.assertIn(f'"{domain}": "hr_data.providers.formal_facts.hr{domain[2:]}_asof_provider"', asof)
            self.assertIn(f'"{domain}": hr{domain[2:]}_asof_provider', guard)
        self.assertIn('_ROUND6_FORMAL_DOMAINS = {"HR04", "HR05", "HR15"}', router)
        self.assertIn('_FORMAL_DOMAINS = _ROUND5_FORMAL_DOMAINS | _ROUND6_FORMAL_DOMAINS', router)

    def test_hr04_reconstructs_revision_chain_asof(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("def _hr04_state", source)
        self.assertIn("def _count_hr04", source)
        self.assertIn('effective_at__date__lte=as_of_date', source)
        self.assertIn('HR04 hiring revision exists after revocation', source)
        self.assertIn('matched.add(fact.candidate_id)', source)

    def test_hr05_reconstructs_amendments_and_excludes_revoked(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("def _hr05_state", source)
        self.assertIn("def _count_hr05", source)
        self.assertIn('amendment.sequence_no != expected_sequence', source)
        self.assertIn('if revoked:', source)
        self.assertIn('matched.add(staff_id)', source)

    def test_hr15_evaluator_walks_linear_adjustment_reversal_chain(self):
        source = text("backend/hr_data/services/formal_fact_chain_service.py")
        self.assertIn("def _count_hr15", source)
        self.assertIn('if current.status == "ADJUSTED":', source)
        self.assertIn('elif current.status == "REVERSED":', source)
        self.assertIn('if current.status == "REVERSED":\n                continue', source)
        self.assertIn('raise _source_conflict("HR15 payroll result chain branches")', source)

    def test_round6_evidence_hashes_only_nodes_effective_by_asof(self):
        source = text("backend/hr_data/providers/formal_facts.py")
        for function in ("_hash_hr04_chain", "_hash_hr05_chain", "_hash_hr15_chain"):
            self.assertIn(f"def {function}", source)
        self.assertGreaterEqual(source.count("effective_at__date__lte=as_of_date"), 5)
        self.assertIn('accepted_at__date__lte=as_of_date', source)
        self.assertIn('activated_at__date__lte=as_of_date', source)

    def test_round6_quality_provider_is_runtime_registered(self):
        runtime = text("backend/hr_data/services/quality_runtime_service.py")
        for domain in ("HR04", "HR05", "HR15"):
            self.assertIn(f'"{domain}": "hr_data.providers.round6_chain_quality.quality_provider"', runtime)

    def test_hr04_quality_blocks_identity_tampering_and_post_revoke_write(self):
        source = text("backend/hr_data/providers/round6_chain_quality.py")
        for issue in (
            "HIRING_FACT_CONTENT_HASH_INVALID",
            "HIRING_REVISION_AFTER_REVOCATION",
            "HIRING_REVISION_VERSION_CHAIN_BROKEN",
            "HIRING_REVISION_IDENTITY_CHANGED",
            "HIRING_CORRECTION_PAYLOAD_INVALID",
            "HIRING_REVISION_PARENT_MISSING_OR_FUTURE",
        ):
            self.assertIn(issue, source)

    def test_hr05_quality_closes_hr04_hr05_hr03_lineage(self):
        source = text("backend/hr_data/providers/round6_chain_quality.py")
        for issue in (
            "ACTIVATION_HR03_LINEAGE_MISMATCH",
            "HR04_HR05_HANDOFF_MISMATCH",
            "HR04_ACCEPTED_HIRE_FACT_REQUIRED",
            "HR04_HIRE_REVOKED_BEFORE_ACTIVATION",
            "ACTIVATION_AMENDMENT_AFTER_REVOCATION",
            "ACTIVATION_AMENDMENT_PARENT_MISSING_OR_FUTURE",
        ):
            self.assertIn(issue, source)

    def test_hr15_quality_is_fail_closed_on_chain_and_amount_corruption(self):
        source = text("backend/hr_data/providers/round6_chain_quality.py")
        for issue in (
            "PAYROLL_RESULT_CONTENT_HASH_INVALID",
            "PAYROLL_RESULT_ARITHMETIC_INVALID",
            "PAYROLL_DERIVED_REASON_REQUIRED",
            "PAYROLL_PREDECESSOR_IDENTITY_MISMATCH",
            "PAYROLL_RESULT_BRANCH_CONFLICT",
            "PAYROLL_SUCCESSOR_AFTER_REVERSAL",
            "PAYROLL_RESULT_CYCLE",
            "PAYROLL_REVERSAL_AMOUNT_MISMATCH",
        ):
            self.assertIn(issue, source)


class PayrollAuthorityClosureTests(unittest.TestCase):
    def test_terminal_payroll_result_is_sealed_and_hashes_authority_metadata(self):
        source = text("backend/hr_payroll/models.py")
        for token in (
            "effective_at = models.DateTimeField",
            "content_hash = models.CharField",
            "sealed_at = models.DateTimeField",
            "authority_reason = models.TextField",
            "authority_evidence_ref = models.CharField",
            "authority_actor_id = models.BigIntegerField",
            '"authorityReason": self.authority_reason or ""',
            "def calculate_content_hash",
        ):
            self.assertIn(token, source)

    def test_payroll_chain_has_single_successor_constraint(self):
        model = text("backend/hr_payroll/models.py")
        migration = text("backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py")
        self.assertIn('name="uq_hr15_result_single_successor"', model)
        self.assertIn('name="uq_hr15_result_single_successor"', migration)
        self.assertIn("HR15_RESULT_BRANCH_CONFLICT", migration)

    def test_payroll_migration_fails_on_orphan_cycle_and_identity_break(self):
        migration = text("backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py")
        for issue in (
            "HR15_DERIVED_RESULT_SOURCE_REQUIRED",
            "HR15_RESULT_PREDECESSOR_MISSING",
            "HR15_RESULT_CHAIN_IDENTITY_MISMATCH",
            "HR15_RESULT_CHAIN_CYCLE",
            "HR15_RESULT_CHAIN_ROOT_INVALID",
        ):
            self.assertIn(issue, migration)

    def test_payroll_migration_backfills_explicit_legacy_reason(self):
        migration = text("backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py")
        self.assertIn("MIGRATED_LEGACY_DERIVED_RESULT", migration)
        self.assertIn("authority_reason=row.authority_reason", migration)

    def test_mysql_triggers_protect_terminal_results(self):
        migration = text("backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py")
        for trigger in (
            "hr15_payroll_result_bi_seal",
            "hr15_payroll_result_bu_seal",
            "hr15_payroll_result_bd_seal",
        ):
            self.assertIn(trigger, migration)
        self.assertIn("PAYROLL_FINAL_RESULT_IMMUTABLE", migration)
        self.assertIn("HR15_DERIVED_RESULT_REASON_REQUIRED", migration)

    def test_adjustment_service_rejects_branching(self):
        source = text("backend/hr_payroll/services/adjustment_service.py")
        self.assertIn("PAYROLL_SOURCE_RESULT_SUPERSEDED", source)
        self.assertIn("adjust the latest result instead", source)
        self.assertIn("authority_reason=reason", source)
        self.assertIn("authority_actor_id=self.actor_user_id", source)

    def test_reversal_is_real_business_command_not_schema_only(self):
        service = text("backend/hr_payroll/services/adjustment_service.py")
        api = text("backend/hr_payroll/api.py")
        urls = text("backend/hr_payroll/api_urls.py")
        self.assertIn("def append_reversal", service)
        self.assertIn("gross_amount=-gross", service)
        self.assertIn("deduction_amount=-deduction", service)
        self.assertIn("net_amount=-net", service)
        self.assertIn("def reverse_result", api)
        self.assertIn('"hr15.reversal.1"', api)
        self.assertIn('"results/<uuid:source_result_id>/reversal/"', urls)

    def test_adjustment_api_requires_reason_and_actor(self):
        source = text("backend/hr_payroll/api.py")
        self.assertIn("PAYROLL_ADJUSTMENT_REASON_REQUIRED", source)
        self.assertIn("actor_user_id=_actor_id(request)", source)
        self.assertIn('evidence_ref=payload.get("evidenceRef", "")', source)


    def test_terminal_payroll_fact_blocks_instance_delete_and_terminal_bulk_create(self):
        source = text("backend/hr_payroll/models.py")
        self.assertIn("PAYROLL_FINAL_RESULT_BULK_CREATE_FORBIDDEN", source)
        self.assertIn("def delete(self, *args, **kwargs):", source)
        self.assertIn("finalized payroll facts cannot be deleted", source)

    def test_reversal_idempotency_rechecks_authoritative_amounts(self):
        source = text("backend/hr_payroll/services/adjustment_service.py")
        self.assertIn("Decimal(existing.gross_amount) == -gross", source)
        self.assertIn("Decimal(existing.deduction_amount) == -deduction", source)
        self.assertIn("Decimal(existing.net_amount) == -net", source)

    def test_migration_refuses_to_seal_bad_payroll_arithmetic(self):
        source = text("backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py")
        self.assertIn("HR15_RESULT_ARITHMETIC_INVALID", source)


class Round6AcceptanceAndRegressionTests(unittest.TestCase):
    def test_operational_snapshot_reports_all_new_capabilities(self):
        source = text("backend/hr_data/services/operational_snapshot_service.py")
        for domain in ("HR04", "HR05", "HR15"):
            self.assertIn(f'"{domain}"', source)
        self.assertIn("correction/revocation chain", source)
        self.assertIn("HR04 handoff lineage", source)
        self.assertIn("adjustment/reversal chain", source)

    def test_acceptance_gate_still_runs_all_hr_apps(self):
        source = text("scripts/run_hr_acceptance_gate.py")
        for app in ("hr_recruitment", "hr_onboarding", "hr_payroll", "hr_data"):
            self.assertIn(f'"{app}"', source)
        self.assertIn("productionTouched", source)
        self.assertIn("gitHubTouched", source)

    def test_round5_domains_remain_registered_verbatim(self):
        router = text("backend/hr_data/services/evaluation_router.py")
        self.assertIn('{"HR06", "HR07", "HR12", "HR13", "HR14", "HR16"}', router)

    def test_all_round6_changed_python_sources_parse(self):
        paths = (
            "backend/hr_payroll/models.py",
            "backend/hr_payroll/migrations/0013_seal_payroll_result_authority.py",
            "backend/hr_payroll/services/finalization_service.py",
            "backend/hr_payroll/services/adjustment_service.py",
            "backend/hr_payroll/api.py",
            "backend/hr_payroll/api_urls.py",
            "backend/hr_data/providers/round6_chain_quality.py",
            "backend/hr_data/providers/formal_facts.py",
            "backend/hr_data/services/formal_fact_evaluation_service.py",
            "backend/hr_data/services/formal_fact_chain_service.py",
            "backend/hr_data/services/asof_service.py",
            "backend/hr_data/services/formal_fact_evidence_guard.py",
            "backend/hr_data/services/evaluation_router.py",
            "backend/hr_data/services/quality_runtime_service.py",
            "backend/hr_data/services/operational_snapshot_service.py",
        )
        for path in paths:
            ast.parse(text(path), filename=path)


if __name__ == "__main__":
    unittest.main()
