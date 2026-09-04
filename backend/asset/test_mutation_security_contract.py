"""Regression contracts for asset inventory and request mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class AssetMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "asset/views.py"
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

    def test_destructive_asset_mutators_are_post_only(self):
        for name in (
            "asset_delete",
            "delete_asset_category",
            "asset_request_reject",
            "asset_allocate_return_request",
            "asset_batch_number_delete",
        ):
            with self.subTest(function=name):
                self.assertIn(
                    '@require_http_methods(["POST"])', self._function_source(name)
                )

    def test_asset_approval_serializes_and_rechecks_inventory(self):
        source = self._function_source("asset_request_approve")
        self.assertIn("with transaction.atomic():", source)
        self.assertGreaterEqual(source.count("select_for_update()"), 2)
        self.assertIn('asset_request.asset_request_status != "Requested"', source)
        self.assertIn("active_count >= asset.quantity", source)
        self.assertIn("asset_category_id=asset_request.asset_category_id", source)
        self.assertNotIn('str(e)', source)

    def test_reject_and_return_are_idempotent_and_locked(self):
        reject = self._function_source("asset_request_reject")
        self.assertIn("@transaction.atomic", reject)
        self.assertIn("select_for_update()", reject)
        self.assertIn('asset_request.asset_request_status != "Requested"', reject)

        returned = self._function_source("asset_allocate_return_request")
        self.assertIn("@transaction.atomic", returned)
        self.assertIn("select_for_update()", returned)
        self.assertIn("asset_assign.return_date or asset_assign.return_request", returned)

        processed_return = self._function_source("asset_allocate_return")
        self.assertIn("AssetAssignment.objects.select_for_update()", processed_return)
        self.assertIn("Asset.objects.select_for_update()", processed_return)
        self.assertIn("pk=asset_id", processed_return)
        self.assertIn("return_date__isnull=True", processed_return)
        self.assertIn("asset.quantity = max(0, asset.quantity - 1)", processed_return)

    def test_direct_allocation_rechecks_inventory_under_lock(self):
        source = self._function_source("asset_allocate_creation")
        self.assertIn('AssetAllocationForm(request.POST, request.FILES)', source)
        self.assertIn("with transaction.atomic():", source)
        self.assertIn("Asset.objects.select_for_update()", source)
        self.assertIn("active_count >= asset.quantity", source)
        self.assertIn(
            "instance.assigned_by_employee_id = request.user.employee_get", source
        )

        forms_source = (self.backend_dir / "asset/forms.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"return_status",', forms_source)
        self.assertIn('"return_request",', forms_source)
        self.assertIn("return_date < self.instance.assigned_date", forms_source)

    def test_templates_use_post_for_asset_reject_and_return_request(self):
        roots = (
            self.backend_dir / "asset/templates",
            self.backend_dir / "employee/templates",
            self.backend_dir / "horilla_theme/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in roots
            for path in root.rglob("*.html")
        )
        self.assertNotIn(
            'hx-get="{% url \'asset-request-reject\'', combined
        )
        self.assertNotIn(
            'hx-get="{% url \'asset-allocate-return-request\'', combined
        )
        self.assertNotIn(
            "asset-allocate-return'  asset_id=asset_allocation.asset_id.id", combined
        )
        self.assertNotIn(
            "asset-allocate-return' asset_id=instance.asset_id.id", combined
        )
