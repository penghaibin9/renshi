"""Executable without Django. These tests do NOT certify MySQL/API integration."""
import ast
from datetime import date, datetime
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[2]

def load(name, relative):
    spec=importlib.util.spec_from_file_location(name, ROOT/relative)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
rules=load("round2_flex_rules", "backend/hr_exit/services/flex_rules.py")
commands=load("round2_command_contract", "backend/hr_self/command_contract.py")
catalog=load("round2_operational_catalog", "backend/hr_data/operational_catalog.py")

class CalendarTests(unittest.TestCase):
    def test_month_end(self): self.assertEqual(rules.add_months(date(2026,1,31),1),date(2026,2,28))
    def test_leap_month_end(self): self.assertEqual(rules.add_months(date(2028,1,31),1),date(2028,2,29))
    def test_negative_months(self): self.assertEqual(rules.add_months(date(2028,2,29),-12),date(2027,2,28))
    def test_reject_datetime(self):
        with self.assertRaises(rules.FlexRuleError): rules.add_months(datetime(2026,1,1),1)
    def test_reject_bool(self):
        with self.assertRaises(rules.FlexRuleError): rules.add_months(date(2026,1,1),True)
    def test_year_overflow(self):
        with self.assertRaises(rules.FlexRuleError): rules.add_months(date(9999,12,1),1)
    def test_year_underflow(self):
        with self.assertRaises(rules.FlexRuleError): rules.add_months(date(1,1,1),-1)

class ChoiceTests(unittest.TestCase):
    def check(self, **changes):
        values=dict(mode="EARLY", requested_date=date(2027,6,1), statutory_date=date(2028,6,1),
            original_minimum_date=date(2026,6,1), notice_date=date(2027,3,1), today=date(2027,3,1))
        values.update(changes);return rules.validate_choice(**values)
    def denied(self, code, **changes):
        with self.assertRaises(rules.FlexRuleError) as exc:self.check(**changes)
        self.assertEqual(exc.exception.code,code)
    def test_early_exact_notice(self):self.check()
    def test_notice_one_day_late(self):self.denied("FLEX_NOTICE_TOO_LATE",notice_date=date(2027,3,2),today=date(2027,3,2))
    def test_early_below_original(self):self.denied("FLEX_EARLY_RANGE",requested_date=date(2026,5,31),today=date(2026,1,1),notice_date=date(2026,1,1))
    def test_early_more_than_three_years(self):self.denied("FLEX_EARLY_RANGE",requested_date=date(2025,5,31),original_minimum_date=date(2024,1,1),today=date(2025,1,1),notice_date=date(2025,1,1))
    def test_early_same_as_statutory(self):self.denied("FLEX_EARLY_RANGE",requested_date=date(2028,6,1))
    def test_delay_exact_three_years(self):self.check(mode="DELAY",requested_date=date(2031,6,1))
    def test_delay_three_years_one_day(self):self.denied("FLEX_DELAY_RANGE",mode="DELAY",requested_date=date(2031,6,2))
    def test_delay_exact_notice(self):self.check(mode="DELAY",requested_date=date(2029,1,1),notice_date=date(2028,5,1),today=date(2028,5,1))
    def test_delay_notice_late(self):self.denied("FLEX_AGREEMENT_TOO_LATE",mode="DELAY",requested_date=date(2029,1,1),notice_date=date(2028,5,2),today=date(2028,5,2))
    def test_future_notice(self):self.denied("FLEX_DATE_INVALID",notice_date=date(2027,3,2))
    def test_past_retirement(self):self.denied("FLEX_PAST_DATE_FORBIDDEN",today=date(2027,6,2))
    def test_unknown_mode(self):self.denied("FLEX_MODE_INVALID",mode="FREEFORM")
    def test_end_delay_no_invented_one_month_notice(self):self.check(mode="END_DELAY",requested_date=date(2028,7,2),parent_date=date(2029,1,1),today=date(2028,7,1),notice_date=date(2028,7,1))
    def test_end_delay_before_statutory(self):self.denied("FLEX_END_DELAY_RANGE",mode="END_DELAY",requested_date=date(2028,5,31),parent_date=date(2029,1,1))
    def test_end_delay_cannot_extend(self):self.denied("FLEX_END_DELAY_RANGE",mode="END_DELAY",requested_date=date(2030,1,1),parent_date=date(2029,1,1))
    def test_end_delay_must_be_in_delay_period(self):self.denied("FLEX_END_DELAY_NOT_ACTIVE",mode="END_DELAY",requested_date=date(2028,7,1),parent_date=date(2029,1,1))
    def test_calendar_three_months_not_90_days(self):self.check(requested_date=date(2027,4,30),notice_date=date(2027,1,31),today=date(2027,1,31))

class ApprovalTests(unittest.TestCase):
    def check(self, **changes):
        values=dict(mode="DELAY",requested_date=date(2030,7,1),statutory_date=date(2029,7,1),
            capacity="PUBLIC_TECHNICAL",contribution_months=180,agreement_date=date(2029,5,1),
            today=date(2029,5,2),has_approval_evidence=True,has_contribution_evidence=True,has_agreement_evidence=True)
        values.update(changes);return rules.validate_approval(**values)
    def denied(self,code,**changes):
        with self.assertRaises(rules.FlexRuleError) as exc:self.check(**changes)
        self.assertEqual(exc.exception.code,code)
    def test_delay_uses_statutory_year(self):self.assertEqual(self.check()["requiredContributionMonths"],180)
    def test_early_uses_selected_year(self):self.denied("FLEX_CONTRIBUTION_INSUFFICIENT",mode="EARLY",statutory_date=date(2031,7,1))
    def test_2030_boundary(self):self.assertEqual(rules.minimum_contribution_months(2030),186)
    def test_2039_cap(self):self.assertEqual(rules.minimum_contribution_months(2039),240)
    def test_long_term_cap(self):self.assertEqual(rules.minimum_contribution_months(2099),240)
    def test_old_year_not_supported(self):
        with self.assertRaises(rules.FlexRuleError):rules.minimum_contribution_months(2024)
    def test_leader_cannot_delay(self):self.denied("FLEX_DELAY_EXCLUDED",capacity="PUBLIC_LEADER")
    def test_management_cannot_delay(self):self.denied("FLEX_DELAY_EXCLUDED",capacity="PUBLIC_MANAGEMENT")
    def test_civil_servant_cannot_delay(self):self.denied("FLEX_DELAY_EXCLUDED",capacity="CIVIL_SERVANT")
    def test_no_user_asserted_capacity(self):self.denied("FLEX_CAPACITY_REQUIRED",capacity="SELF")
    def test_bool_not_month_count(self):self.denied("FLEX_CONTRIBUTION_INVALID",contribution_months=True)
    def test_fraction_not_month_count(self):self.denied("FLEX_CONTRIBUTION_INVALID",contribution_months=180.5)
    def test_missing_pension_document(self):self.denied("FLEX_REVIEW_EVIDENCE_REQUIRED",has_contribution_evidence=False)
    def test_missing_authority_document(self):self.denied("FLEX_REVIEW_EVIDENCE_REQUIRED",has_approval_evidence=False)
    def test_missing_bilateral_document(self):self.denied("FLEX_AGREEMENT_REQUIRED",has_agreement_evidence=False)
    def test_agreement_future(self):self.denied("FLEX_AGREEMENT_DATE_INVALID",agreement_date=date(2029,5,3))
    def test_agreement_late(self):self.denied("FLEX_AGREEMENT_TOO_LATE",agreement_date=date(2029,6,2),today=date(2029,6,2))
    def test_approval_invalid_mode(self):self.denied("FLEX_MODE_INVALID",mode="UNKNOWN")

class SelfCommandTests(unittest.TestCase):
    def test_staff_override_is_rejected(self):
        with self.assertRaises(commands.CommandError) as exc:commands.check_object({"staffId":"x"},{"staffId"})
        self.assertEqual(exc.exception.status,403)
    def test_all_identity_aliases_rejected(self):
        for field in commands.IDENTITY_KEYS:
            with self.subTest(field=field),self.assertRaises(commands.CommandError):commands.check_object({field:"x"},{field})
    def test_unknown_fields_rejected(self):
        with self.assertRaises(commands.CommandError):commands.check_object({"approved":True},{"reason"})
    def test_nested_identity_rejected(self):
        with self.assertRaises(commands.CommandError):commands.check_object({"personId":"x"},{"fieldCode","newValue"})
    def test_list_not_object(self):
        with self.assertRaises(commands.CommandError):commands.check_object([],{"reason"})
    def test_version_bool_rejected(self):
        with self.assertRaises(commands.CommandError):commands.expected_version(True)
    def test_version_string_rejected(self):
        with self.assertRaises(commands.CommandError):commands.expected_version("1")
    def test_version_positive(self):self.assertEqual(commands.expected_version(2),2)
    def test_key_path_injection(self):
        with self.assertRaises(commands.CommandError):commands.idempotency_key("../../bad/key")
    def test_key_valid(self):self.assertEqual(commands.idempotency_key("request-1234"),"request-1234")
    def test_key_missing(self):
        with self.assertRaises(commands.CommandError):commands.idempotency_key(None)
    def test_key_too_long(self):
        with self.assertRaises(commands.CommandError):commands.idempotency_key("a"*129)
    def test_hash_order_independent(self):self.assertEqual(commands.command_hash({"a":1,"b":2}),commands.command_hash({"b":2,"a":1}))
    def test_hash_changes_when_payload_changes(self):self.assertNotEqual(commands.command_hash({"a":1}),commands.command_hash({"a":2}))
    def test_no_payroll_or_contract_self_write(self):self.assertFalse({"staff.staff_no","assignment.position","payroll.net_amount","identity.document_number"}&commands.SELF_FIELDS.keys())

class SourceContractTests(unittest.TestCase):
    def test_missing_is_not_zero(self):self.assertIsNone(catalog.source_result("HR16","x","x",status="UNAVAILABLE")["value"])
    def test_error_ignores_fake_groups(self):self.assertIsNone(catalog.source_result("HR16","x","x",status="ERROR",groups=[{"state":"OK","count":5}])["value"])
    def test_real_empty_is_zero(self):self.assertEqual(catalog.source_result("HR16","x","x",status="OK",groups=[])["value"],0)
    def test_real_count(self):self.assertEqual(catalog.source_result("HR16","x","x",status="OK",groups=[{"state":"DRAFT","count":3},{"state":"DONE","count":4}])["value"],7)
    def test_bool_not_count(self):
        with self.assertRaises(ValueError):catalog.source_result("HR16","x","x",status="OK",groups=[{"state":"OK","count":True}])
    def test_negative_not_count(self):
        with self.assertRaises(ValueError):catalog.source_result("HR16","x","x",status="OK",groups=[{"state":"OK","count":-1}])
    def test_no_silent_historical_claim(self):self.assertFalse(catalog.source_result("HR16","x","x",status="OK",groups=[])["arbitraryHistoricalReconstruction"])
    def test_catalog_unique_codes(self):self.assertEqual(len(catalog.CATALOG),len({x[1] for x in catalog.CATALOG}))
    def test_all_business_domains_represented(self):self.assertEqual({x[0] for x in catalog.CATALOG},{f"HR{i:02d}" for i in range(2,17)})

if __name__=="__main__":unittest.main(verbosity=2)
