from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_onboarding.legacy.horilla import HorillaLegacyOnboardingAdapter


class LegacyOnboardingAdapterTests(SimpleTestCase):
    @patch("onboarding.models.CandidateStage.objects")
    def test_candidate_stage_is_tenant_scoped_and_non_authoritative(self, stage_objects):
        values_qs = MagicMock()
        values_qs.first.return_value = {
            "id": 1,
            "candidate_id_id": 20,
            "onboarding_stage_id_id": 3,
            "onboarding_stage_id__stage_title": "资料核验",
            "sequence": 2,
            "onboarding_end_date": None,
        }
        stage_objects.filter.return_value.values.return_value = values_qs

        row = HorillaLegacyOnboardingAdapter(tenant_id=77).get_candidate_stage(
            legacy_candidate_id=20
        )

        stage_objects.filter.assert_called_once_with(
            candidate_id_id=20,
            candidate_id__recruitment_id__company_id=77,
        )
        self.assertFalse(row["authority"])

    @patch("onboarding.models.CandidateTask.objects")
    def test_candidate_tasks_keep_legacy_status_without_state_translation(self, task_objects):
        values_qs = MagicMock()
        values_qs.__iter__.return_value = iter(
            [{"id": 2, "candidate_id_id": 20, "status": "stuck"}]
        )
        task_objects.filter.return_value.values.return_value = values_qs

        rows = HorillaLegacyOnboardingAdapter(tenant_id=77).list_candidate_tasks(
            legacy_candidate_id=20
        )

        task_objects.filter.assert_called_once_with(
            candidate_id_id=20,
            candidate_id__recruitment_id__company_id=77,
        )
        self.assertEqual(rows[0]["legacyStatus"], "stuck")
        self.assertFalse(rows[0]["authority"])

    def test_tenant_is_required(self):
        with self.assertRaises(ValueError):
            HorillaLegacyOnboardingAdapter(tenant_id=0)
