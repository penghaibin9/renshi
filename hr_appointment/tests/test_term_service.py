import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentPublicityRecord,
    PositionAppointmentFact,
)
from hr_appointment.services.term_service import AppointmentTermError, AppointmentTermService
from hr_appointment.term_models import AppointmentChangeCase, AppointmentRenewalCase, AppointmentTerm


class AppointmentTermServiceTests(TestCase):
    tenant_id = 77

    def _effective_fact(self):
        case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"CASE-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            position_instance_id=101,
            batch_no="B-2026",
            requested_level_code="L7",
            status=AppointmentApplicationCase.Status.PUBLICITY,
        )
        clock = timezone.now()
        publicity = AppointmentPublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no=f"PUB-{uuid.uuid4().hex[:8]}",
            application_case_id=case.id,
            ranking_result_id=uuid.uuid4(),
            batch_no=case.batch_no,
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            attempt_no=1,
            start_at=clock - timedelta(days=2),
            end_at=clock - timedelta(days=1),
            status=AppointmentPublicityRecord.Status.CLOSED,
            opened_by=9,
            closed_by=9,
            closed_at=clock - timedelta(days=1),
        )
        decision = AppointmentCollectiveDecision.objects.create(
            tenant_id=self.tenant_id,
            decision_no=f"DEC-{uuid.uuid4().hex[:8]}",
            application_case_id=case.id,
            publicity=publicity,
            batch_no=case.batch_no,
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
            authority_ref="TEST-COLLECTIVE-AUTHORITY",
            decision_reason="approved prerequisite for term governance fixture",
            evidence_snapshot_json={"source": "test"},
            decided_at=clock,
            created_by=9,
        )
        fact = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=f"APT-{uuid.uuid4().hex[:8]}",
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            application_case_id=case.id,
            level_code="L7",
            effective_from=date(2026, 9, 1),
            effective_to=date(2029, 9, 1),
            effect_receipt_json={
                "hr03AssignmentId": "A-1",
                "hr14CollectiveDecisionId": str(decision.id),
            },
            created_by=9,
            updated_by=9,
        )
        fact.seal(
            status=PositionAppointmentFact.Status.EFFECTIVE,
            actor_user_id=9,
            authority_receipt={
                "permissionCode": "hr.appointment.fact.publish",
                "authorityRef": str(decision.id),
            },
        )
        case.status = AppointmentApplicationCase.Status.EFFECTIVE
        case.save(update_fields=["status", "updated_at"])
        return case, fact

    def _term(self):
        _, fact = self._effective_fact()
        return AppointmentTermService(self.tenant_id, actor_user_id=9).register_from_effective_fact(
            appointment_fact_id=fact.id,
            term_no=f"TERM-{uuid.uuid4().hex[:8]}",
            renewal_due_at=date(2029, 6, 1),
        )

    def test_register_term_is_idempotent_and_freezes_basis(self):
        _, fact = self._effective_fact()
        service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        first = service.register_from_effective_fact(
            appointment_fact_id=fact.id,
            term_no="TERM-001",
            renewal_due_at=date(2029, 6, 1),
        )
        second = service.register_from_effective_fact(
            appointment_fact_id=fact.id,
            term_no="TERM-001",
            renewal_due_at=date(2029, 6, 1),
        )
        self.assertEqual(first.id, second.id)
        first.effective_to = date(2030, 9, 1)
        with self.assertRaisesRegex(ValueError, "term basis must be superseded"):
            first.save()

    def test_renewal_never_overwrites_old_term_and_requires_new_case(self):
        term = self._term()
        old_end = term.effective_to
        service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        renewal = service.open_renewal(
            term_id=term.id,
            renewal_no="REN-001",
            route=AppointmentRenewalCase.Route.DIRECT_RENEWAL,
            proposed_effective_from=old_end,
            proposed_effective_to=old_end + timedelta(days=365 * 3),
        )
        decision = service.decide_renewal(
            renewal.id,
            outcome=AppointmentRenewalCase.Status.APPROVED,
            decision_snapshot={"decision": "renew"},
        )
        term.refresh_from_db()
        self.assertEqual(term.effective_to, old_end)
        self.assertEqual(term.status, AppointmentTerm.Status.RENEWAL_IN_PROGRESS)
        self.assertEqual(decision.renewal.status, AppointmentRenewalCase.Status.APPROVED)
        self.assertIsNone(decision.renewal.successor_fact_id)
        self.assertIsNone(decision.renewal.successor_term_id)

    def test_direct_renewal_cannot_silently_change_appointment_level(self):
        term = self._term()
        with self.assertRaisesRegex(
            AppointmentTermError,
            "formal appointment change workflow",
        ):
            AppointmentTermService(self.tenant_id).open_renewal(
                term_id=term.id,
                renewal_no="REN-LEVEL-BYPASS",
                route=AppointmentRenewalCase.Route.DIRECT_RENEWAL,
                proposed_effective_from=term.effective_to,
                proposed_effective_to=term.effective_to + timedelta(days=365),
                proposed_level_code="L6",
            )
        self.assertFalse(
            AppointmentRenewalCase.objects.filter(
                tenant_id=self.tenant_id,
                renewal_no="REN-LEVEL-BYPASS",
            ).exists()
        )

    def test_term_assessment_renewal_cannot_silently_change_appointment_level(self):
        term = self._term()
        with self.assertRaisesRegex(
            AppointmentTermError,
            "formal appointment change workflow",
        ):
            AppointmentTermService(self.tenant_id).open_renewal(
                term_id=term.id,
                renewal_no="REN-HR12-LEVEL-BYPASS",
                route=AppointmentRenewalCase.Route.TERM_ASSESSMENT,
                proposed_effective_from=term.effective_to,
                proposed_effective_to=term.effective_to + timedelta(days=365),
                proposed_level_code="L6",
                hr12_term_result_ref="HR12-FINAL-2029-001",
            )

    def test_reappointment_route_may_propose_different_level_but_never_effects_directly(self):
        term = self._term()
        renewal = AppointmentTermService(self.tenant_id).open_renewal(
            term_id=term.id,
            renewal_no="REN-REAPPOINT-L6",
            route=AppointmentRenewalCase.Route.REAPPOINTMENT,
            proposed_effective_from=term.effective_to,
            proposed_effective_to=term.effective_to + timedelta(days=365),
            proposed_level_code="L6",
        )
        term.refresh_from_db()
        self.assertEqual(renewal.proposed_level_code, "L6")
        self.assertEqual(
            renewal.status,
            AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED,
        )
        self.assertEqual(term.status, AppointmentTerm.Status.REAPPOINTMENT_REQUIRED)
        self.assertIsNone(renewal.successor_fact_id)
        self.assertIsNone(renewal.successor_term_id)

    def test_term_assessment_route_fails_closed_without_hr12_final_result(self):
        term = self._term()
        with self.assertRaisesRegex(AppointmentTermError, "HR12 final term assessment"):
            AppointmentTermService(self.tenant_id).open_renewal(
                term_id=term.id,
                renewal_no="REN-HR12",
                route=AppointmentRenewalCase.Route.TERM_ASSESSMENT,
                proposed_effective_from=term.effective_to,
                proposed_effective_to=term.effective_to + timedelta(days=365),
                hr12_term_result_ref="",
            )

    def test_renewal_overlap_is_rejected(self):
        term = self._term()
        with self.assertRaisesRegex(AppointmentTermError, "must not silently overlap"):
            AppointmentTermService(self.tenant_id).open_renewal(
                term_id=term.id,
                renewal_no="REN-OVERLAP",
                route=AppointmentRenewalCase.Route.DIRECT_RENEWAL,
                proposed_effective_from=term.effective_to - timedelta(days=1),
                proposed_effective_to=term.effective_to + timedelta(days=365),
            )

    def test_change_approval_is_not_term_effect(self):
        term = self._term()
        old_position = term.position_instance_id
        old_level = term.level_code
        service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        change = service.open_change(
            term_id=term.id,
            change_no="CHG-001",
            change_type=AppointmentChangeCase.ChangeType.PROMOTION,
            effective_date=date(2027, 9, 1),
            target_level_code="L6",
            reason="岗位等级晋升",
        )
        outcome = service.decide_change(
            change.id,
            outcome=AppointmentChangeCase.Status.APPROVED,
            decision_snapshot={"decision": "approved"},
        )
        term.refresh_from_db()
        self.assertEqual(term.position_instance_id, old_position)
        self.assertEqual(term.level_code, old_level)
        self.assertEqual(outcome.change.status, AppointmentChangeCase.Status.APPROVED)
        self.assertIsNone(outcome.change.successor_fact_id)
        self.assertIsNone(outcome.change.successor_term_id)

    def test_termination_requires_reason(self):
        term = self._term()
        with self.assertRaisesRegex(AppointmentTermError, "requires a reason"):
            AppointmentTermService(self.tenant_id).open_change(
                term_id=term.id,
                change_no="TERM-END-001",
                change_type=AppointmentChangeCase.ChangeType.TERMINATION,
                effective_date=date(2027, 1, 1),
                reason="",
            )

    def test_term_cannot_expire_early(self):
        term = self._term()
        with self.assertRaisesRegex(AppointmentTermError, "cannot expire before"):
            AppointmentTermService(self.tenant_id).mark_expired(
                term.id,
                as_of=term.effective_to - timedelta(days=1),
            )
