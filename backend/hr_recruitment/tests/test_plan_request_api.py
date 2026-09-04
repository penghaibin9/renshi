import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from hr_recruitment.api.plan import plan_request_detail
from hr_recruitment.constants import PlanRequestStatus
from hr_recruitment.models import (
    HrHiringPlanCycle,
    HrHiringPlanLine,
    HrHiringPlanRequest,
)
from hr_structure.models import (
    HrOrganization,
    HrOrganizationVersion,
    HrPostCatalog,
    HrPostCatalogVersion,
)


TENANT = 2404


class PlanRequestDetailApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_superuser=True, id=88)
        self.organization = HrOrganization.objects.create(
            tenant_id=TENANT, stable_code="ORG-HR04", org_dimension="ADMIN"
        )
        HrOrganizationVersion.objects.create(
            tenant_id=TENANT,
            organization_id=self.organization,
            name="计算机学院",
            org_type="COLLEGE",
            validity_from=date(2026, 1, 1),
            status="EFFECTIVE",
        )
        self.catalog = HrPostCatalog.objects.create(
            tenant_id=TENANT, stable_code="CAT-HR04"
        )
        HrPostCatalogVersion.objects.create(
            tenant_id=TENANT,
            catalog_id=self.catalog,
            name="专任教师",
            validity_from=date(2026, 1, 1),
            status="ACTIVE",
        )
        self.cycle = HrHiringPlanCycle.objects.create(
            tenant_id=TENANT,
            year=2026,
            title="2026 年用人计划",
            start_date=date(2026, 1, 1),
            status="RETURNED",
        )
        self.plan_request = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT,
            cycle_id=self.cycle,
            organization_id=self.organization.id,
            organization_name="计算机学院",
            status=PlanRequestStatus.RETURNED,
            total_requested=1,
            version=3,
        )
        HrHiringPlanLine.objects.create(
            tenant_id=TENANT,
            request_id=self.plan_request,
            post_catalog_id=self.catalog.id,
            post_catalog_name="专任教师",
            requested_headcount=1,
            requested_fte="1.00",
        )

    def _call(self, method, body=None):
        if method == "GET":
            request = self.factory.get("/api/hr/v1/recruitment/plan-requests/x")
        else:
            request = self.factory.patch(
                "/api/hr/v1/recruitment/plan-requests/x",
                data=json.dumps(body or {}),
                content_type="application/json",
            )
        request.user = self.user
        with patch(
            "hr_recruitment.api.plan.make_hr04_context",
            return_value=SimpleNamespace(tenant_id=TENANT),
        ):
            return plan_request_detail(request, self.plan_request.id)

    def test_get_returns_lines_and_current_version(self):
        response = self._call("GET")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)["data"]
        self.assertEqual(data["version"], 3)
        self.assertEqual(len(data["lines"]), 1)

    def test_patch_replaces_returned_lines_with_optimistic_lock(self):
        response = self._call(
            "PATCH",
            {
                "version": 3,
                "organization_id": self.organization.id,
                "lines": [
                    {
                        "post_catalog_id": self.catalog.id,
                        "need_type": "REPLACEMENT",
                        "requested_headcount": 2,
                        "requested_fte": "1.50",
                        "target_onboard_date": "2026-09-01",
                        "reason": "补足师资",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.plan_request.refresh_from_db()
        self.assertEqual(self.plan_request.version, 4)
        self.assertEqual(self.plan_request.total_requested, 2)
        self.assertEqual(self.plan_request.lines.count(), 1)
        self.assertEqual(
            self.plan_request.lines.get().requested_headcount, 2
        )

    def test_patch_rejects_stale_browser_version(self):
        response = self._call(
            "PATCH",
            {
                "version": 2,
                "organization_id": self.organization.id,
                "lines": [
                    {
                        "post_catalog_id": self.catalog.id,
                        "requested_headcount": 2,
                        "requested_fte": 2,
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "PLAN_REQUEST_VERSION_CONFLICT",
        )

