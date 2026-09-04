"""Contracts for HR05 write APIs accepting business data only in POST bodies."""

import ast
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from hr_onboarding.api.base import get_idempotency_key


class Hr05MutationSecurityContractTests(SimpleTestCase):
    source_path = Path(__file__).resolve().parent / "api/views.py"

    def _function_source(self, name):
        source = self.source_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        node = next(
            item
            for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == name
        )
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(lines[first_line - 1 : node.end_lineno])

    def test_activation_and_delay_do_not_fall_back_to_query_parameters(self):
        for name in ("hr05_case_activate", "hr05_case_request_delay"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("request.POST", source)
                self.assertNotIn("request.GET", source)

    def test_idempotency_key_never_falls_back_to_query_string(self):
        request = RequestFactory().post(
            "/api/hr/v1/onboarding/cases/example/activate?idempotency_key=leaked"
        )
        self.assertIsNone(get_idempotency_key(request))

    def test_idempotency_key_accepts_header_and_legacy_form_body(self):
        header_request = RequestFactory().post(
            "/api/hr/v1/onboarding/cases/example/activate",
            headers={"Idempotency-Key": "header-key"},
        )
        form_request = RequestFactory().post(
            "/api/hr/v1/onboarding/cases/example/activate",
            data={"idempotency_key": "form-key"},
        )

        self.assertEqual(get_idempotency_key(header_request), "header-key")
        self.assertEqual(get_idempotency_key(form_request), "form-key")
