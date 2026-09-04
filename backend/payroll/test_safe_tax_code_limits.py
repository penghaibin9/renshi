from pathlib import Path

from django.test import SimpleTestCase

from payroll.methods import federal_tax
from payroll.methods.safe_tax_code import (
    MAX_RANGE_ITEMS,
    TaxCodeValidationError,
    run_tax_code,
    validate_tax_code,
)


class SafeTaxCodeResourceLimitTests(SimpleTestCase):
    def test_shipped_formula_template_remains_executable(self):
        result = run_tax_code(federal_tax.CODE, 189_000.52)
        self.assertGreater(result, 0)

    def test_existing_finite_formula_remains_supported(self):
        code = """
def calculate_federal_tax(yearly_income):
    brackets = [0.1, 0.2]
    return sum(yearly_income * rate for rate in brackets)
"""
        self.assertEqual(run_tax_code(code, 100), 30)

    def test_unbounded_while_loop_is_rejected_before_execution(self):
        code = """
def calculate_federal_tax(yearly_income):
    while True:
        pass
"""
        with self.assertRaisesRegex(TaxCodeValidationError, "While"):
            validate_tax_code(code)

    def test_huge_range_is_stopped_by_runtime_budget(self):
        code = f"""
def calculate_federal_tax(yearly_income):
    return sum(range({MAX_RANGE_ITEMS + 1}))
"""
        with self.assertRaisesRegex(TaxCodeValidationError, "range exceeds"):
            run_tax_code(code, 100)

    def test_non_finite_result_is_rejected(self):
        code = """
def calculate_federal_tax(yearly_income):
    return float('nan')
"""
        with self.assertRaisesRegex(TaxCodeValidationError, "finite number"):
            run_tax_code(code, 100)

    def test_non_numeric_result_is_rejected(self):
        code = """
def calculate_federal_tax(yearly_income):
    return 'not-money'
"""
        with self.assertRaisesRegex(TaxCodeValidationError, "real number"):
            run_tax_code(code, 100)

    def test_tax_calculation_never_swallows_formula_errors_as_zero_tax(self):
        source = (
            Path(__file__).resolve().parent / "methods" / "tax_calc.py"
        ).read_text(encoding="utf-8")
        self.assertIn("federal_tax = run_tax_code", source)
        self.assertNotIn("except Exception as e", source)
