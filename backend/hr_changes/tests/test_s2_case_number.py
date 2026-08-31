"""S2 案件号服务契约测试：格式 / tenant 隔离 / 递增。"""

from django.test import TestCase

from hr_changes.services.case_number_service import CaseNumberService


class CaseNumberServiceTests(TestCase):
    def test_format_and_increment(self):
        svc = CaseNumberService(1)
        n1 = svc.allocate()
        n2 = svc.allocate()
        # 格式 HRCHG-YYYY-NNNNNN
        parts = n1.split("-")
        self.assertEqual(parts[0], "HRCHG")
        self.assertEqual(len(parts[1]), 4)
        self.assertTrue(parts[2].isdigit())
        # 递增
        self.assertEqual(int(n2.split("-")[2]), int(n1.split("-")[2]) + 1)

    def test_tenant_isolation(self):
        svc1 = CaseNumberService(1)
        svc2 = CaseNumberService(2)
        n1a = svc1.allocate()
        n2a = svc2.allocate()
        n1b = svc1.allocate()
        # tenant1 第二次仍从自己的序列取（tenant2 不干扰）
        self.assertEqual(
            int(n1b.split("-")[2]), int(n1a.split("-")[2]) + 1
        )
        # tenant1 与 tenant2 第一个编号相同（各自从 1 开始）
        self.assertEqual(int(n1a.split("-")[2]), int(n2a.split("-")[2]))
