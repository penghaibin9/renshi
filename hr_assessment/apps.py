"""HR12 Assessment — AppConfig（生产级：注册 signals + 自动注入 URL）。"""

from django.apps import AppConfig


class HrAssessmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_assessment"
    verbose_name = "HR12 年度与聘期考核 (Assessment Authority)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由
        urlpatterns.append(path("hr/assessments/", include("hr_assessment.urls")))
        # API 路由
        urlpatterns.append(path("", include("hr_assessment.api.urls")))
        # 注册 signals
        from hr_assessment import signals  # noqa: F401
