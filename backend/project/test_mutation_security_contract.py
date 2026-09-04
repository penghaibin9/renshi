"""Regression contracts for project, task, stage, and timesheet mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class ProjectMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "project/views.py"
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

    def test_destructive_project_mutators_are_post_only_atomic_and_locked(self):
        for function_name in (
            "project_delete",
            "project_bulk_archive",
            "project_bulk_delete",
            "project_archive",
            "delete_task",
            "task_all_bulk_archive",
            "task_all_bulk_delete",
            "task_all_archive",
            "delete_project_stage",
            "time_sheet_delete",
            "change_project_status",
            "task_stage_change",
            "drag_and_drop_stage",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_project_bulk_delete_executes_the_authorized_deletion(self):
        source = self._function_source("project_bulk_delete")
        self.assertIn(
            "Project.objects.filter(id__in=[p.id for p in deletable_projects]).delete()",
            source,
        )
        self.assertNotIn(
            "# Project.objects.filter(id__in=[p.id for p in deletable_projects]).delete()",
            source,
        )

    def test_task_all_mutations_enforce_object_permissions(self):
        for function_name, permission in (
            ("task_all_bulk_archive", "project.change_task"),
            ("task_all_bulk_delete", "project.delete_task"),
            ("task_all_archive", "project.change_task"),
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn(permission, source)
                if function_name == "task_all_bulk_delete":
                    self.assertIn("_can_manage_task", source)
                else:
                    self.assertIn("task.task_managers.all()", source)
                    self.assertIn("task.project.managers.all()", source)

    def test_task_bulk_delete_and_stage_moves_are_all_or_nothing(self):
        bulk_delete = self._function_source("task_all_bulk_delete")
        self.assertIn("len(tasks) != len(ids)", bulk_delete)
        self.assertIn("_can_manage_task", bulk_delete)
        self.assertIn("transaction.set_rollback(True)", bulk_delete)

        stage_change = self._function_source("task_stage_change")
        self.assertIn("project_id=task.project_id", stage_change)
        self.assertIn("_can_manage_task", stage_change)

        reorder = self._function_source("drag_and_drop_stage")
        self.assertIn("len({stage.project_id for stage in stages}) != 1", reorder)
        self.assertIn("ProjectStage.objects.bulk_update", reorder)

        project_status = self._function_source("change_project_status")
        self.assertIn("Project.PROJECT_STATUS", project_status)
        self.assertIn("_notify_after_commit", project_status)

    def test_bulk_archive_state_is_posted_and_batches_are_all_or_nothing(self):
        project_source = self._function_source("project_bulk_archive")
        self.assertIn('request.POST.get("is_active"', project_source)
        self.assertNotIn("request.GET", project_source)
        self.assertIn("len(projects) != len(set(ids))", project_source)
        self.assertIn("any(not is_project_manager_or_super_user", project_source)

        task_source = self._function_source("task_all_bulk_archive")
        self.assertIn('request.POST.get("is_active"', task_source)
        self.assertNotIn("request.GET", task_source)
        self.assertIn("len(tasks) != len(ids)", task_source)
        self.assertIn('status=403', task_source)

        template = (
            self.backend_dir / "project/templates/cbv/projects/project_nav.html"
        ).read_text(encoding="utf-8")
        script = (
            self.backend_dir / "project/static/task_all/task_all_action.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("project-bulk-archive' %}?is_active=", template)
        self.assertIn("hx-vals='{\"is_active\":", template)
        self.assertNotIn("task-all-bulk-archive/?is_active=", script)
        self.assertEqual(script.count('is_active: "False"'), 2)
        self.assertEqual(script.count('is_active: "True"'), 2)

    def test_delete_task_redirect_does_not_trust_the_referer(self):
        source = self._function_source("delete_task")
        self.assertNotIn("HTTP_REFERER", source)
        self.assertIn('request.GET.get("task_all") == "true"', source)
        self.assertIn('reverse("task-view"', source)

    def test_task_and_timesheet_permission_helpers_fail_closed(self):
        decorator_source = (self.backend_dir / "project/decorator.py").read_text(
            encoding="utf-8"
        )
        methods_source = (self.backend_dir / "project/methods.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('request.user.has_perm("project.delete_task")', decorator_source)
        self.assertIn("if not timesheet:\n        return False", methods_source)

    def test_project_templates_do_not_use_get_for_mutations(self):
        templates = (
            self.backend_dir / "project/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in templates
            for path in root.rglob("*.html")
        )
        for fragment in (
            "hx-get=\"{{instance.get_archive_url}}\"",
            "hx-get=\"{% url 'delete-project'",
            "hx-get=\"{% url 'task-all-archive'",
            "hx-delete=\"{% url 'delete-time-sheet'",
            "href=\"{% url 'delete-time-sheet'",
            "hx-get=\"{% url 'update-project-task-status'",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

    def test_task_status_update_is_post_only_authorized_locked_and_validated(self):
        source = self._function_source("update_project_task_status")
        self.assertIn("@task_update_permission()", source)
        self.assertIn("@require_POST", source)
        self.assertIn("@transaction.atomic", source)
        self.assertIn("select_for_update()", source)
        self.assertIn('request.POST.get("status")', source)
        self.assertIn("Task.TASK_STATUS", source)
