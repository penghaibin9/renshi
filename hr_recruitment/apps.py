from django.apps import AppConfig


class HrRecruitmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_recruitment"
    verbose_name = "HR Recruitment (HR04)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/recruitment/plans 等
        urlpatterns.append(
            path("hr/recruitment/", include("hr_recruitment.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/recruitment/
        urlpatterns.append(
            path("", include("hr_recruitment.api.urls")),
        )
