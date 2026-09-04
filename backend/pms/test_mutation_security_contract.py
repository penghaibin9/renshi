"""Regression contracts for performance-management state mutations."""

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


class PerformanceMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "pms/views.py"
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

    def test_performance_mutators_are_post_only_atomic_and_locked(self):
        for name in (
            "archive_employee_objective",
            "delete_employee_objective",
            "change_employee_objective_status",
            "question_template_delete",
            "period_delete",
            "archive_key_result",
            "objective_delete",
            "objective_manager_remove",
            "key_result_remove",
            "objective_detailed_view_objective_status",
            "objective_detailed_view_key_result_status",
            "objective_detailed_view_current_value",
            "objective_archive",
            "feedback_delete",
            "feedback_detailed_view_status",
            "feedback_archive",
            "archive_anonymous_feedback",
            "delete_anonymous_feedback",
            "delete_employee_keyresult",
            "employee_keyresult_update_status",
            "key_result_current_value_update",
            "archive_meetings",
            "meeting_manager_remove",
            "meeting_employee_remove",
            "delete_bonus_point_setting",
            "delete_employee_bonus_point",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_legacy_status_endpoints_use_object_scope_and_choice_whitelists(self):
        for name in (
            "objective_detailed_view_objective_status",
            "objective_detailed_view_key_result_status",
            "employee_keyresult_update_status",
        ):
            source = self._function_source(name)
            self.assertIn("_can_update_employee_objective", source)
            self.assertIn("_valid_status", source)
        key_result_source = self._function_source(
            "objective_detailed_view_key_result_status"
        )
        self.assertIn("employee_objective_id_id=obj_id", key_result_source)

    def test_current_value_updates_are_bounded_and_authorized(self):
        for name in (
            "objective_detailed_view_current_value",
            "key_result_current_value_update",
        ):
            source = self._function_source(name)
            self.assertIn("_can_update_employee_objective", source)
            self.assertIn("current_value < 0", source)
            self.assertIn("current_value >", source)

    def test_bonus_ledger_updates_by_delta_and_reverses_on_delete(self):
        path = self.backend_dir / "pms/models.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn('previous["bonus_point"] if previous else 0', source)
        self.assertIn("self._adjust_employee_total(employee_id, -points, reason)", source)
        self.assertNotIn("bonus_point.points += self.bonus_point", source)

    def test_objective_status_is_scoped_and_whitelisted(self):
        source = self._function_source("change_employee_objective_status")
        self.assertIn('request.POST.get("empObjId")', source)
        self.assertIn('request.POST.get("status")', source)
        self.assertIn("EmployeeObjective.STATUS_CHOICES", source)
        self.assertIn("if emp_objective is None:", source)
        self.assertIn("self_employee_progress_update", source)
        self.assertEqual(source.count("You dont have permission"), 1)

    def test_performance_templates_do_not_issue_get_mutations(self):
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.backend_dir / "pms/templates").rglob("*.html")
        )
        mutation_names = (
            "period-delete",
            "question-template-delete",
            "archive-employee-objective",
            "delete-employee-objective",
            "change-employee-objective-status",
        )
        for name in mutation_names:
            with self.subTest(route=name):
                self.assertIsNone(
                    re.search(rf"hx-get=[^>\n]*{re.escape(name)}", templates)
                )
        self.assertIsNone(
            re.search(
                r"href=[\"'][^\"']*archive-employee-objective", templates
            )
        )

    def test_bulk_objective_and_feedback_actions_are_atomic_and_scoped(self):
        for name in (
            "objective_bulk_archive",
            "objective_bulk_delete",
            "feedback_bulk_archive",
            "feedback_bulk_delete",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("_posted_json_ids", source)

        objective_archive = self._function_source("objective_bulk_archive")
        self.assertIn("_can_archive_employee_objective", objective_archive)
        self.assertIn('request.POST.get("is_active")', objective_archive)
        self.assertNotIn("request.GET", objective_archive)

        feedback_archive = self._function_source("feedback_bulk_archive")
        self.assertIn("_can_manage_feedback", feedback_archive)
        self.assertIn("_can_manage_anonymous_feedback", feedback_archive)
        self.assertIn('request.POST.get("is_active")', feedback_archive)
        self.assertNotIn("request.GET", feedback_archive)

        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.backend_dir / "pms/static/src/okr/action.js",
                self.backend_dir / "pms/static/src/feedback/action.js",
                self.backend_dir / "pms/static/cbv/360_feedback.js",
            )
        )
        self.assertNotIn("bulk-archive/?is_active=", scripts)
        self.assertIn('is_active: "False"', scripts)
        self.assertIn('is_active: "True"', scripts)
