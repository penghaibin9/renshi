from decimal import Decimal

from django.test import SimpleTestCase

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
