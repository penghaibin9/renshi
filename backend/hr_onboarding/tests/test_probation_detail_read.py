"""HR05 record-reader regressions; run with the existing MySQL test settings.

Read fixtures are deliberately synthetic. They do not certify the onboarding,
review or final-decision writers, nor substitute for multirole browser UAT.
"""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

from hr_onboarding.api.probation_detail import probation_detail
from hr_onboarding.models import (
    HrOnboardingCase,
    HrProbationCase,
    HrProbationExtension,
    HrProbationGoal,
    HrProbationReview,
)


class ProbationDetailReadTests(TestCase):
    def setUp(self):
        self.tenant = 90509
        self.record = HrProbationCase.objects.create(
            tenant_id=self.tenant,
            start_date=date(2026, 1, 1),
            planned_end_date=date(2026, 7, 1),
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
        )
        self.foreign = HrProbationCase.objects.create(
            tenant_id=self.tenant + 1,
            start_date=date(2026, 1, 1),
            planned_end_date=date(2026, 7, 1),
        )
        self.factory = RequestFactory()

    def _request(self, params=None, permissions=None, authenticated=True):
        allowed = {"hr05.probation.manage"} if permissions is None else set(permissions)
        request = self.factory.get("/api/v1/hr/onboarding/probations/" + str(self.record.id), params or {})
        request.user = SimpleNamespace(
            id=90509, is_authenticated=authenticated, is_superuser=False,
            has_perm=lambda code: code in allowed,
        )
        return request

    def _read(self, object_id=None, params=None, permissions=None, membership=True):
        request = self._request(params, permissions)
        with patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=self.tenant), patch(
            "base.auth_backends.get_allowed_company_ids",
            return_value={self.tenant} if membership else set(),
        ), patch("hr_onboarding.api.base.get_authority_mode", return_value="HR05_AUTHORITY"):
            return probation_detail(request, object_id or self.record.id)

    def test_canonical_named_route_resolves_to_protected_reader(self):
        url = reverse("hr05-api-probation-detail", kwargs={"probation_id": self.record.id})
        self.assertEqual(url, f"/api/v1/hr/onboarding/probations/{self.record.id}")
        match = resolve(url)
        self.assertEqual(match.func, probation_detail)
        self.assertEqual(match.func.hr05_permission_code, "hr05.probation.manage")

    def test_summary_is_one_object_and_no_store(self):
        with self.assertNumQueries(1):
            response = self._read()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        data = json.loads(response.content)["data"]
        self.assertEqual(data["probation"]["id"], str(self.record.id))
        self.assertEqual(data["probation"]["start_date"], "2026-01-01")
        self.assertIsNone(data["probation"]["actual_end_date"])
        self.assertEqual(data["probation"]["version"], 1)
        self.assertEqual(data["section"]["key"], "summary")
        self.assertFalse(data["canViewCase"])
        self.assertNotIn("tenant_id", data["probation"])
        self.assertNotIn("items", data["probation"])

    def test_case_link_capability_requires_its_own_permission(self):
        response = self._read(permissions={"hr05.probation.manage", "hr05.case.view"})
        self.assertTrue(json.loads(response.content)["data"]["canViewCase"])

    def test_anonymous_or_missing_manage_cannot_reach_context_or_orm(self):
        for request in (self._request(permissions=set()), self._request(authenticated=False)):
            with self.subTest(user=request.user), self.assertNumQueries(0), patch(
                "hr_onboarding.api.base.make_hr05_context"
            ) as context:
                with self.assertRaises(PermissionDenied):
                    probation_detail(request, self.record.id)
                context.assert_not_called()

    def test_missing_membership_fails_before_record_lookup(self):
        with self.assertNumQueries(0):
            response = self._read(membership=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_foreign_missing_and_invalid_identifiers_share_not_found_message(self):
        for object_id in (self.foreign.id, uuid4(), "not-a-uuid"):
            with self.subTest(object_id=object_id):
                response = self._read(object_id)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(json.loads(response.content)["error"]["message"], "试用记录不存在或无权访问")

    def test_query_tenant_cannot_switch_record_owner(self):
        response = self._read(self.foreign.id, {"tenant_id": self.foreign.tenant_id})
        self.assertEqual(response.status_code, 404)

    def test_unsupported_narrow_scope_is_not_silently_widened(self):
        for params in ({"scope_type": "ASSIGNED"}, {"scope_type": "COLLEGE", "scope_id": "12"}, {"scope_id": "12"}):
            with self.subTest(params=params), self.assertNumQueries(0):
                self.assertEqual(self._read(params=params).status_code, 403)

    def test_invalid_section_or_page_is_rejected_without_lookup(self):
        for params in ({"section": "decision"}, {"page": "0"}, {"page": "-1"}, {"page": "2"}, {"page": "1.5"}, {"section": "reviews", "page": "10001"}):
            with self.subTest(params=params), self.assertNumQueries(0):
                self.assertEqual(self._read(params=params).status_code, 400)

    def test_corrupt_foreign_parent_is_not_exposed(self):
        parent = HrOnboardingCase.objects.create(
            tenant_id=self.tenant + 1, case_no="READ-ONLY-FOREIGN", source_type="HR04_HIRE", source_id="reader-fixture",
        )
        HrProbationCase.objects.filter(pk=self.record.pk).update(onboarding_case=parent)
        self.assertEqual(self._read().status_code, 404)

    def test_reviews_page_is_bounded_and_excludes_foreign_or_other_object_rows(self):
        for number in range(21):
            HrProbationReview.objects.create(
                tenant_id=self.tenant, probation_case=self.record, review_type="HR", content=f"Synthetic read fixture {number}",
            )
        HrProbationReview.objects.create(tenant_id=self.tenant + 1, probation_case=self.record, review_type="HR", content="FOREIGN-CHILD")
        HrProbationReview.objects.create(tenant_id=self.tenant, probation_case=self.foreign, review_type="HR", content="OTHER-OBJECT")
        with self.assertNumQueries(2):
            first = json.loads(self._read(params={"section": "reviews"}).content)["data"]["section"]
        second = json.loads(self._read(params={"section": "reviews", "page": "2"}).content)["data"]["section"]
        self.assertEqual(len(first["items"]), 20)
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(second["items"]), 1)
        self.assertFalse(second["hasMore"])
        self.assertFalse({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
        self.assertNotIn("FOREIGN-CHILD", str(first) + str(second))
        self.assertNotIn("OTHER-OBJECT", str(first) + str(second))
        self.assertNotIn("tenant_id", first["items"][0])

    def test_goals_and_extensions_are_real_rows_without_derived_completion(self):
        goal = HrProbationGoal.objects.create(tenant_id=self.tenant, probation_case=self.record, title="合成读取目标", evidence_required=False)
        extension = HrProbationExtension.objects.create(
            tenant_id=self.tenant, probation_case=self.record, old_end_date=date(2026, 7, 1), new_end_date=date(2026, 8, 1), reason="合成只读历史",
        )
        goals = json.loads(self._read(params={"section": "goals"}).content)["data"]["section"]["items"]
        extensions = json.loads(self._read(params={"section": "extensions"}).content)["data"]["section"]["items"]
        self.assertEqual(goals[0]["id"], str(goal.id))
        self.assertFalse(goals[0]["evidence_required"])
        self.assertNotIn("completed", goals[0])
        self.assertEqual(extensions[0]["id"], str(extension.id))
        self.assertEqual(extensions[0]["old_end_date"], "2026-07-01")
        self.record.refresh_from_db()
        self.assertEqual(self.record.version, 1)
        self.assertEqual(self.record.extension_count, 0)

    def test_unsafe_method_is_not_a_decision_writer(self):
        request = self.factory.post("/api/v1/hr/onboarding/probations/" + str(self.record.id))
        with self.assertNumQueries(0), patch("hr_onboarding.api.base.make_hr05_context") as context:
            self.assertEqual(probation_detail(request, self.record.id).status_code, 405)
            context.assert_not_called()
