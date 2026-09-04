"""Focused HTTP contracts for the HR08 V2 workspace."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from hr_staff.models import HrPerson

from hr_external.api import hiring, integration, renewal_exit, tasks
from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalEngagement,
    HrExternalExitCase,
    HrExternalHiringCase,
    HrExternalServiceTask,
)
from hr_external.services.category_service import CategoryService
from hr_external.services.profile_service import ProfileService


class Hr08CollectionDispatcherTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_hiring_collection_dispatches_get_and_post(self):
        with (
            patch.object(hiring, "hiring_list", return_value="listed") as listed,
            patch.object(hiring, "hiring_create", return_value="created") as created,
        ):
            self.assertEqual(hiring.hiring_collection(self.factory.get("/")), "listed")
            self.assertEqual(hiring.hiring_collection(self.factory.post("/")), "created")
        listed.assert_called_once()
        created.assert_called_once()

    def test_task_collection_dispatches_get_and_post(self):
        with (
            patch.object(tasks, "task_list", return_value="listed") as listed,
            patch.object(tasks, "task_create", return_value="created") as created,
        ):
            self.assertEqual(tasks.task_collection(self.factory.get("/")), "listed")
            self.assertEqual(tasks.task_collection(self.factory.post("/")), "created")
        listed.assert_called_once()
        created.assert_called_once()


class Hr08HiringCreateBoundaryTests(TestCase):
    TENANT = 8808
    OTHER_TENANT = 8809

    def setUp(self):
        self.factory = RequestFactory()
        CategoryService().ensure_default_categories(self.TENANT)
        CategoryService().ensure_default_categories(self.OTHER_TENANT)
        self.person = HrPerson.objects.create(
            tenant_id=self.TENANT,
            legal_name="V2 外聘候选人",
        )
        self.profile = ProfileService().create_profile(
            tenant_id=self.TENANT,
            person_id=self.person.id,
            primary_category_code="PART_TIME_TEACHER",
        )
        self.other_person = HrPerson.objects.create(
            tenant_id=self.OTHER_TENANT,
            legal_name="其他学校候选人",
        )
        self.other_profile = ProfileService().create_profile(
            tenant_id=self.OTHER_TENANT,
            person_id=self.other_person.id,
            primary_category_code="PART_TIME_TEACHER",
        )
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        self.context = SimpleNamespace(tenant_id=self.TENANT, user_id=81)

    def _post(self, **overrides):
        payload = {
            "requestOrgId": 880801,
            "categoryId": str(self.profile.primary_category_id),
            "proposedProfileId": str(self.profile.id),
            "purpose": "外聘教学",
            "requestedStart": date.today().isoformat(),
            "plannedAssignments": [{"assignmentType": "TEACHING"}],
        }
        payload.update(overrides)
        request = self.factory.post(
            "/api/v1/hr/external-teachers/hiring-cases",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = self.user
        with (
            patch.object(hiring, "_ctx", return_value=(self.context, None)),
            patch(
                "hr_structure.public.get_organization_evidence",
                return_value=SimpleNamespace(missing_organization_ids=()),
            ),
        ):
            return hiring.hiring_create(request)

    def test_create_resolves_tenant_scoped_profile_and_category(self):
        response = self._post()
        self.assertEqual(response.status_code, 201)
        case = HrExternalHiringCase.objects.get(tenant_id=self.TENANT)
        self.assertEqual(case.proposed_person_id_id, self.person.id)
        self.assertEqual(case.category_id_id, self.profile.primary_category_id)
        self.assertEqual(case.request_org_id, 880801)
        self.assertEqual(case.status, "DRAFT")

    def test_cross_tenant_profile_is_rejected(self):
        response = self._post(proposedProfileId=str(self.other_profile.id))
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "EXTERNAL_PROFILE_NOT_FOUND")
        self.assertFalse(HrExternalHiringCase.objects.filter(tenant_id=self.TENANT).exists())


class Hr08ActionClosureTests(TestCase):
    TENANT = 8810

    def setUp(self):
        self.factory = RequestFactory()
        CategoryService().ensure_default_categories(self.TENANT)
        self.person = HrPerson.objects.create(
            tenant_id=self.TENANT,
            legal_name="V2 办理闭环候选人",
        )
        self.profile = ProfileService().create_profile(
            tenant_id=self.TENANT,
            person_id=self.person.id,
            primary_category_code="OTHER",
        )
        self.engagement = HrExternalEngagement.objects.create(
            tenant_id=self.TENANT,
            engagement_no="ENG-V2-CLOSURE",
            person_id=self.person,
            external_profile_id=self.profile,
            category_id=self.profile.primary_category,
            host_organization_id=881001,
            start_at=date.today(),
            status="ACTIVE",
        )
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        self.context = SimpleNamespace(tenant_id=self.TENANT, user_id=82)

    def test_task_create_immediately_forms_an_assigned_actionable_task(self):
        request = self.factory.post(
            "/api/v1/hr/external-teachers/tasks",
            data=json.dumps(
                {
                    "engagementId": str(self.engagement.id),
                    "taskType": "TEACHING",
                    "title": "V2 可办理任务",
                    "plannedStart": date.today().isoformat(),
                    "ownerOrgId": 881001,
                }
            ),
            content_type="application/json",
        )
        request.user = self.user
        with patch.object(tasks, "_ctx", return_value=(self.context, None)):
            response = tasks.task_create(request)
        self.assertEqual(response.status_code, 201)
        task = HrExternalServiceTask.objects.get(tenant_id=self.TENANT)
        self.assertEqual(task.status, "ASSIGNED")

    def test_exit_review_advances_one_auditable_state_per_request(self):
        case = HrExternalExitCase.objects.create(
            tenant_id=self.TENANT,
            engagement_id=self.engagement,
            exit_reason="TERM_COMPLETED",
            planned_end_at=date.today(),
            status="PLANNED",
        )
        request = self.factory.post(
            f"/api/v1/hr/external-teachers/exits/{case.id}/prepare"
        )
        request.user = self.user
        with patch.object(
            renewal_exit, "_ctx", return_value=(self.context, None)
        ):
            first = renewal_exit.exit_prepare(request, case.id)
            second = renewal_exit.exit_prepare(request, case.id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        case.refresh_from_db()
        self.assertEqual(case.status, "READY_TO_EXIT")

    def test_engagement_access_api_returns_chinese_status_and_system_labels(self):
        HrExternalAccessGrant.objects.create(
            tenant_id=self.TENANT,
            engagement_id=self.engagement,
            target_system="EXTERNAL_PORTAL",
            role_code="EXTERNAL_TEACHER_PORTAL",
            status="GRANTED",
        )
        request = self.factory.get(
            f"/api/v1/hr/external-teachers/engagements/{self.engagement.id}/access"
        )
        request.user = self.user
        with patch.object(integration, "_ctx", return_value=(self.context, None)):
            response = integration.engagement_access(request, self.engagement.id)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)["data"]
        self.assertEqual(payload["statusLabel"], "聘期中")
        self.assertEqual(payload["items"][0]["targetSystemLabel"], "外聘人员门户")
        self.assertEqual(payload["items"][0]["statusLabel"], "已授权")
