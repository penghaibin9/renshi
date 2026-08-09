"""
hr_qualification/apps.py —— HR09 AppConfig（总册 §105/§161）。

注册：
- 路由：API /api/v1/hr/qualifications/... + 管理端 /hr/qualifications/... + /hr/double-teacher/...
- 权重：HR09 = hr_qualification
"""

from django.apps import AppConfig


class HrQualificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_qualification"
    verbose_name = "HR09 Qualification & Double Teacher"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 管理端页面路由：教师资格 + 双师型
        urlpatterns.append(
            path("hr/qualifications/", include("hr_qualification.urls")),
        )
        urlpatterns.append(
            path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
        )
        # API 路由：独立前缀 /api/v1/hr/qualifications/
        urlpatterns.append(
            path("", include("hr_qualification.api.urls")),
        )
