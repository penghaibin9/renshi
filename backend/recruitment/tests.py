from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.sidebar import SUBMENUS, pipeline_accessibility, survey_accessibility


class SidebarAccessibilityTests(SimpleTestCase):
    def setUp(self):
        self.request = SimpleNamespace(
            user=SimpleNamespace(has_perm=lambda _permission: True)
        )

    @patch("recruitment.sidebar.is_stagemanager", return_value=False)
    def test_pipeline_check_does_not_mutate_redirect(self, _is_stage_manager):
        submenu = {"redirect": "/recruitment/pipeline/?closed=false"}

        pipeline_accessibility(self.request, submenu)
        pipeline_accessibility(self.request, submenu)

        self.assertEqual(submenu["redirect"].count("closed=false"), 1)

    @patch("recruitment.sidebar.is_recruitmentmangers", return_value=False)
    def test_survey_check_does_not_mutate_redirect(self, _is_manager):
        submenu = {"redirect": "/recruitment/survey/?closed=false"}

        survey_accessibility(self.request, submenu)
        survey_accessibility(self.request, submenu)

        self.assertEqual(submenu["redirect"].count("closed=false"), 1)

    def test_sidebar_query_filters_are_declared_once(self):
        self.assertEqual(SUBMENUS[1]["redirect"].count("closed=false"), 1)
        self.assertEqual(SUBMENUS[6]["redirect"].count("closed=false"), 1)
