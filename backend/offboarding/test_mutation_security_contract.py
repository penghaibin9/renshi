"""Regression contracts for offboarding workflow mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class OffboardingMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "offboarding/views.py"
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

    def test_offboarding_mutators_are_post_only(self):
        for name in (
            "offboarding_note_delete",
            "delete_offboarding",
            "delete_employee",
            "delete_stage",
            "change_stage",
            "change_offboarding_stage",
            "delete_attachment",
            "update_task_status",
            "task_assign",
            "delete_task",
            "delete_resignation_request",
            "update_status",
            "enable_resignation_request",
        ):
            with self.subTest(function=name):
                self.assertIn(
                    '@require_http_methods(["POST"])', self._function_source(name)
                )

    def test_task_updates_are_stage_scoped_and_atomic(self):
        source = self._function_source("update_task_status")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("status not in dict(EmployeeTask.statuses)", source)
        self.assertIn("OffboardingTask.objects.select_for_update().filter(", source)
        self.assertIn("id=task_id, stage_id=stage_id", source)
        self.assertIn("id__in=employee_ids, stage_id=stage_id", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("_can_manage_offboarding_task", source)
        self.assertIn("employees.exclude(employee_id_id=actor_id)", source)
        self.assertNotIn("request.GET", source)
        self.assertIn("transaction.on_commit", source)

    def test_task_assignment_does_not_hide_integrity_errors(self):
        source = self._function_source("task_assign")
        self.assertIn("EmployeeTask.objects.select_for_update().get_or_create", source)
        self.assertNotIn("except:", source)
        self.assertIn("stage_id=task.stage_id", source)
        self.assertIn("OffboardingTask.objects.select_for_update()", source)
        self.assertIn("_can_manage_offboarding_task", source)
        self.assertIn("request.POST", source)
        self.assertNotIn("request.GET", source)

    def test_resignation_status_is_validated_and_atomic(self):
        source = self._function_source("update_status")
        self.assertIn("@transaction.atomic", source)
        self.assertIn('status not in {"approved", "rejected"}', source)
        self.assertIn('status == "approved" and not offboarding_id', source)
        self.assertIn("select_for_update()", source)
        self.assertIn("request.POST", source)
        self.assertNotIn("request.GET", source)
        self.assertIn("letters.count() != len(set(ids))", source)
        self.assertIn("contract_status=\"active\"", source)
        self.assertIn("employee_id=letter.employee_id", source)
        self.assertIn("transaction.on_commit", source)

    def test_note_attachment_delete_is_note_scoped(self):
        source = self._function_source("delete_attachment")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("request.POST", source)
        self.assertNotIn("request.GET", source)
        self.assertIn("OffboardingNote.objects.select_for_update()", source)
        self.assertIn("note.attachments.select_for_update().filter(id__in=ids)", source)
        self.assertIn("note.attachments.remove(*records)", source)
        self.assertIn("offboardingnote__isnull=True", source)
        self.assertIn("_can_access_offboarding_employee", source)

    def test_note_access_and_uploads_are_parent_scoped(self):
        view_notes = self._function_source("view_notes")
        self.assertIn("@transaction.atomic", view_notes)
        self.assertIn("OffboardingEmployee.objects.select_for_update()", view_notes)
        self.assertIn("_can_access_offboarding_employee", view_notes)
        self.assertIn('request.method == "POST" and request.FILES', view_notes)
        self.assertIn('request.POST.get("note_id")', view_notes)
        self.assertIn("employee_id=employee", view_notes)
        self.assertNotIn('request.GET["note_id"]', view_notes)

        add_note = self._function_source("add_note")
        self.assertIn("@transaction.atomic", add_note)
        self.assertIn("OffboardingEmployee.objects.select_for_update()", add_note)
        self.assertIn("_can_access_offboarding_employee", add_note)

        note_delete = self._function_source("offboarding_note_delete")
        self.assertIn("_can_access_offboarding_employee", note_delete)
        self.assertIn("note.note_by_id", note_delete)

    def test_task_and_resignation_deletes_are_locked_and_posted(self):
        for name in ("delete_task", "delete_resignation_request"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("request.POST", source)
                self.assertNotIn("request.GET", source)
                self.assertIn("select_for_update()", source)

        task_delete = self._function_source("delete_task")
        self.assertIn("Q(managers=actor_id)", task_delete)
        self.assertIn("tasks.count() != len(set(task_ids))", task_delete)

    def test_stage_changes_are_atomic_locked_and_offboarding_scoped(self):
        for name in ("change_stage", "change_offboarding_stage"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("request.POST", source)
                self.assertNotIn("request.GET", source)
                self.assertIn("OffboardingStage.objects.select_for_update()", source)
                self.assertIn("OffboardingEmployee.objects.select_for_update()", source)
                self.assertIn("stage_id__offboarding_id=stage.offboarding_id", source)
                self.assertIn("_can_move_offboarding_employees", source)
                self.assertIn("transaction.on_commit", source)

    def test_stage_and_employee_forms_are_exactly_scoped_and_atomic(self):
        create_stage = self._function_source("create_stage")
        self.assertIn("@transaction.atomic", create_stage)
        self.assertIn("Offboarding.objects.select_for_update()", create_stage)
        self.assertIn("OffboardingStage.objects.select_for_update()", create_stage)
        self.assertIn("offboarding_id=offboarding", create_stage)
        self.assertIn("_can_manage_offboarding", create_stage)
        self.assertIn("transaction.on_commit", create_stage)

        add_employee = self._function_source("add_employee")
        self.assertIn("@transaction.atomic", add_employee)
        self.assertIn("OffboardingStage.objects.select_for_update()", add_employee)
        self.assertIn("OffboardingEmployee.objects.select_for_update()", add_employee)
        self.assertIn("stage_id__offboarding_id=stage.offboarding_id", add_employee)
        self.assertIn("_can_manage_offboarding_stage", add_employee)
        self.assertIn("transaction.on_commit", add_employee)

    def test_stage_order_is_all_or_nothing_and_validates_the_full_order(self):
        source = self._function_source("update_stage_order")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("Offboarding.objects.select_for_update()", source)
        self.assertIn("OffboardingStage.objects.select_for_update()", source)
        self.assertIn("set(order) !=", source)
        self.assertIn("OffboardingStage.objects.bulk_update", source)
        self.assertNotIn("except Exception", source)

    def test_resignation_setting_update_is_atomic_and_locked(self):
        source = self._function_source("enable_resignation_request")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("select_for_update()", source)

    def test_pipeline_deletes_are_atomic_locked_and_posted(self):
        for name in ("delete_offboarding", "delete_employee", "delete_stage"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
        for name in ("delete_employee", "delete_stage"):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("request.POST", source)
                self.assertNotIn("request.GET", source)

        employee_delete = self._function_source("delete_employee")
        self.assertIn("recipient_ids = list(", employee_delete)
        self.assertIn("transaction.on_commit", employee_delete)

    def test_offboarding_templates_post_mutation_identifiers(self):
        roots = (
            self.backend_dir / "offboarding/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        for endpoint in (
            "delete-resignation-request",
            "update-task-status",
            "delete-note-attachment",
            "offboarding-assign-task",
            "delete-offboarding-employee",
            "delete-offboarding-stage",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertNotIn(f"{endpoint}' %}}?", combined)
                self.assertNotIn(f'{endpoint}" %}}?', combined)
        self.assertNotIn("hx-get=\"{% url 'offboarding-assign-task'", combined)
        self.assertNotIn('hx-get="{% url "offboarding-assign-task"', combined)
        self.assertNotIn('hx-get="{% url "offboarding-change-stage"', combined)
        self.assertNotIn("hx-get='{% url \"offboarding-change-stage\"", combined)
        self.assertNotIn('hx-get="{% url "change-offboarding-stage"', combined)
        self.assertNotIn("add-offboarding-note' %}?employee_id=", combined)
        self.assertNotIn("view-offboarding-note' employee.id %}?note_id=", combined)
        self.assertIn("hx-vals='{\"employee_ids\":", combined)
