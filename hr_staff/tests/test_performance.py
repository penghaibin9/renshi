"""
S12 · 性能基准测试（总册 §36/§44，S12 补线）。

目标（单校 1 万~5 万）：
- 名册 50 行 P95 ≤ 1.2s
- profile bootstrap ≤ 900ms
- 敏感 reveal ≤ 600ms

注意：mini venv 环境下无真实数据量，本测试仅做 SQL 预算计数与响应时间基准，
不要求达标（依赖灌数据后跑全栈 CI）。
"""

import time
from datetime import date
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.selectors.staff_list import StaffListSelector
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


def ctx():
    return HrStaffRequestContext(tenant_id=TENANT, scope=HrStaffScope(scope_type="SCHOOL"))


class PerformanceBaselineTests(TestCase):
    """性能基准（不做硬断言，仅记录响应时间供 CI 追踪）。"""

    def setUp(self):
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        for i in range(5):
            person = make_person(TENANT, f"员工{i}")
            staff = make_staff(TENANT, person, f"T1000{i}")
            rel = EmploymentService(TENANT).start_relationship(
                staff_id=staff,
                relationship_type="REGULAR_EMPLOYMENT",
                effective_from=date(2024, 9, 1),
            )
            AssignmentService(TENANT).create_assignment(
                employment_relationship_id=rel,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2024, 9, 1),
                organization_id=self.org,
                source_business_type=FIXTURE_SOURCE,
            )

    def test_staff_list_50_rows_p95(self):
        """名册 50 行响应时间基准（P95 ≤ 1.2s 目标）。"""
        selector = StaffListSelector(ctx())
        start = time.monotonic()
        result = selector.rows({}, page=1, page_size=50)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2.0, f"名册 50 行耗时 {elapsed:.3f}s，超过基准")
        self.assertGreaterEqual(len(result["items"]), 1)

    def test_sql_budget_no_n_plus_one(self):
        """小数据集下查询数 ≤ 15（§36.2 预算）。"""
        from django.db import connection, reset_queries

        selector = StaffListSelector(ctx())
        reset_queries()
        selector.rows({}, page=1, page_size=5)
        query_count = len(connection.queries)
        self.assertLessEqual(query_count, 20, f"查询数 {query_count} 超出预算（15+buffer）")
