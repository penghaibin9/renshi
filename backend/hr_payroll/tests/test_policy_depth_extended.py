"""Additional amount, import, tenancy, amendment and authorization regressions."""
import copy
from io import BytesIO
from datetime import date
from decimal import Decimal
from uuid import uuid4
from django.test import TestCase, override_settings, RequestFactory
from django.contrib.auth.models import AnonymousUser
from openpyxl import load_workbook
from hr_payroll.tests import test_policy_payroll_depth as seed
PROVIDERS=seed.PROVIDERS;BANK=seed.BANK;tax_data=seed.tax_data
from hr_payroll.policy_models import PayrollStandardVersion,PayrollRetroApplication,PayrollTrialApproval,PayrollTaxAccount,PayrollTaxReservation,PayrollPolicyVersion
from hr_payroll.models import PayrollPeriod,PayrollResultFact
from hr_payroll.services.policy_math import PolicyPayrollError
from hr_payroll.services.policy_import_service import PayrollPolicyImportService,workbook_bytes
from hr_payroll.services.policy_retro_service import PolicyRetroService
from hr_payroll.services.payment_service import PayrollPaymentService,PayrollPaymentError
from hr_payroll.services.adjustment_service import PayrollAdjustmentService,PayrollAdjustmentError


@override_settings(HR15_PAYROLL_INPUT_PROVIDERS=PROVIDERS,HR15_PAYMENT_PROVIDERS=BANK)
class PayrollDepthExtendedTests(TestCase):
    tenant=701
    setUp=seed.PayrollPolicyOrmTests.setUp
    person=seed.PayrollPolicyOrmTests.person
    publish=seed.PayrollPolicyOrmTests.publish
    approved_trial=seed.PayrollPolicyOrmTests.approved_trial
    calculated=seed.PayrollPolicyOrmTests.calculated
    paid=seed.PayrollPolicyOrmTests.paid

    def retro_fixture(self,amount="6200"):
        result,_,_=self.paid()
        self.publish("STANDARD",{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G1","amount":amount,
            "effectiveFrom":"2026-09-16","supersedesId":str(self.standard.id)})
        self.publish("BASIS",{"payrollProfileId":str(self.profile.id),"selectors":{"positionGrade":"G1","employmentRelationshipId":str(self.relation.id)},
            "variables":{},"taxDeductions":tax_data(10),"costShares":{"TEST-COST":"1"},"effectiveFrom":"2026-10-01","supersedesId":str(self.basis.id)})
        engine=PolicyRetroService(self.tenant,101)
        trial=engine.trial_retro(source_result_id=result.id,payment_date="2026-10-25",payment_profile_id=self.profile.id,idempotency_key="RETRO-TEST")
        return result,engine,trial

    def test_retro_recompute_does_not_edit_historical_result(self):
        source,engine,trial=self.retro_fixture()
        self.assertEqual(Decimal(trial.output_json["gross"]),Decimal("100"))
        self.assertEqual(trial.input_payload_json["retro"]["correctedGross"],"6100.00")
        self.assertEqual(PayrollRetroApplication.objects.count(),0)
        PolicyRetroService(self.tenant,102).approve_retro(trial_id=trial.id,expected_hash=trial.content_hash,decision="APPROVE",note="核对原期间与本次支付期")
        result=engine.apply(trial_id=trial.id)
        self.assertEqual(result.gross_amount,Decimal("100"));self.assertEqual(result.status,"ADJUSTED")
        source.refresh_from_db();self.assertEqual(source.gross_amount,Decimal("6000"));self.assertEqual(source.status,"FINALIZED")
        self.assertEqual(engine.apply(trial_id=trial.id).id,result.id)
        self.assertEqual(PayrollRetroApplication.objects.count(),1)
        self.assertEqual(PayrollTaxReservation.objects.get(payroll_result_id=result.id).status,"RESERVED")
        pay=PayrollPaymentService(self.tenant,103)
        instruction=pay.create_instruction(result_id=result.id,instruction_no="TEST-RETRO-PAY",provider_code="SANDBOX_BANK")
        self.assertEqual(instruction.requested_amount,Decimal(trial.output_json["net"]))

    def test_retro_requires_independent_review(self):
        _,engine,trial=self.retro_fixture()
        with self.assertRaises(PolicyPayrollError):engine.apply(trial_id=trial.id)
        with self.assertRaises(PolicyPayrollError):engine.approve_retro(trial_id=trial.id,expected_hash=trial.content_hash,decision="APPROVE",note="self")

    def test_retro_refuses_negative_bank_payment(self):
        with self.assertRaises(PolicyPayrollError) as ctx:self.retro_fixture("5800")
        self.assertEqual(ctx.exception.code,"PAYROLL_RETRO_NO_POSITIVE_DELTA")

    def test_retro_refuses_stale_review(self):
        source,engine,trial=self.retro_fixture()
        PolicyRetroService(self.tenant,102).approve_retro(trial_id=trial.id,expected_hash=trial.content_hash,decision="APPROVE",note="ok")
        self.profile.payment_account_ref="vault://TEST/CHANGED";self.profile.save()
        with self.assertRaises(PolicyPayrollError):engine.apply(trial_id=trial.id)
        self.assertEqual(PayrollRetroApplication.objects.count(),0)

    def test_old_arbitrary_adjustment_cannot_bypass_policy_trial(self):
        source,_,_=self.paid()
        with self.assertRaises(PayrollAdjustmentError) as ctx:
            PayrollAdjustmentService(self.tenant,101).append_adjustment(source_result_id=source.id,adjustment_no="UNSAFE",gross_delta="100",deduction_delta="0",net_delta="100")
        self.assertEqual(ctx.exception.code,"PAYROLL_POLICY_RETRO_REQUIRED")

    def test_account_change_after_calculation_blocks_instruction(self):
        from hr_payroll.services.calculation_service import PayrollCalculationService
        from hr_payroll.services.finalization_service import PayrollFinalizationService
        _,_,result=self.calculated()
        calc=PayrollCalculationService(self.tenant,102);calc.review_result(result_id=result.id,decision="APPROVED",note="ok");calc.complete_review(period_id=self.period.id)
        PayrollFinalizationService(self.tenant).finalize_period(self.period.id)
        self.profile.payment_account_ref="vault://TEST/new";self.profile.save()
        with self.assertRaises(PayrollPaymentError) as ctx:
            PayrollPaymentService(self.tenant,103).create_instruction(result_id=result.id,instruction_no="NEW",provider_code="SANDBOX_BANK")
        self.assertEqual(ctx.exception.code,"PAYROLL_PAYMENT_ACCOUNT_CHANGED")

    def standard_rows(self):
        return [{"payGroupCode":"FACULTY","tableCode":"POSITION","levelCode":"G2","amount":"7100.25","currencyCode":"CNY","effectiveFrom":"2026-09-01","evidenceRef":"TEST-approved-source"}]

    def test_xlsx_preview_confirm_creates_only_drafts_and_replays(self):
        service=PayrollPolicyImportService(self.tenant,101)
        before=PayrollStandardVersion.objects.count()
        stage=service.preview("STANDARD",workbook_bytes("STANDARD",self.standard_rows()))
        self.assertEqual(stage.errors_json,[]);self.assertEqual(PayrollStandardVersion.objects.count(),before)
        result=service.confirm(stage.id,stage.stage_hash)
        self.assertEqual(len(result.applied_ids_json),1)
        self.assertEqual(PayrollStandardVersion.objects.get(id=result.applied_ids_json[0]).status,"DRAFT")
        service.confirm(stage.id,stage.stage_hash);self.assertEqual(PayrollStandardVersion.objects.count(),before+1)

    def test_same_file_reupload_cannot_create_twice(self):
        service=PayrollPolicyImportService(self.tenant,101);blob=workbook_bytes("STANDARD",self.standard_rows())
        one=service.preview("STANDARD",blob);service.confirm(one.id,one.stage_hash)
        two=service.preview("STANDARD",blob)
        with self.assertRaises(PolicyPayrollError):service.confirm(two.id,two.stage_hash)

    def test_xlsx_errors_block_all_rows(self):
        rows=self.standard_rows();rows.append({**rows[0],"levelCode":"G3","amount":"NOT-A-NUMBER"})
        service=PayrollPolicyImportService(self.tenant,101);stage=service.preview("STANDARD",workbook_bytes("STANDARD",rows))
        self.assertEqual(stage.errors_json[0]["row"],3)
        count=PayrollStandardVersion.objects.count()
        with self.assertRaises(PolicyPayrollError):service.confirm(stage.id,stage.stage_hash)
        self.assertEqual(PayrollStandardVersion.objects.count(),count)

    def test_xlsx_formula_is_not_evaluated(self):
        blob=workbook_bytes("STANDARD",self.standard_rows());wb=load_workbook(BytesIO(blob));wb["导入数据"]["D2"]="=1+2";buf=BytesIO();wb.save(buf)
        stage=PayrollPolicyImportService(self.tenant,101).preview("STANDARD",buf.getvalue())
        self.assertEqual(stage.errors_json[0]["code"],"PAYROLL_IMPORT_FORMULA_FORBIDDEN")

    def test_import_cannot_cross_tenant_or_actor(self):
        stage=PayrollPolicyImportService(self.tenant,101).preview("STANDARD",workbook_bytes("STANDARD",self.standard_rows()))
        for tenant,actor in [(999,101),(self.tenant,102)]:
            with self.assertRaises(PolicyPayrollError):PayrollPolicyImportService(tenant,actor).confirm(stage.id,stage.stage_hash)

    def test_import_preview_hash_cannot_be_replaced(self):
        service=PayrollPolicyImportService(self.tenant,101);stage=service.preview("STANDARD",workbook_bytes("STANDARD",self.standard_rows()))
        stage.rows_json[0]["data"]["amount"]="99999";stage.save()
        with self.assertRaises(PolicyPayrollError):service.confirm(stage.id,stage.stage_hash)

    def test_other_group_uses_own_rule_and_standard(self):
        staff,profile,relation,_=self.person("T002","CONTRACT")
        config=copy.deepcopy(self.policy.configuration_json)
        self.publish("POLICY",{"payGroupCode":"CONTRACT","name":"测试合同组","configuration":config})
        self.publish("STANDARD",{"payGroupCode":"CONTRACT","tableCode":"POSITION","levelCode":"G1","amount":"8000"})
        self.publish("RULE",{"payGroupCode":"CONTRACT","ruleCode":"POSITION","itemCode":"BASIC","name":"合同工资","itemType":"EARNING",
            "formula":{"op":"LOOKUP","tableCode":"POSITION","selectorKey":"positionGrade"},"dependencies":[],"allocationMode":"CALENDAR_DAYS"})
        self.publish("BASIS",{"payrollProfileId":str(profile.id),"selectors":{"positionGrade":"G1","employmentRelationshipId":str(relation.id)},"variables":{},"taxDeductions":tax_data(),"costShares":{}})
        one=self.approved_trial(self.staff);two=self.approved_trial(staff)
        self.assertEqual(Decimal(one.output_json["gross"]),Decimal("6000"));self.assertEqual(Decimal(two.output_json["gross"]),Decimal("8000"))

    def test_shared_workload_cannot_exceed_100_percent(self):
        other,_,_,_=self.person("T003","FACULTY")
        base={"periodId":str(self.period.id),"workloadKey":"TEST-CLASS-1","variableKey":"verifiedHours","units":"12","share":"0.6","coefficient":"1"}
        self.publish("WORKLOAD",{**base,"staffId":str(self.staff.id)})
        with self.assertRaises(PolicyPayrollError) as ctx:self.publish("WORKLOAD",{**base,"staffId":str(other.id)})
        self.assertEqual(ctx.exception.code,"PAYROLL_SHARED_WORKLOAD_OVERALLOCATED")

    def test_unapproved_workload_never_enters_input(self):
        self.maker.create("WORKLOAD",{"periodId":str(self.period.id),"staffId":str(self.staff.id),"workloadKey":"TEST-UNVERIFIED","variableKey":"hours","units":"10","share":"1","coefficient":"1","effectiveFrom":"2026-09-01","evidenceRef":"TEST"})
        trial=self.approved_trial()
        self.assertNotIn("hours",trial.input_payload_json["segments"][0]["variables"])

    def test_anonymous_api_does_not_reveal_salary(self):
        from hr_payroll.policy_api import trial_detail
        request=RequestFactory().get("/");request.user=AnonymousUser()
        self.assertEqual(trial_detail(request,trial_id=uuid4()).status_code,403)
