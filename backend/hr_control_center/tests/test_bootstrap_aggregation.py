from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext
from hr_control_center.services.overview_service import OverviewService


class BootstrapAggregationTests(SimpleTestCase):
    def setUp(self):
        self.context = HrRequestContext(tenant_id=1)
        self.user = Mock(is_superuser=True)

    def _service(self, *, todo=None, alert=None, quick=None):
        todo = todo or Mock()
        alert = alert or Mock()
        quick = quick or Mock()
        return OverviewService(
            todo_service_factory=lambda: todo,
            alert_service_factory=lambda: alert,
            quick_action_service_factory=lambda: quick,
        )

    def test_bootstrap_contains_real_subsystems(self):
        todo = Mock()
        todo.get_summary.return_value = {"status": "OK", "total": 3}
        alert = Mock()
        alert.get_summary.return_value = {"critical": 1, "high": 2}
        quick = Mock()
        quick.get_catalog.return_value = [{"key": "staff.create"}]
        service = self._service(todo=todo, alert=alert, quick=quick)

        with patch.object(service, "get_metric") as get_metric:
            get_metric.side_effect = lambda key, _ctx: {"metricKey": key, "status": "OK"}
            payload = service.get_bootstrap(self.context, user=self.user)

        self.assertEqual(payload["todoSummary"]["total"], 3)
        self.assertEqual(payload["alertSummary"]["status"], "OK")
        self.assertEqual(payload["quickActions"][0]["key"], "staff.create")
        self.assertEqual(payload["partialSources"], [])

    def test_todo_failure_does_not_fail_bootstrap_or_become_zero(self):
        todo = Mock()
        todo.get_summary.side_effect = RuntimeError("down")
        alert = Mock()
        alert.get_summary.return_value = {"critical": 0}
        service = self._service(todo=todo, alert=alert)

        with patch.object(service, "get_metric") as get_metric:
            get_metric.side_effect = lambda key, _ctx: {"metricKey": key, "status": "OK"}
            payload = service.get_bootstrap(self.context, user=self.user)

        self.assertEqual(payload["todoSummary"]["status"], "UNAVAILABLE")
        self.assertIsNone(payload["todoSummary"]["total"])
        self.assertIn("todos", payload["partialSources"])
        self.assertEqual(payload["consistency"], "PARTIAL")

    def test_subsystems_are_permission_trimmed(self):
        user = Mock(is_superuser=False)
        user.has_perm.return_value = False
        service = self._service()

        with patch.object(service, "get_metric") as get_metric:
            get_metric.side_effect = lambda key, _ctx: {"metricKey": key, "status": "OK"}
            payload = service.get_bootstrap(self.context, user=user)

        self.assertEqual(payload["todoSummary"]["status"], "FILTERED")
        self.assertEqual(payload["alertSummary"]["status"], "FILTERED")
        self.assertEqual(payload["quickActions"], [])
