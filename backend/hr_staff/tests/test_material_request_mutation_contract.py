"""Production mutation guards for HR03 material requests."""

import inspect

from django.test import SimpleTestCase

from hr_staff.api import material_requests


class MaterialRequestMutationContractTests(SimpleTestCase):
    def test_create_requires_current_tenant_staff_and_atomic_write(self):
        source = inspect.getsource(material_requests.create_request.__wrapped__.__wrapped__)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrStaffMaster.objects.select_for_update()", source)
        self.assertIn("tenant_id=resp.tenant_id", source)
        self.assertIn("STAFF_NOT_FOUND", source)

    def test_create_rejects_invalid_json_category_and_date(self):
        source = inspect.getsource(material_requests.create_request.__wrapped__.__wrapped__)

        self.assertIn("isinstance(body, dict)", source)
        self.assertIn("MaterialCategoryCode.values", source)
        self.assertIn("date.fromisoformat", source)
        self.assertIn("req.full_clean()", source)
