import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_title.models import (
    ProfessionalTitleResult,
    TitleAppealRecord,
    TitleApplicationCase,
    TitlePolicyVersion,
    TitlePublicityRecord,
    TitleReviewBallot,
)
from hr_title.services.result_service import (
    ProfessionalTitleResultService,
    TitleResultError,
    TitleResultInput,
    TitleResultPublicationInput,
)
from hr_title.services.panel_service import TitlePanelService


class ProfessionalTitleResultServiceTests(TestCase):
    def _case(
        self,
        *,
        tenant_id=77,
        status=TitleApplicationCase.Status.PUBLICITY,
        required_ballots=1,
        required_pass_votes=1,
    ):
        policy = TitlePolicyVersion.objects.create(
            tenant_id=tenant_id,
            policy_code=f"POLICY-{uuid.uuid4().hex[:8]}",
            name="教师职称评审规则",
            title_series_code="PROFESSIONAL",
            title_level_code="L7",
            required_ballots=required_ballots,
            required_pass_votes=required_pass_votes,
            effective_from=date(2026, 1, 1),
        )
        policy.status = "PUBLISHED"
        policy.published_at = timezone.now()
        policy.content_hash = policy.calculate_content_hash()
        policy.save(update_fields=["status", "published_at", "content_hash", "updated_at"])
        return TitleApplicationCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"CASE-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=policy.id,
            batch_no="B-2026",
            requested_title_code="PRO-ASSOCIATE",
            requested_title_name="副教授",
            status=status,
        )

    def _closed_publicity(self, case):
        case.status = TitleApplicationCase.Status.ELIGIBLE
        case.save(update_fields=["status", "updated_at"])
        panel = TitlePanelService(case.tenant_id, actor_user_id=99)
        review_round = panel.open_round(
            case_id=case.id,
            round_no=f"ROUND-{uuid.uuid4().hex[:8]}",
            required_ballots=1,
            required_pass_votes=1,
        )
        assignment = panel.assign_reviewer(
            round_id=review_round.id,
            assignment_no=f"ASN-{uuid.uuid4().hex[:8]}",
            reviewer_staff_id=uuid.uuid4(),
        )
        assignment = panel.respond_assignment(assignment.id, accept=True)
        panel.submit_ballot(
            assignment_id=assignment.id,
            ballot_no=f"BAL-{uuid.uuid4().hex[:8]}",
            recommendation=TitleReviewBallot.Recommendation.PASS,
        )
        panel.close_round(review_round.id)
        case.refresh_from_db()
        case.status = TitleApplicationCase.Status.PUBLICITY
        case.save(update_fields=["status", "updated_at"])
        now = timezone.now()
        return TitlePublicityRecord.objects.create(
            tenant_id=case.tenant_id,
            publicity_no=f"PUB-{uuid.uuid4().hex[:8]}",
            application_case_id=case.id,
            start_at=now - timedelta(days=7),
            end_at=now - timedelta(days=1),
            status=TitlePublicityRecord.Status.CLOSED,
            closed_at=now,
        )

    @staticmethod
    def _payload(result_no="RESULT-001", *, effective_from=date(2026, 9, 1)):
        return TitleResultPublicationInput(
            result_no=result_no,
            effective_from=effective_from,
        )

    def test_make_effective_requires_real_closed_publicity(self):
        case = self._case()
        service = ProfessionalTitleResultService(77)
        with self.assertRaises(TitleResultError) as ctx:
            service.make_effective(application_case_id=case.id, payload=self._payload())
        self.assertEqual(ctx.exception.code, "TITLE_PUBLICITY_REQUIRED")
        self.assertFalse(ProfessionalTitleResult.objects.filter(tenant_id=77).exists())

        now = timezone.now()
        TitlePublicityRecord.objects.create(
            tenant_id=77,
            publicity_no="PUB-OPEN",
            application_case_id=case.id,
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=1),
            status=TitlePublicityRecord.Status.OPEN,
        )
        with self.assertRaises(TitleResultError) as ctx:
            service.make_effective(
                application_case_id=case.id,
                payload=self._payload("RESULT-OPEN"),
            )
        self.assertEqual(ctx.exception.code, "TITLE_PUBLICITY_NOT_CLOSED")

    def test_open_or_upheld_appeal_blocks_formal_result(self):
        case = self._case()
        publicity = self._closed_publicity(case)
        appeal = TitleAppealRecord.objects.create(
            tenant_id=77,
            appeal_no="APPEAL-OPEN",
            publicity_id=publicity.id,
            application_case_id=case.id,
            reason="评分材料需要复核",
            status=TitleAppealRecord.Status.OPEN,
        )
        service = ProfessionalTitleResultService(77)
        with self.assertRaises(TitleResultError) as ctx:
            service.make_effective(application_case_id=case.id, payload=self._payload())
        self.assertEqual(ctx.exception.code, "TITLE_APPEALS_PENDING")

        appeal.status = TitleAppealRecord.Status.UPHELD
        appeal.save(update_fields=["status", "updated_at"])
        with self.assertRaises(TitleResultError) as ctx:
            service.make_effective(application_case_id=case.id, payload=self._payload())
        self.assertEqual(ctx.exception.code, "TITLE_APPEAL_UPHELD")

    def test_effective_result_is_exactly_idempotent_after_case_is_effective(self):
        case = self._case()
        self._closed_publicity(case)
        service = ProfessionalTitleResultService(77, actor_user_id=9)
        payload = self._payload()

        first = service.make_effective(application_case_id=case.id, payload=payload)
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.EFFECTIVE)
        self.assertEqual(first.status, ProfessionalTitleResult.Status.EFFECTIVE)

        replay = service.make_effective(application_case_id=case.id, payload=payload)
        self.assertEqual(replay.id, first.id)
        self.assertEqual(
            ProfessionalTitleResult.objects.filter(
                tenant_id=77, result_no="RESULT-001"
            ).count(),
            1,
        )

        with self.assertRaises(TitleResultError) as ctx:
            service.make_effective(
                application_case_id=case.id,
                payload=TitleResultPublicationInput(
                    result_no="RESULT-001",
                    effective_from=date(2026, 9, 2),
                ),
            )
        self.assertEqual(ctx.exception.code, "TITLE_RESULT_IDEMPOTENCY_CONFLICT")

    def test_initial_result_is_derived_from_frozen_application_policy_and_ballots(self):
        case = self._case()
        publicity = self._closed_publicity(case)
        result = ProfessionalTitleResultService(77).make_effective(
            application_case_id=case.id,
            payload=self._payload("RESULT-DERIVED"),
        )

        self.assertEqual(result.title_code, case.requested_title_code)
        self.assertEqual(result.title_name, case.requested_title_name)
        self.assertEqual(result.title_series_code, "PROFESSIONAL")
        self.assertEqual(result.title_level_code, "L7")
        self.assertEqual(result.authority_snapshot_json["decision"], "PASSED")
        self.assertEqual(
            result.authority_snapshot_json["reviewClosure"]["passVotes"], 1
        )
        self.assertEqual(
            result.authority_snapshot_json["reviewBallots"][0]["recommendation"],
            "PASS",
        )
        self.assertEqual(result.authority_snapshot_json["publicityId"], str(publicity.id))

    def test_published_rule_mismatch_blocks_result(self):
        case = self._case(required_ballots=2, required_pass_votes=2)
        self._closed_publicity(case)
        with self.assertRaises(TitleResultError) as ctx:
            ProfessionalTitleResultService(77).make_effective(
                application_case_id=case.id,
                payload=self._payload("RESULT-RULE-MISMATCH"),
            )
        self.assertEqual(ctx.exception.code, "TITLE_RESULT_REVIEW_RULE_MISMATCH")
        self.assertFalse(
            ProfessionalTitleResult.objects.filter(result_no="RESULT-RULE-MISMATCH").exists()
        )

    def test_case_state_alone_cannot_bypass_passed_review_evidence(self):
        case = self._case()
        now = timezone.now()
        TitlePublicityRecord.objects.create(
            tenant_id=77,
            publicity_no="PUB-NO-REVIEW",
            application_case_id=case.id,
            start_at=now - timedelta(days=7),
            end_at=now - timedelta(days=1),
            status=TitlePublicityRecord.Status.CLOSED,
            closed_at=now,
        )
        with self.assertRaises(TitleResultError) as ctx:
            ProfessionalTitleResultService(77).make_effective(
                application_case_id=case.id,
                payload=self._payload("RESULT-NO-REVIEW"),
            )
        self.assertEqual(ctx.exception.code, "TITLE_RESULT_PASSED_REVIEW_REQUIRED")

    def test_publication_identity_and_effective_range_fail_closed(self):
        case = self._case()
        self._closed_publicity(case)
        service = ProfessionalTitleResultService(77)
        for payload, code in (
            (
                TitleResultPublicationInput("", date(2026, 9, 1)),
                "TITLE_RESULT_RESULT_NO_REQUIRED",
            ),
            (
                TitleResultPublicationInput(
                    "R-3",
                    date(2026, 9, 1),
                    effective_to=date(2026, 9, 1),
                ),
                "TITLE_RESULT_EFFECTIVE_RANGE_INVALID",
            ),
        ):
            with self.assertRaises(TitleResultError) as ctx:
                service.make_effective(application_case_id=case.id, payload=payload)
            self.assertEqual(ctx.exception.code, code)

    def test_revision_appends_successor_without_mutating_root_and_replays(self):
        case = self._case()
        self._closed_publicity(case)
        service = ProfessionalTitleResultService(77)
        root = service.make_effective(
            application_case_id=case.id,
            payload=self._payload("RESULT-ROOT", effective_from=date(2026, 9, 1)),
        )
        payload = TitleResultInput(
            result_no="RESULT-REV-1",
            title_code="PRO-FULL",
            title_name="教授",
            title_series_code="PROFESSIONAL",
            title_level_code="L4",
            effective_from=date(2027, 1, 1),
        )

        revised = service.revise(result_id=root.id, payload=payload)
        self.assertEqual(revised.status, ProfessionalTitleResult.Status.REVISED)
        self.assertEqual(revised.supersedes_result_id, root.id)
        root.refresh_from_db()
        self.assertEqual(root.status, ProfessionalTitleResult.Status.EFFECTIVE)
        self.assertEqual(root.title_name, "副教授")

        replay = service.revise(result_id=root.id, payload=payload)
        self.assertEqual(replay.id, revised.id)
        with self.assertRaises(TitleResultError) as ctx:
            service.revise(
                result_id=root.id,
                payload=TitleResultInput(
                    result_no="RESULT-REV-2",
                    title_code="PRO-FULL",
                    title_name="教授（二次）",
                    effective_from=date(2027, 2, 1),
                ),
            )
        self.assertEqual(ctx.exception.code, "TITLE_RESULT_ALREADY_SUPERSEDED")

    def test_revoke_appends_successor_marks_case_and_replays(self):
        case = self._case()
        self._closed_publicity(case)
        service = ProfessionalTitleResultService(77)
        root = service.make_effective(
            application_case_id=case.id,
            payload=self._payload("RESULT-ROOT-REVOKE"),
        )

        revoked = service.revoke(
            result_id=root.id,
            result_no="RESULT-REVOKE-1",
            revoked_at=date(2026, 10, 1),
        )
        self.assertEqual(revoked.status, ProfessionalTitleResult.Status.REVOKED)
        self.assertEqual(revoked.supersedes_result_id, root.id)
        root.refresh_from_db()
        self.assertEqual(root.status, ProfessionalTitleResult.Status.EFFECTIVE)
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.REVOKED)

        replay = service.revoke(
            result_id=root.id,
            result_no="RESULT-REVOKE-1",
            revoked_at=date(2026, 10, 1),
        )
        self.assertEqual(replay.id, revoked.id)

    def test_cross_tenant_case_fails_closed(self):
        case = self._case(tenant_id=88)
        self._closed_publicity(case)
        with self.assertRaises(TitleResultError) as ctx:
            ProfessionalTitleResultService(77).make_effective(
                application_case_id=case.id,
                payload=self._payload(),
            )
        self.assertEqual(ctx.exception.code, "TITLE_CASE_NOT_FOUND")
