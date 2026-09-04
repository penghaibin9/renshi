from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.client import RequestFactory

from horilla_automations import apps as mail_apps
from pms import apps as pms_apps
from base.runtime_automations import RuntimeAutomationMiddleware


class DeferredRuntimeAutomationTests(SimpleTestCase):
    def tearDown(self):
        mail_apps._automation_initialized = False
        pms_apps._automation_initialized = False

    @patch("horilla_automations.signals.start_automation")
    def test_mail_automation_initializes_only_once(self, start):
        mail_apps._automation_initialized = False
        mail_apps.initialize_mail_automation_once()
        mail_apps.initialize_mail_automation_once()
        start.assert_called_once_with()

    @patch("pms.signals.start_automation")
    def test_pms_automation_initializes_only_once(self, start):
        pms_apps._automation_initialized = False
        pms_apps.initialize_pms_automation_once()
        pms_apps.initialize_pms_automation_once()
        start.assert_called_once_with()

    @patch("base.runtime_automations.RuntimeAutomationMiddleware._initialize_optional_automations")
    def test_health_and_readiness_never_initialize_automations(self, initialize):
        middleware = RuntimeAutomationMiddleware(lambda request: object())
        factory = RequestFactory()
        middleware(factory.get("/health/"))
        middleware(factory.get("/ready/"))
        initialize.assert_not_called()

    @patch("base.runtime_automations.RuntimeAutomationMiddleware._initialize_optional_automations")
    def test_business_request_initializes_automations(self, initialize):
        middleware = RuntimeAutomationMiddleware(lambda request: object())
        middleware(RequestFactory().get("/hr/overview"))
        initialize.assert_called_once_with()
