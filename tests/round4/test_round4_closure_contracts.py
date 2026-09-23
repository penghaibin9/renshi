import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


class RetirementEvidenceClosureTests(unittest.TestCase):
    def test_retirement_evidence_categories_are_distinct(self):
        source = text("backend/hr_staff/constants.py")
        for category in (
            "RETIREMENT_NOTICE",
            "RETIREMENT_APPROVAL",
            "RETIREMENT_CONTRIBUTION",
            "RETIREMENT_AGREEMENT",
        ):
            self.assertIn(category, source)

    def test_flex_service_requires_category_and_distinct_materials(self):
        source = text("backend/hr_exit/services/flex_service.py")
        self.assertIn("FLEX_EVIDENCE_CATEGORY_MISMATCH", source)
        self.assertIn("FLEX_EVIDENCE_REUSED", source)
        self.assertIn("verify_material_version", source)
        for category in (
            "MaterialCategoryCode.RETIREMENT_NOTICE",
            "MaterialCategoryCode.RETIREMENT_APPROVAL",
            "MaterialCategoryCode.RETIREMENT_CONTRIBUTION",
            "MaterialCategoryCode.RETIREMENT_AGREEMENT",
        ):
            self.assertIn(category, source)

    def test_manager_upload_does_not_fall_back_to_generic_other_hr(self):
        source = text("backend/hr_exit/flex_api.py")
        section = source[source.index("def upload_evidence"):]
        self.assertIn('request.POST.get("categoryCode")', section)
        self.assertNotIn('category_code="OTHER_HR"', section)
        self.assertIn("RETIREMENT_APPROVAL", section)
        self.assertIn("RETIREMENT_CONTRIBUTION", section)
        self.assertIn("RETIREMENT_AGREEMENT", section)

    def test_self_and_manager_ui_filter_evidence_by_business_use(self):
        self_ui = text("frontend/static/hr/js/pages/hr17-commands.js")
        manager_ui = text("frontend/static/hr/js/pages/hr16-flex.js")
        self.assertIn('materials("RETIREMENT_NOTICE")', self_ui)
        self.assertIn('materials("CORRECTION_EVIDENCE")', self_ui)
        self.assertIn('choices("RETIREMENT_APPROVAL")', manager_ui)
        self.assertIn('choices("RETIREMENT_CONTRIBUTION")', manager_ui)
        self.assertIn('choices("RETIREMENT_AGREEMENT")', manager_ui)


class HistoricalContractClosureTests(unittest.TestCase):
    def test_hr07_is_registered_end_to_end_for_asof_evidence(self):
        asof = text("backend/hr_data/services/asof_service.py")
        guard = text("backend/hr_data/services/formal_fact_evidence_guard.py")
        router = text("backend/hr_data/services/evaluation_router.py")
        provider = text("backend/hr_data/providers/formal_facts.py")
        evaluator = text("backend/hr_data/services/formal_fact_evaluation_service.py")
        self.assertIn('"HR07": "hr_data.providers.formal_facts.hr07_asof_provider"', asof)
        self.assertIn('"HR07": hr07_asof_provider', guard)
        self.assertIn('{"HR06", "HR07", "HR12", "HR13", "HR14", "HR16"}', router)
        self.assertIn('provider_version="hr07-contract-facts-v1"', provider)
        self.assertIn('evaluator_version="hr07-contract-staff-count-v1"', evaluator)

    def test_hr07_counts_staff_from_formal_contract_versions(self):
        source = text("backend/hr_data/services/formal_fact_evaluation_service.py")
        self.assertIn('model_name="HrContractVersion"', source)
        self.assertIn('identity_field="agreement__staff_id"', source)
        self.assertIn('grain=PopulationDefinitionVersion.Grain.STAFF', source)
        self.assertIn('active_statuses=("EFFECTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED")', source)

    def test_hr07_evidence_hash_includes_void_and_successor_identity(self):
        source = text("backend/hr_data/providers/formal_facts.py")
        self.assertIn('allowed_statuses=("EFFECTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED", "VOID")', source)
        self.assertIn('"supersedes_version_id"', source)
        self.assertIn('"content_hash"', source)


    def test_hr07_quality_gate_is_registered_and_checks_authority_breaks(self):
        runtime = text("backend/hr_data/services/quality_runtime_service.py")
        provider = text("backend/hr_data/providers/formal_fact_quality.py")
        self.assertIn('"HR07": "hr_data.providers.formal_fact_quality.quality_provider"', runtime)
        self.assertIn('"HR07_CONTRACT_VERSION_INTEGRITY"', provider)
        for issue in (
            "CROSS_TENANT_AGREEMENT",
            "FORMAL_SIGNATURE_EVIDENCE_REQUIRED",
            "CONTENT_HASH_INVALID",
            "FORMAL_VERSION_OVERLAP",
        ):
            self.assertIn(issue, provider)

    def test_unsafe_domains_remain_fail_closed(self):
        router = text("backend/hr_data/services/evaluation_router.py")
        for domain in ("HR04", "HR05", "HR15"):
            self.assertNotIn(f'"{domain}", "HR13"', router)
        self.assertIn("ASOF_EVALUATION_SOURCE_UNSUPPORTED", router)


class SourceSyntaxTests(unittest.TestCase):
    def test_changed_python_sources_parse(self):
        for relative in (
            "backend/hr_staff/constants.py",
            "backend/hr_staff/services/evidence_reference_service.py",
            "backend/hr_staff/services/material_service.py",
            "backend/hr_exit/services/flex_service.py",
            "backend/hr_exit/flex_api.py",
            "backend/hr_data/services/formal_fact_evaluation_service.py",
            "backend/hr_data/services/formal_fact_chain_service.py",
            "backend/hr_data/providers/formal_facts.py",
            "backend/hr_data/services/asof_service.py",
            "backend/hr_data/services/formal_fact_evidence_guard.py",
            "backend/hr_data/services/evaluation_router.py",
            "backend/hr_data/services/quality_runtime_service.py",
            "backend/hr_data/providers/formal_fact_quality.py",
        ):
            ast.parse(text(relative), filename=relative)


if __name__ == "__main__":
    unittest.main()
