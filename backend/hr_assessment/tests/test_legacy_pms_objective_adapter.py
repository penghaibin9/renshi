from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_assessment.legacy.pms import PmsLegacyObjectiveAdapter


class PmsLegacyObjectiveAdapterTests(SimpleTestCase):
    @patch("hr_assessment.legacy.pms._employee_objective_model")
    def test_objective_read_is_tenant_scoped_bounded_and_non_authoritative(self, model_loader):
        objective_objects = model_loader.return_value.objects
        scoped = MagicMock()
        ordered = MagicMock()
        values_qs = MagicMock()
        values_qs.__getitem__.return_value = [
            {
                "id": 1,
                "objective_id_id": 3,
                "objective": "年度教学目标",
                "objective_description": "完成重点任务",
                "start_date": None,
                "end_date": None,
                "status": "On Track",
                "progress_percentage": 65,
                "archive": False,
            }
        ]
        objective_objects.filter.return_value = scoped
        scoped.order_by.return_value = ordered
        ordered.values.return_value = values_qs

        rows = PmsLegacyObjectiveAdapter(tenant_id=77).list_employee_objectives(
            legacy_employee_id=12,
            limit=9999,
        )

        objective_objects.filter.assert_called_once_with(
            employee_id_id=12,
            employee_id__employee_work_info__company_id_id=77,
        )
        values_qs.__getitem__.assert_called_once_with(slice(None, 1000, None))
        self.assertEqual(rows[0]["legacyStatus"], "On Track")
        self.assertEqual(rows[0]["legacyProgressPercentage"], 65)
        self.assertEqual(rows[0]["factKind"], "LEGACY_OBJECTIVE_PROGRESS")
        self.assertFalse(rows[0]["authority"])

    def test_tenant_is_required(self):
        with self.assertRaises(ValueError):
            PmsLegacyObjectiveAdapter(tenant_id=0)
