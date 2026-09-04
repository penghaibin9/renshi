"""Regression contracts for employee profile mutation endpoints."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class EmployeeMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "employee/views.py"
        module_source = path.read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(module_lines[first_line - 1 : node.end_lineno])

    def test_profile_mutators_are_post_only(self):
        for function_name in (
            "document_approve",
            "delete_employee_note_file",
            "document_delete",
            "employee_account_block_unblock",
            "employee_archive",
            "employee_bulk_archive",
            "employee_note_delete",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn('@require_http_methods(["POST"])', source)

    def test_templates_use_post_for_profile_mutations(self):
        roots = (
            self.backend_dir / "employee/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        for fragment in (
            'hx-get="{% url \'document-approve\'',
            'hx-get="{% url \'delete-employee-note-file\'',
            'hx-get="{% url \'document-delete\'',
            'hx-get="{% url \'employee-archive\'',
            'hx-get="{% url \'employee-note-delete\'',
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

        profile = (
            self.backend_dir
            / "employee/templates/cbv/profile/profile_view.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '<form hidden action="{% url \'employee-account-block-unblock\' instance.id %}" method="post"',
            profile,
        )

    def test_archive_updates_employee_and_login_account_atomically(self):
        source = self._function_source("employee_archive")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("employee.is_active = new_active_state", source)
        self.assertIn("user.is_active = new_active_state", source)
        self.assertIn('user.save(update_fields=["is_active"])', source)

        bulk_source = self._function_source("employee_bulk_archive")
        self.assertIn("@transaction.atomic", bulk_source)
        self.assertIn('request.POST.get("is_active"', bulk_source)
        self.assertNotIn("request.GET", bulk_source)
        self.assertIn("Employee.objects.select_for_update()", bulk_source)
        self.assertIn("HorillaUser.objects.select_for_update()", bulk_source)
        self.assertIn("selected_superusers", bulk_source)
        self.assertIn("employee.save(update_fields=[\"is_active\"])", bulk_source)
        self.assertIn("user.save(update_fields=[\"is_active\"])", bulk_source)

        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.backend_dir / "employee/static/employee/actions.js",
                self.backend_dir / "employee/static/cbv/employee_view/actions.js",
            )
        )
        self.assertNotIn("employee-bulk-archive/?is_active=", scripts)
        self.assertGreaterEqual(scripts.count('is_active: "False"'), 2)
        self.assertGreaterEqual(scripts.count('is_active: "True"'), 2)

    def test_document_decisions_lock_rows_and_bulk_actions_are_scoped(self):
        for function_name in ("document_delete", "document_approve"):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        bulk_approve = self._function_source("document_bulk_approve")
        self.assertIn('@require_http_methods(["POST"])', bulk_approve)
        self.assertIn("@transaction.atomic", bulk_approve)
        self.assertIn("select_for_update()", bulk_approve)
        self.assertIn("approved_ids", bulk_approve)

        bulk_reject = self._function_source("document_bulk_reject")
        self.assertIn('@require_http_methods(["GET", "POST"])', bulk_reject)
        self.assertIn("with transaction.atomic():", bulk_reject)
        self.assertIn("select_for_update()", bulk_reject)
        self.assertIn("document_ids", bulk_reject)

    def test_document_approval_refresh_is_post_only_and_safe(self):
        source = self._function_source("document_approve")
        self.assertIn('request.POST.get("refresh_url")', source)
        self.assertNotIn("request.GET", source)
        self.assertIn("url_has_allowed_host_and_scheme", source)
        self.assertIn('refresh_url.startswith("/")', source)
        self.assertIn('not refresh_url.startswith("//")', source)
        self.assertIn("format_html(", source)

    def test_document_reject_form_locks_and_updates_only_decision_fields(self):
        source = (
            self.backend_dir / "employee/cbv/document_request.py"
        ).read_text(encoding="utf-8")
        self.assertIn("with transaction.atomic():", source)
        self.assertIn("Document.objects.select_for_update().get", source)
        self.assertIn(
            'document.save(update_fields=["reject_reason", "status"])', source
        )

    def test_document_uploads_are_object_scoped_and_server_owned(self):
        source = (
            self.backend_dir / "employee/cbv/document_request.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def scope_documents_for_review", source)
        self.assertIn(
            "employee_id__employee_work_info__reporting_manager_id=manager", source
        )
        self.assertIn("def can_edit_employee_document", source)
        self.assertIn("self.target_employee = get_object_or_404", source)
        self.assertIn("form.instance.employee_id = self.target_employee", source)
        self.assertIn("self.target_document_id = document.pk", source)
        self.assertIn("Document.objects.select_for_update().get", source)
        self.assertIn('document.status = "requested"', source)
        self.assertIn("document.reject_reason = None", source)

        model_source = (
            self.backend_dir / "horilla_documents/models.py"
        ).read_text(encoding="utf-8")
        self.assertIn("is_new = self._state.adding", model_source)
        self.assertIn("if is_new and self.is_digital_asset:", model_source)

    def test_employee_deletes_are_atomic_complete_and_protect_accounts(self):
        for function_name in ("employee_delete", "employee_bulk_delete"):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn('@require_http_methods(["POST"])', source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("Employee.objects.select_for_update()", source)
                self.assertIn("HorillaUser.objects.select_for_update()", source)
                self.assertIn("transaction.set_rollback(True)", source)
                self.assertIn("request.user.id", source)
                self.assertIn("is_superuser", source)

        bulk_source = self._function_source("employee_bulk_delete")
        self.assertIn("_posted_ids(request)", bulk_source)
        self.assertIn("len(employees) != len(ids)", bulk_source)
        self.assertIn("One or more employees are still in use.", bulk_source)

    def test_profile_image_changes_lock_rows_and_defer_file_deletion(self):
        for function_name in (
            "update_profile_image",
            "update_own_profile_image",
            "remove_profile_image",
            "remove_own_profile_image",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("Employee.objects.select_for_update()", source)
                self.assertIn("transaction.on_commit(", source)
                self.assertNotIn("os.remove(", source)

    def test_employee_note_mutations_are_exactly_scoped_and_locked(self):
        for function_name in (
            "add_note",
            "employee_note_update",
            "employee_note_delete",
            "add_more_employee_files",
            "delete_employee_note_file",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("_can_manage_employee(", source)

        file_delete = self._function_source("delete_employee_note_file")
        self.assertIn("file.employeenote_set", file_delete)
        self.assertIn("for note in notes", file_delete)

    def test_inline_employee_updates_lock_and_scope_the_target(self):
        for function_name in (
            "employee_create_update_personal_info",
            "employee_update_work_info",
            "employee_update_bank_details",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("Employee.objects.select_for_update()", source)
                self.assertIn("_can_manage_employee", source)
