"""HR05 collaboration task action guards; run with repository MySQL settings."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from hr_onboarding.api.tasks import task_complete, task_start, task_waive, tasks_list
from hr_onboarding.constants import TaskStatus
from hr_onboarding.models import HrOnboardingTaskInstance
from hr_onboarding.services.task_service import TaskService

from .test_s6 import _prepared_case


class TaskActionGuardTests(TestCase):
    def setUp(self):
        self.tenant = 90511
        self.actor_id = 77
        self.case, _ = _prepared_case(tenant_id=self.tenant)
        TaskService(tenant_id=self.tenant, actor_user_id=9).instantiate_tasks(
            self.case,
            assignee_overrides={"IT_SERVICE": self.actor_id},
        )
        self.task = HrOnboardingTaskInstance.objects.get(case=self.case)
        self.factory = RequestFactory()

    def _user(self, user_id=None, permissions=None):
        allowed = set(permissions or ())
        return SimpleNamespace(
            id=self.actor_id if user_id is None else user_id,
            is_authenticated=True,
            is_superuser=False,
            has_perm=lambda code: code in allowed,
        )

    def _patch_context(self):
        return (
            patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=self.tenant),
            patch("base.auth_backends.get_allowed_company_ids", return_value={self.tenant}),
            patch("hr_onboarding.api.base.get_authority_mode", return_value="HR05_AUTHORITY"),
        )

    def _post(self, view, payload, *, version=None, user_id=None, permissions=None):
        extra = {}
        if version is not None:
            extra["HTTP_IF_MATCH"] = str(version)
        request = self.factory.post(
            "/task-action",
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )
        request.user = self._user(user_id, permissions)
        tenant_patch, member_patch, authority_patch = self._patch_context()
        with tenant_patch, member_patch, authority_patch:
            return view(request, self.task.id)

    def _list(self, *, user_id=None, permissions=None):
        request = self.factory.get(f"/api/v1/hr/onboarding/cases/{self.case.id}/tasks")
        request.user = self._user(user_id, permissions)
        tenant_patch, member_patch, authority_patch = self._patch_context()
        with tenant_patch, member_patch, authority_patch:
            return tasks_list(request, self.case.id)

    def test_list_exposes_version_and_only_authorized_state_actions(self):
        permissions = {"hr05.case.view", "hr05.task.complete", "hr05.task.waive"}
        response = self._list(permissions=permissions)
        self.assertEqual(response.status_code, 200)
        item = json.loads(response.content)["data"]["items"][0]
        self.assertEqual(item["version"], self.task.version)
        self.assertEqual(
            item["actionCapabilities"],
            {"start": True, "complete": False, "waive": True},
        )

    def test_assigned_other_user_cannot_operate_without_manage_override(self):
        permissions = {"hr05.case.view", "hr05.task.complete", "hr05.task.waive"}
        response = self._list(user_id=self.actor_id + 1, permissions=permissions)
        caps = json.loads(response.content)["data"]["items"][0]["actionCapabilities"]
        self.assertEqual(caps, {"start": False, "complete": False, "waive": False})

        response = self._post(
            task_start,
            {},
            version=self.task.version,
            user_id=self.actor_id + 1,
            permissions={"hr05.task.complete"},
        )
        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.NOT_STARTED)

    def test_task_manager_can_act_for_assigned_other_user(self):
        permissions = {
            "hr05.case.view",
            "hr05.task.complete",
            "hr05.task.waive",
            "hr05.task.manage",
        }
        response = self._list(user_id=self.actor_id + 1, permissions=permissions)
        caps = json.loads(response.content)["data"]["items"][0]["actionCapabilities"]
        self.assertTrue(caps["start"])
        self.assertTrue(caps["waive"])

    def test_stale_version_rejected_before_task_transition(self):
        response = self._post(
            task_start,
            {},
            version=self.task.version + 1,
            permissions={"hr05.task.complete"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"]["code"], "VERSION_CONFLICT")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.NOT_STARTED)

    def test_json_start_then_complete_records_actor_note_and_evidence(self):
        response = self._post(
            task_start,
            {},
            version=self.task.version,
            permissions={"hr05.task.complete"},
        )
        self.assertEqual(response.status_code, 200)
        started = json.loads(response.content)["data"]
        self.assertEqual(started["status"], TaskStatus.IN_PROGRESS)

        response = self._post(
            task_complete,
            {"note": "邮箱已开通", "evidence": "IAM-REQ-1001"},
            version=started["version"],
            permissions={"hr05.task.complete"},
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.assertEqual(self.task.completion_payload["completed_by"], self.actor_id)
        self.assertEqual(self.task.completion_payload["note"], "邮箱已开通")
        self.assertEqual(self.task.completion_payload["evidence"]["evidence"], "IAM-REQ-1001")

    def test_waive_requires_reason_and_keeps_authority_fact(self):
        response = self._post(
            task_waive,
            {"reason": ""},
            version=self.task.version,
            permissions={"hr05.task.waive"},
        )
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.NOT_STARTED)

        response = self._post(
            task_waive,
            {"reason": "学校已由统一身份平台自动完成"},
            version=self.task.version,
            permissions={"hr05.task.waive"},
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.WAIVED)
        self.assertEqual(self.task.completion_payload["waived_by"], self.actor_id)
        self.assertEqual(self.task.completion_payload["reason"], "学校已由统一身份平台自动完成")
