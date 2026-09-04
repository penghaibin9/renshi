"""HR05 对账查询必须显式限定学校，数据源故障不得伪装为空。"""

from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_onboarding.jobs.reconcile import _candidate_stages, _candidates


class ReconcileTenantContractTests(SimpleTestCase):
    @patch("hr_onboarding.jobs.reconcile._legacy_candidate_model")
    def test_candidates_are_explicitly_tenant_scoped(self, candidate_model):
        _candidates(17)
        candidate_filter = candidate_model.return_value.objects.filter
        candidate_filter.assert_called_once_with(
            recruitment_id__company_id_id=17
        )

    @patch("hr_onboarding.jobs.reconcile._legacy_candidate_stage_model")
    def test_stages_are_explicitly_tenant_scoped(self, stage_model):
        _candidate_stages(19)
        stage_filter = stage_model.return_value.objects.filter
        stage_filter.assert_called_once_with(
            candidate_id__recruitment_id__company_id_id=19
        )

    def test_reconcile_has_no_silent_empty_fallback(self):
        source = (
            Path(__file__).resolve().parents[1] / "jobs" / "reconcile.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("objects.all()", source)
        self.assertNotIn("except Exception", source)
