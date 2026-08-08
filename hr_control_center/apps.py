from django.apps import AppConfig


class HrControlCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_control_center"
    verbose_name = "HR Control Center (HR01)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/overview 等
        urlpatterns.append(
            path("hr/", include("hr_control_center.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/home/
        urlpatterns.append(
            path("", include("hr_control_center.api.urls")),
        )
