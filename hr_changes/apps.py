from django.apps import AppConfig


class HrChangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_changes"
    verbose_name = "HR Changes (HR06)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/changes/*
        urlpatterns.append(
            path("hr/changes/", include("hr_changes.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/changes/
        urlpatterns.append(
            path("", include("hr_changes.api.urls")),
        )
