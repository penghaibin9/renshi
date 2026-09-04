"""
hr_control_center/tests/test_context.py

学校时区 / as_of / period 边界（总册 33.1 timezone period boundary）。
"""

from datetime import date, datetime, timezone

from django.test import SimpleTestCase

from hr_control_center.context import (
    DEFAULT_SCHOOL_TZ,
    HrContextError,
    HrRequestContext,
    build_hr_context,
)


class HrRequestContextTests(SimpleTestCase):
    def test_default_today_uses_school_timezone(self):
        ctx = HrRequestContext(tenant_id=1, school_timezone="Asia/Shanghai")
        self.assertEqual(ctx.as_of, ctx.today())

    def test_as_of_and_period_defaults(self):
        ctx = HrRequestContext(tenant_id=1, as_of=date(2026, 8, 8))
        self.assertEqual(ctx.as_of, date(2026, 8, 8))
        self.assertEqual(ctx.period_to, date(2026, 8, 8))
        # 默认 period_from = 当月第一天
        self.assertEqual(ctx.period_from, date(2026, 8, 1))

    def test_timezone_shift_changes_today(self):
        """
        school_timezone 必须影响“今天”。
        UTC 23:30 → Asia/Shanghai 已经是第二天。
        """
        from datetime import datetime, timezone as dt_timezone

        # 用一个固定 UTC 时刻构造请求快照
        snapshot = datetime(2026, 8, 8, 23, 30, tzinfo=dt_timezone.utc)
        ctx_shanghai = HrRequestContext(
            tenant_id=1,
            school_timezone="Asia/Shanghai",
            request_snapshot_at=snapshot,
        )
        # Asia/Shanghai = UTC+8 → 2026-08-09
        self.assertEqual(ctx_shanghai.today(), date(2026, 8, 9))

        ctx_utc = HrRequestContext(
            tenant_id=1,
            school_timezone="UTC",
            request_snapshot_at=snapshot,
        )
        self.assertEqual(ctx_utc.today(), date(2026, 8, 8))

    def test_scope_fingerprint(self):
        ctx = HrRequestContext(tenant_id=1)
        self.assertEqual(ctx.scope_fingerprint(), "SCHOOL:")

    def test_now_is_frozen_to_the_request_snapshot(self):
        snapshot = datetime(2026, 9, 2, 23, 30, tzinfo=timezone.utc)
        ctx = HrRequestContext(
            tenant_id=1,
            school_timezone="Asia/Shanghai",
            request_snapshot_at=snapshot,
        )

        self.assertEqual(ctx.now().date(), date(2026, 9, 3))
        self.assertEqual(ctx.now().astimezone(timezone.utc), snapshot)

    def test_build_hr_context_requires_tenant(self):
        with self.assertRaises(HrContextError) as cm:
            build_hr_context(tenant_id=None)
        self.assertEqual(cm.exception.code, "TENANT_CONTEXT_REQUIRED")

    def test_build_hr_context_rejects_bad_scope(self):
        with self.assertRaises(HrContextError) as cm:
            build_hr_context(tenant_id=1, scope_type="GLOBAL")
        self.assertEqual(cm.exception.code, "SCOPE_NOT_ALLOWED")

    def test_build_hr_context_rejects_bad_date(self):
        with self.assertRaises(HrContextError) as cm:
            build_hr_context(tenant_id=1, as_of="not-a-date")
        self.assertEqual(cm.exception.code, "INVALID_REQUEST")
