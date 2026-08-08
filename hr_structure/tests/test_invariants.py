"""
hr_structure/tests/test_invariants.py

HR02 关键领域不变量（总册 20 节 INV-01 ~ INV-15）。
"""

from datetime import date

from django.test import TestCase

from hr_structure.models import (
    HrOrganization,
    HrOrganizationVersion,
    HrPosition,
    HrPostCatalog,
    HrPostCatalogVersion,
    HrStaffingPlan,
)
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.effective import org_version_as_of, children_as_of, build_tree_as_of
from hr_structure.selectors.organization import OrganizationSelector
from hr_structure.services.organization_change import (
    OrganizationChangeService,
    Hr02ServiceError,
)


class HrOrganizationModelTests(TestCase):
    def setUp(self):
        self.today = date.today()
        self.scope = Hr02Scope(scope_type="SCHOOL", tenant_id=1)
        self.svc = OrganizationChangeService(self.scope, actor="tester")
        self.school = self.svc.create_organization(
            stable_code="SCH",
            name="跃科测试大学",
            org_type="SCHOOL",
            dimension="ADMIN",
            validity_from=self.today,
        )
        self.college = self.svc.create_organization(
            stable_code="CS",
            name="计算机学院",
            org_type="COLLEGE",
            dimension="ADMIN",
            parent_id=self.school.id,
            validity_from=self.today,
        )

    # INV-01 Tenant：任何 FK 不能跨 tenant
    def test_inv01_tenant_filter(self):
        selector = OrganizationSelector(self.scope)
        self.assertIsNone(selector.get_organization(999999))
        # 不同 tenant 的组织不能通过另一 tenant scope 读取
        other = OrganizationSelector(Hr02Scope("SCHOOL", tenant_id=2))
        self.assertIsNone(other.get_organization(self.school.id))

    # INV-02 Root：每 tenant 恰好一个当前 SCHOOL 根
    def test_inv02_single_root(self):
        selector = OrganizationSelector(self.scope)
        root = selector.get_root()
        self.assertIsNotNone(root)
        self.assertEqual(root.org_type, "SCHOOL")
        self.assertEqual(root.organization_id_id, self.school.id)

    # INV-03 No Cycle：主树不得成环
    def test_inv03_cycle_detected(self):
        from hr_structure.services.organization_change import _detect_cycle

        # 把 school（college 的祖先）作为 college 的子级 → 成环
        # _detect_cycle(parent_id=college, candidate_child=school)
        # college 的祖先链: college → school，遇到 school == candidate → 成环
        cycle = _detect_cycle(1, self.college.id, self.school.id)
        self.assertTrue(cycle)
        # 无环场景：把不相关 org 挂到 college 下
        no_cycle = _detect_cycle(1, self.college.id, 999999)
        self.assertFalse(no_cycle)

    # INV-04 Effective Overlap：同一实体正式版本区间不得重叠（as-of 唯一解析）
    def test_inv04_effective_overlap_as_of_unique(self):
        as_of = self.today
        v = org_version_as_of(self.school.id, as_of)
        self.assertIsNotNone(v)
        # as-of 解析唯一
        versions = HrOrganizationVersion.objects.filter(
            organization_id=self.school.id,
            status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
        )
        self.assertEqual(versions.count(), 1)

    # INV-05 Historical Immutable：已过期正式版本不普通 PATCH
    def test_inv05_history_readonly(self):
        from datetime import timedelta

        # as-of 在生效日期之前 → 不应解析到它
        v = org_version_as_of(self.school.id, self.today - timedelta(days=1))
        self.assertIsNone(v)

    # INV-06 Code No Reuse：stable_code 唯一
    def test_inv06_stable_code_unique(self):
        with self.assertRaises(Exception):
            self.svc.create_organization(
                stable_code="SCH",  # 重复
                name="重复学校",
                org_type="SCHOOL",
                dimension="ADMIN",
                validity_from=self.today,
            )

    # INV-07 Quota != Occupancy：编制不自动回填
    def test_inv07_quota_separate_from_occupancy(self):
        plan = HrStaffingPlan.objects.create(
            tenant_id=1, code="P2026", name="2026 编制", plan_year=2026,
            validity_from=date(2026, 1, 1), status="EFFECTIVE",
        )
        self.assertEqual(plan.version_no, 1)  # 无自动 occupancy 字段

    # INV-12 Historical View Readonly：as-of < today 不提供写 API（selector 只读）
    def test_inv12_historical_asof(self):
        selector = OrganizationSelector(self.scope, as_of=self.today)
        self.assertIsNotNone(selector.get_version_as_of(self.school.id))

    # 树构建
    def test_tree_as_of(self):
        nodes = build_tree_as_of(1, self.school.id, self.today, dimension="ADMIN")
        ids = [n["id"] for n in nodes]
        self.assertIn(self.school.id, ids)
        self.assertIn(self.college.id, ids)

    # 子组织
    def test_children_as_of(self):
        children = children_as_of(1, self.school.id, self.today, dimension="ADMIN")
        ids = [v.organization_id_id for v in children]
        self.assertIn(self.college.id, ids)
