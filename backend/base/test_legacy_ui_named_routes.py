from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse


class LegacyUiNamedRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_reimbursement_reverse_stays_renderable_and_canonical(self):
        path = reverse("view-reimbursement")
        self.assertEqual(path, "/payroll/view-reimbursement/")

        match = resolve(path)
        self.assertEqual(match.url_name, "view-reimbursement")

        response = match.func(self.factory.get(path), **match.kwargs)
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "/hr/payroll/")
        self.assertEqual(response["Deprecation"], "true")
