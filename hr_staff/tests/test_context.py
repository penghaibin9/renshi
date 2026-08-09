"""S1 · context 契约测试：tenant fail-closed、as_of、scope 校验。"""

from datetime import date

from django.test import SimpleTestCase

from hr_staff.context import (
    HrStaffContextError,
    build_staff_context,
)


class BuildStaffContextTests(SimpleTestCase):
    def test_missing_tenant_fails_closed(self):
        with self.assertRaises(HrStaffContextError) as ctx:
            build_staff_context(tenant_id=None)
        self.assertEqual(ctx.exception.code, "TENANT_CONTEXT_REQUIRED")

    def test_invalid_scope_rejected(self):
        with self.assertRaises(HrStaffContextError) as ctx:
            build_staff_context(tenant_id=1, scope_type="GLOBAL")
        self.assertEqual(ctx.exception.code, "SCOPE_NOT_ALLOWED")

    def test_invalid_as_of_rejected(self):
        with self.assertRaises(HrStaffContextError) as ctx:
            build_staff_context(tenant_id=1, as_of="not-a-date")
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

    def test_default_as_of_is_today(self):
        ctx = build_staff_context(tenant_id=7)
        self.assertEqual(ctx.as_of, ctx.today())
        self.assertEqual(ctx.scope.scope_type, "SCHOOL")

    def test_explicit_staff_set_scope(self):
        ctx = build_staff_context(
            tenant_id=1,
            scope_type="EXPLICIT_STAFF_SET",
            scope_staff_ids=["10", "11"],
        )
        # P1-4：staff id 为 UUID 字符串，不做 int 强转
        self.assertEqual(ctx.scope.staff_ids, frozenset({"10", "11"}))

    def test_authority_mode_default(self):
        ctx = build_staff_context(tenant_id=1)
        self.assertEqual(ctx.authority_mode, "LEGACY_STAFF_ONLY")
