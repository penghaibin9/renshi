"""
hr_time/apps.py

HR11 app 配置。注册 /hr/time/ 页面与 /api/hr/v1/time/ API 前缀。
"""

from django.apps import AppConfig


class HrTimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_time"
    verbose_name = "HR Time & Leave (HR11)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # API 路由：独立前缀 /api/hr/v1/time/
        urlpatterns.append(
            path("", include("hr_time.api.urls")),
        )
