import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import AppointmentApplicationCase, AppointmentPublicityRecord
from hr_appointment.services.decision_service import (
    AppointmentDecisionError,
    AppointmentDecisionService,
)
from hr_title.models import ProfessionalTitleResult
from hr_title.public import PROVIDER_VERSION


class Hr13ToHr14DecisionEvidenceTests(TestCase):
    @staticmethod
    def _sealed_title_result(**kwargs):
        result = ProfessionalTitleResult(sealed_at=timezone.now(), **kwargs)
        result.content_hash = result.calculate_content_hash()
        result.save()
        return result

    def setUp(self):
        self.person_id = uuid.uuid4()
        self.case = AppointmentApplicationCase.objects.create(
            tenant_id=77,
            case_no="APT-TITLE-001",
            person_id=self.person_id,
            policy_version_id=uuid.uuid4(),
            position_instance_id=1001,
            batch_no="APT-2026",
            requested_level_code="L3",
            status=AppointmentApplicationCase.Status.PUBLICITY,
        )
        now = timezone.now()
        self.publicity = AppointmentPublicityRecord.objects.create(
            tenant_id=77,
            publicity_no="PUB-TITLE-001",
            application_case_id=self.case.id,
            ranking_result_id=uuid.uuid4(),
            batch_no=self.case.batch_no,
            person_id=self.person_id,
            position_instance_id=self.case.position_instance_id,
            attempt_no=1,
            start_at=now - timedelta(days=7),
            end_at=now - timedelta(days=2),
            status=AppointmentPublicityRecord.Status.CLOSED,
            closed_at=now - timedelta(days=1),
        )
        self.title_result = self._sealed_title_result(
            tenant_id=77,
            result_no="TITLE-RESULT-001",
            person_id=self.person_id,
            application_case_id=uuid.uuid4(),
            title_code="ASSOCIATE_PROFESSOR",
            title_name="副教授",
            title_series_code="TEACHING",
            title_level_code="ASSOCIATE",
            effective_from=date(2026, 1, 1),
            status=ProfessionalTitleResult.Status.EFFECTIVE,
        )

    def test_collective_decision_freezes_provider_verified_title_result(self):
        decision, created = AppointmentDecisionService(77, actor_user_id=9).record_with_title_result(
            case_id=self.case.id,
            decision_no="DEC-TITLE-001",
            outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
            authority_ref="committee-minutes-2026-001",
            title_result_id=self.title_result.id,
            as_of=date(2026, 8, 1),
            additional_evidence={"rankingRef": "RANK-001"},
        )

        self.assertTrue(created)
        evidence = decision.evidence_snapshot_json["hr13TitleResult"]
        self.assertEqual(evidence["titleResultId"], str(self.title_result.id))
        self.assertEqual(evidence["personId"], str(self.person_id))
        self.assertEqual(evidence["titleCode"], "ASSOCIATE_PROFESSOR")
        self.assertEqual(evidence["providerVersion"], PROVIDER_VERSION)
        self.assertEqual(evidence["asOf"], "2026-08-01")
        self.assertEqual(decision.evidence_snapshot_json["rankingRef"], "RANK-001")

    def test_wrong_person_or_cross_tenant_title_result_fails_closed(self):
        wrong_person_result = self._sealed_title_result(
            tenant_id=77,
            result_no="TITLE-RESULT-WRONG",
            person_id=uuid.uuid4(),
            application_case_id=uuid.uuid4(),
            title_code="PROFESSOR",
            title_name="教授",
            effective_from=date(2026, 1, 1),
            status=ProfessionalTitleResult.Status.EFFECTIVE,
        )
        with self.assertRaises(AppointmentDecisionError) as cm:
            AppointmentDecisionService(77).record_with_title_result(
                case_id=self.case.id,
                decision_no="DEC-WRONG-PERSON",
                outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
                authority_ref="committee-minutes",
                title_result_id=wrong_person_result.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "TITLE_RESULT_IDENTITY_MISMATCH")

        with self.assertRaises(AppointmentDecisionError) as cm:
            AppointmentDecisionService(88).record_with_title_result(
                case_id=self.case.id,
                decision_no="DEC-WRONG-TENANT",
                outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
                authority_ref="committee-minutes",
                title_result_id=self.title_result.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "APPOINTMENT_CASE_NOT_FOUND")

    def test_superseded_or_revoked_title_result_is_not_valid_current_evidence(self):
        revised = self._sealed_title_result(
            tenant_id=77,
            result_no="TITLE-RESULT-REV-001",
            person_id=self.person_id,
            application_case_id=self.title_result.application_case_id,
            title_code="PROFESSOR",
            title_name="教授",
            title_series_code="TEACHING",
            title_level_code="FULL",
            effective_from=date(2026, 7, 1),
            status=ProfessionalTitleResult.Status.REVISED,
            supersedes_result_id=self.title_result.id,
        )

        with self.assertRaises(AppointmentDecisionError) as cm:
            AppointmentDecisionService(77).record_with_title_result(
                case_id=self.case.id,
                decision_no="DEC-SUPERSEDED",
                outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
                authority_ref="committee-minutes",
                title_result_id=self.title_result.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "TITLE_RESULT_SUPERSEDED")

        revoked = self._sealed_title_result(
            tenant_id=77,
            result_no="TITLE-RESULT-REVOKED",
            person_id=self.person_id,
            application_case_id=self.title_result.application_case_id,
            title_code=revised.title_code,
            title_name=revised.title_name,
            effective_from=date(2026, 7, 15),
            status=ProfessionalTitleResult.Status.REVOKED,
            supersedes_result_id=revised.id,
        )
        with self.assertRaises(AppointmentDecisionError) as cm:
            AppointmentDecisionService(77).record_with_title_result(
                case_id=self.case.id,
                decision_no="DEC-REVOKED",
                outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
                authority_ref="committee-minutes",
                title_result_id=revoked.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "TITLE_RESULT_REVOKED")

    def test_historical_as_of_accepts_old_result_before_revision_effective_date(self):
        self._sealed_title_result(
            tenant_id=77,
            result_no="TITLE-RESULT-FUTURE-REV",
            person_id=self.person_id,
            application_case_id=self.title_result.application_case_id,
            title_code="PROFESSOR",
            title_name="教授",
            effective_from=date(2026, 9, 1),
            status=ProfessionalTitleResult.Status.REVISED,
            supersedes_result_id=self.title_result.id,
        )

        decision, _ = AppointmentDecisionService(77).record_with_title_result(
            case_id=self.case.id,
            decision_no="DEC-HISTORICAL",
            outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
            authority_ref="committee-minutes-historical",
            title_result_id=self.title_result.id,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(
            decision.evidence_snapshot_json["hr13TitleResult"]["titleResultId"],
            str(self.title_result.id),
        )
