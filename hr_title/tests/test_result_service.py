from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_title.models import ProfessionalTitleResult, TitleApplicationCase
from hr_title.services.result_service import (
    ProfessionalTitleResultService,
    TitleResultError,
    TitleResultInput,
)


class ProfessionalTitleResultServiceTests(TestCase):
    def _payload(self, *, result_no="R-001", effective_from=date(2026, 8, 10)):
        return TitleResultInput(
            result_no=result_no,
            title_code="ASSOCIATE_PROFESSOR",
            title_name="副教授",
            title_series_code="TEACHING",
            title_level_code="ASSOCIATE",
            effective_from=effective_from,
        )

    @patch("hr_title.services.result_service.ProfessionalTitleResult.objects")
    @patch("hr_title.services.result_service.TitleApplicationCase.objects")
    def test_make_effective_locks_case_inside_tenant_and_creates_one_root_fact(
        self, case_objects, result_objects
    ):
        case = MagicMock()
        case.id = "case-1"
        case.person_id = "person-1"
        case.status = TitleApplicationCase.Status.PUBLICITY
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        result_objects.filter.return_value.exists.return_value = False
        created = MagicMock()
        result_objects.create.return_value = created

        result = ProfessionalTitleResultService(77, actor_user_id=9).make_effective(
            application_case_id="case-1",
            payload=self._payload(),
        )

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        result_objects.filter.assert_called_once_with(
            tenant_id=77, application_case_id="case-1"
        )
        self.assertIs(result, created)
        self.assertEqual(case.status, TitleApplicationCase.Status.EFFECTIVE)
        case.save.assert_called_once_with(
            update_fields=["status", "updated_by", "updated_at"]
        )

    @patch("hr_title.services.result_service.ProfessionalTitleResult.objects")
    @patch("hr_title.services.result_service.TitleApplicationCase.objects")
    def test_second_root_result_is_rejected(self, case_objects, result_objects):
        case = MagicMock()
        case.id = "case-1"
        case.status = TitleApplicationCase.Status.PUBLICITY
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        result_objects.filter.return_value.exists.return_value = True

        with self.assertRaisesRegex(TitleResultError, "formal result already exists"):
            ProfessionalTitleResultService(77).make_effective(
                application_case_id="case-1",
                payload=self._payload(),
            )
        result_objects.create.assert_not_called()

    @patch("hr_title.services.result_service.TitleApplicationCase.objects")
    @patch("hr_title.services.result_service.ProfessionalTitleResult.objects")
    def test_revision_appends_successor_without_saving_old_fact(
        self, result_objects, case_objects
    ):
        current = MagicMock()
        current.id = "old-result"
        current.status = ProfessionalTitleResult.Status.EFFECTIVE
        current.effective_from = date(2026, 1, 1)
        current.application_case_id = "case-1"
        current.person_id = "person-1"
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = current
        result_objects.filter.return_value.exists.return_value = False
        case = MagicMock()
        case.id = "case-1"
        case.person_id = "person-1"
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        successor = MagicMock()
        result_objects.create.return_value = successor

        result = ProfessionalTitleResultService(77, actor_user_id=9).revise(
            result_id="old-result",
            payload=self._payload(
                result_no="R-002", effective_from=date(2026, 8, 10)
            ),
        )

        self.assertIs(result, successor)
        current.save.assert_not_called()
        create_kwargs = result_objects.create.call_args.kwargs
        self.assertEqual(create_kwargs["status"], ProfessionalTitleResult.Status.REVISED)
        self.assertEqual(create_kwargs["supersedes_result_id"], "old-result")
        self.assertEqual(create_kwargs["tenant_id"], 77)

    @patch("hr_title.services.result_service.ProfessionalTitleResult.objects")
    def test_existing_successor_prevents_history_branch(self, result_objects):
        current = MagicMock()
        current.id = "old-result"
        current.status = ProfessionalTitleResult.Status.EFFECTIVE
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = current
        result_objects.filter.return_value.exists.return_value = True

        with self.assertRaisesRegex(TitleResultError, "already has a successor"):
            ProfessionalTitleResultService(77).revise(
                result_id="old-result",
                payload=self._payload(result_no="R-002"),
            )

    @patch("hr_title.services.result_service.TitleApplicationCase.objects")
    @patch("hr_title.services.result_service.ProfessionalTitleResult.objects")
    def test_revoke_appends_fact_and_marks_case_revoked(
        self, result_objects, case_objects
    ):
        current = MagicMock()
        current.id = "old-result"
        current.status = ProfessionalTitleResult.Status.EFFECTIVE
        current.effective_from = date(2026, 1, 1)
        current.application_case_id = "case-1"
        current.person_id = "person-1"
        current.title_code = "ASSOCIATE_PROFESSOR"
        current.title_name = "副教授"
        current.title_series_code = "TEACHING"
        current.title_level_code = "ASSOCIATE"
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = current
        result_objects.filter.return_value.exists.return_value = False
        case = MagicMock()
        case.id = "case-1"
        case.person_id = "person-1"
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        revoked = MagicMock()
        result_objects.create.return_value = revoked

        result = ProfessionalTitleResultService(77, actor_user_id=9).revoke(
            result_id="old-result",
            result_no="R-003",
            revoked_at=date(2026, 8, 10),
        )

        self.assertIs(result, revoked)
        current.save.assert_not_called()
        self.assertEqual(case.status, TitleApplicationCase.Status.REVOKED)
        self.assertEqual(
            result_objects.create.call_args.kwargs["status"],
            ProfessionalTitleResult.Status.REVOKED,
        )
