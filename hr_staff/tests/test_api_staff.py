"""S4/S5 · API 层测试：version envelope、权限、tenant fail-closed、错误信封。"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_staff.api import profile as profile_api
from hr_staff.api import staff as staff_api
from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

User = get_user_model()
TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


def ctx(scope_type="SCHOOL", as_of=None):
    return HrStaffRequestContext(
        tenant_id=TENANT,
        as_of=as_of or date(2026, 8, 1),
        scope=HrStaffScope(scope_type=scope_type),
    )


def body(resp):
    return json.loads(resp.content)


class StaffApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="hr_admin", password="x", is_superuser=True
        )
        self.org = make_org(TENANT, "AIXY", "人工智能学院", date(2026, 2, 1))
        person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, person, "T001238")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2026, 2, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2026, 2, 1),
            organization_id=self.org,
            source_business_type=FIXTURE_SOURCE,
        )

    def _get(self, path):
        request = self.factory.get(path)
        request.user = self.user
        return request

    def test_staff_list_envelope(self):
        request = self._get("/api/hr/v1/staff?page=1&pageSize=50")
        with mock.patch("hr_staff.api.staff.make_staff_context", return_value=ctx()):
            resp = staff_api.staff_list(request)
        data = body(resp)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["apiVersion"], "1.0")
        self.assertEqual(data["schemaVersion"], "hr03.staff.list.1")
        self.assertEqual(data["asOf"], "2026-08-01")
        self.assertIn("requestId", data)
        self.assertEqual(data["scope"]["type"], "SCHOOL")
        self.assertEqual(data["dataBasis"], "LEGACY_CURRENT_SNAPSHOT")
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertNotIn("identity", item)  # 高敏不入列表

    def test_staff_list_unauthorized_403(self):
        """无权限用户直接调用 view → PermissionDenied（Django 中间件层转 403）。"""
        request = self._get("/api/hr/v1/staff")
        request.user = User.objects.create_user(username="nobody", password="x")
        from django.core.exceptions import PermissionDenied

        with mock.patch("hr_staff.api.staff.make_staff_context", return_value=ctx()):
            with self.assertRaises(PermissionDenied):
                staff_api.staff_list(request)

    def test_staff_list_tenant_required_403(self):
        request = self._get("/api/hr/v1/staff")
        from hr_staff.context import HrStaffContextError

        def raise_tenant_required(*a, **k):
            raise HrStaffContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

        with mock.patch("hr_staff.api.staff.make_staff_context", side_effect=raise_tenant_required):
            resp = staff_api.staff_list(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(body(resp)["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_profile_bootstrap_envelope(self):
        request = self._get(f"/api/hr/v1/staff/{self.staff.id}/profile?asOf=2026-08-01")
        with mock.patch("hr_staff.api.profile.make_staff_context", return_value=ctx()):
            resp = profile_api.profile_bootstrap(request, self.staff.id)
        data = body(resp)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["schemaVersion"], "hr03.profile.1")
        self.assertEqual(data["data"]["identityHeader"]["staffNo"], "T001238")
        self.assertEqual(
            data["data"]["currentFacts"]["primaryAssignment"]["orgName"], "人工智能学院"
        )

    def test_profile_not_found_404(self):
        import uuid

        fake = uuid.uuid4()
        request = self._get(f"/api/hr/v1/staff/{fake}/profile")
        with mock.patch("hr_staff.api.profile.make_staff_context", return_value=ctx()):
            resp = profile_api.profile_bootstrap(request, fake)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(body(resp)["error"]["code"], "STAFF_NOT_FOUND")
