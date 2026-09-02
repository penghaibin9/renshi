import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory, SimpleTestCase

from hr_payroll import api
from hr_payroll.authority_registry import (
    PERM_CHANGE_APPROVE,
    PERM_CHANGE_MANAGE,
    PERM_CHANGE_VIEW,
)


CASE_ID = UUID("00000000-0000-0000-0000-000000001515")
STAFF_ID = UUID("00000000-0000-0000-0000-000000001503")


class _User:
    is_authenticated = True
    is_superuser = False
    id = 1515

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, permission):
        return permission in self.permissions


def _case(status="DRAFT"):
    return SimpleNamespace(
        id=CASE_ID,
        case_no="XZ-2026-001",
        staff_id=STAFF_ID,
        change_type="ALLOWANCE_START",
        get_change_type_display=lambda: "津补贴启用",
        payroll_variable_key="transportAllowance",
        item_name="交通补贴",
        amount_mode="SET",
        get_amount_mode_display=lambda: "设置金额",
        amount=Decimal("300.00"),
        currency_code="CNY",
        proration_mode="NONE",
        get_proration_mode_display=lambda: "不折算",
        effective_from=date(2026, 9, 1),
        effective_to=None,
        review_date=None,
        reason_code="SCHOOL_POLICY",
        note="",
        source_domain="HR15",
        source_ref="POLICY-1",
        source_version="1",
        source_snapshot_json={},
        evidence_refs_json=["DOC-1"],
        supersedes_case_id=None,
        status=status,
        get_status_display=lambda: status,
        content_hash="a" * 64 if status != "DRAFT" else "",
        submitted_by=1515 if status != "DRAFT" else None,
        submitted_at=None,
        decided_by=None,
        decided_at=None,
        decision_note="",
    )


class CompensationChangeApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.payload = {
            "caseNo": "XZ-2026-001",
            "staffId": str(STAFF_ID),
            "changeType": "ALLOWANCE_START",
            "payrollVariableKey": "transportAllowance",
            "itemName": "交通补贴",
            "amountMode": "SET",
            "amount": "300.00",
            "effectiveFrom": "2026-09-01",
            "reasonCode": "SCHOOL_POLICY",
            "evidenceRefs": ["DOC-1"],
        }

    def post(self, path, payload, permissions):
        request = self.factory.post(
            path, data=json.dumps(payload), content_type="application/json"
        )
        request.user = _User(permissions)
        return request

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    def test_view_only_user_cannot_create_change(self, _allowed, _tenant):
        request = self.post(
            "/api/v1/hr/payroll/compensation-changes/",
            self.payload,
            {PERM_CHANGE_VIEW},
        )
        with patch("hr_payroll.api.CompensationChangeService") as service:
            response = api.compensation_changes(request)
        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.CompensationChangeService")
    def test_manager_creates_change_draft(self, service_cls, _allowed, _tenant):
        service_cls.return_value.create_draft.return_value = _case()
        request = self.post(
            "/api/v1/hr/payroll/compensation-changes/",
            self.payload,
            {PERM_CHANGE_MANAGE},
        )

        response = api.compensation_changes(request)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(body["schemaVersion"], "hr15.compensation-change.1")
        self.assertEqual(body["data"]["changeTypeLabel"], "津补贴启用")
        service_cls.assert_called_once_with(
            77, actor_user_id=1515, correlation_id=""
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    def test_manager_without_approve_permission_cannot_decide(self, _allowed, _tenant):
        request = self.post(
            f"/api/v1/hr/payroll/compensation-changes/{CASE_ID}/approve/",
            {},
            {PERM_CHANGE_MANAGE},
        )
        with patch("hr_payroll.api.CompensationChangeService") as service:
            response = api.approve_compensation_change(request, CASE_ID)
        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.CompensationChangeService")
    def test_approver_decides_submitted_change(self, service_cls, _allowed, _tenant):
        service_cls.return_value.approve.return_value = _case("APPROVED")
        request = self.post(
            f"/api/v1/hr/payroll/compensation-changes/{CASE_ID}/approve/",
            {"decisionNote": "同意"},
            {PERM_CHANGE_APPROVE},
        )

        response = api.approve_compensation_change(request, CASE_ID)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.approve.assert_called_once_with(
            CASE_ID, decision_note="同意"
        )
