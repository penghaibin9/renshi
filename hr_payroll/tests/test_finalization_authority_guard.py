"""HR15 finalization must not mint ambiguous base payroll facts."""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.finalization_service import (
    PayrollFinalizationError,
    PayrollFinalizationService,
)


class PayrollFinalizationAuthorityGuardTests(TestCase):
    @patch.object(
        PayrollFinalizationService,
        "_time_source_snapshot",
        return_value={"providerVersion": "hr11-time-close-v1", "timeCloseSnapshotId": 101},
    )
    def test_duplicate_base_result_for_same_staff_fails_before_finalization(self, _snapshot):
        tenant_id = 79123
        staff_id = uuid.uuid4()
        period = PayrollPeriod.objects.create(
            tenant_id=tenant_id,
            period_code=f"DUP-{uuid.uuid4().hex}",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.REVIEWED,
        )
        results = []
        for suffix in ("A", "B"):
            results.append(
                PayrollResultFact.objects.create(
                    tenant_id=tenant_id,
                    result_no=f"DUP-{suffix}-{uuid.uuid4().hex}",
                    payroll_period_id=period.id,
                    staff_id=staff_id,
                    currency_code="CNY",
                    gross_amount=Decimal("10000.00"),
                    deduction_amount=Decimal("1200.00"),
                    net_amount=Decimal("8800.00"),
                    status=PayrollResultFact.Status.DRAFT,
                )
            )

        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(tenant_id).finalize_period(period.id)

        self.assertEqual(cm.exception.code, "PAYROLL_RESULT_DUPLICATE_STAFF")
        period.refresh_from_db()
        self.assertEqual(period.status, PayrollPeriod.Status.REVIEWED)
        for result in results:
            result.refresh_from_db()
            self.assertEqual(result.status, PayrollResultFact.Status.DRAFT)
