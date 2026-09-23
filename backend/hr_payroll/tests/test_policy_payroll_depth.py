"""Real Django ORM tests; only payment gateway is a controlled test adapter.

SQLite execution proves service behavior, not MySQL row-lock/concurrency semantics.
School amounts/names and policy evidence below are fictitious test fixtures.
"""
import copy
import calendar
from datetime import date, datetime, timezone as tz
from decimal import Decimal
from uuid import uuid4
from django.test import TestCase, SimpleTestCase, override_settings
from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment, HrOutboxEvent
from hr_staff.tests.factories import make_org
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.calculation_models import PayrollInputSnapshot, PayrollCalculationLine
from hr_payroll.policy_models import (PayrollPolicyVersion, PayrollBasisVersion, PayrollTrial, PayrollTaxAccount,
                                     PayrollTaxReservation, PayrollTrialApproval)
from hr_payroll.services.policy_math import (PolicyPayrollError, decimal, digest, resident_wage_tax,
                                           annual_bonus_tax, allocate_cost, expression)
from hr_payroll.services.policy_configuration_service import PolicyConfigurationService
from hr_payroll.services.policy_payroll_service import PolicyPayrollService, verify_trial
from hr_payroll.services.policy_tax_service import PolicyTaxService
from hr_payroll.services.calculation_service import PayrollCalculationService, PayrollCalculationError
from hr_payroll.services.finalization_service import PayrollFinalizationService
from hr_payroll.services.payment_service import PayrollPaymentService

PROVIDERS={"HR03":"hr_payroll.services.input_fact_providers.Hr03PayrollInputProvider"}
BANK={"SANDBOX_BANK":"hr_payroll.tests.test_payment_provider_boundary.TrustedSandboxPaymentProvider"}
ZERO_DEDUCTIONS={k:"0" for k in ("expenseYtd","specialYtd","additionalYtd","otherYtd","reliefYtd")}


def tax_data(month=9):
    return {"evidenceRef":"TEST-only-tax-confirmation","residentConfirmed":True,
            "paymentMonth":f"2026-{month:02}","deductionMode":"ORDINARY","employmentMonths":month,
            "expenseYtd":str(month*5000),"specialYtd":"0","additionalYtd":"0","otherYtd":"0","reliefYtd":"0",
            "openingEvidenceRef":"TEST-only-confirmed-no-prior-income",
            "openingBalance":{"asOfDate":"2025-12-31","income":"0","exempt":"0","withheld":"0",
                              "deductions":dict(ZERO_DEDUCTIONS),"bonusUsed":False}}


class PayrollPolicyMathTests(SimpleTestCase):
    def test_full_year_cumulative_tax(self):
        withheld=Decimal(0); values=[]
        for month in range(1,13):
            result=resident_wage_tax(ytd_income=str(11000*month),ytd_exempt="0",ytd_expense=str(5000*month),
                ytd_special=str(1500*month),ytd_additional=str(1000*month),ytd_other="0",ytd_relief="0",withheld=withheld)
            current=Decimal(result["withholding"]);values.append(current);withheld+=current
        self.assertEqual(values,[Decimal("105")]*10+[Decimal("280"),Decimal("350")])
        self.assertEqual(withheld,Decimal("1680"))

    def test_same_month_supplement_does_not_repeat_expense(self):
        one=resident_wage_tax(ytd_income="10000",ytd_exempt="0",ytd_expense="5000",ytd_special="0",ytd_additional="0",ytd_other="0",ytd_relief="0",withheld="0")
        two=resident_wage_tax(ytd_income="12000",ytd_exempt="0",ytd_expense="5000",ytd_special="0",ytd_additional="0",ytd_other="0",ytd_relief="0",withheld=one["withholding"])
        self.assertEqual(Decimal(two["withholding"]),Decimal("60"))

    def test_missing_nan_and_float_are_not_zero(self):
        for value in (None,float('nan'),"NaN","Infinity",True,1.2):
            with self.subTest(value=value),self.assertRaises(PolicyPayrollError):decimal(value)
        self.assertEqual(decimal("0"),Decimal(0))

    def test_bonus_expiry_and_double_use_block(self):
        self.assertEqual(Decimal(annual_bonus_tax("36000",payment_date=date(2026,12,25),eligible=True,already_used=False)["withholding"]),Decimal("1080"))
        for day,eligible,used in ((date(2028,1,1),True,False),(date(2026,12,25),False,False),(date(2026,12,25),True,True)):
            with self.assertRaises(PolicyPayrollError):annual_bonus_tax("36000",payment_date=day,eligible=eligible,already_used=used)

    def test_cost_tail_cent_is_conserved(self):
        result=allocate_cost("100.01",{"A":"0.5","B":"0.5"})
        self.assertEqual(sum(map(Decimal,result.values())),Decimal("100.01"))
        with self.assertRaises(PolicyPayrollError):allocate_cost("100",{"A":"0.6","B":"0.6"})

    def test_no_eval_or_unbounded_formula(self):
        with self.assertRaises(PolicyPayrollError):
            expression({"op":"PYTHON","code":"__import__('os')"},variables={},calculated={},selectors={},standards=[],on=date(2026,1,1))
        node={"op":"FIXED","amount":"1"}
        for _ in range(10):node={"op":"SUM","args":[node]}
        with self.assertRaises(PolicyPayrollError):expression(node,variables={},calculated={},selectors={},standards=[],on=date(2026,1,1))


@override_settings(HR15_PAYROLL_INPUT_PROVIDERS=PROVIDERS,HR15_PAYMENT_PROVIDERS=BANK)
class PayrollPolicyOrmTests(TestCase):
    tenant=701
    def setUp(self):
        self.maker=PolicyConfigurationService(self.tenant,101)
        self.checker=PolicyConfigurationService(self.tenant,102)
        self.engine=PolicyPayrollService(self.tenant,101)
        self.reviewer=PolicyPayrollService(self.tenant,102)
        self.period=PayrollPeriod.objects.create(tenant_id=self.tenant,period_code="2026-09",start_date=date(2026,9,1),end_date=date(2026,9,30),
                      engine_version="POLICY_V1",payment_date=date(2026,9,30),payroll_purpose="REGULAR")
        self.org=make_org(self.tenant,"TEST-COLLEGE","核算测试学院",date(2020,1,1))
        self.staff,self.profile,self.relation,self.assignment=self.person("T001","FACULTY")
        self.policy=self.publish("POLICY",{"payGroupCode":"FACULTY","name":"仅测试制度","configuration":{
              "requiredAuthorities":["HR03"],"itemCodes":["BASIC"],"taxMethod":"RESIDENT_WAGE","withholdingAgent":"TEST-AGENT",
              "statutoryMode":"NOT_APPLICABLE","statutoryCodes":[],"statutoryReason":"TEST ONLY explicit scope exemption"}})
        self.standard=self.publish("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":"6000.00"})
        self.rule=self.publish("RULE",{"payGroupCode":"FACULTY","ruleCode":"POSITION","itemCode":"BASIC","name":"岗位工资",
              "itemType":"EARNING","formula":{"op":"LOOKUP","tableCode":"POSITION","selectorKey":"positionGrade"},"allocationMode":"CALENDAR_DAYS"})
        self.basis=self.publish("BASIS",{"payrollProfileId":str(self.profile.id),"selectors":{"positionGrade":"G1","employmentRelationshipId":str(self.relation.id)},
              "variables":{},"taxDeductions":tax_data(),"costShares":{"TEST-COST":"1"}})

    def person(self,no,group):
        person=HrPerson.objects.create(tenant_id=self.tenant,legal_name="虚构验算人员"+no)
        staff=HrStaffMaster.objects.create(tenant_id=self.tenant,person_id=person,staff_no=no)
        # Explicit historical fixture, not a production backdating mechanism.
        at=datetime(2020,1,1,tzinfo=tz.utc)
        HrPerson.objects.filter(pk=person.pk).update(created_at=at,updated_at=at)
        HrStaffMaster.objects.filter(pk=staff.pk).update(created_at=at,updated_at=at)
        relation=HrEmploymentRelationship.objects.create(tenant_id=self.tenant,staff_id=staff,effective_from=date(2020,1,1),status="ACTIVE")
        assignment=HrStaffAssignment.objects.create(tenant_id=self.tenant,employment_relationship_id=relation,organization_id=self.org,
                      effective_from=date(2020,1,1),assignment_type="PRIMARY",status="ACTIVE")
        profile=PayrollProfile.objects.create(tenant_id=self.tenant,staff_id=staff.id,payroll_identity_no="PAY-"+no,pay_group_code=group,
                     currency_code="CNY",payment_account_ref="vault://TEST/"+no,effective_from=date(2020,1,1))
        return staff,profile,relation,assignment

    def publish(self,kind,values):
        data={"effectiveFrom":"2020-01-01","evidenceRef":"TEST-FICTITIOUS-POLICY",**values}
        draft=self.maker.create(kind,data)
        return self.checker.publish(kind,draft.id)

    def approved_trial(self,staff=None,key=None):
        staff=staff or self.staff
        trial=self.engine.trial(period_id=self.period.id,staff_id=staff.id,idempotency_key=key or str(uuid4()))
        self.reviewer.approve(trial_id=trial.id,expected_hash=trial.content_hash,note="人工独立核对测试金额")
        return trial

    def calculated(self):
        trial=self.approved_trial()
        self.period.status="INPUT_FROZEN";self.period.save()
        calc=PayrollCalculationService(self.tenant,actor_user_id=101)
        snap=calc.capture_input(period_id=self.period.id,staff_id=self.staff.id)
        out=calc.calculate(period_id=self.period.id,batch_no="TEST-BATCH",idempotency_key="TEST-CALCULATE")
        return trial,snap,PayrollResultFact.objects.get(pk=out.result_ids[0])

    def paid(self,paid_date="2026-09-30"):
        trial,snap,result=self.calculated()
        calc=PayrollCalculationService(self.tenant,actor_user_id=102)
        calc.review_result(result_id=result.id,decision="APPROVED",note="复核金额及明细")
        calc.complete_review(period_id=self.period.id)
        PayrollFinalizationService(self.tenant).finalize_period(self.period.id)
        pay=PayrollPaymentService(self.tenant,actor_user_id=103)
        instruction=pay.create_instruction(result_id=result.id,instruction_no="TEST-PAY",provider_code="SANDBOX_BANK")
        pay.dispatch(instruction_id=instruction.id)
        receipt={"tenantId":self.tenant,"instructionId":str(instruction.id),"instructionNo":instruction.instruction_no,
                 "providerCode":"SANDBOX_BANK","receiptNo":"TEST-BANK-RECEIPT","status":"ACCEPTED","settledAmount":str(result.net_amount),
                 "currencyCode":"CNY","idempotencyKey":f"hr15:{self.tenant}:{instruction.id}"}
        if paid_date:receipt["paidDate"]=paid_date
        pay.ingest_provider_receipt(instruction_id=instruction.id,provider_payload=receipt)
        return result,instruction,receipt

    def test_existing_capture_calculate_review_finalize_pay_chain(self):
        result,instruction,receipt=self.paid()
        result.refresh_from_db()
        self.assertEqual(result.gross_amount,Decimal("6000"))
        self.assertEqual(result.status,"FINALIZED")
        account=PayrollTaxAccount.objects.get(tenant_id=self.tenant)
        self.assertEqual(account.version_no,1)
        self.assertEqual(Decimal(account.totals_json["income"]),Decimal("6000"))
        self.assertIsNone(account.pending_result_id)
        self.assertEqual(PayrollTaxReservation.objects.get().status,"POSTED")
        self.assertTrue(HrOutboxEvent.objects.filter(tenant_id=self.tenant,event_type="hr.payroll.calculation.completed").exists())
        PayrollPaymentService(self.tenant,actor_user_id=103).ingest_provider_receipt(instruction_id=instruction.id,provider_payload=receipt)
        account.refresh_from_db();self.assertEqual(account.version_no,1)

    def test_midmonth_standard_replacement_is_6100(self):
        self.publish("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":"6200.00",
                                 "effectiveFrom":"2026-09-16","supersedesId":str(self.standard.id)})
        trial=self.approved_trial()
        self.assertEqual(Decimal(trial.output_json["gross"]),Decimal("6100"))
        self.assertEqual(len(trial.output_json["lines"][0]["segments"]),2)

    def test_missing_grade_blocks_instead_of_zero(self):
        self.publish("BASIS",{"payrollProfileId":str(self.profile.id),"selectors":{"positionGrade":"UNKNOWN","employmentRelationshipId":str(self.relation.id)},
            "variables":{},"taxDeductions":tax_data(),"costShares":{"TEST-COST":"1"},"effectiveFrom":"2026-09-01","supersedesId":str(self.basis.id)})
        with self.assertRaises(PolicyPayrollError) as ctx:self.approved_trial()
        self.assertEqual(ctx.exception.code,"PAYROLL_STANDARD_MISSING_OR_OVERLAP")
        self.assertEqual(PayrollResultFact.objects.count(),0)

    def test_approved_revisions_are_not_overwritten(self):
        first=self.approved_trial()
        self.period.status="INPUT_FROZEN";self.period.save()
        self.engine.capture(period_id=self.period.id,staff_id=self.staff.id)
        self.publish("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":"6200.00",
                                 "effectiveFrom":"2026-09-16","supersedesId":str(self.standard.id)})
        second=self.approved_trial()
        self.engine.capture(period_id=self.period.id,staff_id=self.staff.id)
        first.refresh_from_db();self.assertEqual(Decimal(first.output_json["gross"]),Decimal("6000"))
        self.assertEqual(second.revision_no,2)
        self.assertEqual(PayrollInputSnapshot.objects.count(),2)
        out=self.engine.calculate(period_id=self.period.id,batch_no="REV2",idempotency_key="REV2")
        self.assertEqual(PayrollResultFact.objects.get(pk=out.result_ids[0]).gross_amount,Decimal("6100"))

    def test_review_stale_version_fails(self):
        trial=self.engine.trial(period_id=self.period.id,staff_id=self.staff.id,idempotency_key="STALE")
        self.publish("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":"6200.00",
                                 "effectiveFrom":"2026-09-16","supersedesId":str(self.standard.id)})
        with self.assertRaises(PolicyPayrollError) as ctx:self.reviewer.approve(trial_id=trial.id,expected_hash=trial.content_hash,note="核对")
        self.assertEqual(ctx.exception.code,"PAYROLL_TRIAL_STALE")

    def test_maker_cannot_approve_trial(self):
        trial=self.engine.trial(period_id=self.period.id,staff_id=self.staff.id,idempotency_key="SOD")
        with self.assertRaises(PolicyPayrollError) as ctx:self.engine.approve(trial_id=trial.id,expected_hash=trial.content_hash,note="本人审批")
        self.assertEqual(ctx.exception.code,"PAYROLL_SEPARATION_OF_DUTIES")

    def test_cross_tenant_cannot_read_or_approve(self):
        trial=self.engine.trial(period_id=self.period.id,staff_id=self.staff.id,idempotency_key="TENANT")
        with self.assertRaises(PolicyPayrollError):PolicyPayrollService(702,102).approve(trial_id=trial.id,expected_hash=trial.content_hash,note="越校")
        with self.assertRaises(PolicyPayrollError):PolicyPayrollService(702,102).trial(period_id=self.period.id,staff_id=self.staff.id,idempotency_key="TENANT")

    def test_payroll_no_hr14_when_policy_does_not_require_it(self):
        trial=self.approved_trial()
        self.assertEqual(set(trial.input_payload_json["segments"][0]["sources"]),{"HR03"})

    def test_required_hr14_is_not_silently_waived(self):
        cfg=copy.deepcopy(self.policy.configuration_json);cfg["requiredAuthorities"].append("HR14")
        self.publish("POLICY",{"payGroupCode":"FACULTY","name":"需要聘任依据的测试制度","configuration":cfg,
              "effectiveFrom":"2026-09-01","supersedesId":str(self.policy.id)})
        with self.assertRaises(PolicyPayrollError) as ctx:self.approved_trial()
        self.assertEqual(ctx.exception.code,"PAYROLL_INPUT_PROVIDER_UNAVAILABLE")

    def test_missing_primary_employment_relation_blocks(self):
        self.relation.status="CANCELLED";self.relation.save()
        with self.assertRaises(PolicyPayrollError) as ctx:self.approved_trial()
        self.assertEqual(ctx.exception.code,"PAYROLL_PRIMARY_RELATION_REQUIRED")

    def test_double_primary_assignment_blocks(self):
        self.assignment.effective_to=date(2026,10,1);self.assignment.save()
        HrStaffAssignment.objects.create(tenant_id=self.tenant,employment_relationship_id=self.relation,organization_id=self.org,
                                        assignment_type="PRIMARY",status="ACTIVE",effective_from=date(2026,9,1),effective_to=date(2026,10,1))
        with self.assertRaises(PolicyPayrollError) as ctx:self.approved_trial()
        self.assertEqual(ctx.exception.code,"PAYROLL_PRIMARY_ASSIGNMENT_REQUIRED")

    def test_missing_bank_payment_date_does_not_fake_tax_posting(self):
        result,instruction,receipt=self.paid(None)
        instruction.refresh_from_db();self.assertEqual(instruction.status,"ACCEPTED")
        self.assertEqual(PayrollTaxReservation.objects.get().status,"DATE_REVIEW")
        self.assertEqual(PayrollTaxAccount.objects.get().version_no,0)

    def test_trial_is_not_a_payment(self):
        self.approved_trial()
        self.assertEqual(PayrollTaxAccount.objects.count(),0)
        self.assertEqual(PayrollTaxReservation.objects.count(),0)

    def test_unpaid_result_blocks_next_dependent_tax(self):
        self.calculated()
        other=PayrollPeriod.objects.create(tenant_id=self.tenant,period_code="2026-09-extra",start_date=date(2026,9,1),end_date=date(2026,9,30),
                  engine_version="POLICY_V1",payment_date=date(2026,9,30),payroll_purpose="SUPPLEMENT")
        data={"personId":str(self.staff.person_id_id),"withholdingAgent":"TEST-AGENT","paymentDate":"2026-09-30",
              "method":"RESIDENT_WAGE","income":"100","deductions":tax_data()}
        with self.assertRaises(PolicyPayrollError) as ctx:PolicyTaxService(self.tenant,101).quote(data)
        self.assertEqual(ctx.exception.code,"PAYROLL_TAX_PENDING_SETTLEMENT")

    def test_first_tax_use_requires_verified_opening_balance(self):
        deductions=tax_data();deductions.pop("openingBalance")
        self.publish("BASIS",{"payrollProfileId":str(self.profile.id),"selectors":self.basis.selectors_json,
            "variables":{},"taxDeductions":deductions,"costShares":{"TEST-COST":"1"},"effectiveFrom":"2026-09-01","supersedesId":str(self.basis.id)})
        with self.assertRaises(PolicyPayrollError) as ctx:self.approved_trial()
        self.assertEqual(ctx.exception.code,"PAYROLL_TAX_OPENING_REQUIRED")

    def test_roster_cannot_silently_omit_second_teacher(self):
        self.person("T002","FACULTY")
        self.approved_trial();self.period.status="INPUT_FROZEN";self.period.save()
        self.engine.capture(period_id=self.period.id,staff_id=self.staff.id)
        with self.assertRaises(PolicyPayrollError) as ctx:self.engine.calculate(period_id=self.period.id,batch_no="OMIT",idempotency_key="OMIT")
        self.assertEqual(ctx.exception.code,"PAYROLL_ROSTER_INCOMPLETE")
        self.assertEqual(PayrollResultFact.objects.count(),0)

    def test_configuration_overlap_and_maker_checker(self):
        draft=self.maker.create("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":"8000",
              "effectiveFrom":"2026-09-01","evidenceRef":"TEST"})
        with self.assertRaises(PolicyPayrollError) as ctx:self.maker.publish("STANDARD",draft.id)
        self.assertEqual(ctx.exception.code,"PAYROLL_SEPARATION_OF_DUTIES")
        with self.assertRaises(PolicyPayrollError) as ctx:self.checker.publish("STANDARD",draft.id)
        self.assertEqual(ctx.exception.code,"PAYROLL_CONFIGURATION_OVERLAP")
