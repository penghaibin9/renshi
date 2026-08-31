from django.test import SimpleTestCase

from hr_self.services.experience_projection_service import (
    SelfExperienceProjectionService,
)
from hr_self.services.provider_gateway import SelfProviderResult


class SelfExperienceProjectionServiceTests(SimpleTestCase):
    def test_todos_only_use_source_owned_non_terminal_tasks(self):
        projection = SelfExperienceProjectionService(
            provider_results={
                "HR05": SelfProviderResult.ok(
                    {
                        "tasks": [
                            {
                                "id": "task-1",
                                "title": "提交入职材料",
                                "status": "PENDING",
                                "dueAt": "2026-09-01T00:00:00+08:00",
                            },
                            {"id": "task-2", "title": "已办", "status": "COMPLETED"},
                        ]
                    }
                )
            },
            services=[{"source_domain": "HR05", "route": "/hr/onboarding/"}],
        )

        todos = projection.todos()

        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["key"], "HR05:task:task-1")
        self.assertEqual(todos[0]["actionRoute"], "/hr/onboarding/")

    def test_unavailable_source_is_not_reported_as_fake_empty_progress(self):
        projection = SelfExperienceProjectionService(
            provider_results={
                "HR05": SelfProviderResult.unavailable("SOURCE_DOWN"),
                "HR06": SelfProviderResult.ok(
                    {
                        "changeCases": [
                            {
                                "id": "change-1",
                                "caseNo": "CHG-001",
                                "status": "UNDER_REVIEW",
                                "updatedAt": "2026-08-30T09:00:00+08:00",
                            }
                        ]
                    }
                ),
            }
        )

        progress = projection.progress()

        self.assertEqual([item["sourceDomain"] for item in progress], ["HR06"])
        self.assertEqual(progress[0]["name"], "CHG-001")

    def test_external_routes_are_not_exposed_as_actions(self):
        projection = SelfExperienceProjectionService(
            provider_results={},
            services=[
                {"source_domain": "HR05", "route": "https://evil.example/"},
                {"source_domain": "HR06", "route": "//evil.example/"},
            ],
        )
        self.assertEqual(projection.routes, {})
