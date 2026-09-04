"""Regression contracts for leave approval and destructive endpoints."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class LeaveMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "leave/views.py"
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

    def test_leave_mutators_are_post_only(self):
        names = (
            "leave_type_delete",
            "leave_request_delete",
            "leave_request_approve",
            "leave_assign_delete",
            "restrict_delete",
            "restrict_days_bulk_delete",
            "user_request_delete",
            "leave_allocation_request_approve",
            "leave_allocation_request_delete",
            "delete_allocationrequest_comment",
            "delete_allocation_comment_file",
            "delete_leaverequest_comment",
            "delete_leave_comment_file",
            "delete_compensatory_leave",
            "approve_compensatory_leave",
            "delete_comment_compensatory_file",
            "delete_leaverequest_compensatory_comment",
            "leave_request_bulk_approve",
            "leave_bulk_reject",
            "leave_type_condition_delete",
        )
        for name in names:
            with self.subTest(function=name):
                self.assertIn(
                    '@require_http_methods(["POST"])', self._function_source(name)
                )

    def test_balance_changing_approvals_are_atomic_and_lock_rows(self):
        for name in (
            "leave_request_approve",
            "leave_allocation_request_approve",
            "leave_request_bulk_approve",
            "leave_bulk_reject",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_leave_decisions_are_scoped_to_the_target_request(self):
        module_source = (self.backend_dir / "leave/views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _can_decide_leave_request", module_source)
        self.assertIn("leave_request.employee_id_id == actor.id", module_source)
        self.assertIn("work_info.reporting_manager_id_id == actor.id", module_source)
        self.assertIn("approvals.filter(manager_id=actor).exists()", module_source)

        for name in (
            "leave_request_approve",
            "leave_request_bulk_approve",
            "leave_bulk_reject",
            "leave_request_cancel",
        ):
            with self.subTest(function=name):
                self.assertIn(
                    "_can_decide_leave_request", self._function_source(name)
                )

    def test_multi_step_approval_enforces_sequence_and_locks_decision(self):
        source = self._function_source("leave_request_approve")
        self.assertIn("LeaveRequestConditionApproval.objects.select_for_update()", source)
        self.assertIn("sequence__lt=condition_approval.sequence", source)
        self.assertIn("is_approved=False", source)

    def test_rejection_and_employee_cancellation_lock_balance_state(self):
        reject = self._function_source("leave_request_cancel")
        self.assertIn("@transaction.atomic", reject)
        self.assertIn("queryset.select_for_update()", reject)
        self.assertIn("AvailableLeave.objects.select_for_update()", reject)
        self.assertIn("transaction.on_commit", reject)

        employee_cancel = self._function_source("user_leave_cancel")
        self.assertIn("@transaction.atomic", employee_cancel)
        self.assertIn("queryset.select_for_update()", employee_cancel)
        self.assertIn("employee_user_id.id == request.user.id", employee_cancel)
        self.assertIn("transaction.on_commit", employee_cancel)

    def test_leave_templates_do_not_use_get_for_hardened_mutations(self):
        roots = (
            self.backend_dir / "leave/templates",
            self.backend_dir / "employee/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        for fragment in (
            'hx-get="{% url \'leave-request-delete-comment\'',
            'hx-get="{% url \'allocation-request-delete-comment\'',
            'hx-get="{% url \'delete-leave-comment-file\'',
            'hx-get="{% url \'delete-allocation-comment-file\'',
            'hx-get="{% url \'request-delete\'',
            'hx-get="{% url \'request-approve\'',
            'href="{% url \'request-approve\'',
            'href="{% url \'type-delete\'',
            'hx-get="{% url \'compensatory-request-delete-comment\'',
            'hx-get="{% url \'delete-compensatory-comment-file\'',
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

    def test_comment_file_deletes_are_scoped_to_the_parent_comment(self):
        source = (self.backend_dir / "leave/views.py").read_text(encoding="utf-8")
        self.assertIn("def _delete_scoped_leave_comment_files", source)
        self.assertIn("comment.files.select_for_update().filter(id__in=ids)", source)
        self.assertIn("comment.files.remove(*files)", source)
        for function_name in (
            "delete_allocation_comment_file",
            "delete_leave_comment_file",
            "delete_comment_compensatory_file",
        ):
            with self.subTest(function=function_name):
                function_source = self._function_source(function_name)
                self.assertIn("transaction.atomic", function_source)
                self.assertIn("_delete_scoped_leave_comment_files", function_source)
                self.assertIn("request.POST", function_source)
                self.assertNotIn("request.GET", function_source)

        for function_name in (
            "delete_allocation_comment_file",
            "delete_leave_comment_file",
        ):
            function_source = self._function_source(function_name)
            self.assertIn("request_id_id=leave_id", function_source)
            self.assertIn("_is_direct_reporting_manager", function_source)

    def test_comment_file_templates_post_identifiers_in_the_body(self):
        roots = (
            self.backend_dir / "leave/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        for endpoint in (
            "delete-allocation-comment-file",
            "delete-leave-comment-file",
            "delete-compensatory-comment-file",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertNotIn(f"{endpoint}' %}}?", combined)
        self.assertGreaterEqual(combined.count("hx-vals='{\"ids\":"), 5)

    def test_leave_comment_models_are_tenant_scoped(self):
        source = (self.backend_dir / "leave/models.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count(
                'related_company_field="request_id__employee_id__employee_work_info__company_id"'
            ),
            3,
        )

    def test_restricted_days_and_conditions_delete_exact_locked_rows(self):
        for name in (
            "restrict_delete",
            "restrict_days_bulk_delete",
            "leave_type_condition_delete",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        bulk_source = self._function_source("restrict_days_bulk_delete")
        self.assertIn("restrict_days.count() != len(restrict_day_ids)", bulk_source)
        self.assertIn("transaction.set_rollback(True)", bulk_source)

        condition_source = self._function_source("leave_type_condition_delete")
        self.assertIn("leavetype__id=leave_type.id", condition_source)
        self.assertIn("condition.leavetype_set.exists()", condition_source)

    def test_allocation_reject_and_delete_lock_balance_state(self):
        reject_source = self._function_source("leave_allocation_request_reject")
        self.assertIn("@transaction.atomic", reject_source)
        self.assertIn("allocation_queryset.select_for_update()", reject_source)
        self.assertIn("AvailableLeave.objects.select_for_update()", reject_source)
        self.assertIn("_notify_after_commit", reject_source)

        approve_source = self._function_source("leave_allocation_request_approve")
        self.assertIn("_notify_after_commit", approve_source)

        delete_source = self._function_source("leave_allocation_request_delete")
        self.assertIn("@transaction.atomic", delete_source)
        self.assertIn("select_for_update()", delete_source)
        self.assertIn("transaction.set_rollback(True)", delete_source)

    def test_leave_and_assignment_deletes_are_atomic_and_locked(self):
        for name in (
            "leave_type_delete",
            "leave_request_delete",
            "leave_assign_delete",
            "leave_assign_bulk_delete",
            "user_request_delete",
            "leave_request_bulk_delete",
            "user_request_bulk_delete",
            "delete_compensatory_leave",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        manager_delete = self._function_source("leave_request_delete")
        self.assertIn("_can_decide_leave_request", manager_delete)
        assignment_delete = self._function_source("leave_assign_delete")
        self.assertIn("_is_direct_reporting_manager", assignment_delete)
        own_delete = self._function_source("user_request_delete")
        self.assertIn("employee_id=request.user.employee_get", own_delete)

    def test_leave_bulk_deletes_validate_the_complete_selection(self):
        for name in (
            "leave_assign_bulk_delete",
            "leave_request_bulk_delete",
            "user_request_bulk_delete",
        ):
            with self.subTest(function=name):
                source = self._function_source(name)
                self.assertIn("_posted_ids(request)", source)
                self.assertIn("!= len(ids)", source)
                self.assertIn("transaction.set_rollback(True)", source)

        manager_bulk = self._function_source("leave_request_bulk_delete")
        self.assertIn("_can_decide_leave_request", manager_bulk)
        self.assertIn('status != "requested"', manager_bulk)

        own_bulk = self._function_source("user_request_bulk_delete")
        self.assertIn("employee_id=request.user.employee_get", own_bulk)
        self.assertIn('exclude(status="requested")', own_bulk)
