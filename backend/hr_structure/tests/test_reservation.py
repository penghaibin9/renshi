"""
hr_structure/tests/test_reservation.py

岗位预占并发防超卖（总册 50.1 + 40.8）：
- 20 并发争抢 1 个 max_incumbents=1 的岗位 → 成功 HELD = 1，其余被拒；
- 预占-提交-释放状态机；
- 幂等重试不重复占额。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from django.conf import settings
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.test.utils import skipIf

from hr_structure.models import HrPosition, HrPositionReservation
from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.position import PositionService, PositionServiceError
from hr_structure.services.post_catalog import PostCatalogService


class PositionReservationTests(TransactionTestCase):
    """TransactionTestCase：允许真实事务/并发（select_for_update 在 PostgreSQL 生效，
    本地 SQLite 下 select_for_update 为 no-op，但写串行化 + 状态校验仍保证正确性）。"""

    def setUp(self):
        self.today = date.today()
        self.scope = Hr02Scope("SCHOOL", tenant_id=1)
        org_svc = OrganizationChangeService(self.scope, actor="t")
        self.school = org_svc.create_organization(
            stable_code="SCH1", name="大学", org_type="SCHOOL", dimension="ADMIN",
            validity_from=self.today,
        )
        self.college = org_svc.create_organization(
            stable_code="CS1", name="学院", org_type="COLLEGE", dimension="ADMIN",
            parent_id=self.school.id, validity_from=self.today,
        )
        self.catalog = PostCatalogService(self.scope).create_catalog(
            stable_code="PC1", name="教师岗", category="PROFESSIONAL_TECHNICAL", subcategory="TEACHER",
        )
        self.svc = PositionService(self.scope, actor="t")
        self.position = self.svc.create_position(
            position_code="P001", organization_id=self.college.id,
            post_catalog_version_id=self.catalog.versions.first().id,
            max_incumbents=1,
        )

    def test_reserve_commit_release_state_machine(self):
        r = self.svc.reserve(
            source_domain="hr04", source_business_type="req", source_business_id="B1",
            position_id=self.position.id, count=1, idempotency_key="K1",
        )
        self.assertEqual(r.status, HrPositionReservation.Status.HELD)

        # 幂等重试 → 同一实例
        r2 = self.svc.reserve(
            source_domain="hr04", source_business_type="req", source_business_id="B1",
            position_id=self.position.id, count=1, idempotency_key="K1",
        )
        self.assertEqual(r.id, r2.id)

        # commit
        r = self.svc.commit(r.id)
        self.assertEqual(r.status, HrPositionReservation.Status.COMMITTED)

        # COMMITTED 不可 release
        with self.assertRaises(PositionServiceError) as cm:
            self.svc.release(r.id)
        self.assertEqual(cm.exception.code, "HR02_POSITION_NOT_AVAILABLE")

    @skipIf(
        "sqlite" in settings.DATABASES["default"]["ENGINE"],
        "SQLite 单写者不支持真并发（select_for_update 是 no-op）；真并发由 PostgreSQL CI 跑 test_reservation.py（总册 40.8）",
    )
    def test_concurrent_reservation_20_take_1(self):
        """20 并发抢 1 个 max_incumbents=1 岗位 → 仅 1 个成功。"""

        def try_reserve(i):
            close_old_connections()
            try:
                self.svc.reserve(
                    source_domain="hr04", source_business_type="req",
                    source_business_id=f"B{i}", position_id=self.position.id,
                    count=1, idempotency_key=f"K{i}",
                )
                return True
            except PositionServiceError:
                return False

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(try_reserve, range(20)))
        close_old_connections()

        held = HrPositionReservation.objects.filter(
            position_id=self.position, status="HELD"
        ).count()
        self.assertEqual(sum(results), 1)
        self.assertEqual(held, 1)

    def test_over_commit_blocked(self):
        r = self.svc.reserve(
            source_domain="hr04", source_business_type="req", source_business_id="B1",
            position_id=self.position.id, count=1, idempotency_key="K1",
        )
        with self.assertRaises(PositionServiceError) as cm:
            self.svc.reserve(
                source_domain="hr04", source_business_type="req", source_business_id="B2",
                position_id=self.position.id, count=1, idempotency_key="K2",
            )
        self.assertEqual(cm.exception.code, "HR02_POSITION_NOT_AVAILABLE")
        self.assertEqual(
            HrPositionReservation.objects.filter(status="HELD").count(), 1
        )

    def test_release_frees_capacity(self):
        r = self.svc.reserve(
            source_domain="hr04", source_business_type="req", source_business_id="B1",
            position_id=self.position.id, count=1, idempotency_key="K1",
        )
        self.svc.release(r.id)
        # 释放后重新可预占
        r2 = self.svc.reserve(
            source_domain="hr04", source_business_type="req", source_business_id="B2",
            position_id=self.position.id, count=1, idempotency_key="K2",
        )
        self.assertEqual(r2.status, HrPositionReservation.Status.HELD)

    def test_fractional_reservation_count_and_non_positive_fte_are_rejected(self):
        with self.assertRaises(PositionServiceError):
            self.svc.reserve(
                source_domain="hr04",
                source_business_type="req",
                source_business_id="fractional",
                position_id=self.position.id,
                count="0.5",
                idempotency_key="K-FRACTIONAL",
            )
        with self.assertRaises(PositionServiceError):
            self.svc.reserve(
                source_domain="hr04",
                source_business_type="req",
                source_business_id="zero-fte",
                position_id=self.position.id,
                count=1,
                fte=0,
                idempotency_key="K-ZERO-FTE",
            )
