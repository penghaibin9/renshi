"""HR15 benefit and occupational-pension Authority services."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_models import BenefitEnrollmentFact, BenefitPlan, OccupationalPensionContributionFact, OccupationalPensionPeriod, OccupationalPensionPlan, OccupationalPensionSettlementFact
from hr_payroll.authority_registry import EVENT_BENEFIT_ENROLLMENT_EFFECTIVE, EVENT_BENEFIT_PLAN_PUBLISHED, EVENT_PENSION_CONTRIBUTION_FINALIZED, EVENT_PENSION_PLAN_PUBLISHED, EVENT_PENSION_SETTLEMENT_CLOSED
from hr_staff.models import HrStaffMaster


class PayrollAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _hash(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class BenefitPensionAuthorityService:
    def __init__(self, tenant_id: int, *, actor_user_id=None, correlation_id=""):
        if not tenant_id:
            raise PayrollAuthorityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def _staff(self, staff_id):
        staff = HrStaffMaster.objects.filter(id=staff_id, tenant_id=self.tenant_id).first()
        if staff is None:
            raise PayrollAuthorityError("STAFF_NOT_FOUND", "staff not found inside tenant")
        return staff

    def _benefit_plan(self, plan_id, lock=False):
        qs = BenefitPlan.objects.select_for_update() if lock else BenefitPlan.objects
        plan = qs.filter(id=plan_id, tenant_id=self.tenant_id).first()
        if plan is None:
            raise PayrollAuthorityError("BENEFIT_PLAN_NOT_FOUND", "benefit plan not found")
        return plan

    @transaction.atomic
    def create_benefit_plan(self, *, plan_code, version_no, name, benefit_type, effective_from, rule_snapshot, provider_name="", employer_rate=0, employee_rate=0, fixed_amount=0, effective_to=None):
        if effective_to is not None and effective_to <= effective_from:
            raise PayrollAuthorityError("EFFECTIVE_DATE_INVALID", "invalid benefit plan range")
        existing = BenefitPlan.objects.select_for_update().filter(tenant_id=self.tenant_id, plan_code=plan_code, version_no=version_no).first()
        if existing:
            return existing
        return BenefitPlan.objects.create(tenant_id=self.tenant_id, created_by=self.actor_user_id, updated_by=self.actor_user_id, plan_code=plan_code, version_no=version_no, name=name, benefit_type=benefit_type, provider_name=provider_name or "", employer_rate=Decimal(str(employer_rate or 0)), employee_rate=Decimal(str(employee_rate or 0)), fixed_amount=_money(fixed_amount), effective_from=effective_from, effective_to=effective_to, rule_snapshot_json=rule_snapshot or {}, status=BenefitPlan.Status.DRAFT)

    @transaction.atomic
    def publish_benefit_plan(self, plan_id):
        plan = self._benefit_plan(plan_id, lock=True)
        if plan.status == BenefitPlan.Status.PUBLISHED:
            return plan
        if plan.status != BenefitPlan.Status.DRAFT:
            raise PayrollAuthorityError("BENEFIT_PLAN_STATE_INVALID", "only DRAFT plan may be published")
        plan.content_hash = _hash({"planCode": plan.plan_code, "version": plan.version_no, "name": plan.name, "type": plan.benefit_type, "provider": plan.provider_name, "employerRate": plan.employer_rate, "employeeRate": plan.employee_rate, "fixedAmount": plan.fixed_amount, "effectiveFrom": plan.effective_from, "effectiveTo": plan.effective_to, "rules": plan.rule_snapshot_json})
        plan.status = BenefitPlan.Status.PUBLISHED
        plan.updated_by = self.actor_user_id
        plan.save(update_fields=["content_hash", "status", "updated_by", "updated_at"])
        emit_registered_event(tenant_id=self.tenant_id, event_name=EVENT_BENEFIT_PLAN_PUBLISHED, payload={"planId": str(plan.id), "planCode": plan.plan_code, "versionNo": plan.version_no, "effectiveDate": str(plan.effective_from), "contentHash": plan.content_hash}, correlation_id=self.correlation_id)
        return plan

    @transaction.atomic
    def enroll_benefit(self, *, enrollment_no, plan_id, staff_id, effective_from, employer_amount=0, employee_amount=0, effective_to=None, snapshot=None, supersedes_enrollment_id=None):
        plan = self._benefit_plan(plan_id, lock=True)
        if plan.status != BenefitPlan.Status.PUBLISHED:
            raise PayrollAuthorityError("BENEFIT_PLAN_NOT_PUBLISHED", "benefit plan must be published")
        staff = self._staff(staff_id)
        if effective_to is not None and effective_to <= effective_from:
            raise PayrollAuthorityError("EFFECTIVE_DATE_INVALID", "invalid enrollment range")
        prior = None
        if supersedes_enrollment_id:
            prior = BenefitEnrollmentFact.objects.filter(id=supersedes_enrollment_id, tenant_id=self.tenant_id, benefit_plan_id=plan.id, staff_id=staff.id).first()
            if prior is None:
                raise PayrollAuthorityError("BENEFIT_ENROLLMENT_SUPERSEDES_INVALID", "superseded enrollment not found")
        else:
            superseded = BenefitEnrollmentFact.objects.filter(tenant_id=self.tenant_id, supersedes_enrollment_id__isnull=False).values_list("supersedes_enrollment_id", flat=True)
            if BenefitEnrollmentFact.objects.filter(tenant_id=self.tenant_id, benefit_plan_id=plan.id, staff_id=staff.id, effective_to__isnull=True).exclude(id__in=superseded).exists():
                raise PayrollAuthorityError("BENEFIT_ENROLLMENT_ACTIVE_CONFLICT", "active enrollment already exists")
        existing = BenefitEnrollmentFact.objects.filter(tenant_id=self.tenant_id, enrollment_no=enrollment_no).first()
        if existing:
            return existing
        fact = BenefitEnrollmentFact.objects.create(tenant_id=self.tenant_id, created_by=self.actor_user_id, updated_by=self.actor_user_id, enrollment_no=enrollment_no, benefit_plan_id=plan.id, staff_id=staff.id, effective_from=effective_from, effective_to=effective_to, employer_amount=_money(employer_amount), employee_amount=_money(employee_amount), snapshot_json=snapshot or {}, supersedes_enrollment_id=prior.id if prior else None)
        emit_registered_event(tenant_id=self.tenant_id, event_name=EVENT_BENEFIT_ENROLLMENT_EFFECTIVE, payload={"enrollmentId": str(fact.id), "planId": str(plan.id), "staffId": str(staff.id), "effectiveDate": str(effective_from)}, correlation_id=self.correlation_id)
        return fact

    def _pension_plan(self, plan_id, lock=False):
        qs = OccupationalPensionPlan.objects.select_for_update() if lock else OccupationalPensionPlan.objects
        plan = qs.filter(id=plan_id, tenant_id=self.tenant_id).first()
        if plan is None:
            raise PayrollAuthorityError("PENSION_PLAN_NOT_FOUND", "pension plan not found")
        return plan

    @transaction.atomic
    def create_pension_plan(self, *, plan_code, version_no, name, employer_rate, employee_rate, basis_rule, effective_from, effective_to=None):
        if Decimal(str(employer_rate)) < 0 or Decimal(str(employee_rate)) < 0:
            raise PayrollAuthorityError("PENSION_RATE_INVALID", "contribution rates cannot be negative")
        if effective_to is not None and effective_to <= effective_from:
            raise PayrollAuthorityError("EFFECTIVE_DATE_INVALID", "invalid pension plan range")
        existing = OccupationalPensionPlan.objects.select_for_update().filter(tenant_id=self.tenant_id, plan_code=plan_code, version_no=version_no).first()
        if existing:
            return existing
        return OccupationalPensionPlan.objects.create(tenant_id=self.tenant_id, created_by=self.actor_user_id, updated_by=self.actor_user_id, plan_code=plan_code, version_no=version_no, name=name, employer_rate=Decimal(str(employer_rate)), employee_rate=Decimal(str(employee_rate)), contribution_basis_rule_json=basis_rule or {}, effective_from=effective_from, effective_to=effective_to, status=OccupationalPensionPlan.Status.DRAFT)

    @transaction.atomic
    def publish_pension_plan(self, plan_id):
        plan = self._pension_plan(plan_id, lock=True)
        if plan.status == OccupationalPensionPlan.Status.PUBLISHED:
            return plan
        if plan.status != OccupationalPensionPlan.Status.DRAFT:
            raise PayrollAuthorityError("PENSION_PLAN_STATE_INVALID", "only DRAFT plan may be published")
        plan.content_hash = _hash({"planCode": plan.plan_code, "version": plan.version_no, "name": plan.name, "employerRate": plan.employer_rate, "employeeRate": plan.employee_rate, "basisRule": plan.contribution_basis_rule_json, "effectiveFrom": plan.effective_from, "effectiveTo": plan.effective_to})
        plan.status = OccupationalPensionPlan.Status.PUBLISHED
        plan.updated_by = self.actor_user_id
        plan.save(update_fields=["content_hash", "status", "updated_by", "updated_at"])
        emit_registered_event(tenant_id=self.tenant_id, event_name=EVENT_PENSION_PLAN_PUBLISHED, payload={"planId": str(plan.id), "planCode": plan.plan_code, "versionNo": plan.version_no, "effectiveDate": str(plan.effective_from), "contentHash": plan.content_hash}, correlation_id=self.correlation_id)
        return plan

    @transaction.atomic
    def open_pension_period(self, *, plan_id, period_code, start_date, end_date):
        plan = self._pension_plan(plan_id, lock=True)
        if plan.status != OccupationalPensionPlan.Status.PUBLISHED:
            raise PayrollAuthorityError("PENSION_PLAN_NOT_PUBLISHED", "pension plan must be published")
        if end_date <= start_date:
            raise PayrollAuthorityError("PENSION_PERIOD_DATE_INVALID", "end_date must be after start_date")
        period, created = OccupationalPensionPeriod.objects.get_or_create(tenant_id=self.tenant_id, plan_id=plan.id, period_code=period_code, defaults={"start_date": start_date, "end_date": end_date, "created_by": self.actor_user_id, "updated_by": self.actor_user_id})
        if not created and (period.start_date != start_date or period.end_date != end_date):
            raise PayrollAuthorityError("PENSION_PERIOD_IDEMPOTENCY_CONFLICT", "period code already has different dates")
        return period

    @transaction.atomic
    def record_pension_contribution(self, *, contribution_no, period_id, staff_id, basis_amount, supersedes_contribution_id=None, snapshot=None):
        period = OccupationalPensionPeriod.objects.select_for_update().filter(id=period_id, tenant_id=self.tenant_id).first()
        if period is None:
            raise PayrollAuthorityError("PENSION_PERIOD_NOT_FOUND", "pension period not found")
        if period.status != OccupationalPensionPeriod.Status.OPEN:
            raise PayrollAuthorityError("PENSION_PERIOD_CLOSED", "closed period cannot accept contributions")
        plan = self._pension_plan(period.plan_id)
        staff = self._staff(staff_id)
        existing = OccupationalPensionContributionFact.objects.filter(tenant_id=self.tenant_id, contribution_no=contribution_no).first()
        if existing:
            return existing
        prior = None
        sequence_no = 1
        if supersedes_contribution_id:
            prior = OccupationalPensionContributionFact.objects.filter(id=supersedes_contribution_id, tenant_id=self.tenant_id, pension_period_id=period.id, staff_id=staff.id).first()
            if prior is None:
                raise PayrollAuthorityError("PENSION_CONTRIBUTION_SUPERSEDES_INVALID", "prior contribution not found")
            sequence_no = prior.sequence_no + 1
        elif OccupationalPensionContributionFact.objects.filter(tenant_id=self.tenant_id, pension_period_id=period.id, staff_id=staff.id).exists():
            raise PayrollAuthorityError("PENSION_CONTRIBUTION_ACTIVE_CONFLICT", "base contribution already exists")
        basis = _money(basis_amount)
        employer = _money(basis * plan.employer_rate)
        employee = _money(basis * plan.employee_rate)
        fact = OccupationalPensionContributionFact.objects.create(tenant_id=self.tenant_id, created_by=self.actor_user_id, updated_by=self.actor_user_id, contribution_no=contribution_no, pension_period_id=period.id, pension_plan_id=plan.id, staff_id=staff.id, sequence_no=sequence_no, basis_amount=basis, employer_amount=employer, employee_amount=employee, total_amount=employer + employee, supersedes_contribution_id=prior.id if prior else None, snapshot_json={"planVersion": plan.version_no, "employerRate": str(plan.employer_rate), "employeeRate": str(plan.employee_rate), **(snapshot or {})})
        emit_registered_event(tenant_id=self.tenant_id, event_name=EVENT_PENSION_CONTRIBUTION_FINALIZED, payload={"contributionId": str(fact.id), "periodId": str(period.id), "staffId": str(staff.id), "sequenceNo": fact.sequence_no}, correlation_id=self.correlation_id)
        return fact

    @transaction.atomic
    def close_pension_period(self, *, period_id, settlement_no):
        period = OccupationalPensionPeriod.objects.select_for_update().filter(id=period_id, tenant_id=self.tenant_id).first()
        if period is None:
            raise PayrollAuthorityError("PENSION_PERIOD_NOT_FOUND", "pension period not found")
        if period.status == OccupationalPensionPeriod.Status.CLOSED:
            settlement = OccupationalPensionSettlementFact.objects.filter(tenant_id=self.tenant_id, pension_period_id=period.id).first()
            if settlement and settlement.settlement_no == settlement_no:
                return settlement
            raise PayrollAuthorityError("PENSION_SETTLEMENT_IDEMPOTENCY_CONFLICT", "period already closed with another settlement")
        qs = OccupationalPensionContributionFact.objects.filter(tenant_id=self.tenant_id, pension_period_id=period.id)
        superseded_ids = qs.exclude(supersedes_contribution_id__isnull=True).values_list("supersedes_contribution_id", flat=True)
        current = qs.exclude(id__in=superseded_ids)
        totals = current.aggregate(contribution_count=Count("id"), staff_count=Count("staff_id", distinct=True), employer_total=Sum("employer_amount"), employee_total=Sum("employee_amount"), grand_total=Sum("total_amount"))
        closed_at = timezone.now()
        settlement = OccupationalPensionSettlementFact.objects.create(tenant_id=self.tenant_id, created_by=self.actor_user_id, updated_by=self.actor_user_id, settlement_no=settlement_no, pension_period_id=period.id, pension_plan_id=period.plan_id, contribution_count=totals["contribution_count"] or 0, staff_count=totals["staff_count"] or 0, employer_total=totals["employer_total"] or Decimal("0.00"), employee_total=totals["employee_total"] or Decimal("0.00"), grand_total=totals["grand_total"] or Decimal("0.00"), snapshot_json={"periodCode": period.period_code, "currentContributionIds": [str(x) for x in current.values_list("id", flat=True)]}, closed_at=closed_at)
        period.status = OccupationalPensionPeriod.Status.CLOSED
        period.closed_at = closed_at
        period.updated_by = self.actor_user_id
        period.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
        emit_registered_event(tenant_id=self.tenant_id, event_name=EVENT_PENSION_SETTLEMENT_CLOSED, payload={"settlementId": str(settlement.id), "periodId": str(period.id), "contributionCount": settlement.contribution_count, "staffCount": settlement.staff_count, "closedAt": closed_at.isoformat()}, correlation_id=self.correlation_id)
        return settlement
