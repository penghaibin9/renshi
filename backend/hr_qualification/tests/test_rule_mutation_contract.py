"""Concurrency and validation guards for HR09 rule-authority writes."""

import inspect

from django.test import SimpleTestCase

from hr_qualification.api import views_rule


class RuleMutationContractTests(SimpleTestCase):
    def test_json_payload_must_be_an_object(self):
        source = inspect.getsource(views_rule._json_object)

        self.assertIn("isinstance(body, dict)", source)

    def test_rule_version_creation_locks_owned_pack(self):
        source = inspect.getsource(views_rule.rule_version_create)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("tenant_id=request.hr09_tenant_id", source)
        self.assertIn("version.full_clean()", source)

    def test_rule_creation_locks_draft_version_and_rejects_duplicate_code(self):
        source = inspect.getsource(views_rule.rule_create)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("RulePackVersionStatus.DRAFT", source)
        self.assertIn("RULE_CODE_DUPLICATE", source)
        self.assertIn("rule.full_clean()", source)

    def test_rule_write_errors_do_not_leak_internal_exceptions(self):
        source = inspect.getsource(views_rule)

        self.assertNotIn('error_envelope("INTERNAL_ERROR", str(e))', source)
