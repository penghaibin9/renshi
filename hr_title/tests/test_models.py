from django.test import SimpleTestCase

from hr_title.models import ProfessionalTitleResult, TitleApplicationCase, TitlePolicyVersion


class Hr13ModelContractTests(SimpleTestCase):
    def test_returned_and_rejected_are_distinct_states(self):
        assert TitleApplicationCase.Status.RETURNED != TitleApplicationCase.Status.REJECTED

    def test_title_result_has_only_fact_revision_states(self):
        assert set(ProfessionalTitleResult.Status.values) == {"EFFECTIVE", "REVISED", "REVOKED"}

    def test_policy_uses_named_effective_range_constraint(self):
        names = {constraint.name for constraint in TitlePolicyVersion._meta.constraints}
        assert "ck_hr13_policy_effective_range" in names
        assert "uq_hr13_policy_tenant_code_ver" in names

    def test_result_uses_named_tenant_identity_constraint(self):
        names = {constraint.name for constraint in ProfessionalTitleResult._meta.constraints}
        assert "uq_hr13_result_tenant_no" in names
        assert "ck_hr13_result_hash_format" in names
        assert "ck_hr13_result_sealed_at" in names

    def test_tenant_is_fail_closed_before_database_write(self):
        policy = TitlePolicyVersion(
            tenant_id=None,
            policy_code="PROFESSOR",
            name="Professor policy",
            effective_from="2026-01-01",
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            policy.save()
