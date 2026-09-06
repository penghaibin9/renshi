"""School bootstrap contracts; DB tests must run on the real MySQL CI schema.

These are not a replacement for full-shell multi-role Chromium acceptance.
Rendering is captured in write tests to isolate permission/transaction behavior.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from base import school_management as sm
from base.models import Company, CompanyGroupAssignment
from base.settings_center import _selected_company, company_create_form
from horilla.horilla_middlewares import tenant_context
from platform_access.middleware import SafeCompanyMiddleware
from platform_access.services import is_platform_operator


class PlatformIdentityBootstrapTests(SimpleTestCase):
    def test_active_platform_account_without_school_membership(self):
        assignments = Mock()
        assignments.exists.return_value = False
        user = SimpleNamespace(is_authenticated=True, is_active=True,
                               is_superuser=True, employee_get=None,
                               company_group_assignments=assignments)
        self.assertTrue(is_platform_operator(user))
        assignments.exists.return_value = True
        self.assertFalse(is_platform_operator(user))

    def test_inactive_operator_is_rejected(self):
        self.assertFalse(is_platform_operator(SimpleNamespace(
            is_authenticated=True, is_active=False, is_superuser=True)))

    def test_identity_database_failure_does_not_grant_operator_access(self):
        assignments = Mock()
        assignments.exists.side_effect = DatabaseError("database unavailable")
        user = SimpleNamespace(is_authenticated=True, is_active=True,
                               is_superuser=True, employee_get=None,
                               company_group_assignments=assignments)
        with self.assertRaises(DatabaseError):
            is_platform_operator(user)

    def test_fingerprint_has_no_dependency_on_dict_order_or_unknown_fields(self):
        values = {field: field for field in sm.PROFILE_FIELDS}
        reverse_order = dict(reversed(list(values.items())))
        reverse_order["hq"] = True
        self.assertEqual(sm.profile_fingerprint(values), sm.profile_fingerprint(reverse_order))
        self.assertFalse(sm.profile_complete({**values, "address": "   "}))


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True)
class SchoolManagementMySQLTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.school = Company.objects.create(
            company="Bootstrap School A", address="A address", country="CN",
            state="Hunan", city="Changsha", zip="410000",
        )
        self.other = Company.objects.create(
            company="Bootstrap School B", address="B address", country="CN",
            state="Hunan", city="Changsha", zip="410001",
        )
        self.admin = self._account("bootstrap-school-admin", edit=True)
        self.viewer = self._account("bootstrap-school-viewer", edit=False)

    def _account(self, username, *, edit):
        user = get_user_model().objects.create_user(username=username, password="unused-ci-password")
        user.is_new_employee = False
        user.save(update_fields=["is_new_employee"])
        group = Group.objects.create(name=username)
        codes = ["view_company", "change_company"] if edit else ["view_company"]
        permissions = Permission.objects.filter(content_type__app_label="base", codename__in=codes)
        self.assertEqual(permissions.count(), len(codes))
        group.permissions.set(permissions)
        CompanyGroupAssignment.objects.create(user=user, company=self.school, group=group)
        CompanyGroupAssignment.sync_user_group_membership(user, group)
        return user

    def _request(self, method="GET", data=None, *, user=None, school=None):
        request = getattr(self.factory, method.lower())("/settings/school-management/", data=data or {})
        request.user = user or self.admin
        request.session = SessionStore()
        request.session["selected_company"] = str((school or self.school).pk)
        request._messages = FallbackStorage(request)
        return request

    def _payload(self, **changes):
        request = self._request()
        return {**sm.profile_values(self.school), "profile_token": sm._profile_token(request, self.school),
                **changes}

    @staticmethod
    def _capture_render(request, template, context, status=200):
        response = HttpResponse(status=status)
        response.context_data = context
        return response

    def _call(self, request):
        with tenant_context(self.school.pk), patch.object(sm, "render", side_effect=self._capture_render):
            return sm.school_management(request)

    def test_get_is_read_only_and_never_production_ready(self):
        count = LogEntry.objects.count()
        response = self._call(self._request())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data["setup"]["productionReady"])
        self.assertEqual(LogEntry.objects.count(), count)
        self.assertEqual(Company.objects.count(), 2)

    def test_first_admin_has_no_employee_but_keeps_school_session(self):
        self.assertIsNone(getattr(self.admin, "employee_get", None))
        request = self._request()
        middleware = SafeCompanyMiddleware(lambda _request: HttpResponse())
        self.assertEqual(middleware._get_user_default_company(request).pk, self.school.pk)
        middleware._set_company_session(request, self.school)
        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(request.session["selected_company"], str(self.school.pk))
        self.assertEqual(request.session["selected_company_instance"]["icon"], "")

    def test_foreign_school_is_denied_even_to_historical_school_superuser(self):
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        request = self._request(school=self.other)
        with tenant_context(self.other.pk), self.assertRaises(Http404):
            _selected_company(request)

    def test_school_superuser_cannot_create_tenants(self):
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        with self.assertRaises(PermissionDenied):
            company_create_form(self._request("POST"))
        self.assertEqual(Company.objects.count(), 2)

    def test_missing_or_union_school_never_falls_back_to_first_school(self):
        for selected in (None, "", "all"):
            with self.subTest(selected=selected):
                request = self._request()
                request.session["selected_company"] = selected
                with self.assertRaises(PermissionDenied):
                    _selected_company(request)

    def test_profile_save_reloads_and_audits_only_own_school(self):
        response = self._call(self._request("POST", self._payload(
            address="Updated address", hq="on", tenant_id=str(self.other.pk))))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("school-management"))
        self.school.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.school.address, "Updated address")
        self.assertFalse(self.school.hq)
        self.assertEqual(self.other.address, "B address")
        self.assertTrue(LogEntry.objects.filter(
            object_pk=str(self.school.pk), actor=self.admin,
            additional_data__source="school_management",
        ).exists())

    def test_view_only_user_cannot_write(self):
        request = self._request("POST", self._payload(address="Forbidden"), user=self.viewer)
        with self.assertRaises(PermissionDenied):
            self._call(request)
        self.school.refresh_from_db()
        self.assertEqual(self.school.address, "A address")

    def test_missing_tampered_and_other_actor_tokens_do_not_write(self):
        viewer_request = self._request(user=self.viewer)
        tokens = ("", "tampered", sm._profile_token(viewer_request, self.school))
        for token in tokens:
            with self.subTest(token_type="missing" if not token else "invalid"):
                response = self._call(self._request("POST", self._payload(
                    address="Forbidden", profile_token=token)))
                self.assertEqual(response.status_code, 409)
                self.school.refresh_from_db()
                self.assertEqual(self.school.address, "A address")

    def test_expired_token_does_not_write(self):
        with patch.object(sm.signing, "loads", side_effect=signing.SignatureExpired("expired")):
            response = self._call(self._request("POST", self._payload(address="Forbidden")))
        self.assertEqual(response.status_code, 409)
        self.school.refresh_from_db()
        self.assertEqual(self.school.address, "A address")

    def test_stale_snapshot_does_not_overwrite_second_edit(self):
        payload = self._payload(address="Stale edit")
        Company.objects.filter(pk=self.school.pk).update(address="Another saved edit")
        response = self._call(self._request("POST", payload))
        self.assertEqual(response.status_code, 409)
        self.school.refresh_from_db()
        self.assertEqual(self.school.address, "Another saved edit")

    def test_invalid_form_can_be_corrected_with_fresh_persisted_snapshot(self):
        response = self._call(self._request("POST", self._payload(address="", city="New city")))
        self.assertEqual(response.status_code, 400)
        token = response.context_data["profile_token"]
        self.school.refresh_from_db()
        self.assertEqual(self.school.city, "Changsha")
        response = self._call(self._request("POST", self._payload(
            address="Corrected", city="New city", profile_token=token)))
        self.assertEqual(response.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.address, "Corrected")

    def test_audit_failure_rolls_back_profile_write(self):
        with patch.object(sm.LogEntry.objects, "log_create", side_effect=RuntimeError("audit failure")):
            with self.assertRaises(RuntimeError):
                self._call(self._request("POST", self._payload(address="Must roll back")))
        self.school.refresh_from_db()
        self.assertEqual(self.school.address, "A address")

    def test_fact_query_is_explicitly_scoped_and_unavailable_is_not_empty(self):
        request = self._request()
        request.user = SimpleNamespace(has_perm=lambda _code: True)
        model = Mock()
        model.objects.filter.return_value.count.return_value = 0
        kwargs = dict(key="organizations", title="组织", permission="hr.structure.organization.view",
                      app="hr_structure", model="HrOrganization", route="hr-structure-organizations",
                      help_text="configure")
        with patch.object(sm.apps, "get_model", return_value=model):
            result = sm._count_fact(request, self.school, **kwargs)
        model.objects.filter.assert_called_once_with(tenant_id=self.school.pk)
        self.assertEqual(result["state"], "MISSING")
        with patch.object(sm.apps, "get_model", side_effect=LookupError("unavailable")):
            result = sm._count_fact(request, self.school, **kwargs)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIsNone(result["count"])

    def test_status_endpoint_returns_503_for_unavailable_not_success(self):
        summary = {"productionReady": False, "steps": [{"state": "UNAVAILABLE"}]}
        with tenant_context(self.school.pk), patch.object(sm, "setup_summary", return_value=summary):
            response = sm.school_setup_status(self._request())
        self.assertEqual(response.status_code, 503)
        self.assertFalse(json.loads(response.content)["productionReady"])
