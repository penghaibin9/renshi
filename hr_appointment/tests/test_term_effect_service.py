import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentPublicityRecord,
    PositionAppointmentFact,
)
from hr_appointment.services.term_effect_service import (
    AppointmentTermEffectError,
    AppointmentTermEffectService,
)
from hr_appointment.services.term_service import AppointmentTermService
from hr_appointment.term_models import AppointmentChangeCase, AppointmentRenewalCase, AppointmentTerm


class AppointmentTermEffectServiceTests(TestCase):
    tenant_id = 77

    def _source(self):
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
            decision_reason="approved prerequisite for term effect fixture",
            evidence_snapshot_json={"source": "test"},
            decided_at=clock,
            created_by=9,
        )
        fact = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=f"APT-{uuid.uuid4().hex[:8]}",
            person_id=case.person_id,
            position_instance_id=101,
            application_case_id=case.id,
            level_code="L7",
            effective_from=date(2026, 9, 1),
            effective_to=date(2029, 9, 1),
            effect_receipt_json={
                "hr03AssignmentId": "old-assignment",
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
        term = AppointmentTermService(
            self.tenant_id, actor_user_id=9
        ).register_from_effective_fact(
            appointment_fact_id=fact.id,
            term_no=f"TERM-{uuid.uuid4().hex[:8]}",
            renewal_due_at=date(2029, 6, 1),
        )
        return case, fact, term

    def _assignment(self, *, position_id=101):
        return SimpleNamespace(
            id=uuid.uuid4(),
            position_id_id=position_id,
            employment_relationship_id=SimpleNamespace(id=uuid.uuid4()),
        )

    def test_approved_renewal_applies_successor_fact_and_term(self):
        _, source_fact, source_term = self._source()
        term_service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        renewal = term_service.open_renewal(
            term_id=source_term.id,
            renewal_no="REN-001",
            route=AppointmentRenewalCase.Route.DIRECT_RENEWAL,
            proposed_effective_from=source_term.effective_to,
            proposed_effective_to=source_term.effective_to + timedelta(days=365 * 3),
            proposed_level_code="L7",
        )
        term_service.decide_renewal(
            renewal.id,
            outcome=AppointmentRenewalCase.Status.APPROVED,
            decision_snapshot={"decision": "renew"},
        )

        service = AppointmentTermEffectService(self.tenant_id, actor_user_id=9)
        with patch.object(
            service,
            "_current_primary_assignment",
            return_value=self._assignment(),
        ):
            result = service.apply_renewal(
                renewal.id,
                appointment_no="APT-REN-001",
                successor_term_no="TERM-REN-001",
                renewal_due_at=date(2032, 6, 1),
            )

        renewal.refresh_from_db()
        source_term.refresh_from_db()
        source_fact.refresh_from_db()
        self.assertTrue(result.applied)
        self.assertEqual(result.fact.supersedes_fact_id, source_fact.id)
        self.assertEqual(result.fact.status, PositionAppointmentFact.Status.EFFECTIVE)
        self.assertEqual(result.term.supersedes_term_id, source_term.id)
        self.assertEqual(result.term.appointment_fact_id, result.fact.id)
        self.assertEqual(source_term.status, AppointmentTerm.Status.RENEWED)
        self.assertEqual(renewal.status, AppointmentRenewalCase.Status.APPLIED)
        self.assertEqual(renewal.successor_fact_id, result.fact.id)
        self.assertEqual(renewal.successor_term_id, result.term.id)
        self.assertEqual(
            result.fact.effect_receipt_json["hr03Effect"],
            "VERIFIED_UNCHANGED_POSITION",
        )

    def test_promotion_closes_old_fact_and_supersedes_term(self):
        _, source_fact, source_term = self._source()
        term_service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        change = term_service.open_change(
            term_id=source_term.id,
            change_no="CHG-PROMOTE-001",
            change_type=AppointmentChangeCase.ChangeType.PROMOTION,
            effective_date=date(2027, 9, 1),
            target_level_code="L6",
            reason="岗位等级晋升",
        )
        term_service.decide_change(
            change.id,
            outcome=AppointmentChangeCase.Status.APPROVED,
            decision_snapshot={"decision": "approved"},
        )

        service = AppointmentTermEffectService(self.tenant_id, actor_user_id=9)
        with patch.object(
            service,
            "_current_primary_assignment",
            return_value=self._assignment(),
        ):
            result = service.apply_change(
                change.id,
                appointment_no="APT-PROMOTE-001",
                successor_term_no="TERM-PROMOTE-001",
            )

        change.refresh_from_db()
        source_fact.refresh_from_db()
        source_term.refresh_from_db()
        self.assertEqual(source_fact.effective_to, date(2029, 9, 1))
        self.assertEqual(result.fact.position_instance_id, 101)
        self.assertEqual(result.fact.level_code, "L6")
        self.assertEqual(result.fact.supersedes_fact_id, source_fact.id)
        self.assertEqual(result.term.supersedes_term_id, source_term.id)
        self.assertEqual(source_term.status, AppointmentTerm.Status.SUPERSEDED)
        self.assertEqual(change.status, AppointmentChangeCase.Status.APPLIED)

    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_termination_closes_hr03_assignment_and_creates_terminal_fact(
        self, assignment_service_cls
    ):
        _, source_fact, source_term = self._source()
        term_service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        change = term_service.open_change(
            term_id=source_term.id,
            change_no="CHG-END-001",
            change_type=AppointmentChangeCase.ChangeType.TERMINATION,
            effective_date=date(2027, 6, 1),
            reason="聘任终止",
        )
        term_service.decide_change(
            change.id,
            outcome=AppointmentChangeCase.Status.APPROVED,
            decision_snapshot={"decision": "approved"},
        )
        current_assignment = self._assignment()
        assignment_service_cls.return_value.close_assignment.return_value = current_assignment

        service = AppointmentTermEffectService(self.tenant_id, actor_user_id=9)
        with patch.object(
            service,
            "_current_primary_assignment",
            return_value=current_assignment,
        ):
            result = service.apply_change(
                change.id,
                appointment_no="APT-END-001",
            )

        source_fact.refresh_from_db()
        source_term.refresh_from_db()
        change.refresh_from_db()
        self.assertTrue(result.applied)
        self.assertIsNone(result.term)
        self.assertEqual(result.fact.status, PositionAppointmentFact.Status.ENDED)
        self.assertEqual(source_fact.effective_to, date(2029, 9, 1))
        self.assertEqual(source_term.status, AppointmentTerm.Status.TERMINATED)
        self.assertEqual(change.status, AppointmentChangeCase.Status.APPLIED)
        self.assertIsNone(change.successor_term_id)
        assignment_service_cls.return_value.close_assignment.assert_called_once_with(
            assignment_id=current_assignment.id,
            effective_to=date(2027, 6, 1),
            reason_code="HR14_APPOINTMENT_TERMINATION",
            source_business_type="HR14_APPOINTMENT",
            source_business_id=str(result.fact.id),
        )

    def test_transfer_fails_closed_without_hr02_reservation(self):
        _, _, source_term = self._source()
        term_service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        change = term_service.open_change(
            term_id=source_term.id,
            change_no="CHG-TRANSFER-001",
            change_type=AppointmentChangeCase.ChangeType.TRANSFER,
            effective_date=date(2027, 6, 1),
            target_position_instance_id=202,
            reason="调岗",
        )
        term_service.decide_change(
            change.id,
            outcome=AppointmentChangeCase.Status.APPROVED,
            decision_snapshot={"decision": "approved"},
        )

        service = AppointmentTermEffectService(self.tenant_id, actor_user_id=9)
        with patch.object(
            service,
            "_current_primary_assignment",
            return_value=self._assignment(),
        ), patch.object(
            service,
            "_target_position",
            return_value=SimpleNamespace(id=202),
        ):
            with self.assertRaisesRegex(
                AppointmentTermEffectError, "requires an HR02 HELD reservation"
            ):
                service.apply_change(
                    change.id,
                    appointment_no="APT-TRANSFER-001",
                    successor_term_no="TERM-TRANSFER-001",
                )

        change.refresh_from_db()
        self.assertEqual(change.status, AppointmentChangeCase.Status.APPROVED)
        self.assertFalse(
            PositionAppointmentFact.objects.filter(
                tenant_id=self.tenant_id,
                appointment_no="APT-TRANSFER-001",
            ).exists()
        )

    def test_correction_remains_fail_closed_without_explicit_authority_payload(self):
        _, _, source_term = self._source()
        term_service = AppointmentTermService(self.tenant_id, actor_user_id=9)
        change = term_service.open_change(
            term_id=source_term.id,
            change_no="CHG-CORRECT-001",
            change_type=AppointmentChangeCase.ChangeType.CORRECTION,
            effective_date=date(2027, 6, 1),
            reason="正式更正",
        )
        term_service.decide_change(
            change.id,
            outcome=AppointmentChangeCase.Status.APPROVED,
            decision_snapshot={"decision": "approved"},
        )

        with self.assertRaisesRegex(
            AppointmentTermEffectError, "explicit correction authority"
        ):
            AppointmentTermEffectService(self.tenant_id).apply_change(
                change.id,
                appointment_no="APT-CORRECT-001",
                successor_term_no="TERM-CORRECT-001",
            )
