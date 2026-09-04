"""Regression contracts for shift and work-type request mutations."""

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


class ScheduleMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "base/views.py"
        module_source = path.read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.walk(ast.parse(module_source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(module_lines[first_line - 1 : node.end_lineno])

    def test_single_schedule_mutators_are_post_only_and_atomic(self):
        for name in (
            "work_type_request_cancel",
            "work_type_request_approve",
            "shift_request_cancel",
            "shift_request_approve",
            "shift_allocation_request_cancel",
            "shift_allocation_request_approve",
            "rotating_work_type_assign_archive",
            "rotating_shift_assign_archive",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_shift_transitions_are_idempotent_and_reallocation_is_authorized(self):
        approve = self._function_source("shift_request_approve")
        self.assertIn("not shift_request.canceled", approve)
        self.assertIn("not shift_request.reallocate_approved", approve)
        self.assertIn("shift_request.shift_changed = True", approve)

        cancel = self._function_source("shift_request_cancel")
        self.assertIn("if shift_request.canceled:", cancel)
        self.assertIn("if shift_request.shift_changed:", cancel)
        self.assertNotIn("datetime.today()", cancel)

        for name in (
            "shift_allocation_request_cancel",
            "shift_allocation_request_approve",
        ):
            source = self._function_source(name)
            self.assertIn("actor != shift_request.reallocate_to", source)
            self.assertIn("Shift reallocation request is already processed.", source)

    def test_work_type_transitions_lock_employee_state(self):
        for name in ("work_type_request_cancel", "work_type_request_approve"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn(
                    "EmployeeWorkInformation.objects.select_for_update()", source
                )
        approve = self._function_source("work_type_request_approve")
        self.assertIn("not work_type_request.canceled", approve)
        self.assertIn("work_type_request.work_type_changed = True", approve)

    def test_rotating_assignment_reactivation_excludes_itself(self):
        for name in (
            "rotating_work_type_assign_archive",
            "rotating_shift_assign_archive",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn(".exclude(pk=", source)
                self.assertIn("next_active = not", source)

    def test_schedule_templates_and_ajax_use_post(self):
        roots = (
            self.backend_dir / "base/templates",
            self.backend_dir / "employee/templates",
        )
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertIsNone(
            re.search(
                r"hx-get=[^>\n]*(rotating-shift-assign-archive|rotating-work-type-assign-archive)",
                templates,
            )
        )
        self.assertIsNone(
            re.search(
                r"href=[\"']/(?:shift|work-type)-request-(?:approve|cancel)/",
                templates,
            )
        )

        for relative_path in (
            "base/static/cbv/work_type_request/work_request_bulk_action.js",
            "base/static/cbv/shift_request/shift_request_bulk_actions.js",
        ):
            javascript = (self.backend_dir / relative_path).read_text(encoding="utf-8")
            function_name = (
                "workTypeRequestRowApprove"
                if "work_request" in relative_path
                else "shiftRequestRowApprove"
            )
            start = javascript.index(f"function {function_name}")
            function_source = javascript[start : javascript.index("\n}", start) + 2]
            self.assertIn('type: "POST"', function_source)
            self.assertIn('csrfmiddlewaretoken: getCookie("csrftoken")', function_source)

    def test_schedule_comments_and_files_are_scoped_post_mutations(self):
        for name in (
            "delete_shift_comment_file",
            "delete_work_type_comment_file",
            "delete_shiftrequest_comment",
            "delete_worktyperequest_comment",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("_can_delete_schedule_comment", source)

        for name in (
            "create_shiftrequest_comment",
            "view_shift_comment",
            "create_worktyperequest_comment",
            "view_work_type_comment",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("_can_participate_in_schedule_request", source)

        views_source = (self.backend_dir / "base/views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("comment.files.select_for_update().filter(id__in=ids)", views_source)

        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.backend_dir / "base/templates").rglob("*.html")
        )
        for route_name in (
            "shift-request-delete-comment",
            "worktype-request-delete-comment",
            "delete-shift-comment-file",
            "delete-work-type-comment-file",
        ):
            with self.subTest(route=route_name):
                self.assertIsNone(
                    re.search(rf"hx-get=[^>\n]*{route_name}", templates)
                )
