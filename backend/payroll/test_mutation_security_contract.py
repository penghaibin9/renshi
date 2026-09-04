"""Regression contracts for payroll balance and destructive mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class PayrollMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, relative_path, function_name):
        path = self.backend_dir / relative_path
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

    def test_payroll_mutators_are_post_only(self):
        functions = (
            ("payroll/views/component_views.py", "delete_loan"),
            ("payroll/views/component_views.py", "approve_reimbursements"),
            ("payroll/views/component_views.py", "delete_reimbursements"),
            ("payroll/views/component_views.py", "delete_allowance"),
            ("payroll/views/component_views.py", "delete_deduction"),
            ("payroll/views/component_views.py", "delete_attachments"),
            ("payroll/views/views.py", "delete_payrollrequest_comment"),
            ("payroll/views/views.py", "delete_reimbursement_comment_file"),
            ("payroll/views/views.py", "delete_auto_payslip"),
            ("payroll/views/views.py", "contract_status_update"),
            ("payroll/views/views.py", "bulk_contract_status_update"),
            ("payroll/views/views.py", "update_contract_filing_status"),
            ("payroll/views/views.py", "contract_delete"),
            ("payroll/views/views.py", "update_payslip_status"),
            ("payroll/views/views.py", "update_payslip_status_no_id"),
            ("payroll/views/views.py", "initial_notice_period"),
            ("payroll/views/views.py", "delete_payslip"),
            ("payroll/views/views.py", "payslip_bulk_delete"),
            ("payroll/views/views.py", "contract_bulk_delete"),
        )
        for path, name in functions:
            with self.subTest(function=name):
                source = self._function_source(path, name)
                self.assertTrue(
                    '@require_http_methods(["POST"])' in source
                    or "@require_POST" in source,
                    f"{name} must reject GET mutations",
                )

    def test_contract_and_payslip_status_updates_are_atomic_and_validated(self):
        functions = (
            "contract_status_update",
            "bulk_contract_status_update",
            "update_contract_filing_status",
            "contract_delete",
            "update_payslip_status",
            "update_payslip_status_no_id",
        )
        for name in functions:
            with self.subTest(function=name):
                source = self._function_source("payroll/views/views.py", name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        contract_bulk = self._function_source(
            "payroll/views/views.py", "bulk_contract_status_update"
        )
        self.assertIn("status not in dict(Contract.CONTRACT_STATUS_CHOICES)", contract_bulk)
        self.assertIn(".exclude(pk__in=ids)", contract_bulk)

        payslip_bulk = self._function_source(
            "payroll/views/views.py", "update_payslip_status_no_id"
        )
        self.assertIn("status not in dict(Payslip.status_choices)", payslip_bulk)
        self.assertIn("slips.count() != len(ids)", payslip_bulk)

    def test_payroll_bulk_deletes_are_locked_and_all_or_nothing(self):
        for name, model_name in (
            ("payslip_bulk_delete", "Payslip"),
            ("contract_bulk_delete", "Contract"),
        ):
            with self.subTest(function=name):
                source = self._function_source("payroll/views/views.py", name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn(f"{model_name}.objects.select_for_update()", source)
                self.assertIn("!= len(ids)", source)
                self.assertIn("transaction.set_rollback(True)", source)

        contract_status = self._function_source(
            "payroll/views/views.py", "bulk_contract_status_update"
        )
        self.assertIn("len(contracts) != len(ids)", contract_status)
        self.assertIn("duplicate_employees", contract_status)
        self.assertIn("external_conflict", contract_status)

    def test_notice_period_is_posted_locked_and_company_scoped(self):
        source = self._function_source(
            "payroll/views/views.py", "initial_notice_period"
        )
        self.assertIn("request.POST", source)
        self.assertNotIn("request.GET", source)
        self.assertIn("@transaction.atomic", source)
        self.assertIn("select_for_update()", source)
        self.assertIn('request.session.get("selected_company")', source)
        self.assertIn(".filter(company=company)", source)

        for path in (
            "payroll/templates/payroll/settings/settings.html",
            "horilla_theme/templates/payroll/settings/settings.html",
        ):
            template = (self.backend_dir / path).read_text(encoding="utf-8")
            self.assertIn("hx-post=", template)
            self.assertNotIn("hx-get=", template)

    def test_reimbursement_approval_locks_balance_rows(self):
        source = self._function_source(
            "payroll/views/component_views.py", "approve_reimbursements"
        )
        self.assertIn("@transaction.atomic", source)
        self.assertGreaterEqual(source.count("select_for_update()"), 3)
        self.assertIn('status not in {"approved", "rejected"}', source)
        self.assertIn("math.isfinite(amount)", source)

    def test_loan_delete_limits_and_validates_ids(self):
        source = self._function_source(
            "payroll/views/component_views.py", "delete_loan"
        )
        self.assertIn("len(ids) > 500", source)
        self.assertIn("int(value) <= 0", source)

    def test_rejected_encashments_restore_leave_and_bonus_balances(self):
        source = (self.backend_dir / "payroll/models/models.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('self.type == "leave_encashment"', source)
        self.assertNotIn('self.type == "leave encashment"', source)
        self.assertIn('elif self.type == "bonus_encashment":', source)
        self.assertIn("bonus_points.points += self.bonus_to_encash", source)

    def test_comment_file_delete_is_scoped_to_its_comment(self):
        source = self._function_source(
            "payroll/views/views.py", "delete_reimbursement_comment_file"
        )
        self.assertIn("comment.files.select_for_update().filter(id__in=ids)", source)
        self.assertIn("comment.files.remove(*records)", source)
        self.assertIn("reimbursementrequestcomment__isnull=True", source)
        self.assertIn("request.POST", source)
        self.assertIn("@transaction.atomic", source)

        for path in (
            "payroll/templates/payroll/reimbursement/reimbursement_comment.html",
            "horilla_theme/templates/payroll/reimbursement/reimbursement_comment.html",
        ):
            template = (self.backend_dir / path).read_text(encoding="utf-8")
            self.assertNotIn("delete-reimbursement-comment-file' %}?", template)
            self.assertIn("hx-vals=", template)

    def test_reimbursement_attachment_delete_is_parent_scoped_and_locked(self):
        source = self._function_source(
            "payroll/views/component_views.py", "delete_attachments"
        )
        self.assertIn("transaction.atomic()", source)
        self.assertIn("Reimbursement.objects.select_for_update()", source)
        self.assertIn(
            "reimbursement.other_attachments.select_for_update()", source
        )
        self.assertIn("reimbursement.other_attachments.remove(*attachments)", source)
        self.assertNotIn("request.GET.getlist", source)

        template = (
            self.backend_dir
            / "payroll/templates/payroll/reimbursement/attachments.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('href="{% url \'delete-attachments\'', template)
        self.assertIn('method="post"', template)
        self.assertIn("{% csrf_token %}", template)

    def test_allowance_and_deduction_delete_are_atomic_and_locked(self):
        for function_name in ("delete_allowance", "delete_deduction"):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "payroll/views/component_views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertNotIn('request.META.get("HTTP_REFERER"', source)
