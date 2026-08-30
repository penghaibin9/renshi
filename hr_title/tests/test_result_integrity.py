import uuid
from datetime import date, timedelta
from unittest.mock import patch

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
    TitlePublicityRecord,
)
from hr_title.services.result_service import (
    ProfessionalTitleResultService,
    TitleResultInput,
)


class ProfessionalTitleResultIntegrityTests(TestCase):
    def setUp(self):
        self.case = TitleApplicationCase.objects.create(
            tenant_id=77,
            case_no="CASE-INTEGRITY",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="B-2026",
            requested_title_code="PRO-ASSOCIATE",
            requested_title_name="副教授",
            status=TitleApplicationCase.Status.PUBLICITY,
        )
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
        return TitleResultInput(
            result_no=result_no,
            title_code="PRO-ASSOCIATE",
            title_name=title_name,
            title_series_code="PROFESSIONAL",
            title_level_code="L7",
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
            payload=self._payload(
                "RESULT-REVISED",
                title_name="教授",
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
            **base,
            result_no="RESULT-FORGED-HASH",
            sealed_at=timezone.now(),
            content_hash="0" * 64,
        )
        with self.assertRaisesMessage(ValueError, "TITLE_RESULT_HASH_INVALID"):
            forged.save()
