import importlib
import inspect
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from hr_payroll.calculation_models import SalaryRuleVersion
from hr_payroll.compensation_models import CompensationChangeCase
from hr_payroll.models import PayrollPeriod, PayrollProfile
from hr_payroll.services.calculation_service import (
    PayrollCalculationService,
    PayrollRuleService,
    verify_payroll_input_snapshot,
)
from hr_payroll.services.compensation_change_service import (
    CompensationChangeError,
    CompensationChangeService,
)
from hr_staff.models import HrOutboxEvent
from hr_staff.tests.factories import make_person, make_staff


TENANT = 1515


class CompensationInputProvider:
    def collect(self, request):
        authority = request["authority"]
        return {
            "authority": authority,
            "tenantId": request["tenantId"],
            "periodId": request["periodId"],
            "staffId": request["staffId"],
            "version": f"{authority.lower()}-v1",
            "evidenceId": f"{authority}-{request['staffId']}",
            "snapshot": {"sealed": True},
            "variables": (
                {"approvedMonthlySalary": "10000.00"}
                if authority == "HR14"
                else {}
            ),
        }


INPUT_PROVIDERS = {
    authority: (
        "hr_payroll.tests.test_compensation_change_service."
        "CompensationInputProvider"
    )
    for authority in ("HR03", "HR11", "HR12", "HR14")
}


class CompensationChangeServiceTests(TestCase):
    def setUp(self):
        person = make_person(TENANT, "调资老师")
        self.staff = make_staff(TENANT, person, "PAY-CHANGE-001")
        self.maker = CompensationChangeService(
            TENANT, actor_user_id=71, correlation_id="change-test"
        )
        self.approver = CompensationChangeService(
            TENANT, actor_user_id=72, correlation_id="change-test"
        )

    def draft(self, **overrides):
        values = {
            "case_no": "XC-2026-001",
            "staff_id": self.staff.id,
            "change_type": CompensationChangeCase.ChangeType.ALLOWANCE_START,
            "payroll_variable_key": "transportAllowance",
            "item_name": "交通补贴",
            "amount_mode": CompensationChangeCase.AmountMode.SET,
            "amount": "300.00",
            "effective_from": date(2026, 9, 1),
            "reason_code": "SCHOOL_POLICY",
            "source_domain": "HR15",
            "source_ref": "POLICY-2026-01",
            "source_version": "1",
            "evidence_refs": ["DOC-001"],
        }
        return self.maker.create_draft(**{**values, **overrides})

    def test_submit_and_independent_approval_create_immutable_fact(self):
        case = self.maker.submit(self.draft().id)
        self.assertEqual(case.status, CompensationChangeCase.Status.SUBMITTED)
        self.assertEqual(len(case.content_hash), 64)

        with self.assertRaises(CompensationChangeError) as ctx:
            self.maker.approve(case.id)
        self.assertEqual(
            ctx.exception.code, "COMPENSATION_CHANGE_MAKER_CHECKER_REQUIRED"
        )

        case = self.approver.approve(case.id, decision_note="政策依据已复核")
        self.assertEqual(case.status, CompensationChangeCase.Status.APPROVED)
        self.assertEqual(case.decided_by, 72)
        self.assertTrue(
            HrOutboxEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.payroll.compensation_change.approved",
            ).exists()
        )
        case.amount = Decimal("1.00")
        with self.assertRaises(ValueError):
            case.save()
        with self.assertRaises(ValueError):
            CompensationChangeCase.objects.filter(id=case.id).delete()
        with self.assertRaises(ValueError):
            CompensationChangeCase.objects.filter(id=case.id).update(amount=1)

    def test_rejection_requires_reason_and_different_actor(self):
        case = self.maker.submit(self.draft().id)
        with self.assertRaises(CompensationChangeError) as ctx:
            self.approver.reject(case.id, decision_note="")
        self.assertEqual(
            ctx.exception.code, "COMPENSATION_CHANGE_DECISION_NOTE_REQUIRED"
        )

        case = self.approver.reject(case.id, decision_note="依据不足")
        self.assertEqual(case.status, CompensationChangeCase.Status.REJECTED)

    def test_approved_case_becomes_hashed_payroll_input_with_proration(self):
        case = self.draft(
            amount="310.00",
            effective_from=date(2026, 9, 16),
            proration_mode=CompensationChangeCase.ProrationMode.CALENDAR_DAYS,
        )
        self.maker.submit(case.id)
        self.approver.approve(case.id)
        case.refresh_from_db()

        source = self.approver.payroll_input_source(
            staff_id=self.staff.id,
            period_id="00000000-0000-0000-0000-000000001515",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            base_variables={},
        )

        self.assertEqual(source["authority"], "HR15_CHANGE")
        self.assertEqual(source["variables"]["transportAllowance"], "155.00")
        self.assertEqual(len(source["evidenceId"]), 64)
        self.assertEqual(source["snapshot"]["cases"][0]["contentHash"], case.content_hash)

    def test_delta_change_overrides_the_trusted_base_variable(self):
        case = self.draft(
            change_type=CompensationChangeCase.ChangeType.SALARY_STEP_CHANGE,
            payroll_variable_key="approvedMonthlySalary",
            item_name="薪级工资",
            amount_mode=CompensationChangeCase.AmountMode.DELTA,
            amount="500.00",
        )
        self.maker.submit(case.id)
        self.approver.approve(case.id)

        source = self.approver.payroll_input_source(
            staff_id=self.staff.id,
            period_id="00000000-0000-0000-0000-000000001515",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            base_variables={"approvedMonthlySalary": "10000.00"},
        )

        self.assertEqual(source["variables"]["approvedMonthlySalary"], "10500.00")

    def test_midmonth_delta_prorates_only_the_delta_and_preserves_base(self):
        case = self.draft(
            change_type=CompensationChangeCase.ChangeType.SALARY_STEP_CHANGE,
            payroll_variable_key="approvedMonthlySalary",
            item_name="薪级工资",
            amount_mode=CompensationChangeCase.AmountMode.DELTA,
            amount="500.00",
            effective_from=date(2026, 9, 16),
            proration_mode=CompensationChangeCase.ProrationMode.CALENDAR_DAYS,
        )
        self.maker.submit(case.id)
        self.approver.approve(case.id)

        source = self.approver.payroll_input_source(
            staff_id=self.staff.id,
            period_id="00000000-0000-0000-0000-000000001515",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            base_variables={"approvedMonthlySalary": "10000.00"},
        )

        self.assertEqual(source["variables"]["approvedMonthlySalary"], "10250.00")

    def test_superseding_allowance_uses_old_then_new_daily_amount(self):
        original = self.draft(
            amount="100.00",
            proration_mode=CompensationChangeCase.ProrationMode.CALENDAR_DAYS,
        )
        self.maker.submit(original.id)
        self.approver.approve(original.id)
        replacement = self.draft(
            case_no="XC-2026-002",
            change_type=CompensationChangeCase.ChangeType.ALLOWANCE_CHANGE,
            amount="300.00",
            effective_from=date(2026, 9, 16),
            proration_mode=CompensationChangeCase.ProrationMode.CALENDAR_DAYS,
            supersedes_case_id=original.id,
        )
        self.maker.submit(replacement.id)
        self.approver.approve(replacement.id)

        source = self.approver.payroll_input_source(
            staff_id=self.staff.id,
            period_id="00000000-0000-0000-0000-000000001515",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            base_variables={},
        )

        self.assertEqual(source["variables"]["transportAllowance"], "200.00")

    def test_allowance_change_requires_approved_superseded_case(self):
        case = self.draft(
            change_type=CompensationChangeCase.ChangeType.ALLOWANCE_CHANGE
        )
        with self.assertRaises(CompensationChangeError) as ctx:
            self.maker.submit(case.id)
        self.assertEqual(
            ctx.exception.code, "COMPENSATION_CHANGE_SUPERSEDES_REQUIRED"
        )

    @override_settings(HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS)
    def test_approved_change_is_sealed_into_trusted_payroll_input(self):
        period = PayrollPeriod.objects.create(
            tenant_id=TENANT,
            period_code="2026-09",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            status=PayrollPeriod.Status.INPUT_FROZEN,
        )
        PayrollProfile.objects.create(
            tenant_id=TENANT,
            staff_id=self.staff.id,
            payroll_identity_no="PAY-CHANGE-IDENTITY",
            pay_group_code="FACULTY",
            effective_from=date(2026, 1, 1),
        )
        rules = PayrollRuleService(TENANT, actor_user_id=71)
        rule = rules.create_draft(
            rule_code="BASIC-PAY",
            version_no=1,
            item_code="BASIC",
            name="基本工资",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            formula={"op": "INPUT", "key": "approvedMonthlySalary"},
            effective_from=date(2026, 1, 1),
        )
        rules.publish(rule.id)
        case = self.draft(
            change_type=CompensationChangeCase.ChangeType.SALARY_STEP_CHANGE,
            payroll_variable_key="approvedMonthlySalary",
            item_name="薪级工资",
            amount_mode=CompensationChangeCase.AmountMode.DELTA,
            amount="500.00",
        )
        self.maker.submit(case.id)
        self.approver.approve(case.id)

        snapshot = PayrollCalculationService(TENANT, actor_user_id=71).capture_input(
            period_id=period.id,
            staff_id=self.staff.id,
        )

        self.assertEqual(snapshot.variables_json["approvedMonthlySalary"], "10500.00")
        self.assertIn("HR15_CHANGE", snapshot.source_versions_json)
        verify_payroll_input_snapshot(snapshot)


class CompensationChangeMigrationContractTests(TestCase):
    def test_mysql_ledger_triggers_are_non_atomic_and_reversible(self):
        module = importlib.import_module(
            "hr_payroll.migrations.0012_compensation_change_cases"
        )
        source = inspect.getsource(module)

        self.assertIs(module.Migration.atomic, False)
        self.assertIn("BEFORE UPDATE", source)
        self.assertIn("BEFORE DELETE", source)
        self.assertGreaterEqual(source.count("DROP TRIGGER IF EXISTS"), 2)
