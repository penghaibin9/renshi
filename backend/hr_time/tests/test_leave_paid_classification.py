"""MySQL contracts: published school rule -> approved absence -> close basis.

Policies/calendar/identity are synthetic prerequisites. Approval, reservation,
usage and close facts are created by production services, never prefilled.
"""
from datetime import date, timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, RequestFactory

from hr_staff.models import HrPerson, HrStaffMaster
from hr_time.api.workbench import provision_leave_account
from hr_time.models import (
    HrAbsenceFact, HrCalendarDay, HrLeaveAccount, HrLeaveLedgerEntry,
    HrLeavePolicyPack, HrLeavePolicyVersion, HrLeaveRequest, HrLeaveType,
    HrPayrollTimeBasis, HrScheduleAssignment, HrTimeClosePeriod,
    HrTimeCloseSnapshot, HrWorkCalendar, HrWorkCalendarVersion,
)
from hr_time.services.calendar_service import CalendarService
from hr_time.services.close_service import CloseService, CloseServiceError
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.services.leave_request_service import LeaveRequestError, LeaveRequestService
from hr_time.services.schedule_service import ScheduleService

DAY = date(2026, 9, 7)


class LeavePaidClassificationTests(TestCase):
    tenant_id = 803
    staff_id = 9003

    def setUp(self):
        calendar = HrWorkCalendar.objects.create(
            tenant_id=self.tenant_id, code="CLASSIFICATION-CAL", name="计薪口径验收日历"
        )
        version = HrWorkCalendarVersion.objects.create(
            tenant_id=self.tenant_id, calendar=calendar, year=DAY.year,
            version_no=1, source_ref="isolated school calendar fixture",
        )
        HrCalendarDay.objects.create(
            tenant_id=self.tenant_id, calendar_version=version, date=DAY,
            day_type="REGULAR_WORKDAY", is_working_day=True, expected_work_minutes=480,
        )
        CalendarService.publish_version(version)
        ScheduleService.create_assignment(HrScheduleAssignment(
            tenant_id=self.tenant_id, staff_master_id=self.staff_id,
            calendar_version=version, effective_from=DAY,
            effective_to=DAY + timedelta(days=1), source="CLASSIFICATION_CONTRACT",
        ))
        self.period = HrTimeClosePeriod.objects.create(
            tenant_id=self.tenant_id, start_date=DAY, end_date=DAY,
        )

    def policy(self, classification="PAID", *, tenant_id=None, code="TEST", rules=None, publish=True):
        tenant = self.tenant_id if tenant_id is None else tenant_id
        leave_type = HrLeaveType.objects.create(
            tenant_id=tenant, code=code, name="校本假别", unit="DAYS",
            category="OTHER", paid_classification=classification,
        )
        pack = HrLeavePolicyPack.objects.create(tenant_id=tenant, code=code, name="校本版本")
        policy = HrLeavePolicyVersion.objects.create(
            tenant_id=tenant, leave_policy_pack=pack, leave_type=leave_type,
            version_no=1, status="DRAFT", effective_from=DAY,
            interaction_rules={} if rules is None else rules,
        )
        if publish:
            policy.status = "PUBLISHED"
            policy.save()
        return policy

    def submitted(self, policy):
        grant = LeaveAccountService.grant(
            tenant_id=self.tenant_id, staff_master_id=self.staff_id,
            leave_type_id=policy.leave_type_id, account_year=DAY.year,
            amount=5, effective_date=DAY, policy_version_id=policy.pk,
        )
        request = HrLeaveRequest.objects.create(
            tenant_id=self.tenant_id, staff_master_id=self.staff_id,
            leave_type_id=policy.leave_type_id, policy_version_id=policy.pk,
            account_id=grant.account_id, start_at=DAY, end_at=DAY,
            requested_amount=1, unit="DAYS",
        )
        LeaveRequestService.submit(request)
        self.assertEqual(request.calculation_snapshot["scheduledMinutes"], 480)
        return request

    def test_paid_approval_and_month_close_use_published_rule(self):
        policy = self.policy("PAID")
        request = self.submitted(policy)
        fact = LeaveRequestService.approve(request)
        self.assertEqual(fact.paid_classification, "PAID")
        self.assertEqual(fact.effective_snapshot["paidClassificationBasis"]["policyContentHash"], policy.content_hash)
        self.assertEqual(len(policy.content_hash), 64)
        snapshot = CloseService.close(tenant_id=self.tenant_id, period=self.period)
        basis = HrPayrollTimeBasis.objects.get(close_snapshot=snapshot, staff_master_id=self.staff_id)
        self.assertEqual(basis.payable_authorized_absence_minutes, 480)
        self.assertEqual(basis.unpaid_absence_minutes, 0)
        self.assertEqual(HrAbsenceFact.objects.filter(leave_request=request).count(), 1)

    def test_explicit_version_rule_wins_over_catalogue_and_unpaid_basis(self):
        policy = self.policy("PAID", rules={"paidClassification": "UNPAID"})
        fact = LeaveRequestService.approve(self.submitted(policy))
        self.assertEqual(fact.paid_classification, "UNPAID")
        snapshot = CloseService.close(tenant_id=self.tenant_id, period=self.period)
        basis = HrPayrollTimeBasis.objects.get(close_snapshot=snapshot, staff_master_id=self.staff_id)
        self.assertEqual(basis.unpaid_absence_minutes, 480)
        self.assertEqual(basis.payable_authorized_absence_minutes, 0)

    def test_catalogue_change_does_not_reinterpret_submitted_policy(self):
        policy = self.policy("PAID")
        request = self.submitted(policy)
        policy.leave_type.paid_classification = "UNPAID"
        policy.leave_type.save(update_fields=["paid_classification"])
        fact = LeaveRequestService.approve(request)
        self.assertEqual(fact.paid_classification, "PAID")
        policy.refresh_from_db()
        self.assertEqual(policy.interaction_rules["paidClassification"], "PAID")

    def test_unknown_classification_blocks_close_without_manufacturing_a_basis(self):
        policy = self.policy("POLICY_DEPENDENT")
        request = self.submitted(policy)
        fact = LeaveRequestService.approve(request)
        self.assertEqual(fact.paid_classification, "POLICY_DEPENDENT")
        with self.assertRaises(CloseServiceError) as caught:
            CloseService.close(tenant_id=self.tenant_id, period=self.period)
        self.assertEqual(caught.exception.code, "TIME_CLOSE_BLOCKED")
        self.assertEqual(caught.exception.blockers, [{"code": "UNRESOLVED_ABSENCE_CLASSIFICATION", "count": 1}])
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, "OPEN")
        self.assertFalse(HrTimeCloseSnapshot.objects.filter(period=self.period).exists())
        self.assertFalse(HrPayrollTimeBasis.objects.filter(tenant_id=self.tenant_id).exists())

    def test_retired_published_version_still_governs_pending_request(self):
        policy = self.policy("PAID")
        request = self.submitted(policy)
        original_hash = policy.content_hash
        policy.status = "RETIRED"
        policy.save(update_fields=["status"])
        fact = LeaveRequestService.approve(request)
        self.assertEqual(fact.paid_classification, "PAID")
        self.assertEqual(fact.effective_snapshot["paidClassificationBasis"]["policyContentHash"], original_hash)

    def test_replayed_approval_does_not_reclassify_or_duplicate_ledger(self):
        policy = self.policy("PAID")
        request = self.submitted(policy)
        first = LeaveRequestService.approve(request)
        count = HrLeaveLedgerEntry.objects.filter(account=request.account).count()
        policy.leave_type.paid_classification = "UNPAID"
        policy.leave_type.save(update_fields=["paid_classification"])
        again = LeaveRequestService.approve(request)
        self.assertEqual((again.pk, again.paid_classification), (first.pk, "PAID"))
        self.assertEqual(HrLeaveLedgerEntry.objects.filter(account=request.account).count(), count)

    def test_cross_school_policy_rejected_before_ledger_and_fact_writes(self):
        request = self.submitted(self.policy())
        foreign = self.policy(tenant_id=804)
        self._assert_invalid_policy_is_atomic(request, foreign.pk, "CROSS_TENANT_REFERENCE")

    def test_different_leave_type_policy_rejected_before_writes(self):
        request = self.submitted(self.policy())
        other_type = self.policy(code="OTHER-TYPE")
        self._assert_invalid_policy_is_atomic(request, other_type.pk, "CROSS_TENANT_REFERENCE")

    def test_unpublished_policy_rejected_before_writes(self):
        policy = self.policy()
        request = self.submitted(policy)
        draft = HrLeavePolicyVersion.objects.create(
            tenant_id=self.tenant_id, leave_policy_pack=policy.leave_policy_pack,
            leave_type=policy.leave_type, version_no=2, effective_from=DAY,
        )
        self._assert_invalid_policy_is_atomic(request, draft.pk, "LEAVE_POLICY_NOT_PUBLISHED")

    def _assert_invalid_policy_is_atomic(self, request, policy_id, expected_code):
        # Negative fixture: simulate a stale/corrupt submitted reference. Never
        # bypass the approval service to create the final absence or usage facts.
        request.policy_version_id = policy_id
        request.save(update_fields=["policy_version_id"])
        ledger_count = HrLeaveLedgerEntry.objects.filter(account=request.account).count()
        with self.assertRaises(LeaveRequestError) as caught:
            LeaveRequestService.approve(request)
        self.assertEqual(caught.exception.code, expected_code)
        request.refresh_from_db()
        self.assertEqual(request.status, "SUBMITTED")
        self.assertFalse(HrAbsenceFact.objects.filter(leave_request=request).exists())
        self.assertEqual(HrLeaveLedgerEntry.objects.filter(account=request.account).count(), ledger_count)

    def test_publish_with_update_fields_persists_frozen_rule_and_hash(self):
        policy = self.policy("UNPAID", publish=False)
        policy.status = "PUBLISHED"
        policy.save(update_fields=["status"])
        policy.refresh_from_db()
        self.assertEqual(policy.interaction_rules["paidClassification"], "UNPAID")
        self.assertEqual(len(policy.content_hash), 64)
        self.assertIsNotNone(policy.published_at)
        policy.interaction_rules = {"paidClassification": "PAID"}
        policy.status = "RETIRED"
        with self.assertRaises(ValidationError):
            policy.save()

    def test_invalid_classification_cannot_be_published(self):
        policy = self.policy(publish=False)
        for value in ("GUESS", True, {}, []):
            with self.subTest(value=value):
                policy.interaction_rules = {"paidClassification": value}
                policy.status = "PUBLISHED"
                with self.assertRaises(ValidationError):
                    policy.save()
                policy.refresh_from_db()
                self.assertEqual(policy.status, "DRAFT")

    def test_legacy_missing_rule_has_no_mutable_catalogue_fallback(self):
        policy = self.policy("PAID")
        request = self.submitted(policy)
        policy.interaction_rules = {}  # in-memory representation of an old version
        with patch.object(HrLeavePolicyVersion.objects, "filter") as query:
            query.return_value.first.return_value = policy
            basis = LeaveRequestService._paid_classification_basis(request)
        self.assertEqual(basis["paidClassification"], "POLICY_DEPENDENT")
        self.assertEqual(basis["source"], "UNRESOLVED_LEGACY_POLICY")
        policy.refresh_from_db()
        self.assertEqual(policy.interaction_rules["paidClassification"], "PAID")


class LeaveClassificationProvisionTests(TestCase):
    """Canonical view + MySQL contracts; request tenant resolver is isolated."""
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="hr11-classification-api", email="classification@example.invalid", password="isolated-only-secret"
        )
        person = HrPerson.objects.create(tenant_id=803, legal_name="合成校本规则验收人员")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=803, person_id=person, staff_no="CLASS-803", legacy_employee_id=9003
        )
        self.payload = {"staffId": 9003, "accountYear": 2026, "amount": "5",
                        "effectiveDate": "2026-09-07", "leaveTypeCode": "SCHOOL-PAID",
                        "leaveTypeName": "校本明确带薪假", "paidClassification": "PAID"}

    def call(self, payload):
        request = RequestFactory().post("/api/v1/hr/time/leave-accounts/provision", json.dumps(payload), content_type="application/json")
        request.user = self.user
        with patch("hr_time.api.views.resolve_tenant_from_request", return_value=803):
            return provision_leave_account(request)

    def test_provision_freezes_explicit_classification_and_replay_is_idempotent(self):
        first = self.call(self.payload)
        self.assertEqual(first.status_code, 201, first.content)
        policy = HrLeavePolicyVersion.objects.get(tenant_id=803)
        self.assertEqual(policy.interaction_rules["paidClassification"], "PAID")
        old_hash = policy.content_hash
        again = self.call(self.payload)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(HrLeaveLedgerEntry.objects.filter(tenant_id=803).count(), 1)
        policy.refresh_from_db()
        self.assertEqual(policy.content_hash, old_hash)

    def test_invalid_input_rejected_before_any_business_creation(self):
        for value in ("guess", True, None, [], {}):
            response = self.call({**self.payload, "paidClassification": value})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HrLeaveType.objects.filter(tenant_id=803).exists())
        self.assertFalse(HrLeavePolicyVersion.objects.filter(tenant_id=803).exists())
        self.assertFalse(HrLeaveAccount.objects.filter(tenant_id=803).exists())
        self.assertFalse(HrLeaveLedgerEntry.objects.filter(tenant_id=803).exists())

    def test_cross_school_staff_cannot_receive_a_policy_account(self):
        person = HrPerson.objects.create(tenant_id=804, legal_name="其他学校合成人员")
        HrStaffMaster.objects.create(tenant_id=804, person_id=person, staff_no="OTHER-804", legacy_employee_id=9004)
        response = self.call({**self.payload, "staffId": 9004})
        self.assertEqual(response.status_code, 404, response.content)
        self.assertFalse(HrLeavePolicyVersion.objects.filter(tenant_id=803).exists())
        self.assertFalse(HrLeaveAccount.objects.filter(tenant_id=803).exists())
