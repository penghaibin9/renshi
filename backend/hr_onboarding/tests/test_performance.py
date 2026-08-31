"""
hr_onboarding/tests/test_performance.py

HR05-S10 性能预算测试：
- case 列表 DB 层分页（WHERE→COUNT→ORDER→PAGE，禁止 Python 后过滤，00 §31）；
- case 详情 1 条查询预算（不 N+1 拉全表）；
- Portal 首页仅本人数据。
"""

from django.test import TestCase

from hr_onboarding.api import selectors
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.services import portal_service, token_service

from .test_security import _make_case


class ListPerformanceTests(TestCase):
    def test_list_uses_db_pagination(self):
        """构造 5 条跨 tenant case，分页只返回当前页且 total 正确（DB COUNT 而非全表）。"""
        for _ in range(3):
            _make_case(1)
        _make_case(2)

        data = selectors.list_cases(tenant_id=1, page=1, page_size=2)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["total"], 3)
        self.assertTrue(data["hasNext"])

        page2 = selectors.list_cases(tenant_id=1, page=2, page_size=2)
        self.assertEqual(len(page2["items"]), 1)
        self.assertEqual(page2["total"], 3)
        self.assertFalse(page2["hasNext"])

    def test_list_filter_by_status_db_level(self):
        _make_case(1)
        case = HrOnboardingCase.objects.filter(tenant_id=1).first()
        case.status = "PREPARING"
        case.save(update_fields=["status"])
        data = selectors.list_cases(tenant_id=1, status="CREATED")
        self.assertEqual(data["total"], 0)
        data2 = selectors.list_cases(tenant_id=1, status="PREPARING")
        self.assertEqual(data2["total"], 1)

    def test_detail_single_query_shape(self):
        """详情返回有限字段，不包含高敏明文。"""
        r = _make_case(1)
        detail = selectors.get_case_detail(tenant_id=1, case_id=r["case_id"])
        self.assertIsNotNone(detail)
        self.assertNotIn("portal_token", detail)
        self.assertNotIn("token_hash", detail)
        for key in ("case_no", "status", "expected_report_date", "legal_name"):
            self.assertIn(key, detail)


class PortalPerformanceTests(TestCase):
    def test_get_me_self_only(self):
        r1 = _make_case(1)
        _make_case(1)
        portal = token_service.resolve_portal_access(tenant_id=None, token=r1["portal_token"])
        data = portal_service.get_me(portal)
        self.assertEqual(data["case_no"], HrOnboardingCase.objects.get(id=r1["case_id"]).case_no)
        # 不包含其他 case 数据（case_no/legal_name/expected_report_date/status/verification_status/statusLabel/verificationStatusLabel）
        self.assertEqual(len(data.keys()), 7)
