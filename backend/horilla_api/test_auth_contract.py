from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from horilla_api.api_views.auth.views import LoginAPIView


class LoginApiContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = LoginAPIView.as_view()

    @patch("horilla_api.api_views.auth.views.authenticate")
    def test_username_and_password_are_both_required(self, authenticate):
        for payload in ({"username": "teacher"}, {"password": "secret"}, {}):
            response = self.view(self.factory.post("/api/login/", payload))

            self.assertEqual(response.status_code, 400)
        authenticate.assert_not_called()

    @patch("horilla_api.api_views.auth.views.authenticate", return_value=None)
    def test_invalid_credentials_return_unauthorized(self, authenticate):
        response = self.view(
            self.factory.post(
                "/api/login/",
                {"username": "teacher", "password": "wrong"},
            )
        )

        self.assertEqual(response.status_code, 401)
        authenticate.assert_called_once_with(username="teacher", password="wrong")
