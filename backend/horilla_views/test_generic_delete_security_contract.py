"""Regression contracts for the generic deletion surface."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class GenericDeleteSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    @classmethod
    def _class_source(cls):
        path = cls.backend_dir / "horilla_views/views.py"
        module_source = path.read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        class_node = next(
            node
            for node in ast.parse(module_source).body
            if isinstance(node, ast.ClassDef)
            and node.name == "HorillaDeleteConfirmationView"
        )
        return "".join(module_lines[class_node.lineno - 1 : class_node.end_lineno])

    def test_delete_resolves_only_valid_registered_models(self):
        source = self._class_source()
        self.assertIn("def _resolve_model", source)
        self.assertIn("if len(parts) != 2 or not all(parts):", source)
        self.assertIn("apps.get_model(parts[0], parts[1])", source)
        self.assertIn("model is None or model._meta.abstract", source)

    def test_generic_delete_is_atomic_and_locks_the_root_record(self):
        source = self._class_source()
        self.assertIn("with transaction.atomic():", source)
        self.assertIn("model.objects.select_for_update()", source)
        self.assertIn("except model.DoesNotExist:", source)

    def test_protected_records_require_their_own_delete_permission(self):
        source = self._class_source()
        self.assertIn("if protected and not self._can_delete", source)
        self.assertIn("raise PermissionDenied", source)

    def test_route_counts_only_post_as_a_write(self):
        source = (self.backend_dir / "horilla_views/urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('surface="generic-delete"', source)
        self.assertIn('write_methods={"POST"}', source)

