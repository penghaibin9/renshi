"""Contracts for HR10 approval mutation request parsing."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class Hr10MutationSecurityContractTests(SimpleTestCase):
    source_path = Path(__file__).resolve().parent / "api/requests.py"

    def test_session_api_modules_do_not_bypass_django_csrf_middleware(self):
        api_root = Path(__file__).resolve().parent / "api"
        public_modules = (
            "dashboard.py",
            "development_records.py",
            "enrollments.py",
            "imports.py",
            "plans.py",
            "practice.py",
            "practice_process.py",
            "programs.py",
            "requests.py",
            "workbench.py",
        )

        for module_name in public_modules:
            with self.subTest(module=module_name):
                source = (api_root / module_name).read_text(encoding="utf-8")
                self.assertNotIn("csrf_exempt", source)
                self.assertIn("require_hr10_permission", source)

        internal_source = (api_root / "internal.py").read_text(encoding="utf-8")
        self.assertIn("@csrf_exempt", internal_source)
        self.assertIn("@require_hr10_internal_service", internal_source)

    def test_approval_workflow_version_comes_from_the_post_body(self):
        source = self.source_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        node = next(
            item
            for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == "approve_request"
        )
        function_source = "".join(lines[node.lineno - 1 : node.end_lineno])
        self.assertIn('request.POST.get("workflowVersion"', function_source)
        self.assertIn("json.loads(request.body", function_source)
        self.assertNotIn("request.GET", function_source)

    def test_approval_service_relocks_and_validates_request_state(self):
        source = (
            Path(__file__).resolve().parent / "services/approval_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("HrTrainingRequest.objects.select_for_update()", source)
        self.assertGreaterEqual(source.count("ApprovalService._lock_request"), 3)
        self.assertGreaterEqual(source.count("ApprovalService._is_reviewable"), 3)
        self.assertIn("current_status = request_obj.lifecycle_status", source)
        self.assertIn("role=ApprovalService._role_for_status(current_status)", source)

    def test_submit_and_withdraw_lock_the_request_rows(self):
        source = self.source_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("submit_request", "withdraw_request"):
            with self.subTest(function=name):
                node = functions[name]
                first_line = min(
                    [node.lineno]
                    + [decorator.lineno for decorator in node.decorator_list]
                )
                function_source = "".join(lines[first_line - 1 : node.end_lineno])
                self.assertIn("@transaction.atomic", function_source)
                self.assertIn("select_for_update()", function_source)

    def test_self_approval_compares_matching_employee_identifiers(self):
        source = self.source_path.read_text(encoding="utf-8")
        self.assertIn("def _approver_employee_id", source)
        self.assertIn("request.user.employee_get.id", source)
        self.assertIn("approver_id = _approver_employee_id(request)", source)
        self.assertNotIn(
            "approver_id = request.user.id if request.user.is_authenticated else 0",
            source,
        )
