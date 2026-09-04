"""Regression contracts for saved-filter and view preference writes."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class PreferenceMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    @classmethod
    def _method_source(cls, class_name, method_name):
        path = cls.backend_dir / "horilla_views/views.py"
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        module = ast.parse(source)
        class_node = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        method = next(
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == method_name
        )
        return "".join(lines[method.lineno - 1 : method.end_lineno])

    def test_saved_filter_delete_posts_and_locks_owner_record(self):
        source = self._method_source("DeleteSavedFilter", "post")
        self.assertIn("transaction.atomic()", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("created_by=self.request.user", source)

    def test_active_view_posts_validated_user_preference(self):
        source = self._method_source("ActiveView", "post")
        self.assertIn("self.request.POST", source)
        self.assertIn('path.startswith("/")', source)
        self.assertIn("transaction.atomic()", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("created_by=self.request.user", source)

    def test_preference_templates_do_not_write_with_get(self):
        roots = (
            self.backend_dir / "horilla_views/templates/generic",
            self.backend_dir / "horilla_theme/templates/generic",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertNotIn("hx-get=\"{% url 'delete-saved-filter'", combined)
        self.assertNotIn('hx-get=\'{% url "delete-saved-filter"', combined)
        self.assertNotIn("hx-get=\"{% url 'active-hnv-view-type'", combined)
        self.assertNotIn('hx-get=\'{% url "active-hnv-view-type"', combined)

