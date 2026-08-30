import importlib
import inspect
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from hr_payroll import api
from hr_payroll.calculation_models import PayrollInputSnapshot, SalaryRuleVersion
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.services.calculation_service import (
    PayrollCalculationError,
    PayrollCalculationService,
    PayrollRuleService,
)
from hr_payroll.services.payment_service import PayrollPaymentError, PayrollPaymentService


class TrustedPayrollInputProvider:
    provided_variables = {"approvedMonthlySalary": "10000.00"}
    calls = []

    def collect(self, request):
        self.__class__.calls.append(dict(request))
        authority = request["authority"]
        return {
            "authority": authority,
            "tenantId": request["tenantId"],
            "periodId": request["periodId"],
            "staffId": request["staffId"],
            "version": f"{authority.lower()}-trusted-v1",
            "evidenceId": f"{authority}-evidence-{request['staffId']}",
            "snapshot": {"authority": authority, "sealed": True},
            "variables": (
                dict(self.__class__.provided_variables)
                if authority == "HR14"
                else {}
            ),
        }


class CrossTenantPayrollInputProvider(TrustedPayrollInputProvider):
    def collect(self, request):
        result = super().collect(request)
        result["tenantId"] = int(request["tenantId"]) + 1
        return result


INPUT_PROVIDERS = {
    authority: (
        "hr_payroll.tests.test_input_fact_provider_boundary."
        "TrustedPayrollInputProvider"
    )
    for authority in ("HR03", "HR11", "HR12", "HR14")
}


class _User:
    is_authenticated = True
    is_superuser = False
    id = 901

    def has_perm(self, permission):
        return permission == api.PERM_INPUT_MANAGE


class PayrollInputFactProviderBoundaryTests(TestCase):
    tenant_id = 77
    actor_id = 901
    staff_id = uuid.UUID("00000000-0000-0000-0000-000000001501")

    def setUp(self):
        TrustedPayrollInputProvider.calls.clear()
        TrustedPayrollInputProvider.provided_variables = {
            "approvedMonthlySalary": "10000.00"
        }
        self.period = PayrollPeriod.objects.create(
            tenant_id=self.tenant_id,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.INPUT_FROZEN,
        )
        PayrollProfile.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff_id,
            payroll_identity_no="PAY-ID-1501",
            pay_group_code="FACULTY",
            currency_code="CNY",
            payment_account_ref="vault://payroll/1501",
            effective_from=date(2026, 1, 1),
        )
        self.service = PayrollCalculationService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        self.rule_service = PayrollRuleService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        self.rule = self.rule_service.create_draft(
            rule_code="RULE-BASIC",
            version_no=1,
            item_code="BASIC",
            name="Basic salary",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            formula={"op": "INPUT", "key": "approvedMonthlySalary"},
            effective_from=date(2026, 1, 1),
        )
        self.rule_service.publish(self.rule.id)

    def test_unconfigured_required_provider_fails_closed(self):
        with self.assertRaises(PayrollCalculationError) as caught:
            self.service.capture_input(
                period_id=self.period.id,
                staff_id=self.staff_id,
            )

        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_PROVIDER_UNAVAILABLE")
        self.assertFalse(PayrollInputSnapshot.objects.exists())

    @override_settings(HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS)
    def test_snapshot_comes_only_from_trusted_providers_and_is_idempotent(self):
        snapshot = self.service.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )
        replay = self.service.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )

        self.assertEqual(replay.id, snapshot.id)
        self.assertEqual(snapshot.snapshot_version, "hr15-payroll-input-v2")
        self.assertEqual(snapshot.variables_json, {"approvedMonthlySalary": "10000.00"})
        self.assertEqual(set(snapshot.source_versions_json), {"HR03", "HR11", "HR12", "HR14"})
        self.assertEqual(len(TrustedPayrollInputProvider.calls), 8)
        self.assertNotIn("variables", TrustedPayrollInputProvider.calls[0])

    @override_settings(HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS)
    def test_changed_provider_facts_conflict_with_frozen_staff_snapshot(self):
        self.service.capture_input(period_id=self.period.id, staff_id=self.staff_id)
        TrustedPayrollInputProvider.provided_variables = {
            "approvedMonthlySalary": "10001.00"
        }

        with self.assertRaises(PayrollCalculationError) as caught:
            self.service.capture_input(period_id=self.period.id, staff_id=self.staff_id)

        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_IDEMPOTENCY_CONFLICT")

    @override_settings(
        HR15_PAYROLL_INPUT_PROVIDERS={
            **INPUT_PROVIDERS,
            "HR12": (
                "hr_payroll.tests.test_input_fact_provider_boundary."
                "CrossTenantPayrollInputProvider"
            ),
        }
    )
    def test_cross_tenant_provider_response_is_rejected(self):
        with self.assertRaises(PayrollCalculationError) as caught:
            self.service.capture_input(period_id=self.period.id, staff_id=self.staff_id)

        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID")
        self.assertFalse(PayrollInputSnapshot.objects.exists())

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.PayrollCalculationService")
    def test_business_api_rejects_client_authoritative_inputs(
        self, service_cls, _allowed, _tenant
    ):
        request = RequestFactory().post(
            f"/api/v1/hr/payroll/periods/{self.period.id}/inputs/",
            data=json.dumps(
                {
                    "staffId": str(self.staff_id),
                    "variables": {"approvedMonthlySalary": "99999999.00"},
                    "sourceVersions": {"HR03": {"version": "forged"}},
                    "currencyCode": "USD",
                }
            ),
            content_type="application/json",
        )
        request.user = _User()

        response = api.capture_period_input(request, self.period.id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "PAYROLL_INPUT_CLIENT_AUTHORITY_FORBIDDEN",
        )
        service_cls.assert_not_called()

    @override_settings(HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS)
    def test_calculation_detects_raw_snapshot_tampering(self):
        snapshot = self.service.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE hr15_payroll_input_snapshot SET variables_json = %s WHERE id = %s",
                [json.dumps({"approvedMonthlySalary": "1.00"}), snapshot.id.hex],
            )

        with self.assertRaises(PayrollCalculationError) as caught:
            self.service.calculate(
                period_id=self.period.id,
                batch_no="CALC-TAMPER",
                idempotency_key="idem-calc-tamper",
            )

        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_SNAPSHOT_TAMPERED")
        self.assertFalse(PayrollResultFact.objects.exists())

    @override_settings(HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS)
    def test_snapshot_orm_bulk_mutation_is_blocked(self):
        snapshot = self.service.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )

        with self.assertRaisesMessage(ValueError, "PAYROLL_INPUT_IMMUTABLE"):
            PayrollInputSnapshot.objects.filter(id=snapshot.id).update(
                variables_json={"approvedMonthlySalary": "1.00"}
            )
        with self.assertRaisesMessage(ValueError, "PAYROLL_INPUT_IMMUTABLE"):
            PayrollInputSnapshot.objects.filter(id=snapshot.id).delete()
        snapshot.variables_json = {"approvedMonthlySalary": "1.00"}
        with self.assertRaisesMessage(ValueError, "PAYROLL_INPUT_IMMUTABLE"):
            PayrollInputSnapshot.objects.bulk_update([snapshot], ["variables_json"])

    @override_settings(
        HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS,
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TrustedSandboxPaymentProvider"
            )
        },
    )
    def test_payslip_publish_rejects_result_without_input_evidence(self):
        result = PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no="UNTRUSTED-DIRECT-RESULT",
            payroll_period_id=self.period.id,
            staff_id=self.staff_id,
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("0.00"),
            net_amount=Decimal("10000.00"),
            status=PayrollResultFact.Status.FINALIZED,
        )
        self.period.status = PayrollPeriod.Status.FINALIZED
        self.period.save(update_fields=["status", "updated_at"])
        payment = PayrollPaymentService(self.tenant_id, actor_user_id=self.actor_id)
        instruction = payment.create_instruction(
            result_id=result.id,
            instruction_no="PAY-UNTRUSTED-RESULT",
            provider_code="SANDBOX_BANK",
        )
        payment.dispatch(instruction_id=instruction.id)
        payment.ingest_provider_receipt(
            instruction_id=instruction.id,
            provider_payload={
                "tenantId": self.tenant_id,
                "instructionId": str(instruction.id),
                "instructionNo": instruction.instruction_no,
                "providerCode": instruction.provider_code,
                "receiptNo": "BANK-UNTRUSTED-RESULT",
                "status": "ACCEPTED",
                "settledAmount": "10000.00",
                "currencyCode": "CNY",
                "idempotencyKey": f"hr15:{self.tenant_id}:{instruction.id}",
            },
        )

        with self.assertRaises(PayrollPaymentError) as caught:
            payment.publish_payslip(
                result_id=result.id,
                payslip_no="PAYSLIP-UNTRUSTED-RESULT",
            )

        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_EVIDENCE_REQUIRED")


class PayrollInputSnapshotMigrationContractTests(SimpleTestCase):
    def test_mysql_trigger_migration_is_non_atomic_and_reversible(self):
        module = importlib.import_module(
            "hr_payroll.migrations.0010_trusted_input_snapshot_boundary"
        )
        source = inspect.getsource(module)

        self.assertIs(module.Migration.atomic, False)
        self.assertIn("BEFORE UPDATE", source)
        self.assertIn("BEFORE DELETE", source)
        self.assertIn("DROP TRIGGER IF EXISTS", source)
        self.assertIn("reverse_code=drop_snapshot_triggers", source)
