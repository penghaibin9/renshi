"""
hr10_development/apps.py

HR10 app 配置。注册 /api/v1/hr/development/ API 前缀。
"""

from django.apps import AppConfig


class Hr10DevelopmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr10_development"
    verbose_name = "HR10 培训进修与企业实践"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        urlpatterns.append(
            path("", include("hr10_development.api.urls")),
        )
        urlpatterns.append(
            path("", include("hr10_development.urls")),
        )
