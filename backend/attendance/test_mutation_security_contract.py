"""Regression contracts for attendance approval and comment mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class AttendanceMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "attendance/views/views.py"
        if function_name in {
            "approve_validate_attendance_request",
            "cancel_attendance_request",
            "bulk_approve_attendance_request",
            "bulk_reject_attendance_request",
            "delete_batch",
        }:
            path = self.backend_dir / "attendance/views/requests.py"
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

    def test_attendance_mutators_are_post_only(self):
        for name in (
            "validate_this_attendance",
            "revalidate_this_attendance",
            "approve_overtime",
            "attendance_delete",
            "attendance_bulk_delete",
            "attendance_overtime_delete",
            "attendance_account_bulk_delete",
            "attendance_activity_delete",
            "attendance_activity_bulk_delete",
            "validate_bulk_attendance",
            "approve_bulk_overtime",
            "delete_allowed_ips",
            "bulk_approve_attendance_request",
            "bulk_reject_attendance_request",
            "delete_batch",
            "delete_attendancerequest_comment",
            "delete_comment_file",
            "approve_validate_attendance_request",
            "cancel_attendance_request",
        ):
            with self.subTest(function=name):
                self.assertIn(
                    '@require_http_methods(["POST"])', self._function_source(name)
                )

    def test_attendance_approvals_lock_rows(self):
        for name in (
            "validate_this_attendance",
            "revalidate_this_attendance",
            "approve_overtime",
            "attendance_delete",
            "attendance_bulk_delete",
            "attendance_overtime_delete",
            "attendance_account_bulk_delete",
            "attendance_activity_delete",
            "attendance_activity_bulk_delete",
            "validate_bulk_attendance",
            "approve_bulk_overtime",
            "delete_allowed_ips",
            "bulk_approve_attendance_request",
            "bulk_reject_attendance_request",
            "delete_batch",
            "approve_validate_attendance_request",
            "cancel_attendance_request",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_attendance_delete_updates_the_exact_month_balance_without_underflow(self):
        source = self._function_source("_subtract_approved_overtime")
        self.assertIn('year=str(attendance.attendance_date.year)', source)
        self.assertIn("max(0, total_seconds - attendance_seconds)", source)
        self.assertIn("overtime.overtime_second = remaining_seconds", source)
        for name in ("attendance_delete", "attendance_bulk_delete"):
            self.assertIn(
                "_subtract_approved_overtime(attendance)",
                self._function_source(name),
            )

    def test_bulk_attendance_actions_apply_row_level_authorization(self):
        for name in ("validate_bulk_attendance", "approve_bulk_overtime"):
            source = self._function_source(name)
            self.assertIn("is_reportingmanger(request, attendance)", source)
            self.assertIn('request.user.has_perm("attendance.change_attendance")', source)

        for name in (
            "bulk_approve_attendance_request",
            "bulk_reject_attendance_request",
        ):
            source = self._function_source(name)
            compact_source = "".join(source.split())
            self.assertIn(
                "_can_manage_attendance_request(request,attendance",
                compact_source,
            )
            self.assertIn("select_for_update()", source)

        reject_source = self._function_source("bulk_reject_attendance_request")
        self.assertIn("original_request_type = attendance.request_type", reject_source)
        self.assertIn('if original_request_type == "create_request":', reject_source)

    def test_bulk_deletes_and_overtime_approval_are_all_or_nothing(self):
        for name in (
            "attendance_bulk_delete",
            "attendance_account_bulk_delete",
            "attendance_activity_bulk_delete",
            "approve_bulk_overtime",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("len(", source)
                self.assertIn("len(ids)", source)
                self.assertIn("select_for_update()", source)
        approval = self._function_source("approve_bulk_overtime")
        self.assertIn("transaction.on_commit", approval)
        self.assertIn("if any(", approval)

    def test_missing_work_information_never_grants_reporting_manager_access(self):
        path = self.backend_dir / "attendance/methods/utils.py"
        source = path.read_text(encoding="utf-8")
        module_lines = source.splitlines(keepends=True)
        node = next(
            item
            for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == "is_reportingmanger"
        )
        function_source = "".join(module_lines[node.lineno - 1 : node.end_lineno])
        self.assertIn("return False", function_source)
        self.assertNotIn("return HttpResponse", function_source)

    def test_allowed_ip_delete_uses_posted_indices_and_row_lock(self):
        source = self._function_source("delete_allowed_ips")
        self.assertIn('@require_http_methods(["POST"])', source)
        self.assertIn("@transaction.atomic", source)
        self.assertIn('request.POST.getlist("id")', source)
        self.assertIn("select_for_update()", source)
        self.assertNotIn("request.GET.getlist", source)

    def test_comment_file_delete_is_scoped_to_comment_and_owner(self):
        source = self._function_source("delete_comment_file")
        self.assertIn("@transaction.atomic", source)
        self.assertIn('request.POST.get("request_id")', source)
        self.assertNotIn("request.GET", source)
        self.assertIn("select_for_update()", source)
        self.assertIn("request_id_id=request_id", source)
        self.assertIn("comment.files.select_for_update().filter(id__in=ids)", source)
        self.assertIn("comment.employee_id.employee_user_id_id", source)
        self.assertIn("attendancerequestcomment__isnull=True", source)

    def test_add_to_batch_posts_ids_and_rejects_out_of_scope_rows(self):
        source = self._function_source("attendance_add_to_batch")
        self.assertIn("@transaction.atomic", source)
        self.assertIn("ids = _posted_ids(request)", source)
        self.assertIn("BatchAttendance.objects.select_for_update()", source)
        self.assertIn("Attendance.objects.select_for_update()", source)
        self.assertIn("reporting_manager_id=request.user.employee_get", source)
        self.assertIn("attendances.count() != len(set(ids))", source)

    def test_templates_do_not_use_get_for_hardened_attendance_mutations(self):
        roots = (
            self.backend_dir / "attendance/templates",
            self.backend_dir / "employee/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        for fragment in (
            "hx-get=\"{% url 'validate-this-attendance'",
            'hx-get="{% url \'attendance-request-delete-comment\'',
            'hx-get="{% url \'delete-comment-file\'',
            "htmx.ajax('GET', '{% url 'validate-this-attendance'",
            'hx-get="{% url \'approve-validate-attendance-request\'',
            'hx-get="{% url \'cancel-validate-attendance-request\'',
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

        cancel_source = self._function_source("cancel_attendance_request")
        self.assertIn("original_request_type = attendance.request_type", cancel_source)
        self.assertIn('if original_request_type == "create_request":', cancel_source)

        ip_templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.backend_dir / "attendance/templates/attendance/ip_restriction").rglob("*.html")
        )
        self.assertNotIn("delete-allowed-ip' %}?id=", ip_templates)
        self.assertNotIn("hx-post=\"{% url 'edit-allowed-ip' %}?id=", ip_templates)

        attendance_templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.backend_dir / "attendance/templates").rglob("*.html")
        )
        self.assertNotIn("delete-comment-file' %}?", attendance_templates)
        self.assertIn("hx-vals='{\"ids\":\"{{ file.id }}\",\"request_id\":", attendance_templates)
        add_batch = (
            self.backend_dir
            / "attendance/templates/attendance/attendance/attendance_add_batch.html"
        ).read_text(encoding="utf-8")
        self.assertIn('name="ids" value="{{ attendance_id }}"', add_batch)
