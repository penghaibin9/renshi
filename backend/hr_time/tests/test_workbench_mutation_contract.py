"""Atomicity and idempotency guards for HR11 workbench writes."""

import inspect

from django.test import SimpleTestCase

from hr_time.api import workbench
from hr_time.services.leave_account_service import LeaveAccountService


class WorkbenchMutationContractTests(SimpleTestCase):
    def test_account_provision_is_atomic_locked_and_decimal_safe(self):
        source = inspect.getsource(workbench.provision_leave_account)

        self.assertIn("Decimal(str(payload.get", source)
        self.assertIn("amount.is_finite()", source)
        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrStaffMaster.objects.select_for_update()", source)
        self.assertIn("HrLeavePolicyPack.objects.select_for_update()", source)

    def test_leave_and_close_creation_lock_business_scope(self):
        leave_source = inspect.getsource(workbench.create_leave)
        close_source = inspect.getsource(workbench.create_close_period)

        self.assertIn("HrLeaveAccount.objects.select_for_update()", leave_source)
        self.assertIn("HrTimeClosePeriod.objects.select_for_update()", close_source)
        self.assertIn("tenant_id=ctx.tenant_id", leave_source)
        self.assertIn("tenant_id=ctx.tenant_id", close_source)

    def test_ledger_grant_is_idempotent_for_business_source(self):
        source = inspect.getsource(LeaveAccountService.grant)

        self.assertIn("source_type=source_type", source)
        self.assertIn("source_id=source_id", source)
        self.assertIn("LEDGER_SOURCE_CONFLICT", source)
        self.assertIn("return existing", source)
