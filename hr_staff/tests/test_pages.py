"""S4/S5 · 页面视图测试：名册/主档/任职履历页面可渲染（Django test client + mini urls）。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from hr_staff import views
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


def ctx():
    return HrStaffRequestContext(tenant_id=TENANT, scope=HrStaffScope(scope_type="SCHOOL"))


class PageViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")

    def test_staff_list_page_renders(self):
        request = self.factory.get("/hr/staff/")
        with mock.patch("hr_staff.views.make_staff_context", return_value=ctx()):
            resp = views.staff_list(request)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "教职工名册")

    def test_profile_page_renders_with_staff_id(self):
        request = self.factory.get(f"/hr/staff/{self.staff.id}/")
        with mock.patch("hr_staff.views.make_staff_context", return_value=ctx()):
            resp = views.staff_profile(request, self.staff.id)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "教职工主档")
        self.assertContains(resp, str(self.staff.id))

    def test_assignment_history_page_renders(self):
        request = self.factory.get(f"/hr/staff/{self.staff.id}/assignments")
        with mock.patch("hr_staff.views.make_staff_context", return_value=ctx()):
            resp = views.assignment_history(request, self.staff.id)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "任职与身份履历")

    def test_missing_tenant_renders_403(self):
        from hr_staff.context import HrStaffContextError

        def raise_tenant(*a, **k):
            raise HrStaffContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

        request = self.factory.get("/hr/staff/")
        with mock.patch("hr_staff.views.make_staff_context", side_effect=raise_tenant):
            resp = views.staff_list(request)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("TENANT_CONTEXT_REQUIRED", resp.content.decode("utf-8"))
