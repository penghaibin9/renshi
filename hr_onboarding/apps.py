from django.apps import AppConfig


class HrOnboardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_onboarding"
    verbose_name = "HR Onboarding (HR05)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/onboarding/prehires 等
        urlpatterns.append(
            path("hr/onboarding/", include("hr_onboarding.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/onboarding/
        urlpatterns.append(
            path("", include("hr_onboarding.api.urls")),
        )
