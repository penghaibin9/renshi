"""Regression contracts for settings deletion endpoints."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class SettingsMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "base/views.py"
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

    def test_settings_deletes_are_post_only_atomic_and_locked(self):
        for function_name in (
            "delete_mail_templates",
            "mail_server_delete",
            "replace_primary_mail",
            "multiple_level_approval_delete",
            "action_type_delete",
            "holiday_delete",
            "company_leave_delete",
            "delete_penalities",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_bulk_schedule_mutations_are_post_only_atomic_and_locked(self):
        for function_name in (
            "rotating_work_type_assign_bulk_archive",
            "rotating_work_type_assign_bulk_delete",
            "rotating_shift_assign_bulk_archive",
            "rotating_shift_assign_bulk_delete",
            "work_type_request_bulk_cancel",
            "work_type_request_bulk_approve",
            "work_type_request_bulk_delete",
            "shift_request_bulk_cancel",
            "shift_request_bulk_approve",
            "shift_request_bulk_delete",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertNotIn("request.GET.get(\"is_active\")", source)

    def test_single_schedule_request_deletes_are_locked_and_authorized(self):
        for function_name, permission_name in (
            ("work_type_request_delete", "base.delete_worktyperequest"),
            ("shift_request_delete", "base.delete_shiftrequest"),
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn(permission_name, source)
                self.assertIn("is_reportingmanger(request", source)

    def test_dashboard_get_requests_do_not_create_preferences(self):
        for function_name in ("employee_chart_show", "reorder_dashboard_charts"):
            source = self._function_source(function_name)
            get_branch = source.split('if request.method == "POST":', 1)[0]
            self.assertNotIn("get_or_create", get_branch)
            self.assertIn("select_for_update()", source)

    def test_user_preferences_and_notifications_are_post_only_and_scoped(self):
        for function_name in (
            "clear_notification",
            "delete_all_notifications",
            "delete_notification",
            "mark_as_read_notification",
            "mark_as_read_notification_json",
            "read_notifications",
            "notification_sound",
            "driver_viewed_status",
            "dashboard_components_toggle",
            "activate_biometric_attendance",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("@transaction.atomic", source)
        self.assertIn(
            "request.user.notifications.select_for_update()",
            self._function_source("mark_as_read_notification"),
        )
        self.assertNotIn(
            "DriverForm(request.GET)", self._function_source("driver_viewed_status")
        )

    def test_company_group_removal_is_posted_atomic_and_locked(self):
        source = self._function_source("group_remove_user")
        self.assertIn('@require_http_methods(["POST"])', source)
        self.assertIn("@transaction.atomic", source)
        self.assertIn("Group.objects.select_for_update()", source)
        self.assertIn("HorillaUser.objects.select_for_update()", source)
        self.assertIn('request.POST.get("company_id")', source)
        self.assertNotIn("request.GET", source)

        template = (
            self.backend_dir
            / "horilla_theme/templates/base/auth/group_member_row.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("group-remove-user' user.id group.id %}?company_id=", template)
        self.assertIn("hx-vals='{\"company_id\":", template)

    def test_missing_work_information_never_grants_manager_access(self):
        source = self._function_source("is_reportingmanger")
        self.assertIn("return False", source)
        self.assertNotIn("return HttpResponse", source)

    def test_settings_templates_do_not_delete_with_get(self):
        roots = (
            self.backend_dir / "base/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertNotIn('hx-get="{% url \'multiple-level-approval-delete\'', combined)
        self.assertNotIn("hx-get='{% url \"multiple-level-approval-delete\"", combined)
        self.assertNotIn('href="{% url \'delete-mail-template\'', combined)
        self.assertNotIn("delete-mail-template' %}?ids=", combined)
        self.assertIn("hx-vals='{\"ids\":\"{{ template.id }}\"}'", combined)
        self.assertNotIn("bulk-archive/?is_active=", combined)
        self.assertNotIn("dashboard-components-toggle' %}?chart_id=", combined)
        self.assertNotIn("hx-get=\"{% url 'notification-sound'", combined)
        self.assertNotIn("hx-get=\"{% url 'read-notifications'", combined)

    def test_group_permission_and_generic_delete_lock_targets(self):
        group_update = self._function_source("update_group_permission")
        self.assertIn('@require_http_methods(["POST"])', group_update)
        self.assertIn("@transaction.atomic", group_update)
        self.assertIn("Group.objects.select_for_update()", group_update)
        self.assertIn("@superuser_required", group_update)

        generic_delete = self._function_source("object_delete")
        self.assertIn('@require_http_methods(["POST", "DELETE"])', generic_delete)
        self.assertIn("@transaction.atomic", generic_delete)
        self.assertIn("model.objects.select_for_update()", generic_delete)

    def test_rotating_assignment_deletes_are_complete_and_scoped(self):
        for function_name, model_name in (
            ("rotating_work_type_assign_bulk_delete", "RotatingWorkTypeAssign"),
            ("rotating_shift_assign_bulk_delete", "RotatingShiftAssign"),
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn(f"{model_name}.objects.select_for_update()", source)
                self.assertIn("len(assignments) != len(ids)", source)
                self.assertIn("transaction.set_rollback(True)", source)
                self.assertIn('"deleted": len(assignments)', source)

        shift_bulk = self._function_source("rotating_shift_assign_bulk_delete")
        self.assertIn("is_reportingmanger(request, assignment)", shift_bulk)

        for function_name, model_name in (
            ("rotating_work_type_assign_delete", "RotatingWorkTypeAssign"),
            ("rotating_shift_assign_delete", "RotatingShiftAssign"),
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn(f"{model_name}.objects.select_for_update()", source)

        shift_single = self._function_source("rotating_shift_assign_delete")
        self.assertIn("is_reportingmanger(request, rotating_shift_assign_obj)", shift_single)

    def test_bulk_id_parser_rejects_partial_or_oversized_payloads(self):
        source = self._function_source("_posted_json_ids")
        self.assertIn("len(values) > 500", source)
        self.assertIn("return []", source)
        self.assertIn("value <= 0 or value in ids", source)
        self.assertNotIn("continue", source)
