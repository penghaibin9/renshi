"""Regression contracts for announcement access and destructive actions."""

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


class AnnouncementSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "base/announcement.py"
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(lines[first_line - 1 : node.end_lineno])

    def test_destructive_announcement_actions_are_post_only_and_locked(self):
        for name in (
            "delete_announcement",
            "remove_announcement_file",
            "delete_announcement_comment",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_announcement_and_attachment_deletes_require_permissions(self):
        self.assertIn(
            '@permission_required("base.delete_announcement")',
            self._function_source("delete_announcement"),
        )
        self.assertIn(
            '@permission_required("base.change_announcement")',
            self._function_source("remove_announcement_file"),
        )

    def test_comment_read_write_and_delete_are_object_scoped(self):
        for name in ("create_announcement_comment", "comment_view"):
            with self.subTest(function=name):
                self.assertIn(
                    "_can_access_announcement(request,", self._function_source(name)
                )
        create = self._function_source("create_announcement_comment")
        self.assertIn("if anoun.disable_comments:", create)

        delete = self._function_source("delete_announcement_comment")
        self.assertIn("is_author =", delete)
        self.assertIn('has_perm("base.delete_announcement")', delete)
        self.assertIn("return HttpResponse(status=403)", delete)

    def test_comment_delete_templates_use_post(self):
        roots = (
            self.backend_dir / "base/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertIsNone(
            re.search(
                r"hx-get=[^>\n]*announcement-delete-comment", templates
            )
        )

