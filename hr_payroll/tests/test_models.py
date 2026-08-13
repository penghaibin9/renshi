import uuid
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact


class Hr15ModelContractTests(SimpleTestCase):
    def test_period_has_explicit_finalization_states(self):
        assert "FINALIZED" in PayrollPeriod.Status.values
        assert "CLOSED" in PayrollPeriod.Status.values

    def test_payroll_amounts_are_decimal_fields(self):
        assert PayrollResultFact._meta.get_field("gross_amount").get_internal_type() == "DecimalField"
        assert PayrollResultFact._meta.get_field("net_amount").get_internal_type() == "DecimalField"
        fact = PayrollResultFact(gross_amount=Decimal("100.01"), net_amount=Decimal("90.01"))
        assert fact.gross_amount == Decimal("100.01")

    def test_profile_does_not_store_raw_bank_account_field(self):
        names = {field.name for field in PayrollProfile._meta.fields}
        assert "bank_account" not in names
        assert "payment_account_ref" in names

    def test_tenant_is_fail_closed_before_database_write(self):
        period = PayrollPeriod(
            tenant_id=None,
            period_code="2026-08",
            start_date="2026-08-01",
            end_date="2026-09-01",
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            period.save()


class Hr15FinalFactImmutabilityTests(TestCase):
    def _draft_fact(self):
        return PayrollResultFact.objects.create(
            tenant_id=1,
            result_no="PAY-202608-T001",
            payroll_period_id=uuid.uuid4(),
            staff_id=uuid.uuid4(),
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("2000.00"),
            net_amount=Decimal("8000.00"),
            status=PayrollResultFact.Status.DRAFT,
        )

    def test_draft_can_cross_finalization_boundary_once(self):
        fact = self._draft_fact()
        fact.status = PayrollResultFact.Status.FINALIZED
        fact.save(update_fields=["status", "updated_at"])
        fact.refresh_from_db()
        self.assertEqual(fact.status, PayrollResultFact.Status.FINALIZED)

    def test_finalized_fact_amount_cannot_be_overwritten(self):
        fact = self._draft_fact()
        fact.status = PayrollResultFact.Status.FINALIZED
        fact.save(update_fields=["status", "updated_at"])

        fact.net_amount = Decimal("7999.99")
        with self.assertRaisesRegex(ValueError, "PAYROLL_FINAL_RESULT_IMMUTABLE"):
            fact.save(update_fields=["net_amount", "updated_at"])

        persisted = PayrollResultFact.objects.get(pk=fact.pk)
        self.assertEqual(persisted.net_amount, Decimal("8000.00"))

    def test_finalized_fact_cannot_be_relabelled_as_adjusted(self):
        fact = self._draft_fact()
        fact.status = PayrollResultFact.Status.FINALIZED
        fact.save(update_fields=["status", "updated_at"])

        fact.status = PayrollResultFact.Status.ADJUSTED
        with self.assertRaisesRegex(ValueError, "PAYROLL_FINAL_RESULT_IMMUTABLE"):
            fact.save(update_fields=["status", "updated_at"])
