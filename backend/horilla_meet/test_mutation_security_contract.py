"""Regression contracts for Google Meet destructive operations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class GoogleMeetMutationSecurityContractTests(SimpleTestCase):
    path = Path(__file__).resolve().parent / "views.py"

    def _function_source(self, name):
        source = self.path.read_text(encoding="utf-8")
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

    def test_google_meet_deletes_are_post_only_and_tenant_scoped(self):
        credentials = self._function_source("delete_google_credentials")
        self.assertIn("@require_POST", credentials)
        self.assertIn("@transaction.atomic", credentials)
        self.assertIn("select_for_update()", credentials)

        meeting = self._function_source("delete_google_meet")
        self.assertIn("@require_POST", meeting)
        self.assertIn("GoogleMeeting.objects.only", meeting)
        self.assertIn("GoogleMeeting.objects.select_for_update()", meeting)
        self.assertIn('request.POST.get("detail_view")', meeting)
        self.assertNotIn("request.GET.get", meeting)
