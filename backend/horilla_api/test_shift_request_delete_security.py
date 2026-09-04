from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from horilla_api.api_views.base.views import (
    ShiftRequestDeleteView,
    can_delete_shift_request,
)


class ShiftRequestDeleteAuthorityTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _request(self, *, employee, permissions=()):
        return SimpleNamespace(
            user=SimpleNamespace(
                employee_get=employee,
                has_perm=lambda permission: permission in permissions,
            )
        )

    @patch(
        "horilla_api.api_views.base.views.is_reportingmanger",
        return_value=False,
    )
    def test_owner_can_only_delete_unapproved_request(self, _is_manager):
        employee = object()
        request = self._request(employee=employee)

        self.assertTrue(
            can_delete_shift_request(
                request,
                SimpleNamespace(employee_id=employee, approved=False),
            )
        )
        self.assertFalse(
            can_delete_shift_request(
                request,
                SimpleNamespace(employee_id=employee, approved=True),
            )
        )

    @patch(
        "horilla_api.api_views.base.views.is_reportingmanger",
        return_value=False,
    )
    def test_delete_permission_can_delete_approved_request(self, _is_manager):
        request = self._request(
            employee=object(), permissions={"base.delete_shiftrequest"}
        )

        allowed = can_delete_shift_request(
            request,
            SimpleNamespace(employee_id=object(), approved=True),
        )

        self.assertTrue(allowed)

    @patch(
        "horilla_api.api_views.base.views.is_reportingmanger",
        return_value=True,
    )
    def test_reporting_manager_can_delete_request(self, _is_manager):
        request = self._request(employee=object())

        allowed = can_delete_shift_request(
            request,
            SimpleNamespace(employee_id=object(), approved=True),
        )

        self.assertTrue(allowed)

    @patch(
        "horilla_api.api_views.base.views.can_delete_shift_request",
        return_value=False,
    )
    @patch("horilla_api.api_views.base.views.ShiftRequest.objects.filter")
    def test_bulk_delete_is_all_or_nothing_on_permission_denial(
        self, filter_requests, _can_delete
    ):
        filter_requests.return_value = [SimpleNamespace(id=1)]
        request = self.factory.delete(
            "/api/shift-request-bulk-delete", {"ids": [1]}, format="json"
        )
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True))

        response = ShiftRequestDeleteView.as_view()(request)

        self.assertEqual(response.status_code, 403)
        filter_requests.assert_called_once_with(id__in={1})

    @patch(
        "horilla_api.api_views.base.views.can_delete_shift_request",
        return_value=True,
    )
    @patch("horilla_api.api_views.base.views.ShiftRequest.objects.filter")
    def test_authorized_bulk_delete_removes_only_requested_rows(
        self, filter_requests, _can_delete
    ):
        item = SimpleNamespace(id=1)
        delete_queryset = MagicMock()
        filter_requests.side_effect = [[item], delete_queryset]
        request = self.factory.delete(
            "/api/shift-request-bulk-delete", {"ids": [1]}, format="json"
        )
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True))

        response = ShiftRequestDeleteView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        delete_queryset.delete.assert_called_once_with()
