from django.apps import AppConfig


class HrExternalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_external"
    verbose_name = "HR External Workforce (HR08)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/external-teachers/（HR08-01~05 工作区；S3 起逐区挂入）
        urlpatterns.append(
            path("hr/external-teachers/", include("hr_external.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/external-teachers/
        urlpatterns.append(
            path("", include("hr_external.api.urls")),
        )
