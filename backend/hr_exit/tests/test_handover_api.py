import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr16HandoverApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()
        self.item_id = uuid.uuid4()

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_view_permission_alone_cannot_create_handover_item(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/exit/cases/{self.case_id}/handover-items/",
            data=json.dumps(
                {"itemNo": "HO-1", "categoryCode": "WORK", "title": "工作交接"}
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.READ_PERMISSION})

        response = api.create_handover_item(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.HANDOVER_PERMISSION.encode(), response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitHandoverService")
    def test_handover_permission_uses_resolved_tenant_and_actor(
        self, service_cls, _allowed, _tenant
    ):
        item = SimpleNamespace(
            id=self.item_id,
            item_no="HO-2",
            case_id=self.case_id,
            category_code="WORK",
            title="工作资料移交",
            required=True,
            owner_staff_id=None,
            due_date=None,
            status="PENDING",
            supersedes_item_id=None,
        )
        service_cls.return_value.add_item.return_value = item
        request = self.factory.post(
            f"/api/v1/hr/exit/cases/{self.case_id}/handover-items/",
            data=json.dumps(
                {
                    "itemNo": "HO-2",
                    "categoryCode": "WORK",
                    "title": "工作资料移交",
                    "required": True,
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.HANDOVER_PERMISSION})

        response = api.create_handover_item(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.add_item.assert_called_once_with(
            case_id=self.case_id,
            item_no="HO-2",
            category_code="WORK",
            title="工作资料移交",
            description="",
            required=True,
            owner_staff_id=None,
            due_date=None,
            supersedes_item_id=None,
        )
        self.assertIn(b'"status": "PENDING"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitHandoverService")
    def test_complete_endpoint_preserves_evidence_reference(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.complete.return_value = SimpleNamespace(
            id=self.item_id,
            status="COMPLETED",
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/handover-items/{self.item_id}/complete/",
            data=json.dumps({"evidenceRef": "file:handover-proof"}),
            content_type="application/json",
        )
        request.user = UserStub({api.HANDOVER_PERMISSION})

        response = api.complete_handover_item(request, self.item_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.complete.assert_called_once_with(
            self.item_id, evidence_ref="file:handover-proof"
        )
        self.assertIn(b"COMPLETED", response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitHandoverService")
    def test_waive_endpoint_preserves_reason(self, service_cls, _allowed, _tenant):
        service_cls.return_value.waive.return_value = SimpleNamespace(
            id=self.item_id,
            status="WAIVED",
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/handover-items/{self.item_id}/waive/",
            data=json.dumps({"reason": "无资产领用记录"}),
            content_type="application/json",
        )
        request.user = UserStub({api.HANDOVER_PERMISSION})

        response = api.waive_handover_item(request, self.item_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.waive.assert_called_once_with(
            self.item_id, reason="无资产领用记录"
        )
        self.assertIn(b"WAIVED", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/exit/cases/{self.case_id}/handover-items/"
        )
        request.user = UserStub({api.HANDOVER_PERMISSION})
        response = api.create_handover_item(request, self.case_id)
        self.assertEqual(response.status_code, 405)
