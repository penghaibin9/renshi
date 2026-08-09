"""S1 bootstrap/API 契约测试：envelope + 动作/原因/受管字段 + 中文 label 成对。"""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from unittest import mock

from hr_changes.api import views as api_views
from hr_changes.api.labels import (
    action_label,
    case_status_label,
    event_type_label,
    impact_level_label,
)
from hr_changes.constants import (
    CASE_TERMINAL_STATUSES,
    CaseStatus,
    ChangeActionCode,
)
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason

TENANT = 1


def ctx():
    return HrChangeRequestContext(tenant_id=TENANT, scope=HrChangeScope(scope_type="SCHOOL"))


class ContractProbeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="hr06", password="x", is_superuser=True
        )

    def _get(self, path):
        request = self.factory.get(path)
        request.user = self.user
        return request

    def test_contract_probe_envelope(self):
        resp = api_views.contract_probe(self._get("/api/hr/v1/changes/contract"))
        body = json.loads(resp.content)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["apiVersion"], "1.0")
        self.assertEqual(body["schemaVersion"], "hr06.contract.1")
        self.assertIn("requestId", body)
        self.assertIn("generatedAt", body)
        self.assertEqual(body["data"]["status"], "ok")


class BootstrapApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="hr06", password="x", is_superuser=True
        )
        self.action = HrChangeAction.objects.create(
            tenant_id=TENANT, code=ChangeActionCode.ORG_TRANSFER, name="组织调动"
        )
        self.reason = HrChangeReason.objects.create(
            tenant_id=TENANT, action_code=ChangeActionCode.ORG_TRANSFER,
            code="WORK_NEED", name="工作需要",
        )
        HrChangeFieldDefinition.objects.create(
            tenant_id=TENANT, domain="assignment", field_code="organization",
            label="所属单位", legacy_field="EmployeeWorkInformation.department_id",
            authority_source="hr03.HrStaffAssignment.organization_id",
        )

    def _get(self, path):
        request = self.factory.get(path)
        request.user = self.user
        return request

    def test_bootstrap_data(self):
        with mock.patch("hr_changes.api.views.make_hr_change_context", return_value=ctx()):
            resp = api_views.bootstrap(self._get("/api/hr/v1/changes/bootstrap"))
        body = json.loads(resp.content)
        self.assertEqual(resp.status_code, 200)
        data = body["data"]
        # 动作
        actions = {a["code"]: a for a in data["actions"]}
        self.assertIn("ORG_TRANSFER", actions)
        self.assertEqual(actions["ORG_TRANSFER"]["label"], "组织调动")
        # 原因
        reasons = [r for r in data["reasons"] if r["actionCode"] == "ORG_TRANSFER"]
        self.assertEqual(reasons[0]["label"] if "label" in reasons[0] else reasons[0]["name"], "工作需要")
        # 受管字段
        fields = data["fieldDefinitions"]
        self.assertTrue(any(f["fieldCode"] == "organization" for f in fields))
        # 状态元数据
        meta = data["statusMeta"]
        terminal_codes = {s["code"] for s in meta["terminalStatuses"]}
        self.assertIn("REJECTED", terminal_codes)
        self.assertIn("RESCINDED", terminal_codes)
        self.assertIn("CORRECTED", terminal_codes)
        active_codes = {s["code"] for s in meta["activeStatuses"]}
        self.assertIn("APPROVED_WAITING_EFFECTIVE", active_codes)
        self.assertIn("RETURNED", active_codes)
        self.assertNotIn("REJECTED", active_codes)
        # 机器字段名不含中文
        for key in data["statusMeta"]:
            self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in key))


class LabelContractTests(TestCase):
    def test_labels(self):
        self.assertEqual(case_status_label("APPROVED_WAITING_EFFECTIVE"), "已批准待生效")
        self.assertEqual(case_status_label("RETURNED"), "已退回")
        self.assertEqual(case_status_label("REJECTED"), "已驳回")
        self.assertEqual(action_label("ORG_POSITION_TRANSFER"), "组织+岗位调动")
        self.assertEqual(action_label("TEMPORARY_SECONDMENT"), "借调")
        self.assertEqual(impact_level_label("BLOCKER"), "阻断")
        self.assertEqual(event_type_label("PersonnelChangeEffective"), "异动生效")
        # 未命中回退原值（不空）
        self.assertEqual(case_status_label("UNKNOWN"), "UNKNOWN")
        # RETURNED/REJECTED label 不同
        self.assertNotEqual(case_status_label("RETURNED"), case_status_label("REJECTED"))


class TenantIsolationTests(TestCase):
    """A0 硬门：不同 tenant 互不可见。"""

    def test_tenant_isolation_in_selector(self):
        HrChangeAction.objects.create(tenant_id=1, code="ORG_TRANSFER", name="组织调动")
        HrChangeAction.objects.create(tenant_id=2, code="ORG_TRANSFER", name="组织调动")
        from hr_changes.selectors.bootstrap_data import BootstrapDataSelector

        s1 = BootstrapDataSelector(1).actions()
        s2 = BootstrapDataSelector(2).actions()
        self.assertEqual(len(s1), 1)
        self.assertEqual(len(s2), 1)
        # tenant 2 不因 tenant 1 存在而多返回
        HrChangeAction.objects.create(tenant_id=1, code="MANAGER_CHANGE", name="直属上级变更")
        self.assertEqual(len(BootstrapDataSelector(2).actions()), 1)
