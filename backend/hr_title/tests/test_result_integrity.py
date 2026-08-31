import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from hr_title.authority_registry import (
    EVENT_RESULT_PUBLISHED,
    EVENT_RESULT_REVISED,
    EVENT_RESULT_REVOKED,
)
from hr_title.models import (
    ProfessionalTitleResult,
    TitleApplicationCase,
    TitlePolicyVersion,
    TitlePublicityRecord,
    TitleReviewBallot,
    TitleReviewRound,
)
from hr_title.services.result_service import (
    ProfessionalTitleResultService,
    TitleResultInput,
    TitleResultPublicationInput,
)
from hr_title.services.panel_service import TitlePanelService


class ProfessionalTitleResultIntegrityTests(TestCase):
    def setUp(self):
        policy = TitlePolicyVersion.objects.create(
            tenant_id=77,
            policy_code="POLICY-INTEGRITY",
            name="教师职称评审规则",
            title_series_code="PROFESSIONAL",
            title_level_code="L7",
            required_ballots=1,
            required_pass_votes=1,
            effective_from=date(2026, 1, 1),
        )
        policy.status = "PUBLISHED"
        policy.published_at = timezone.now()
        policy.content_hash = policy.calculate_content_hash()
        policy.save(update_fields=["status", "published_at", "content_hash", "updated_at"])
        self.case = TitleApplicationCase.objects.create(
            tenant_id=77,
            case_no="CASE-INTEGRITY",
            person_id=uuid.uuid4(),
            policy_version_id=policy.id,
            batch_no="B-2026",
            requested_title_code="PRO-ASSOCIATE",
            requested_title_name="副教授",
            status=TitleApplicationCase.Status.PUBLICITY,
        )
        self.case.status = TitleApplicationCase.Status.ELIGIBLE
        self.case.save(update_fields=["status", "updated_at"])
        panel = TitlePanelService(77, actor_user_id=99)
        review_round = panel.open_round(
            case_id=self.case.id,
            round_no="ROUND-INTEGRITY",
            required_ballots=1,
            required_pass_votes=1,
        )
        assignment = panel.assign_reviewer(
            round_id=review_round.id,
            assignment_no="ASN-INTEGRITY",
            reviewer_staff_id=uuid.uuid4(),
        )
        assignment = panel.respond_assignment(assignment.id, accept=True)
        panel.submit_ballot(
            assignment_id=assignment.id,
            ballot_no="BAL-INTEGRITY",
            recommendation=TitleReviewBallot.Recommendation.PASS,
        )
        panel.close_round(review_round.id)
        self.case.refresh_from_db()
        self.case.status = TitleApplicationCase.Status.PUBLICITY
        self.case.save(update_fields=["status", "updated_at"])
        now = timezone.now()
        TitlePublicityRecord.objects.create(
            tenant_id=77,
            publicity_no="PUB-INTEGRITY",
            application_case_id=self.case.id,
            start_at=now - timedelta(days=7),
            end_at=now - timedelta(days=1),
            status=TitlePublicityRecord.Status.CLOSED,
            closed_at=now,
        )
        self.service = ProfessionalTitleResultService(
            77,
            actor_user_id=9,
            correlation_id="hr13-integrity-test",
        )

    @staticmethod
    def _payload(result_no, title_name="副教授", effective_from=date(2026, 9, 1)):
        return TitleResultPublicationInput(
            result_no=result_no,
            effective_from=effective_from,
        )

    @patch("hr_title.services.result_service.emit_registered_event")
    def test_publish_seals_hash_emits_once_and_exact_replay_is_quiet(self, emit):
        result = self.service.make_effective(
            application_case_id=self.case.id,
            payload=self._payload("RESULT-SEALED"),
        )

        self.assertIsNotNone(result.sealed_at)
        self.assertEqual(len(result.content_hash), 64)
        self.assertEqual(result.content_hash, result.calculate_content_hash())
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs["event_name"], EVENT_RESULT_PUBLISHED)
        self.assertEqual(
            emit.call_args.kwargs["payload"]["contentHash"], result.content_hash
        )

        replay = self.service.make_effective(
            application_case_id=self.case.id,
            payload=self._payload("RESULT-SEALED"),
        )
        self.assertEqual(replay.id, result.id)
        emit.assert_called_once()

    @patch("hr_title.services.result_service.emit_registered_event")
    def test_revision_and_revocation_append_sealed_events(self, emit):
        root = self.service.make_effective(
            application_case_id=self.case.id,
            payload=self._payload("RESULT-ROOT"),
        )
        revised = self.service.revise(
            result_id=root.id,
            payload=TitleResultInput(
                result_no="RESULT-REVISED",
                title_code="PRO-FULL",
                title_name="教授",
                title_series_code="PROFESSIONAL",
                title_level_code="L4",
                effective_from=date(2027, 1, 1),
            ),
        )
        revoked = self.service.revoke(
            result_id=revised.id,
            result_no="RESULT-REVOKED",
            revoked_at=date(2027, 2, 1),
        )

        self.assertEqual(revised.supersedes_result_id, root.id)
        self.assertEqual(revoked.supersedes_result_id, revised.id)
        self.assertEqual(revised.content_hash, revised.calculate_content_hash())
        self.assertEqual(revoked.content_hash, revoked.calculate_content_hash())
        self.assertEqual(
            [call.kwargs["event_name"] for call in emit.call_args_list],
            [EVENT_RESULT_PUBLISHED, EVENT_RESULT_REVISED, EVENT_RESULT_REVOKED],
        )

    @patch("hr_title.services.result_service.emit_registered_event")
    def test_instance_bulk_update_and_delete_paths_are_blocked(self, _emit):
        result = self.service.make_effective(
            application_case_id=self.case.id,
            payload=self._payload("RESULT-LOCKED"),
        )

        result.title_name = "被篡改的职称"
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_IMMUTABLE"):
            result.save(update_fields=["title_name", "updated_at"])

        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_IMMUTABLE"):
            ProfessionalTitleResult.objects.filter(id=result.id).update(
                title_name="批量篡改"
            )
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_IMMUTABLE"):
            ProfessionalTitleResult.objects.filter(id=result.id).delete()

        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_SEAL_REQUIRED"):
            ProfessionalTitleResult.objects.bulk_create(
                [ProfessionalTitleResult(result_no="BULK-FORGED")]
            )

        pristine = ProfessionalTitleResult.objects.get(id=result.id)
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_IMMUTABLE"):
            pristine.delete()

    def test_direct_unsealed_or_forged_fact_is_rejected(self):
        base = dict(
            tenant_id=77,
            result_no="RESULT-FORGED",
            person_id=self.case.person_id,
            application_case_id=self.case.id,
            title_code="PRO-ASSOCIATE",
            title_name="副教授",
            effective_from=date(2026, 9, 1),
            created_by=9,
            updated_by=9,
        )
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_SEAL_REQUIRED"):
            ProfessionalTitleResult.objects.create(**base)

        forged = ProfessionalTitleResult(
            **{**base, "result_no": "RESULT-FORGED-HASH"},
            sealed_at=timezone.now(),
            content_hash="0" * 64,
        )
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_HASH_INVALID"):
            forged.save()

    def test_frozen_rule_round_and_ballot_block_orm_and_mysql_rewrites(self):
        policy = TitlePolicyVersion.objects.get(id=self.case.policy_version_id)
        review_round = TitleReviewRound.objects.get(application_case_id=self.case.id)
        ballot = TitleReviewBallot.objects.get(review_round_id=review_round.id)

        with self.assertRaisesMessage(ValueError, "TITLE_POLICY_IMMUTABLE"):
            TitlePolicyVersion.objects.filter(id=policy.id).update(required_ballots=9)
        with self.assertRaisesMessage(ValueError, "TITLE_REVIEW_ROUND_IMMUTABLE"):
            TitleReviewRound.objects.filter(id=review_round.id).update(required_ballots=9)
        review_round.status = TitleReviewRound.Status.NOT_PASSED
        with self.assertRaisesMessage(ValueError, "TITLE_REVIEW_ROUND_IMMUTABLE"):
            review_round.save(update_fields=["status", "updated_at"])
        with self.assertRaisesMessage(ValueError, "TITLE_REVIEW_BALLOT_IMMUTABLE"):
            TitleReviewBallot.objects.filter(id=ballot.id).update(recommendation="FAIL")
        with self.assertRaisesMessage(ValueError, "TITLE_REVIEW_BALLOT_APPEND_ONLY"):
            ballot.delete()
        with self.assertRaisesMessage(ValueError, "TITLE_APPLICATION_IDENTITY_IMMUTABLE"):
            TitleApplicationCase.objects.filter(id=self.case.id).update(
                requested_title_name="客户端伪造职称"
            )

        if connection.vendor == "mysql":
            probes = (
                (
                    "UPDATE hr13_title_policy_version SET required_ballots=9 WHERE id=%s",
                    [policy.id.hex],
                ),
                (
                    "UPDATE hr13_title_review_round SET required_ballots=9 WHERE id=%s",
                    [review_round.id.hex],
                ),
                (
                    "UPDATE hr13_title_review_ballot SET recommendation='FAIL' WHERE id=%s",
                    [ballot.id.hex],
                ),
                (
                    "UPDATE hr13_title_application_case SET requested_title_name='forged' WHERE id=%s",
                    [self.case.id.hex],
                ),
            )
            for sql, params in probes:
                with self.assertRaises(DatabaseError):
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(sql, params)
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    TitleReviewBallot.objects.create(
                        tenant_id=77,
                        ballot_no="BAL-AFTER-CLOSE",
                        review_round_id=review_round.id,
                        assignment_id=ballot.assignment_id,
                        recommendation=TitleReviewBallot.Recommendation.PASS,
                    )

    @patch("hr_title.services.result_service.emit_registered_event")
    def test_event_failure_rolls_back_result_and_case_state(self, emit):
        emit.side_effect = RuntimeError("outbox unavailable")
        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            self.service.make_effective(
                application_case_id=self.case.id,
                payload=self._payload("RESULT-ROLLBACK"),
            )
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, TitleApplicationCase.Status.PUBLICITY)
        self.assertFalse(
            ProfessionalTitleResult.objects.filter(result_no="RESULT-ROLLBACK").exists()
        )
