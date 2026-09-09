"""Installation is not school onboarding: exact routes and no-write MySQL proof."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from base import legacy_initialization, urls as legacy_urls
from base.models import Company, CompanyGroupAssignment, Department, JobPosition
from employee.models import Employee


class RetiredInitializationRouteTests(SimpleTestCase):
    def test_every_legacy_initialization_route_is_explicitly_owned(self):
        declared = {name: route for route, name in legacy_initialization.ROUTES}
        legacy = {
            item.name: str(item.pattern)
            for item in legacy_urls.urlpatterns
            if (getattr(item, "name", None) or "").startswith("initialize-")
            or getattr(item, "name", "") == "load-demo-database"
        }
        self.assertEqual(declared, legacy)
        self.assertEqual(len(declared), 10)
        for route, name in legacy_initialization.ROUTES:
            kwargs = {"obj_id": 1} if "<int:obj_id>" in route else {}
            url = reverse(name, kwargs=kwargs)
            self.assertEqual(url, "/" + route.replace("<int:obj_id>", "1"))
            self.assertIs(resolve(url).func, legacy_initialization.retired_initialization)

    def test_retired_callback_is_method_independent_and_database_free(self):
        for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                request = RequestFactory().generic(method, "/initialize-database-user/")
                response = legacy_initialization.retired_initialization(request, obj_id=1)
                self.assertEqual(response.status_code, 410)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertIn(b"LEGACY_INITIALIZATION_RETIRED", response.content)
                self.assertNotIn("HX-Redirect", response.headers)
                self.assertNotIn("HX-Refresh", response.headers)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                   ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class RetiredInitializationMySQLTests(TestCase):
    password = "isolated-legacy-boundary-test-only"

    def setUp(self):
        self.browser = Client(enforce_csrf_checks=True)

    @staticmethod
    def facts():
        # Deliberately unscoped only in tests: detect mutations in ANY school.
        models = (get_user_model(), Company, Department, JobPosition, Employee)
        return {model._meta.label: list(model._base_manager.order_by("pk").values())
                for model in models}

    def _csrf(self):
        self.assertEqual(self.browser.get("/login/").status_code, 200)
        return self.browser.cookies["csrftoken"].value

    def _matrix(self):
        token = self._csrf()
        before = self.facts()
        for route, _name in legacy_initialization.ROUTES:
            url = "/" + route.replace("<int:obj_id>", "1")
            for method in ("get", "post"):
                with self.subTest(path=url, method=method):
                    response = getattr(self.browser, method)(
                        url,
                        {"username": "must-not-be-created", "password": self.password,
                         "confirm_password": self.password, "company": "Must not create school",
                         "department": "Must not create department", "company_id": "1"},
                        HTTP_HX_REQUEST="true", HTTP_X_CSRFTOKEN=token,
                    )
                    self.assertEqual(response.status_code, 410)
                    self.assertEqual(response.json()["error"]["code"], "LEGACY_INITIALIZATION_RETIRED")
                    self.assertEqual(self.facts(), before)

    def _sign_in(self, *, school_bound, superuser):
        User = get_user_model()
        user = User.objects.create_user(username="legacy-boundary-account", password=self.password)
        user.is_superuser = superuser
        user.is_staff = superuser
        user.is_new_employee = False
        user.save(update_fields=["is_superuser", "is_staff", "is_new_employee"])
        if school_bound:
            school = Company.objects.create(company="Boundary school", country="CN")
            group = Group.objects.create(name="School member")
            CompanyGroupAssignment.objects.create(user=user, company=school, group=group)
            CompanyGroupAssignment.sync_user_group_membership(user, group)
        csrf = self._csrf()
        response = self.browser.post("/login/", {"username": user.username, "password": self.password},
                                     HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.browser.session["_auth_user_id"]), user.pk)
        self.assertIsNone(getattr(user, "employee_get", None))

    def test_anonymous_empty_installation_cannot_bootstrap_over_http(self):
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Company.objects.exists())
        login = self.browser.get("/login/")
        self.assertNotContains(login, 'href="/initialize-database/"')
        self._matrix()

    def test_school_member_cannot_reopen_installation(self):
        self._sign_in(school_bound=True, superuser=False)
        self._matrix()

    def test_historical_school_superuser_cannot_reopen_installation(self):
        self._sign_in(school_bound=True, superuser=True)
        self._matrix()

    def test_platform_operator_also_uses_controlled_provisioning_not_old_wizard(self):
        self._sign_in(school_bound=False, superuser=True)
        self._matrix()

    def test_debug_does_not_reopen_installation(self):
        for debug in (False, True):
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                response = self.browser.get("/initialize-database-user/", HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 410)

    def test_csrf_remains_enabled_for_unsafe_requests(self):
        before = self.facts()
        response = self.browser.post("/initialize-database-user/", {"username": "denied"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.facts(), before)
