"""Regression contracts for backup configuration mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class BackupMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    @classmethod
    def _function_source(cls, function_name):
        path = cls.backend_dir / "horilla_backup/views.py"
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

    def test_backup_start_stop_and_delete_are_post_only_atomic_and_locked(self):
        for function_name in (
            "gdrive_Backup_stop_or_start",
            "gdrive_Backup_delete",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("transaction.on_commit", source)

    def test_google_drive_views_use_the_google_drive_permissions(self):
        source = (self.backend_dir / "horilla_backup/views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("horilla_backup.add_googledrivebackup", source)
        self.assertIn("horilla_backup.change_googledrivebackup", source)
        self.assertIn("horilla_backup.delete_googledrivebackup", source)

    def test_backup_template_posts_mutations_with_csrf(self):
        source = (
            self.backend_dir / "horilla_backup/templates/backup/gdrive_setup_form.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('href="{% url \'gdrive_start_stop\'', source)
        self.assertNotIn('href="{% url \'gdrive_delete\'', source)
        self.assertIn('method="post" action="{% url \'gdrive_start_stop\'', source)
        self.assertIn('method="post" action="{% url \'gdrive_delete\'', source)
        self.assertIn("{% csrf_token %}", source)

