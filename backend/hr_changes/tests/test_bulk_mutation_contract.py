"""Atomicity and tenant-scope guards for HR06 bulk changes."""

import inspect

from django.test import SimpleTestCase

from hr_changes.api import bulk
from hr_changes.services.bulk_service import BulkService


class BulkMutationContractTests(SimpleTestCase):
    def test_create_validates_whole_staff_selection_before_write(self):
        source = inspect.getsource(bulk.create_bulk)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrStaffMaster.objects.select_for_update()", source)
        self.assertIn("len(staff) != len(staff_ids)", source)
        self.assertIn("HrBulkChangeItem.objects.bulk_create", source)
        self.assertNotIn("len(HrBulkChangeBatch.objects.filter", source)

    def test_payload_must_be_object_and_selection_is_bounded(self):
        self.assertIn("isinstance(value, dict)", inspect.getsource(bulk._body))
        source = inspect.getsource(bulk.create_bulk)
        self.assertIn("len(staff_ids) > 500", source)
        self.assertIn("len({str(value) for value in staff_ids})", source)

    def test_prevalidate_and_execute_lock_batch_in_transactions(self):
        prevalidate = inspect.getsource(BulkService.prevalidate)
        execute = inspect.getsource(BulkService.execute)

        self.assertIn("@transaction.atomic", prevalidate)
        self.assertIn("select_for_update()", prevalidate)
        self.assertIn("@transaction.atomic", execute)
        self.assertIn("select_for_update()", execute)
        self.assertIn("CHANGE_BULK_STATE_CONFLICT", execute)
