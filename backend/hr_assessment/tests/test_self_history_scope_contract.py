"""个人考核历史只能读取本人且必须限定学校。"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_assessment.service.ethics_history import SelfHistoryService


class SelfHistoryScopeContractTests(SimpleTestCase):
    @patch("hr_assessment.service.ethics_history.HrFinalAssessmentResult.objects.filter")
    @patch("hr_assessment.service.ethics_history.HrAssessmentCase.objects.filter")
    def test_timeline_filters_tenant_and_staff(self, case_filter, result_filter):
        staff_id = uuid.uuid4()
        case_id = uuid.uuid4()
        case_queryset = MagicMock()
        case_queryset.values_list.return_value = [case_id]
        case_filter.return_value = case_queryset

        result = SimpleNamespace(
            case_id=case_id,
            assessment_type="ANNUAL",
            grade_code="EXCELLENT",
            result_version_no=1,
            finalized_at=None,
            status="FINALIZED",
        )
        ordered = MagicMock()
        ordered.__getitem__.return_value = [result]
        result_queryset = MagicMock()
        result_queryset.order_by.return_value = ordered
        result_filter.return_value = result_queryset

        timeline = SelfHistoryService().get_personal_timeline(7, staff_id)

        case_filter.assert_called_once_with(tenant_id=7, staff_id=staff_id)
        case_queryset.values_list.assert_called_once_with("id", flat=True)
        result_filter.assert_called_once_with(
            tenant_id=7,
            case_id__in=[case_id],
        )
        ordered.__getitem__.assert_called_once_with(slice(None, 50, None))
        self.assertEqual(timeline[0]["case_id"], str(case_id))
        self.assertEqual(timeline[0]["grade_code"], "EXCELLENT")
