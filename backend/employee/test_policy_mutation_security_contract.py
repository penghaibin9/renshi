"""Regression contracts for policy access and mutation endpoints."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class PolicyMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "employee/policies.py"
        module_source = path.read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, ast.FunctionDef)
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(module_lines[first_line - 1 : node.end_lineno])

    def test_policy_mutators_are_post_only_and_lock_records(self):
        for function_name in (
            "delete_policies",
            "add_attachment",
            "remove_attachment",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("with transaction.atomic():", source)
                self.assertIn("select_for_update()", source)
                mutation_prefix = source.split("if request.META", 1)[0]
                self.assertNotIn("request.GET", mutation_prefix)

    def test_attachment_deletion_is_scoped_to_its_policy(self):
        source = self._function_source("remove_attachment")
        self.assertIn("policy.attachments.select_for_update()", source)
        self.assertIn(".filter(id__in=requested_ids)", source)
        self.assertIn("policy.attachments.remove(*attachment_ids)", source)
        self.assertIn("policy__isnull=True", source)

    def test_non_public_policy_reads_use_the_visibility_scope(self):
        source = (self.backend_dir / "employee/policies.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _policies_visible_to_request", source)
        self.assertIn("Q(specific_employees=employee)", source)
        for function_name in ("view_policies", "search_policies", "view_policy"):
            with self.subTest(function=function_name):
                self.assertIn(
                    "_policies_visible_to_request", self._function_source(function_name)
                )

    def test_policy_form_uses_create_or_change_permission_by_operation(self):
        source = (self.backend_dir / "employee/cbv/policy_cbv.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"employee.change_policy"', source)
        self.assertIn('"employee.add_policy"', source)
        self.assertIn("if kwargs.get(\"pk\")", source)

    def test_policy_templates_do_not_delete_with_get(self):
        roots = (
            self.backend_dir / "employee/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertNotIn("hx-get=\"{% url 'delete-policies'", combined)
        self.assertNotIn("hx-get=\"{% url 'remove-attachment-policy'", combined)
        self.assertNotIn("delete-policies' %}?ids=", combined)
        self.assertNotIn("add-attachment-policy' %}?policy_id=", combined)
        self.assertNotIn("remove-attachment-policy' %}?ids=", combined)
        self.assertIn('name="policy_id" value="{{ policy.id }}"', combined)
        self.assertIn("hx-vals='{\"ids\":\"{{ attachment.id }}\"", combined)
